"""Jooble India job search API (free key: https://in.jooble.org/api/about).

POST https://in.jooble.org/api/<key> with {"keywords", "location", "page", ...}.
Keys are per country: an India key works only on in.jooble.org (a key from jooble.org
searches US jobs). We search "Kolkata" once per common job keyword and merge the results
(same job id = same job). Jobs older than 60 days (MAX_JOB_AGE_DAYS) are dropped here.
A few extra searches look for work-from-home jobs anywhere in India; only jobs that really say
remote / work from home are kept, and they are marked so they can be shown under "Work from home".

Jooble sometimes answers with a server error (500) in the middle of a run. A failed search is
tried again after a short wait; if it still fails, that one keyword is skipped and the run goes on.
Only a wrong key (4xx answer) or several keywords failing in a row stops the whole run.
"""
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

from pipeline.collectors.base import TIMEOUT_SECONDS, CollectResult, safe_error
from pipeline.collectors.salary_text import parse_salary
from pipeline.models import RawJob
from pipeline.normalize import MAX_JOB_AGE_DAYS

API_URL = "https://in.jooble.org/api/{key}"
LOCATION = "Kolkata"
# one search per keyword; grouped by field so it is easy to see what is covered
KEYWORDS = [
    # IT and software
    "developer", "software engineer", "python", "java", "web developer", "frontend", "react", "android",
    "devops", "cloud", "cyber security", "sql", "sap", "embedded", "ui ux", "network engineer", "it support",
    "tester",
    # data and AI
    "data analyst", "data scientist", "machine learning", "data entry", "computer operator",
    # accounts, banking and insurance
    "accountant", "accounts executive", "tally", "gst", "audit", "finance", "bank", "loan",
    "relationship manager", "insurance",
    # sales, marketing and customer service
    "sales", "field executive", "marketing", "digital marketing", "social media", "seo",
    "business development", "customer support", "telecaller", "bpo", "voice process", "back office",
    # office and people
    "hr", "recruiter", "admin", "office assistant", "receptionist", "operations", "manager", "supervisor",
    "legal",
    # education
    "teacher", "school", "tutor", "counsellor",
    # health
    "nurse", "pharmacist", "medical representative", "lab technician", "physiotherapist", "hospital", "doctor",
    # engineering, factory and trades
    "civil engineer", "site engineer", "mechanical engineer", "electrical engineer", "autocad", "architect",
    "production", "quality", "technician", "electrician",
    # retail, hotels, travel and logistics
    "retail", "store manager", "cashier", "hotel", "chef", "restaurant", "housekeeping", "travel", "event",
    "logistics", "supply chain", "purchase", "warehouse", "delivery", "driver", "security guard",
    # creative
    "graphic designer", "video editor", "content writer", "interior designer", "fashion", "beautician",
    # early career
    "intern", "fresher",
]
# work-from-home searches across all of India (someone living in Kolkata can do these jobs)
REMOTE_LOCATION = "India"
REMOTE_KEYWORDS = [
    "work from home", "remote", "remote developer", "remote data entry", "remote customer support",
    "remote sales", "remote content writer", "online tutor",
]
REMOTE_WORDS = re.compile(r"(?<![a-z])(remote|work from home|work-from-home|wfh)(?![a-z])")
RESULTS_PER_PAGE = 50
PAGES_PER_KEYWORD = 3             # a keyword rarely has more than 150 Kolkata jobs
MAX_REQUESTS = 400                # safety limit for one run (a full run needs about 300)
PAGE_DELAY = 0.7                  # seconds between requests, to be polite to the API
RETRY_WAITS = (3, 10)             # a search that fails with a server error is tried again after 3 s, then 10 s
MAX_FAILED_IN_A_ROW = 3           # this many keywords failing one after another: Jooble is down, stop
MAX_AGE_DAYS = MAX_JOB_AGE_DAYS        # same rule as the rest of the pipeline (60 days)


def _parse_date(value) -> Optional[datetime]:
    if not value:
        return None
    text = re.sub(r"(\.\d{6})\d+", r"\1", str(value).replace("Z", "+00:00"))   # Jooble sends 7 decimals
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _really_remote(item: dict) -> bool:
    """A work-from-home search can also return office jobs; keep only jobs that say they are remote."""
    text = " ".join(str(item.get(k) or "") for k in ("title", "location", "snippet", "type")).lower()
    return bool(REMOTE_WORDS.search(text)) and "hybrid" not in text


def _to_job(item: dict, remote: bool = False) -> RawJob:
    salary = parse_salary(item.get("salary"))
    return RawJob(
        source="jooble",
        source_job_id=str(item.get("id", "")),
        company_name=item.get("company") or "",
        title=item.get("title") or "",
        apply_url=item.get("link") or "",
        locations=[item.get("location") or ""],
        description=item.get("snippet") or "",
        posted_at=_parse_date(item.get("updated")),
        salary_min=salary.get("min"),
        salary_max=salary.get("max"),
        salary_currency=salary.get("currency"),
        salary_period=salary.get("period"),
        job_type_hint=item.get("type") or "",
        work_mode_hint="remote" if remote else "",
        remote_from_india=remote,
    )


class TemporaryError(Exception):
    """A search still failed after all retries (Jooble server error or no connection)."""
    def __init__(self, original: Exception):
        super().__init__(str(original))
        self.original = original


def _post(session: requests.Session, url: str, body: dict, result: CollectResult) -> requests.Response:
    """One search, tried again after a short wait if Jooble has a temporary problem."""
    for wait in (*RETRY_WAITS, None):
        result.requests_made += 1
        try:
            resp = session.post(url, json=body, timeout=TIMEOUT_SECONDS)
            if resp.status_code < 500:
                resp.raise_for_status()                # 4xx (e.g. wrong key): retrying will not help
                return resp
            error = requests.HTTPError(f"{resp.status_code} Server Error from Jooble")
        except (requests.ConnectionError, requests.Timeout) as problem:
            error = problem
        if wait is None:
            raise TemporaryError(error)
        time.sleep(wait)
    raise AssertionError("unreachable")


def collect(session: requests.Session, api_key: str, now: Optional[datetime] = None) -> CollectResult:
    # snapshot=False: search results change with ranking, so a job missing today is not proof it closed
    # (the 60-day rule closes old ones)
    result = CollectResult(source="jooble", scope="jooble", snapshot=False)
    if not api_key:
        result.error = "JOOBLE_API_KEY not set in .env (source skipped)"
        return result
    oldest = (now or datetime.now(timezone.utc)) - timedelta(days=MAX_AGE_DAYS)
    url = API_URL.format(key=api_key)
    seen = set()
    failed: list[str] = []                             # keywords skipped after retries
    in_a_row = 0
    last_problem: Optional[Exception] = None
    try:
        searches = [(k, LOCATION, False) for k in KEYWORDS] + [(k, REMOTE_LOCATION, True) for k in REMOTE_KEYWORDS]
        for keyword, location, remote in searches:
            try:
                for page in range(1, PAGES_PER_KEYWORD + 1):
                    if result.requests_made >= MAX_REQUESTS:
                        break                         # safety limit reached: keep what we have
                    if result.requests_made:
                        time.sleep(PAGE_DELAY)
                    body = {"keywords": keyword, "location": location, "page": str(page),
                            "ResultOnPage": str(RESULTS_PER_PAGE)}
                    data = _post(session, url, body, result).json()
                    items = data.get("jobs") or []
                    for item in items:
                        if remote and not _really_remote(item):
                            continue                  # an office job found by a work-from-home search
                        job = _to_job(item, remote)
                        key = job.source_job_id or job.apply_url
                        if not key or key in seen:
                            continue                  # same job found under another keyword
                        seen.add(key)
                        if job.posted_at and job.posted_at < oldest:
                            continue
                        result.jobs.append(job)
                    total = data.get("totalCount") or 0
                    if len(items) < RESULTS_PER_PAGE or page * RESULTS_PER_PAGE >= total:
                        break                         # no more pages for this keyword
                in_a_row = 0
            except TemporaryError as problem:
                failed.append(keyword)
                in_a_row += 1
                last_problem = problem.original
                if in_a_row >= MAX_FAILED_IN_A_ROW:
                    raise problem.original            # Jooble looks down: stop here, keep what we have
            if result.requests_made >= MAX_REQUESTS:
                break
        if failed:
            result.error = safe_error(last_problem, (api_key,)) + \
                f" ({len(failed)} of {len(searches)} searches skipped: {', '.join(failed[:5])})"
        else:
            result.complete = True
    except (requests.RequestException, ValueError, AttributeError) as error:
        result.error = safe_error(error, (api_key,))
    return result
