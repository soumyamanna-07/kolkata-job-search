"""Jooble job search API (free key: https://jooble.org/api/about).

POST https://jooble.org/api/<key> with {"keywords", "location", "page", ...}.
Only jobs from the last 30 days are asked for, so a run stays small.
"""
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

from pipeline.collectors.base import TIMEOUT_SECONDS, CollectResult, safe_error
from pipeline.collectors.salary_text import parse_salary
from pipeline.models import RawJob

API_URL = "https://jooble.org/api/{key}"
RESULTS_PER_PAGE = 50
MAX_PAGES = 20                    # safety limit: 20 x 50 = 1000 jobs per run
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


def collect(session: requests.Session, api_key: str, now: Optional[datetime] = None) -> CollectResult:
    # snapshot=False: search results change with ranking, so a job missing today is not proof it closed
    # (the 30-day rule closes old ones)
    result = CollectResult(source="jooble", scope="jooble", snapshot=False)
    if not api_key:
        result.error = "JOOBLE_API_KEY not set in .env (source skipped)"
        return result
    since = ((now or datetime.now(timezone.utc)) - timedelta(days=MAX_AGE_DAYS)).date().isoformat()
    try:
        total = None
        for page in range(1, MAX_PAGES + 1):
            if page > 1:
                time.sleep(PAGE_DELAY)
            body = {"keywords": "", "location": "Kolkata", "page": str(page),
                    "ResultOnPage": str(RESULTS_PER_PAGE), "datecreatedfrom": since}
            resp = session.post(API_URL.format(key=api_key), json=body, timeout=TIMEOUT_SECONDS)
            result.requests_made += 1
            resp.raise_for_status()
            data = resp.json()
            total = data.get("totalCount", total)
            items = data.get("jobs") or []
            for item in items:
                salary = parse_salary(item.get("salary"))
                result.jobs.append(RawJob(
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
                ))
            if not items or (total is not None and len(result.jobs) >= total):
                result.complete = True
                break
        else:
            result.complete = True            # safety limit reached: keep what we have
    except (requests.RequestException, ValueError, AttributeError) as error:
        result.error = safe_error(error, (api_key,))
    return result
