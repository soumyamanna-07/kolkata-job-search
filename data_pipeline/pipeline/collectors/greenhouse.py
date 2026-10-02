"""Greenhouse job boards: https://boards-api.greenhouse.io/v1/boards/<token>/jobs"""
from datetime import datetime

import requests

from pipeline.collectors.base import TIMEOUT_SECONDS, CollectResult, safe_error
from pipeline.models import RawJob

API_URL = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs"


def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def collect(session: requests.Session, token: str, company_name: str, company_id: str) -> CollectResult:
    result = CollectResult(source="greenhouse", scope=f"greenhouse:{token}", company_id=company_id)
    try:
        resp = session.get(API_URL.format(token=token), params={"content": "true"}, timeout=TIMEOUT_SECONDS)
        result.requests_made += 1
        resp.raise_for_status()
        data = resp.json()
        for item in data.get("jobs", []):
            locations = [(item.get("location") or {}).get("name", "")]
            locations += [o.get("location") or o.get("name") or "" for o in item.get("offices") or []]
            result.jobs.append(RawJob(
                source="greenhouse",
                source_job_id=str(item.get("id", "")),
                company_id=company_id,
                company_name=company_name,
                title=item.get("title", ""),
                apply_url=item.get("absolute_url", ""),
                locations=[l for l in locations if l],
                description=item.get("content", ""),
                posted_at=_parse_date(item.get("first_published") or item.get("updated_at")),
            ))
        result.complete = True
    except (requests.RequestException, ValueError) as error:
        result.error = safe_error(error)
    return result
