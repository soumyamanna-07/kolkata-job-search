"""Syllabus fetcher (Stage 1.9): reads the syllabus files that colleges publish on their websites.

The links come from Admin > Syllabi > Syllabus links (table syllabus_sources): one PDF or Word file
per college + department. For each link that is switched on:
  1. robots.txt of the website must allow us (checked again after every redirect); if the website
     does not answer robots.txt at all, we wait for the next run instead of guessing,
  2. the file is downloaded (max 10 MB), slowly, one file at a time, with a clear User-Agent,
  3. if the file is the same as last time, or the same as a syllabus we already have for this
     college (also one the admin removed), nothing is added,
  4. otherwise its subjects are read and it is saved as a syllabus with source 'website' and
     status 'pending' (Waiting). It is NOT used for anyone until an admin approves it.
The result of every link (new / unchanged / blocked / error) is saved on the link for the admin.

Run from the backend/ folder:
    python -m scripts.fetch_syllabi              # check every link
    python -m scripts.fetch_syllabi --no-ai      # rules only, no AI reader (no Groq calls)
"""
import argparse
import hashlib
import sys
import time
from dataclasses import dataclass, field
from typing import Callable, Optional
from urllib.parse import unquote, urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
import psycopg
from psycopg.rows import dict_row

from app import config, embeddings, syllabus_parser
from app.routers.syllabus import MAX_SUBJECTS, _map, _subject_dict

USER_AGENT = "KolkataLiveJobSearch-Syllabus/1.0 (+https://github.com/soumyamanna-07/kolkata-job-search)"
ROBOTS_AGENT = "KolkataLiveJobSearch"
TIMEOUT_SECONDS = 30
MAX_REDIRECTS = 5
DELAY_SECONDS = 5                    # pause between two downloads, to be gentle with college websites
MAX_PER_RUN = 100
NEW, UNCHANGED, BLOCKED, ERROR = "new", "unchanged", "blocked", "error"

DUE_SQL = """
    select s.id, s.college_id, s.url, s.department, s.batch, s.semester, s.last_hash
    from public.syllabus_sources s join public.colleges c on c.id = s.college_id
    where s.enabled and c.status <> 'rejected'
    order by s.last_checked_at nulls first, s.created_at
    limit %s
"""


class FetchProblem(Exception):
    """A link could not be read; the message is shown to the admin."""
    def __init__(self, message: str, status: str = ERROR):
        super().__init__(message)
        self.status = status


class Robots:
    """robots.txt answers, one file per website (RFC 9309: missing = allowed, unreachable = wait)."""
    def __init__(self, client: httpx.Client):
        self.client, self.cache = client, {}

    def allowed(self, url: str) -> bool:
        parts = urlparse(url)
        root = f"{parts.scheme}://{parts.netloc}"
        if root not in self.cache:
            try:
                response = self.client.get(root + "/robots.txt")
            except httpx.HTTPError:
                raise FetchProblem("The website did not answer (robots.txt); will try again next run.", BLOCKED)
            if response.status_code >= 500:
                raise FetchProblem(f"The website's robots.txt gave error {response.status_code}; "
                                   "will try again next run.", BLOCKED)
            parser = RobotFileParser()
            parser.parse(response.text.splitlines() if response.status_code == 200 else [])
            self.cache[root] = parser
        return self.cache[root].can_fetch(ROBOTS_AGENT, url)


def download(client: httpx.Client, robots: Robots, url: str) -> tuple[bytes, str]:
    """The file at url (following redirects, each one checked against robots.txt): (data, final url)."""
    for _ in range(MAX_REDIRECTS + 1):
        if urlparse(url).scheme not in ("http", "https"):
            raise FetchProblem("The link does not start with http:// or https://.")
        if not robots.allowed(url):
            raise FetchProblem("robots.txt of this website does not allow reading this file.", BLOCKED)
        try:
            with client.stream("GET", url) as response:
                if response.is_redirect:
                    url = urljoin(url, response.headers.get("location", ""))
                    continue
                if response.status_code != 200:
                    raise FetchProblem(f"The website answered {response.status_code} for this link.")
                if "text/html" in response.headers.get("content-type", "").lower():
                    raise FetchProblem("This link opens a web page, not a PDF or Word file. "
                                       "Use the link of the file itself.")
                data = bytearray()
                for chunk in response.iter_bytes():
                    data += chunk
                    if len(data) > syllabus_parser.MAX_FILE_BYTES:
                        raise FetchProblem("The file is larger than 10 MB.")
                return bytes(data), url
        except httpx.HTTPError as error:
            raise FetchProblem(f"Could not download the file ({type(error).__name__}).")
    raise FetchProblem("Too many redirects.")


def file_name(url: str) -> str:
    return (unquote(urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]) or urlparse(url).netloc)[:200]


def save_syllabus(conn: psycopg.Connection, source: dict, url: str, data: bytes, digest: str,
                  allow_ai: bool) -> tuple[str, int]:
    """Read the file and save it as a Waiting syllabus: (syllabus id, number of subjects)."""
    try:
        text = syllabus_parser.extract_text(data)
        parsed = syllabus_parser.read_syllabus(text, allow_ai=allow_ai)
    except syllabus_parser.SyllabusError as error:
        raise FetchProblem(str(error))
    subjects = [_subject_dict(s) for s in parsed.subjects]
    if source["semester"] is not None:
        subjects = [s for s in subjects if s["semester"] in (None, source["semester"])]
    if len(subjects) < syllabus_parser.MIN_SUBJECTS:
        raise FetchProblem("Could not find the subject list in this file.")
    subjects = subjects[:MAX_SUBJECTS]
    mapped = _map(subjects)
    with conn.transaction():
        sid = conn.execute(
            """insert into public.syllabi (college_id, department, batch, semester, source, status, source_url,
                                           file_name, raw_text, content_hash)
               values (%s, %s, %s, %s, 'website', 'pending', %s, %s, %s, %s) returning id""",
            (source["college_id"], source["department"], source["batch"] or parsed.batch, source["semester"],
             url[:500], file_name(url), text[:400000], digest)).fetchone()[0]
        with conn.cursor() as cur:
            cur.executemany(
                """insert into public.syllabus_subjects (syllabus_id, semester, code, name, kind, is_elective, options,
                                                         credits, topics, skills, embedding, position)
                   values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::extensions.vector, %s)""",
                [(sid, s["semester"], s["code"], s["name"], s["kind"], s["is_elective"], s["options"], s["credits"],
                  s["topics"] or None, sorted({l.skill for l in m.links}),
                  embeddings.to_pgvector(m.vector) if m.vector is not None else None, i)
                 for i, (s, m) in enumerate(zip(subjects, mapped))])
    return str(sid), len(subjects)


def check_source(conn: psycopg.Connection, client: httpx.Client, robots: Robots, source: dict,
                 allow_ai: bool) -> tuple[str, str, Optional[str]]:
    """(status, message for the log, file fingerprint)."""
    try:
        data, url = download(client, robots, source["url"])
        digest = hashlib.sha256(data).hexdigest()
        if digest == source["last_hash"]:
            return UNCHANGED, "same file as last time", digest
        known = conn.execute("select status from public.syllabi where college_id = %s and content_hash = %s limit 1",
                             (source["college_id"], digest)).fetchone()
        if known:
            return UNCHANGED, f"we already have this file (status {known[0]})", digest
        sid, count = save_syllabus(conn, source, url, data, digest, allow_ai)
        return NEW, f"added to Waiting: {count} subjects (syllabus {sid})", digest
    except FetchProblem as problem:
        return problem.status, str(problem), source["last_hash"]
    except Exception as error:            # noqa: BLE001 - one bad link must not stop the other links
        return ERROR, f"Unexpected problem ({type(error).__name__}).", source["last_hash"]


@dataclass
class Stats:
    checked: int = 0
    counts: dict = field(default_factory=lambda: {NEW: 0, UNCHANGED: 0, BLOCKED: 0, ERROR: 0})


def run(conn: psycopg.Connection, client: httpx.Client, allow_ai: bool = True, limit: int = MAX_PER_RUN,
        delay: float = DELAY_SECONDS, sleep: Callable[[float], None] = time.sleep,
        log: Callable[[str], None] = print) -> Stats:
    stats, robots = Stats(), Robots(client)
    with conn.cursor(row_factory=dict_row) as cur:
        sources = cur.execute(DUE_SQL, (limit,)).fetchall()
    for i, source in enumerate(sources):
        if i:
            sleep(delay)
        status, message, digest = check_source(conn, client, robots, source, allow_ai)
        stats.checked += 1
        stats.counts[status] += 1
        log(f"  {status:9} {source['url']}: {message}")
        conn.execute("""update public.syllabus_sources set last_checked_at = now(), last_status = %s,
                               last_error = %s, last_hash = %s where id = %s""",
                     (status, None if status in (NEW, UNCHANGED) else message[:500], digest, source["id"]))
    return stats


def make_client() -> httpx.Client:
    return httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=False, headers={"User-Agent": USER_AGENT})


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch college syllabi from their websites into the Waiting list.")
    parser.add_argument("--no-ai", action="store_true", help="read subjects with the rules only (no AI reader)")
    parser.add_argument("--limit", type=int, default=MAX_PER_RUN)
    args = parser.parse_args(argv)
    if not config.DATABASE_URL:
        print("DATABASE_URL is not set in .env", file=sys.stderr)
        return 1
    with psycopg.connect(config.DATABASE_URL, autocommit=True) as conn, make_client() as client:
        stats = run(conn, client, allow_ai=not args.no_ai, limit=args.limit)
    c = stats.counts
    print(f"Syllabus links checked {stats.checked}: new {c[NEW]}, unchanged {c[UNCHANGED]}, "
          f"blocked {c[BLOCKED]}, errors {c[ERROR]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
