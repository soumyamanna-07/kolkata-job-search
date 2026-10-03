"""Job alerts: find the NEW jobs for a saved search, and write the email.

Used by the API (alert preview) and by scripts/send_alerts.py (the daily sender).
"New" means first seen by our pipeline after the last email, so a job is never
sent twice for the same alert.
"""
import hashlib
import hmac
import html
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

import psycopg
from psycopg.rows import dict_row

from app import config
from app.job_search import JobFiltersIn, build_search_query
from app.matching import CVProfile, rank

MAX_ALERTS_PER_USER = 10
MAX_JOBS_PER_EMAIL = 10
CV_MIN_SCORE = 60                     # "match my CV" alerts only send real matches
SEARCH_LIMIT = 200                    # new jobs looked at per alert
WINDOW = {"daily": timedelta(days=1), "weekly": timedelta(days=7)}
EARLY = timedelta(hours=2)            # a run a little before exactly 24h / 7 days still counts


def is_due(frequency: str, last_sent_at: Optional[datetime], now: datetime) -> bool:
    if last_sent_at is None:
        return True
    return now - last_sent_at >= WINDOW[frequency] - EARLY


def since_for(frequency: str, last_sent_at: Optional[datetime], created_at: datetime) -> datetime:
    """Jobs first seen after this time go in the next email. The first email also
    covers the day (or week) before the alert was made, so it is not empty."""
    return last_sent_at or (created_at - WINDOW[frequency])


def search_filters(filters: dict, since: datetime) -> JobFiltersIn:
    return JobFiltersIn(
        q=filters.get("q"), areas=filters.get("areas") or [], skills=filters.get("skills") or [],
        salary_expected=filters.get("salary_expected"),
        include_undisclosed_salary=filters.get("include_undisclosed_salary", True),
        experience_years=filters.get("experience_years"), job_types=filters.get("job_types") or [],
        work_modes=filters.get("work_modes") or [], seen_since=since, sort="newest", page_size=SEARCH_LIMIT)


def active_cv(conn: psycopg.Connection, user_id: str) -> Optional[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute("""select skills, experience_years, embedding::text as embedding
                              from public.cvs where user_id = %s and is_active""", (user_id,)).fetchone()


def find_new_jobs(conn: psycopg.Connection, user_id: str, filters: dict, use_cv_match: bool,
                  since: datetime, limit: int = MAX_JOBS_PER_EMAIL) -> tuple[list[dict], int]:
    """(up to `limit` new jobs, how many new jobs in total). With use_cv_match, jobs
    are ranked against the user's saved CV and only scores of 60+ are kept."""
    list_sql, _, params = build_search_query(search_filters(filters, since))
    with conn.cursor(row_factory=dict_row) as cur:
        jobs = cur.execute(list_sql, params).fetchall()
    total = jobs[0]["total_count"] if jobs else 0
    for job in jobs:
        job.pop("total_count")
    if not use_cv_match:
        return jobs[:limit], total

    cv = active_cv(conn, user_id)
    if not jobs or cv is None or cv["embedding"] is None:
        return [], 0
    similarity = dict(conn.execute(
        """select id, 1 - (embedding operator(extensions.<=>) %s::extensions.vector)
           from public.jobs where id = any(%s) and embedding is not null""",
        (cv["embedding"], [job["id"] for job in jobs])).fetchall())
    profile = CVProfile(skills=cv["skills"],
                        experience_years=None if cv["experience_years"] is None else float(cv["experience_years"]))
    ranked = rank([{**job, "similarity": similarity[job["id"]]} for job in jobs if job["id"] in similarity], profile)
    good = []
    for job, match in ranked:
        if match.score >= CV_MIN_SCORE:
            job.pop("similarity")
            good.append({**job, "match_score": match.score})
    return good[:limit], len(good)


# ---------------------------------------------------------------- unsubscribe links
def unsubscribe_sig(alert_id) -> str:
    return hmac.new(config.ALERTS_SECRET.encode(), f"unsubscribe:{alert_id}".encode(),
                    hashlib.sha256).hexdigest()[:32]


def sig_ok(alert_id, sig: str) -> bool:
    return bool(config.ALERTS_SECRET) and hmac.compare_digest(unsubscribe_sig(alert_id), sig or "")


def unsubscribe_url(alert_id) -> str:
    return f"{config.API_URL}/api/alerts/{alert_id}/unsubscribe?sig={unsubscribe_sig(alert_id)}"


# ---------------------------------------------------------------- the email
@dataclass
class Email:
    subject: str
    text: str
    html: str
    unsubscribe_url: str


def _lakh(value: int) -> str:
    return f"{value / 100000:.1f}".rstrip("0").rstrip(".") + " L"


def salary_text(job: dict) -> str:
    low, high = job.get("salary_min"), job.get("salary_max")
    if low is None and high is None:
        return ""
    period = job.get("salary_period") or "year"
    fmt = _lakh if period == "year" else (lambda v: f"{v:,}")
    amount = fmt(low or high) if (low is None or high is None or low == high) else f"{fmt(low)} - {fmt(high)}"
    return f"\u20b9{amount} a {period}"


def _job_line(job: dict) -> str:
    parts = [job["company_name"], job["area"], salary_text(job)]
    if job.get("match_score") is not None:
        parts.append(f"match {job['match_score']}%")
    return " | ".join(p for p in parts if p)


def _safe_link(url: str, fallback: str) -> str:
    return url if (url or "").startswith(("https://", "http://")) else fallback


def build_email(full_name: Optional[str], alert_name: str, jobs: list[dict], total: int, alert_id) -> Email:
    n = len(jobs)
    subject = f"{total} new Kolkata job{'' if total == 1 else 's'} for \"{alert_name}\""
    hello = f"Hi {full_name}," if full_name else "Hi,"
    more = f"Showing the newest {n} of {total}." if total > n else ""
    all_url = f"{config.APP_URL}/alerts"
    unsub = unsubscribe_url(alert_id)
    adzuna = any(job.get("source") == "adzuna" for job in jobs)

    text_lines = [hello, "", f"New jobs for your alert \"{alert_name}\":", ""]
    for i, job in enumerate(jobs, 1):
        page = f"{config.APP_URL}/jobs/{job['id']}"
        text_lines += [f"{i}. {job['title']}", f"   {_job_line(job)}",
                       f"   Apply: {_safe_link(job['apply_url'], page)}", ""]
    if more:
        text_lines += [more, f"See all: {all_url}", ""]
    if adzuna:
        text_lines.append("Jobs by Adzuna.")
    text_lines += ["Always check a job on the company's own site. Never pay anyone to get a job.",
                   f"Stop this alert: {unsub}"]

    e = html.escape
    rows = []
    for job in jobs:
        page = f"{config.APP_URL}/jobs/{job['id']}"
        rows.append(
            f'<tr><td style="padding:10px 0;border-bottom:1px solid #e5e7eb">'
            f'<a href="{e(_safe_link(job["apply_url"], page))}" style="font-weight:600;color:#1d4ed8">'
            f'{e(job["title"])}</a><br><span style="color:#4b5563">{e(_job_line(job))}</span><br>'
            f'<a href="{e(page)}" style="color:#6b7280;font-size:13px">Details</a></td></tr>')
    html_body = (
        '<div style="font-family:Arial,sans-serif;max-width:600px;margin:auto;color:#111827">'
        f'<p>{e(hello)}</p><p>New jobs for your alert <b>{e(alert_name)}</b>:</p>'
        f'<table style="width:100%;border-collapse:collapse">{"".join(rows)}</table>'
        + (f'<p>{e(more)} <a href="{e(all_url)}">See all</a></p>' if more else "")
        + ('<p style="font-size:13px">Jobs by <a href="https://www.adzuna.in">Adzuna</a>.</p>' if adzuna else "")
        + '<p style="font-size:13px;color:#6b7280">Always check a job on the company\'s own site. '
          'Never pay anyone to get a job.<br>'
          f'<a href="{e(unsub)}" style="color:#6b7280">Stop this alert</a></p></div>')
    return Email(subject=subject, text="\n".join(text_lines), html=html_body, unsubscribe_url=unsub)
