"""Ashby job boards: https://api.ashbyhq.com/posting-api/job-board/<board>  (public, no key)"""
from datetime import datetime

import requests

from pipeline.collectors.base import TIMEOUT_SECONDS, CollectResult, safe_error
from pipeline.models import RawJob

API_URL = "https://api.ashbyhq.com/posting-api/job-board/{board}"


def _parse_date(value):
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None
    except ValueError:
        return None


def _address(item: dict) -> str:
    postal = (item.get("address") or {}).get("postalAddress") or {}
    return ", ".join(filter(None, [postal.get("addressLocality"), postal.get("addressRegion"),
                                   postal.get("addressCountry")]))


def _salary(item: dict) -> dict:
    """First salary part of the compensation summary: {min, max, currency, period}."""
    for part in (item.get("compensation") or {}).get("summaryComponents") or []:
        if (part.get("compensationType") or "").lower() == "salary":
            interval = (part.get("interval") or "").upper()
            period = "month" if "MONTH" in interval else "hour" if "HOUR" in interval else "year"
            return {"min": part.get("minValue"), "max": part.get("maxValue"),
                    "currency": part.get("currencyCode"), "period": period}
    return {}


def collect(session: requests.Session, board: str, company_name: str, company_id: str) -> CollectResult:
    result = CollectResult(source="ashby", scope=f"ashby:{board}", company_id=company_id)
    try:
        resp = session.get(API_URL.format(board=board), params={"includeCompensation": "true"},
                           timeout=TIMEOUT_SECONDS)
        result.requests_made += 1
        resp.raise_for_status()
        jobs = resp.json().get("jobs")
        if not isinstance(jobs, list):
            raise ValueError("unexpected response format (expected a jobs list)")
        for item in jobs:
            if item.get("isListed") is False:
                continue
            locations = [item.get("location") or "", _address(item)]
            for extra in item.get("secondaryLocations") or []:
                locations += [extra.get("location") or "", _address(extra)]
            salary = _salary(item)
            result.jobs.append(RawJob(
                source="ashby",
                source_job_id=str(item.get("id", "")),
                company_id=company_id,
                company_name=company_name,
                title=item.get("title", ""),
                apply_url=item.get("jobUrl") or item.get("applyUrl") or "",
                locations=[l for l in locations if l],
                description=item.get("descriptionHtml") or item.get("descriptionPlain") or "",
                posted_at=_parse_date(item.get("publishedAt")),
                salary_min=salary.get("min"),
                salary_max=salary.get("max"),
                salary_currency=salary.get("currency"),
                salary_period=salary.get("period"),
                job_type_hint=item.get("employmentType") or "",
                work_mode_hint=(item.get("workplaceType") or "").lower(),
            ))
        result.complete = True
    except (requests.RequestException, ValueError, AttributeError) as error:
        result.error = safe_error(error)
    return result
