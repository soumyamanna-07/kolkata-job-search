"""Stage 1 (deep-learning skill extraction): more job descriptions for the NER dataset.

Kolkata alone has too few full job descriptions from sources we may use (11 in October 2026). The
public job-board APIs our pipeline already reads (Greenhouse, Lever, Ashby, Workable) list each
company's jobs in ALL locations; the pipeline keeps only Kolkata. For the research dataset this script
also keeps the jobs in other Indian cities, from:
  - the boards of the companies in our database, and
  - the India-hiring companies listed in scripts/discover_boards.py (wrong guesses are skipped).
At most PER_COMPANY jobs per company, so one big company cannot fill the dataset.

The texts are added to research/data/ner_jobs.jsonl (local only, never committed; already-saved jobs
are not added twice). Then label them with:  python -m research.ner_dataset --label

Run from the backend/ folder:
    python -m research.ner_collect --max 400
"""
import argparse
import json
import re
import sys
import time
from html import unescape
from typing import Callable, Optional
from urllib.parse import quote

import httpx
import psycopg

from app import companies, config
from research.ner_dataset import JOBS_FILE, MAX_CHARS, MIN_CHARS, clean, read_jsonl
from scripts.discover_boards import CANDIDATES

PER_COMPANY = 40
DELAY_SECONDS = 1.0              # pause between two boards (polite)
INDIA = re.compile(r"(?<![a-z])(india|bengaluru|bangalore|mumbai|pune|hyderabad|chennai|delhi|new delhi|gurgaon|"
                   r"gurugram|noida|kolkata|calcutta|salt ?lake|new ?town|howrah|ahmedabad|jaipur|kochi|cochin|"
                   r"coimbatore|indore|chandigarh|thiruvananthapuram|trivandrum|bhubaneswar|nagpur|lucknow|"
                   r"mysuru|mysore|vadodara|surat|visakhapatnam|goa)(?![a-z])")
DETAIL_URLS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true",
    "lever": "https://api.lever.co/v0/postings/{token}?mode=json",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{token}",
    "workable": "https://www.workable.com/api/accounts/{token}?details=true",
}


def in_india(locations: list[str]) -> bool:
    text = " | ".join(l for l in locations if l).lower()
    return bool(INDIA.search(text)) and not companies.ABROAD_WORDS.search(text)


def _lever_text(item: dict) -> str:
    parts = [item.get("descriptionPlain") or ""]
    for block in item.get("lists") or []:
        parts.append(block.get("text") or "")
        parts.append(clean(block.get("content") or ""))
    parts.append(item.get("additionalPlain") or "")
    return "\n".join(p for p in parts if p)


def board_jobs(platform: str, data) -> list[dict]:
    """[{id, title, text, locations}] from a board's JSON (with descriptions)."""
    titles_locs = companies._jobs_and_locations(platform, data)
    items = data if platform == "lever" else [i for i in data.get("jobs", [])
                                               if not (platform == "ashby" and i.get("isListed") is False)]
    out = []
    for item, (title, locs) in zip(items, titles_locs):
        if platform == "greenhouse":
            text = clean(unescape(item.get("content") or ""))      # Greenhouse sends escaped HTML
            job_id = item.get("id")
        elif platform == "lever":
            text, job_id = _lever_text(item), item.get("id")
        elif platform == "ashby":
            text = item.get("descriptionPlain") or clean(item.get("descriptionHtml") or "")
            job_id = item.get("id") or item.get("jobUrl")
        else:
            text = clean(item.get("description") or "")
            job_id = item.get("shortcode") or item.get("id") or item.get("url")
        out.append({"id": str(job_id or ""), "title": title, "text": text.strip(), "locations": [l for l in locs if l]})
    return out


def boards_from_db() -> list[tuple[str, str, str]]:
    if not config.DATABASE_URL:
        return []
    with psycopg.connect(config.DATABASE_URL) as conn:
        rows = conn.execute("""select name, ats_platform, ats_token from public.companies
                               where ats_platform = any(%s) and ats_token is not null""",
                            (list(DETAIL_URLS),)).fetchall()
    return [(n, p, t) for n, p, t in rows]


def collect(client: httpx.Client, boards: list[tuple[str, str, str]], guesses: list[tuple[str, str]],
            limit: int, have: set[str], delay: float = DELAY_SECONDS,
            log: Callable[[str], None] = print) -> list[dict]:
    """New India job texts. boards: known (name, platform, token); guesses: (name, token) to try on each platform."""
    known = {b[2].lower() for b in boards}             # a company already in our database is not guessed again
    tries = list(boards) + [(n, p, t) for n, t in guesses if t.lower() not in known for p in DETAIL_URLS]
    new: list[dict] = []
    found_boards = set()
    for name, platform, token in tries:
        if len(new) >= limit:
            break
        if name in found_boards:
            continue                                  # a guessed company already answered on another platform
        try:
            response = client.get(DETAIL_URLS[platform].format(token=quote(token, safe="")))
        except httpx.HTTPError:
            continue
        finally:
            if delay:
                time.sleep(delay)
        if response.status_code != 200:
            continue
        try:
            jobs = board_jobs(platform, response.json())
        except (ValueError, AttributeError, TypeError):
            continue
        if not jobs:
            continue
        found_boards.add(name)
        kept = 0
        for job in jobs:
            key = f"{platform}:{token.lower()}:{job['id']}"
            if kept >= PER_COMPANY or len(new) >= limit or key in have or not job["id"]:
                continue
            if not in_india(job["locations"]) or len(job["text"]) < MIN_CHARS:
                continue
            have.add(key)
            new.append({"id": key, "title": job["title"], "text": job["text"][:MAX_CHARS], "company": name,
                        "city": next((l for l in job["locations"] if INDIA.search(l.lower())), "")})
            kept += 1
        log(f"  {name:<24} {platform:<10} {len(jobs):>4} jobs, India texts kept: {kept}")
    return new


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Add India job descriptions from public job boards to the NER dataset.")
    parser.add_argument("--max", type=int, default=400, help="how many new job texts to add at most")
    args = parser.parse_args(argv)
    JOBS_FILE.parent.mkdir(exist_ok=True)
    existing = read_jsonl(JOBS_FILE)
    have = {j["id"] for j in existing}
    print(f"{len(existing)} job texts saved already; looking for up to {args.max} more")
    with companies.make_client() as client:
        new = collect(client, boards_from_db(), CANDIDATES, args.max, have)
    with open(JOBS_FILE, "a", encoding="utf-8") as f:
        for job in new:
            f.write(json.dumps(job, ensure_ascii=True) + "\n")
    print(f"Added {len(new)} job texts; {len(existing) + len(new)} in {JOBS_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
