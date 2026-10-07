"""Jooble India job search API (free key: https://in.jooble.org/api/about).

POST https://in.jooble.org/api/<key> with {"keywords", "location", "page", ...}.
Keys are per country: an India key works only on in.jooble.org (a key from jooble.org
searches US jobs). We search "Kolkata" once per common job keyword and merge the results
(same job id = same job). Jobs older than 30 days are dropped here, so a run stays small.
"""
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

from pipeline.collectors.base import TIMEOUT_SECONDS, CollectResult, safe_error
from pipeline.collectors.salary_text import parse_salary
from pipeline.models import RawJob

API_URL = "https://in.jooble.org/api/{key}"
LOCATION = "Kolkata"
KEYWORDS = [
    "developer", "software engineer", "python", "java", "web developer", "data analyst", "data scientist",
    "machine learning", "tester", "network engineer", "it support", "accountant", "finance", "bank",
    "sales", "marketing", "digital marketing", "business development", "customer support", "telecaller",
    "hr", "recruiter", "admin", "receptionist", "operations", "manager", "teacher", "nurse", "pharmacist",
    "civil engineer", "mechanical engineer", "electrical engineer", "graphic designer", "content writer",
    "logistics", "delivery", "driver", "intern", "fresher",
]
RESULTS_PER_PAGE = 50
PAGES_PER_KEYWORD = 3             # a keyword rarely has more than 150 Kolkata jobs
MAX_REQUESTS = 100                # safety limit for one run
PAGE_DELAY = 1.0
MAX_AGE_DAYS = 30


def _parse_date(value) -> Optional[datetime]:
    if not value:
        return None
    text = re.sub(r"(\.\d{6})\d+", r"\1", str(value).replace("Z", "+00:00"))   # Jooble sends 7 decimals
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _to_job(item: dict) -> RawJob:
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
    )


def collect(session: requests.Session, api_key: str, now: Optional[datetime] = None) -> CollectResult:
    # snapshot=False: search results change with ranking, so a job missing today is not proof it closed
    # (the 30-day rule closes old ones)
    result = CollectResult(source="jooble", scope="jooble", snapshot=False)
    if not api_key:
        result.error = "JOOBLE_API_KEY not set in .env (source skipped)"
        return result
    oldest = (now or datetime.now(timezone.utc)) - timedelta(days=MAX_AGE_DAYS)
    seen = set()
    try:
        for keyword in KEYWORDS:
            for page in range(1, PAGES_PER_KEYWORD + 1):
                if result.requests_made >= MAX_REQUESTS:
                    result.complete = True            # safety limit reached: keep what we have
                    return result
                if result.requests_made:
                    time.sleep(PAGE_DELAY)
                body = {"keywords": keyword, "location": LOCATION, "page": str(page),
                        "ResultOnPage": str(RESULTS_PER_PAGE)}
                resp = session.post(API_URL.format(key=api_key), json=body, timeout=TIMEOUT_SECONDS)
                result.requests_made += 1
                resp.raise_for_status()
                data = resp.json()
                items = data.get("jobs") or []
                for item in items:
                    job = _to_job(item)
                    key = job.source_job_id or job.apply_url
                    if not key or key in seen:
                        continue                      # same job found under another keyword
                    seen.add(key)
                    if job.posted_at and job.posted_at < oldest:
                        continue
                    result.jobs.append(job)
                total = data.get("totalCount") or 0
                if len(items) < RESULTS_PER_PAGE or page * RESULTS_PER_PAGE >= total:
                    break                             # no more pages for this keyword
        result.complete = True
    except (requests.RequestException, ValueError, AttributeError) as error:
        result.error = safe_error(error, (api_key,))
    return result
