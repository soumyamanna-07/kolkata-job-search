"""Lever job boards: https://api.lever.co/v0/postings/<slug>?mode=json"""
from datetime import datetime, timezone

import requests

from pipeline.collectors.base import TIMEOUT_SECONDS, CollectResult, safe_error
from pipeline.models import RawJob

API_URL = "https://api.lever.co/v0/postings/{slug}"

LEVER_INTERVAL = {"per-year-salary": "year", "per-month-salary": "month", "per-hour-wage": "hour"}


def collect(session: requests.Session, slug: str, company_name: str, company_id: str) -> CollectResult:
    result = CollectResult(source="lever", scope=f"lever:{slug}", company_id=company_id)
    try:
        resp = session.get(API_URL.format(slug=slug), params={"mode": "json"}, timeout=TIMEOUT_SECONDS)
        result.requests_made += 1
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, list):
            raise ValueError("unexpected response format (expected a list)")
        for item in data:
            cats = item.get("categories") or {}
            locations = [cats.get("location") or ""] + list(cats.get("allLocations") or [])
            salary = item.get("salaryRange") or {}
            created_ms = item.get("createdAt")
            description = "\n\n".join(filter(None, [
                item.get("descriptionPlain") or item.get("description") or "",
                *[f"{lst.get('text', '')}\n{lst.get('content', '')}" for lst in item.get("lists") or []],
                item.get("additionalPlain") or "",
            ]))
            result.jobs.append(RawJob(
                source="lever",
                source_job_id=str(item.get("id", "")),
                company_id=company_id,
                company_name=company_name,
                title=item.get("text", ""),
                apply_url=item.get("hostedUrl") or item.get("applyUrl") or "",
                locations=[l for l in locations if l],
                description=description,
                posted_at=datetime.fromtimestamp(created_ms / 1000, tz=timezone.utc) if created_ms else None,
                salary_min=salary.get("min"),
                salary_max=salary.get("max"),
                salary_currency=salary.get("currency"),
                salary_period=LEVER_INTERVAL.get(salary.get("interval", ""), "year"),
                job_type_hint=cats.get("commitment") or "",
                work_mode_hint=item.get("workplaceType") or "",
            ))
        result.complete = True
    except (requests.RequestException, ValueError) as error:
        result.error = safe_error(error)
    return result
