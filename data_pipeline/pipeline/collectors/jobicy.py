"""Jobicy remote jobs API (free, no key: https://github.com/Jobicy/remote-jobs-api).

GET https://jobicy.com/api/v2/remote-jobs?geo=<region>&count=<n>. It lists remote jobs from the last
few days. We ask for jobs open "Anywhere" and in "APAC" and keep only the ones a person living in
India can apply for (jobGeo says Anywhere, APAC, Asia or India). They are shown under "Work from home".

Jobicy's rules: keep Jobicy as the source and link to the Jobicy job page (we use its url as the
apply link and show "Jobs by Jobicy"), and do not ask more than once an hour (we run twice a day).
"""
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

from pipeline.collectors.base import TIMEOUT_SECONDS, CollectResult, safe_error
from pipeline.models import RawJob
from pipeline.normalize import MAX_JOB_AGE_DAYS

API_URL = "https://jobicy.com/api/v2/remote-jobs"
GEOS = ("anywhere", "apac")            # regions to ask for
COUNT = 100                            # jobs per request (the API allows up to 200)
OPEN_TO_INDIA = re.compile(r"(?<![a-z])(anywhere|worldwide|apac|asia|india)(?![a-z])")


def _parse_date(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _number(value) -> Optional[float]:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _to_job(item: dict) -> RawJob:
    geo = (item.get("jobGeo") or "Anywhere").strip()
    job_type = item.get("jobType") or []
    period = str(item.get("salaryPeriod") or "").lower()
    return RawJob(
        source="jobicy",
        source_job_id=str(item.get("id", "")),
        company_name=item.get("companyName") or "",
        title=item.get("jobTitle") or "",
        apply_url=item.get("url") or "",
        locations=[f"Remote ({geo})"],
        description=item.get("jobDescription") or item.get("jobExcerpt") or "",
        posted_at=_parse_date(item.get("pubDate")),
        salary_min=_number(item.get("salaryMin")),
        salary_max=_number(item.get("salaryMax")),
        salary_currency=item.get("salaryCurrency") or None,     # usually USD: not shown (we show rupees only)
        salary_period={"yearly": "year", "monthly": "month", "hourly": "hour"}.get(period),
        job_type_hint=", ".join(job_type) if isinstance(job_type, list) else str(job_type),
        work_mode_hint="remote",
        remote_from_india=True,
    )


def collect(session: requests.Session, now: Optional[datetime] = None) -> CollectResult:
    # snapshot=False: the API only lists recent jobs, so a job missing today is not proof it closed
    # (the 60-day rule closes old ones)
    result = CollectResult(source="jobicy", scope="jobicy", snapshot=False)
    oldest = (now or datetime.now(timezone.utc)) - timedelta(days=MAX_JOB_AGE_DAYS)
    seen = set()
    try:
        for geo in GEOS:
            resp = session.get(API_URL, params={"geo": geo, "count": COUNT}, timeout=TIMEOUT_SECONDS)
            result.requests_made += 1
            resp.raise_for_status()
            for item in resp.json().get("jobs") or []:
                if not OPEN_TO_INDIA.search((item.get("jobGeo") or "anywhere").lower()):
                    continue                          # e.g. "Hong Kong, Singapore" only
                job = _to_job(item)
                if not job.source_job_id or job.source_job_id in seen:
                    continue
                seen.add(job.source_job_id)
                if job.posted_at and job.posted_at < oldest:
                    continue
                result.jobs.append(job)
        result.complete = True
    except (requests.RequestException, ValueError, AttributeError) as error:
        result.error = safe_error(error)
    return result
