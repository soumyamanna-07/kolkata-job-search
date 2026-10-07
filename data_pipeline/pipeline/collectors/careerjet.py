"""Careerjet job search API v4 (free publisher key: https://www.careerjet.co.in/partners/).

GET https://search.api.careerjet.net/v4/query, Basic auth with the API key as user name.
The API gives at most 10 pages of 100 jobs, newest first; we stop at jobs older than 60 days (MAX_JOB_AGE_DAYS).
"""
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Optional

import requests

from pipeline.collectors.base import TIMEOUT_SECONDS, USER_AGENT, CollectResult, safe_error
from pipeline.models import RawJob
from pipeline.normalize import MAX_JOB_AGE_DAYS

API_URL = "https://search.api.careerjet.net/v4/query"
PAGE_SIZE = 100
MAX_PAGES = 10                        # the API's own limit
PAGE_DELAY = 1.0
MAX_AGE_DAYS = MAX_JOB_AGE_DAYS        # same rule as the rest of the pipeline (60 days)
SALARY_PERIOD = {"Y": "year", "M": "month", "H": "hour"}     # weekly / daily salaries are not kept


def _parse_date(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(str(value))                # "Mon, 05 Oct 2026 08:30:00 GMT"
    except (TypeError, ValueError):
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def collect(session: requests.Session, api_key: str, user_ip: str = "",
            now: Optional[datetime] = None) -> CollectResult:
    # snapshot=False: search results change with ranking, so a job missing today is not proof it closed
    # (the 60-day rule closes old ones)
    result = CollectResult(source="careerjet", scope="careerjet", snapshot=False)
    if not api_key:
        result.error = "CAREERJET_API_KEY not set in .env (source skipped)"
        return result
    oldest_allowed = (now or datetime.now(timezone.utc)) - timedelta(days=MAX_AGE_DAYS)
    params = {"locale_code": "en_IN", "location": "Kolkata", "keywords": "", "sort": "date",
              "page_size": PAGE_SIZE, "user_ip": user_ip or "127.0.0.1", "user_agent": USER_AGENT}
    try:
        for page in range(1, MAX_PAGES + 1):
            if page > 1:
                time.sleep(PAGE_DELAY)
            resp = session.get(API_URL, params={**params, "page": page}, auth=(api_key, ""),
                               timeout=TIMEOUT_SECONDS)
            result.requests_made += 1
            resp.raise_for_status()
            data = resp.json()
            if data.get("type", "JOBS") != "JOBS":
                raise ValueError(f"unexpected answer type {data.get('type')!r} (check the location)")
            items = data.get("jobs") or []
            reached_old = False
            for item in items:
                posted = _parse_date(item.get("date"))
                if posted and posted < oldest_allowed:
                    reached_old = True                    # newest first: the rest are older too
                    continue
                period = SALARY_PERIOD.get(str(item.get("salary_type") or "").upper())
                result.jobs.append(RawJob(
                    source="careerjet",
                    source_job_id=item.get("url") or "",
                    company_name=item.get("company") or "",
                    title=item.get("title") or "",
                    apply_url=item.get("url") or "",
                    locations=[item.get("locations") or ""],
                    description=item.get("description") or "",
                    posted_at=posted,
                    salary_min=item.get("salary_min") if period else None,
                    salary_max=item.get("salary_max") if period else None,
                    salary_currency=item.get("salary_currency_code") or "INR",
                    salary_period=period,
                ))
            if not items or reached_old or len(result.jobs) >= (data.get("hits") or 0):
                result.complete = True
                break
        else:
            result.complete = True            # 1000 newest jobs read; that is the API's limit
    except (requests.RequestException, ValueError, AttributeError) as error:
        result.error = safe_error(error, (api_key,))
    return result
