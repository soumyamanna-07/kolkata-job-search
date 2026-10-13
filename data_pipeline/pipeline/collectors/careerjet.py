"""Careerjet job search API v4 (free publisher key: https://www.careerjet.co.in/partners/).

GET https://search.api.careerjet.net/v4/query, Basic auth with the API key as user name.
Careerjet also checks the Referer header: it must be the website registered with the key
(our Vercel site), otherwise it answers 403 "Undeclared referrer".
Paging: our key gets at most 20 jobs per answer (page_size is not honoured), so we move through the
results with "offset" (0, 20, 40 ...), which goes up to 999: about the 1,000 newest Kolkata jobs per run.
Newest first; we stop at jobs older than 60 days (MAX_JOB_AGE_DAYS).
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
PAGE_SIZE = 100                       # asked for; Careerjet may send fewer (20 for our key)
MAX_OFFSET = 999                      # the API's own limit
MAX_REQUESTS = 60                     # safety limit for one run (1,000 jobs / 20 per answer = 50)
PAGE_DELAY = 1.0
REFERER = "https://kolkata-live-jobs.vercel.app/"   # the website registered with our Careerjet key
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
    seen = set()
    offset = 0
    try:
        while True:
            if result.requests_made >= MAX_REQUESTS:
                result.complete = True        # safety limit reached: keep what we have
                break
            if result.requests_made:
                time.sleep(PAGE_DELAY)
            resp = session.get(API_URL, params={**params, "offset": offset}, auth=(api_key, ""),
                               headers={"Referer": REFERER}, timeout=TIMEOUT_SECONDS)
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
                url = item.get("url") or ""
                if not url or url in seen:
                    continue
                seen.add(url)
                period = SALARY_PERIOD.get(str(item.get("salary_type") or "").upper())
                result.jobs.append(RawJob(
                    source="careerjet",
                    source_job_id=url,
                    company_name=item.get("company") or "",
                    title=item.get("title") or "",
                    apply_url=url,
                    locations=[item.get("locations") or ""],
                    description=item.get("description") or "",
                    posted_at=posted,
                    salary_min=item.get("salary_min") if period else None,
                    salary_max=item.get("salary_max") if period else None,
                    salary_currency=item.get("salary_currency_code") or "INR",
                    salary_period=period,
                ))
            offset += len(items)
            if not items or reached_old or offset >= (data.get("hits") or 0) or offset > MAX_OFFSET:
                result.complete = True        # end of the list, old jobs reached, or the API's limit
                break
    except (requests.RequestException, ValueError, AttributeError) as error:
        result.error = safe_error(error, (api_key,))
    return result
