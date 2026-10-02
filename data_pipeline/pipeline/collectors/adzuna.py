"""Adzuna India job search API (free key: https://developer.adzuna.com).

Two modes, to stay inside the free quota (2,500 calls a month):
  recent - only jobs posted in the last few days (a few calls). Adds new jobs,
           never closes any. Run daily.
  full   - every Kolkata job (about 75 calls). Also lets the pipeline close jobs
           that disappeared. Run once a week.
Pages are fetched slowly (max ~24 a minute) to respect Adzuna's rate limit.
"""
import time
from datetime import datetime

import requests

from pipeline.collectors.base import TIMEOUT_SECONDS, CollectResult, safe_error
from pipeline.models import RawJob

API_URL = "https://api.adzuna.com/v1/api/jobs/in/search/{page}"
RESULTS_PER_PAGE = 50
MAX_PAGES = 100         # safety limit: 100 x 50 = 5000 jobs per run
PAGE_DELAY = 2.5        # seconds between pages (Adzuna allows 25 calls a minute)
RECENT_DAYS = 3         # "recent" mode: jobs posted in the last N days
MODES = ("recent", "full")


def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def collect(session: requests.Session, app_id: str, app_key: str, mode: str = "recent") -> CollectResult:
    if mode not in MODES:
        raise ValueError(f"unknown Adzuna mode: {mode}")
    result = CollectResult(source="adzuna", scope=f"adzuna:{mode}", snapshot=(mode == "full"))
    if not app_id or not app_key:
        result.error = "ADZUNA_APP_ID / ADZUNA_APP_KEY not set in .env (source skipped)"
        return result
    try:
        total = None
        params = {
            "app_id": app_id,
            "app_key": app_key,
            "where": "Kolkata",
            "results_per_page": RESULTS_PER_PAGE,
            "sort_by": "date",
            "content-type": "application/json",
        }
        if mode == "recent":
            params["max_days_old"] = RECENT_DAYS
        for page in range(1, MAX_PAGES + 1):
            if page > 1:
                time.sleep(PAGE_DELAY)
            resp = session.get(API_URL.format(page=page), params=params, timeout=TIMEOUT_SECONDS)
            result.requests_made += 1
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
