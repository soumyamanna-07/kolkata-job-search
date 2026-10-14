"""Stage 1 (deep-learning skill extraction), step 1: a labelled dataset of Indian job descriptions.

Takes a random sample of job descriptions from our database and asks the LLM (Groq) to mark every
job skill written in each one. Only skills that really appear in the text are kept, with their exact
character positions, so the data can train a token-level model (BERT NER) later. These are "silver"
labels (made by a machine); a part of them is checked by hand in the next step to make the "gold" set.

Which jobs: only sources whose full description we may use for research (company career boards and
jobs posted on our site). Adzuna, Jooble, Careerjet and Jobicy are left out (their terms / short
snippets), and government notices too (not normal job text).
The descriptions are company text: the data stays in research/data/ on your computer and is NOT
committed to GitHub (that folder ignores everything).

Run from the backend/ folder (needs DATABASE_URL and the Groq key in .env):
    python -m research.ner_dataset --sample 400        # pick the jobs (once)
    python -m research.ner_dataset --label             # label them; safe to stop and run again
"""
import argparse
import json
import random
import re
import sys
import time
from html import unescape
from pathlib import Path
from typing import Callable, Optional

import psycopg

from app import config, llm

DATA = Path(__file__).resolve().parent / "data"
JOBS_FILE = DATA / "ner_jobs.jsonl"          # the sampled job texts
SILVER_FILE = DATA / "ner_silver.jsonl"      # LLM labels with character spans
SOURCES = ("greenhouse", "lever", "ashby", "smartrecruiters", "workable", "career_page", "indian_ats",
           "employer", "campus", "community")
MIN_CHARS = 300                  # shorter texts have too little to label
MAX_CHARS = 3000                 # keeps one job inside one LLM request
SEED = 23
PAUSE_SECONDS = 2.5              # Groq free plan: about 30 requests a minute

PROMPT = """You label job skills in Indian job descriptions for a research dataset.

List EVERY job skill written in the text: programming languages, frameworks, libraries, tools,
platforms, databases, cloud services, methods (e.g. agile, machine learning), and domain skills
(e.g. financial analysis, GST filing, AutoCAD, Tally). Include spoken languages only when asked as a
skill (e.g. "fluent in Bengali").
Do NOT list: soft traits (team player, hard-working), degrees (B.Tech, MBA), job titles, company or
product names that are not skills, years of experience, locations.

Rules:
- "text" must be copied EXACTLY as written in the job description (same spelling and case).
- "skill" is the common lower-case name (e.g. text "ReactJS" -> skill "react", "MS-Excel" -> "excel").
- List each different spelling once.
Reply with JSON only: {"skills": [{"text": "...", "skill": "..."}]}"""

_TAG = re.compile(r"<[^>]+>")
_SPACES = re.compile(r"[ \t\r\f\v]+")
_LINES = re.compile(r"\n\s*\n+")


def clean(text: str) -> str:
    """Plain text from a description that may contain HTML."""
    text = re.sub(r"(?i)<\s*(br|/p|/li|/div|/h\d)\s*/?>", "\n", text or "")
    text = unescape(_TAG.sub(" ", text)).replace("\xa0", " ")         # &nbsp; -> normal space
    text = "\n".join(_SPACES.sub(" ", line).strip() for line in text.splitlines())
    return _LINES.sub("\n\n", text).strip()


def spans(text: str, surface: str) -> list[list[int]]:
    """Every [start, end) where `surface` appears as a whole word (exact case first, else any case)."""
    if not surface.strip():
        return []
    def find(flags):
        pattern = re.compile(r"(?<![A-Za-z0-9])" + re.escape(surface) + r"(?![A-Za-z0-9])", flags)
        return [[m.start(), m.end()] for m in pattern.finditer(text)]
    return find(0) or find(re.I)


def parse_reply(reply: str) -> list[dict]:
    """The skills list from the LLM reply (tolerates text around the JSON)."""
    start, end = reply.find("{"), reply.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON in the reply")
    data = json.loads(reply[start:end + 1])
    out = []
    for item in data.get("skills", []):
        if isinstance(item, dict) and str(item.get("text", "")).strip():
            out.append({"text": str(item["text"]).strip()[:80],
                        "skill": " ".join(str(item.get("skill") or item["text"]).lower().split())[:60]})
    return out


def label_one(job: dict, chat: Callable = llm.chat) -> dict:
    """Ask the LLM, keep only skills found in the text, with their spans."""
    reply = chat([{"role": "system", "content": PROMPT},
                  {"role": "user", "content": f"Job title: {job['title']}\n\n{job['text']}"}],
                 max_tokens=1500, temperature=0.0)
    entities, dropped, seen = [], [], set()
    for item in parse_reply(reply):
        found = spans(job["text"], item["text"])
        if not found:
            dropped.append(item["text"])             # the model invented or changed the wording
            continue
        for start, end in found:
            if (start, end) not in seen:
                seen.add((start, end))
                entities.append({"start": start, "end": end, "text": job["text"][start:end], "skill": item["skill"]})
    entities.sort(key=lambda e: e["start"])
    # overlapping spans (e.g. "SQL" inside "SQL Server"): keep the longer one
    kept: list[dict] = []
    for e in sorted(entities, key=lambda e: (e["start"], -(e["end"] - e["start"]))):
        if kept and e["start"] < kept[-1]["end"]:
            continue
        kept.append(e)
    return {"id": job["id"], "entities": kept, "not_in_text": dropped}


def sample_jobs(conn: psycopg.Connection, n: int, seed: int = SEED) -> list[dict]:
    rows = conn.execute("""select id::text, title, description from public.jobs
                           where source = any(%s) and description is not null
                           order by id""", (list(SOURCES),)).fetchall()
    jobs = []
    for job_id, title, description in rows:
        text = clean(description)
        if len(text) >= MIN_CHARS:
            jobs.append({"id": job_id, "title": title, "text": text[:MAX_CHARS]})
    random.Random(seed).shuffle(jobs)
    return jobs[:n]


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def label_all(chat: Callable = llm.chat, pause: float = PAUSE_SECONDS, log: Callable[[str], None] = print,
              jobs_file: Path = JOBS_FILE, silver_file: Path = SILVER_FILE) -> int:
    jobs = read_jsonl(jobs_file)
    done = {r["id"] for r in read_jsonl(silver_file)}
    todo = [j for j in jobs if j["id"] not in done]
    log(f"{len(done)} of {len(jobs)} jobs already labelled, {len(todo)} to go")
    failures = 0
    with open(silver_file, "a", encoding="utf-8") as out:
        for i, job in enumerate(todo, 1):
            try:
                result = label_one(job, chat)
            except (llm.LLMError, ValueError) as error:
                failures += 1
                log(f"  [{i}/{len(todo)}] skipped ({error}); it will be tried again next run")
                if failures >= 5 and failures == i:
                    log("Stopping: the first 5 requests all failed (check the Groq key / limits).")
                    return 1
                time.sleep(pause * 4)
                continue
            out.write(json.dumps(result, ensure_ascii=True) + "\n")
            out.flush()
            log(f"  [{i}/{len(todo)}] {len(result['entities'])} skills"
                + (f" ({len(result['not_in_text'])} not in the text, dropped)" if result["not_in_text"] else ""))
            time.sleep(pause)
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Build the job-skill NER dataset (silver labels from the LLM).")
    parser.add_argument("--sample", type=int, help="pick this many jobs from the database")
    parser.add_argument("--label", action="store_true", help="label the picked jobs with the LLM")
    args = parser.parse_args(argv)
    DATA.mkdir(exist_ok=True)
    if args.sample:
        if JOBS_FILE.exists():
            print(f"{JOBS_FILE} already exists; delete it first to pick a new sample", file=sys.stderr)
            return 1
        if not config.DATABASE_URL:
            print("DATABASE_URL is not set in .env", file=sys.stderr)
            return 1
        with psycopg.connect(config.DATABASE_URL) as conn:
            jobs = sample_jobs(conn, args.sample)
        JOBS_FILE.write_text("".join(json.dumps(j, ensure_ascii=True) + "\n" for j in jobs), encoding="utf-8")
        print(f"Saved {len(jobs)} job descriptions to {JOBS_FILE}")
    if args.label:
        if not llm.is_configured():
            print("The Groq key (LLM_API_KEY) is not set in .env", file=sys.stderr)
            return 1
        return label_all()
    if not (args.sample or args.label):
        parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
