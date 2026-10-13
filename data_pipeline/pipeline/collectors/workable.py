"""Workable job boards: https://www.workable.com/api/accounts/<account>?details=true  (public, no key)

The answer's shape differs a little between accounts, so every field is read carefully.
"""
from datetime import datetime

import requests

from pipeline.collectors.base import TIMEOUT_SECONDS, CollectResult, safe_error
from pipeline.models import RawJob

API_URL = "https://www.workable.com/api/accounts/{account}"


def _parse_date(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")) if value else None
    except ValueError:
        return None


def _join(*parts) -> str:
    return ", ".join(str(p) for p in parts if p)


def _locations(item: dict) -> list[str]:
    loc = item.get("location") or {}
    out = [loc.get("location_str"), _join(loc.get("city"), loc.get("region") or loc.get("state"), loc.get("country")),
           _join(item.get("city"), item.get("state"), item.get("country"))]
    for extra in item.get("locations") or []:
        out.append(_join(extra.get("city"), extra.get("region") or extra.get("state_name") or extra.get("state"),
                         extra.get("country_name") or extra.get("country")))
    return [l for l in out if l]


def _work_mode(item: dict) -> str:
    loc = item.get("location") or {}
    mode = (loc.get("workplace_type") or item.get("workplace_type") or "").lower().replace("_", "")
    if mode in ("remote", "hybrid", "onsite"):
        return mode
    return "remote" if (loc.get("telecommuting") or item.get("telecommuting")) else ""


def collect(session: requests.Session, account: str, company_name: str, company_id: str) -> CollectResult:
    result = CollectResult(source="workable", scope=f"workable:{account}", company_id=company_id)
    try:
        resp = session.get(API_URL.format(account=account), params={"details": "true"}, timeout=TIMEOUT_SECONDS)
        result.requests_made += 1
        resp.raise_for_status()
        jobs = resp.json().get("jobs")
        if not isinstance(jobs, list):
            raise ValueError("unexpected response format (expected a jobs list)")
        for item in jobs:
            salary = item.get("salary") or {}
            result.jobs.append(RawJob(
                source="workable",
                source_job_id=str(item.get("shortcode") or item.get("id") or ""),
                company_id=company_id,
                company_name=company_name,
                title=item.get("title") or item.get("full_title") or "",
                apply_url=item.get("url") or item.get("shortlink") or item.get("application_url") or "",
                locations=_locations(item),
                description=item.get("description") or "",
                posted_at=_parse_date(item.get("published_on") or item.get("created_at")),
                salary_min=salary.get("salary_from"),
                salary_max=salary.get("salary_to"),
                salary_currency=salary.get("salary_currency"),
                job_type_hint=item.get("employment_type") or "",
                work_mode_hint=_work_mode(item),
            ))
        result.complete = True
    except (requests.RequestException, ValueError, AttributeError) as error:
        result.error = safe_error(error)
    return result
