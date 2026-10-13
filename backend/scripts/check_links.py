"""Dead-link checker: close open jobs whose apply link no longer works.

Checks jobs that no source API keeps up to date: recruiter posts and shared job links
(campus = from college TPOs, community = from users). Adzuna / Greenhouse / Lever jobs
are closed by the pipeline when they disappear from the source, so we do not crawl those.

A job is closed only after 3 failed checks on different days, so a website that is
down for an afternoon does not lose its jobs. "Blocked" answers (403, 429, 5xx,
timeouts) are not counted as failures.

Run from the backend/ folder:
    python -m scripts.check_links --dry-run       # check links, change nothing
    python -m scripts.check_links                 # check and close dead jobs
"""
import argparse
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

import httpx
import psycopg
from psycopg.rows import dict_row

from app import config

DEFAULT_SOURCES = ("employer", "campus", "community")
FAILS_TO_CLOSE = 3
RECHECK_AFTER = timedelta(hours=20)
MAX_PER_RUN = 300
WORKERS = 8
USER_AGENT = "KolkataLiveJobSearch-LinkChecker/1.0 (+https://github.com/soumyamanna-07/kolkata-job-search)"
OK, DEAD, UNSURE = "ok", "dead", "unsure"

DUE_SQL = """
    select id, apply_url, link_fail_count from public.jobs
    where status = 'open' and source = any(%s)
      and (link_checked_at is null or link_checked_at < %s)
    order by link_checked_at nulls first, first_seen_at
    limit %s
"""


def classify(status: int) -> str:
    if status in (404, 410):
        return DEAD                       # page not found / gone
    if 200 <= status < 400:
        return OK
    return UNSURE                         # 401/403/429 (bot blocked), 5xx (site trouble)


def check_url(client: httpx.Client, url: str) -> str:
    try:
        status = client.head(url).status_code
        if status in (403, 405, 501):     # some sites refuse HEAD; ask the normal way
            with client.stream("GET", url) as response:
                status = response.status_code
    except httpx.ConnectError:
        return DEAD                       # domain gone or nothing listening
    except httpx.HTTPError:
        return UNSURE                     # timeout, too many redirects, bad link format ...
    return classify(status)


def make_client() -> httpx.Client:
    return httpx.Client(timeout=10, follow_redirects=True, max_redirects=5, headers={"User-Agent": USER_AGENT})


@dataclass
class Stats:
    checked: int = 0
    ok: int = 0
    dead: int = 0
    unsure: int = 0
    closed: int = 0


def run(conn: psycopg.Connection, client: httpx.Client, now: datetime, sources=DEFAULT_SOURCES,
        dry_run: bool = False, limit: int = MAX_PER_RUN, log: Callable[[str], None] = print) -> Stats:
    stats = Stats()
    with conn.cursor(row_factory=dict_row) as cur:
        jobs = cur.execute(DUE_SQL, (list(sources), now - RECHECK_AFTER, limit)).fetchall()
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        results = list(pool.map(lambda job: check_url(client, job["apply_url"]), jobs))
    for job, result in zip(jobs, results):
        stats.checked += 1
        setattr(stats, result, getattr(stats, result) + 1)
        fails = 0 if result == OK else job["link_fail_count"] + (1 if result == DEAD else 0)
        close = fails >= FAILS_TO_CLOSE
        if close:
            stats.closed += 1
            log(f"  {'would close' if dry_run else 'closed'}: {job['apply_url']} (dead {fails} checks in a row)")
        if dry_run:
            continue
        with conn.transaction():
            conn.execute(
                """update public.jobs set link_checked_at = %s, link_fail_count = %s,
                          status = case when %s then 'closed' else status end,
                          closed_at = case when %s then %s else closed_at end,
                          close_reason = case when %s then 'dead_link' else close_reason end
                   where id = %s""", (now, fails, close, close, now, close, job["id"]))
            if close:
                conn.execute("update public.job_submissions set status = 'closed' "
                             "where published_job_id = %s and status = 'approved'", (job["id"],))
    return stats


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Close open jobs whose apply link is dead.")
    parser.add_argument("--dry-run", action="store_true", help="check links but change nothing")
    parser.add_argument("--sources", default=",".join(DEFAULT_SOURCES), help="comma-separated job sources")
    parser.add_argument("--limit", type=int, default=MAX_PER_RUN)
    args = parser.parse_args(argv)

    if not config.DATABASE_URL:
        print("DATABASE_URL is not set in .env", file=sys.stderr)
        return 1
    sources = [s.strip() for s in args.sources.split(",") if s.strip()]
    with psycopg.connect(config.DATABASE_URL, autocommit=True) as conn, make_client() as client:
        stats = run(conn, client, datetime.now(timezone.utc), sources, args.dry_run, args.limit)
    print(f"Links checked {stats.checked} (sources: {', '.join(sources)}): ok {stats.ok}, dead {stats.dead}, "
          f"unsure {stats.unsure}, {'would close' if args.dry_run else 'closed'} {stats.closed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
