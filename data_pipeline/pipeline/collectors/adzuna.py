"""Adzuna India job search API (free key: https://developer.adzuna.com).

Searches jobs around Kolkata, page by page, until every result is fetched.
"""
from datetime import datetime

import requests

from pipeline.collectors.base import TIMEOUT_SECONDS, CollectResult, safe_error
from pipeline.models import RawJob

API_URL = "https://api.adzuna.com/v1/api/jobs/in/search/{page}"
RESULTS_PER_PAGE = 50
MAX_PAGES = 40          # safety limit: 40 x 50 = 2000 jobs per run


def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def collect(session: requests.Session, app_id: str, app_key: str) -> CollectResult:
    result = CollectResult(source="adzuna", scope="adzuna")
    if not app_id or not app_key:
        result.error = "ADZUNA_APP_ID / ADZUNA_APP_KEY not set in .env (source skipped)"
        return result
    try:
        total = None
        for page in range(1, MAX_PAGES + 1):
            resp = session.get(
                API_URL.format(page=page),
                params={
                    "app_id": app_id,
                    "app_key": app_key,
                    "where": "Kolkata",
                    "results_per_page": RESULTS_PER_PAGE,
                    "content-type": "application/json",
                },
                timeout=TIMEOUT_SECONDS,
            )
            resp.raise_for_status()
            data = resp.json()
            total = data.get("count", total)
            items = data.get("results") or []
            for item in items:
                loc = item.get("location") or {}
                predicted = str(item.get("salary_is_predicted", "0")) == "1"
                result.jobs.append(RawJob(
                    source="adzuna",
                    source_job_id=str(item.get("id", "")),
                    company_name=(item.get("company") or {}).get("display_name", ""),
                    title=item.get("title", ""),
                    apply_url=item.get("redirect_url", ""),
                    locations=[loc.get("display_name", ""), *(loc.get("area") or [])],
                    description=item.get("description", ""),
                    posted_at=_parse_date(item.get("created")),
                    # Adzuna sometimes ESTIMATES salary; we only keep real, advertised salaries
                    salary_min=None if predicted else item.get("salary_min"),
                    salary_max=None if predicted else item.get("salary_max"),
                    salary_currency="INR",
                    salary_period="year",
                    job_type_hint=" ".join(filter(None, [item.get("contract_time"), item.get("contract_type")])),
                ))
            if not items or (total is not None and len(result.jobs) >= total):
                result.complete = True
                break
        else:
            # hit MAX_PAGES before reaching the end: data is partial, do not close anything
            result.error = f"stopped at {MAX_PAGES} pages ({len(result.jobs)} of {total} jobs)"
    except (requests.RequestException, ValueError) as error:
        result.error = safe_error(error, (app_id, app_key))
    return result
