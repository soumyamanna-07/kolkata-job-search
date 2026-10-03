"""Job alerts: save a search, get an email when NEW jobs for it open (daily or weekly).

Logged-in users manage their alerts under /api/me/alerts. The emails are sent by
scripts/send_alerts.py. Every email has an "unsubscribe" link that works without
logging in; it is signed, so nobody can switch off someone else's alert.
"""
import html
from datetime import datetime, timezone
from typing import Literal, Optional
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import HTMLResponse
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field, field_validator, model_validator

from app import alerts
from app.auth import CurrentUser, get_current_user
from app.db import get_conn
from app.job_search import AREAS, JOB_TYPES, WORK_MODES
from app.schemas import JobSummary
from app.skills import known_skill

router = APIRouter(prefix="/api", tags=["alerts"])


# ---------------------------------------------------------------- shapes (shown in /docs)
class AlertFilters(BaseModel):
    """Same filters as job search. Empty = not used."""
    q: Optional[str] = Field(default=None, max_length=200, description="search words, e.g. data analyst")
    areas: list[Literal[AREAS]] = Field(default=[], max_length=4)
    skills: list[str] = Field(default=[], max_length=20)
    salary_expected: Optional[int] = Field(default=None, ge=0, le=100_000_000, description="yearly INR")
    include_undisclosed_salary: bool = True
    experience_years: Optional[float] = Field(default=None, ge=0, le=50)
    job_types: list[Literal[JOB_TYPES]] = Field(default=[], max_length=5)
    work_modes: list[Literal[WORK_MODES]] = Field(default=[], max_length=3)

    @field_validator("q")
    @classmethod
    def _strip(cls, v: Optional[str]) -> Optional[str]:
        return (v or "").strip() or None

    @field_validator("skills")
    @classmethod
    def _skills(cls, v: list[str]) -> list[str]:
        names = sorted({s.strip().lower() for s in v if s.strip()})
        unknown = [s for s in names if not known_skill(s)]
        if unknown:
            raise ValueError(f"unknown skill(s): {', '.join(unknown)}. Use names from /api/jobs/filters")
        return names

    def is_empty(self) -> bool:
        return not (self.q or self.areas or self.skills or self.job_types or self.work_modes
                    or self.salary_expected is not None or self.experience_years is not None)


class AlertIn(BaseModel):
    name: str = Field(min_length=1, max_length=80, description='e.g. "Python jobs in Salt Lake"')
    filters: AlertFilters = AlertFilters()
    use_cv_match: bool = Field(default=False, description="only jobs that match your saved CV (score 60+)")
    frequency: Literal["daily", "weekly"] = "daily"
    is_active: bool = True

    @model_validator(mode="after")
    def _something_to_watch(self) -> "AlertIn":
        self.name = self.name.strip()
        if not self.name:
            raise ValueError("name is required")
        if self.filters.is_empty() and not self.use_cv_match:
            raise ValueError("add at least one filter (search words, skill, area ...) or turn on use_cv_match")
        return self


class Alert(AlertIn):
    id: UUID
    last_sent_at: Optional[datetime] = None
    created_at: datetime


class AlertJob(JobSummary):
    match_score: Optional[int] = None


class AlertPreview(BaseModel):
    since: datetime
    total_new: int
    items: list[AlertJob]                # what the email would show (newest / best first, max 10)
    note: Optional[str] = None


# ---------------------------------------------------------------- helpers
COLUMNS = "id, name, filters, use_cv_match, frequency, is_active, last_sent_at, created_at"


def _get(conn: psycopg.Connection, user: CurrentUser, alert_id: UUID) -> dict:
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(f"select {COLUMNS} from public.job_alerts where id = %s and user_id = %s",
                          (alert_id, user.id)).fetchone()
    if row is None:
        raise HTTPException(404, "Alert not found")
    return row


def _need_cv(conn: psycopg.Connection, user: CurrentUser, body: AlertIn) -> None:
    if body.use_cv_match and alerts.active_cv(conn, user.id) is None:
        raise HTTPException(422, "Save your CV first (POST /api/me/cv) to get alerts that match it.")


def _filters_json(body: AlertIn) -> Jsonb:
    return Jsonb(body.filters.model_dump(mode="json", exclude_defaults=True))


# ---------------------------------------------------------------- my alerts
@router.get("/me/alerts", response_model=list[Alert])
def list_alerts(user: CurrentUser = Depends(get_current_user), conn: psycopg.Connection = Depends(get_conn)):
    """Your job alerts, oldest first."""
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(f"select {COLUMNS} from public.job_alerts where user_id = %s order by created_at",
                           (user.id,)).fetchall()


@router.post("/me/alerts", response_model=Alert, status_code=status.HTTP_201_CREATED)
def create_alert(body: AlertIn, user: CurrentUser = Depends(get_current_user),
                 conn: psycopg.Connection = Depends(get_conn)):
    """Save a search as an alert. You get an email when new jobs for it open."""
    count = conn.execute("select count(*) from public.job_alerts where user_id = %s", (user.id,)).fetchone()[0]
    if count >= alerts.MAX_ALERTS_PER_USER:
        raise HTTPException(409, f"You can have at most {alerts.MAX_ALERTS_PER_USER} alerts. Delete one first.")
    _need_cv(conn, user, body)
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(
            f"""insert into public.job_alerts (user_id, name, filters, use_cv_match, frequency, is_active)
                values (%s, %s, %s, %s, %s, %s) returning {COLUMNS}""",
            (user.id, body.name, _filters_json(body), body.use_cv_match, body.frequency, body.is_active)).fetchone()


@router.put("/me/alerts/{alert_id}", response_model=Alert)
def update_alert(alert_id: UUID, body: AlertIn, user: CurrentUser = Depends(get_current_user),
                 conn: psycopg.Connection = Depends(get_conn)):
    """Change an alert (send the whole alert). Set is_active=false to pause it."""
    _get(conn, user, alert_id)
    _need_cv(conn, user, body)
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(
            f"""update public.job_alerts set name = %s, filters = %s, use_cv_match = %s, frequency = %s,
                       is_active = %s
                where id = %s and user_id = %s returning {COLUMNS}""",
            (body.name, _filters_json(body), body.use_cv_match, body.frequency, body.is_active,
             alert_id, user.id)).fetchone()


@router.delete("/me/alerts/{alert_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_alert(alert_id: UUID, user: CurrentUser = Depends(get_current_user),
                 conn: psycopg.Connection = Depends(get_conn)):
    """Delete an alert."""
    _get(conn, user, alert_id)
    conn.execute("delete from public.job_alerts where id = %s and user_id = %s", (alert_id, user.id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me/alerts/{alert_id}/preview", response_model=AlertPreview)
def preview_alert(alert_id: UUID, user: CurrentUser = Depends(get_current_user),
                  conn: psycopg.Connection = Depends(get_conn)):
    """What this alert would send for the last day (daily) or week (weekly)."""
    row = _get(conn, user, alert_id)
    since = datetime.now(timezone.utc) - alerts.WINDOW[row["frequency"]]
    items, total = alerts.find_new_jobs(conn, user.id, row["filters"], row["use_cv_match"], since)
    note = None
    if row["use_cv_match"] and alerts.active_cv(conn, user.id) is None:
        note = "This alert matches your CV, but you have no CV saved, so it finds nothing."
    elif total == 0:
        note = "No new jobs in this period. Try fewer filters."
    return AlertPreview(since=since, total_new=total, items=items, note=note)


# ---------------------------------------------------------------- unsubscribe (link in every email)
def _page(title: str, body: str, code: int = 200) -> HTMLResponse:
    return HTMLResponse(
        f'<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
        f'<title>{html.escape(title)}</title></head>'
        f'<body style="font-family:Arial,sans-serif;max-width:480px;margin:40px auto;padding:0 16px">'
        f'<h2>{html.escape(title)}</h2>{body}</body></html>', status_code=code)


def _check_link(alert_id: UUID, sig: str) -> Optional[HTMLResponse]:
    if not alerts.sig_ok(alert_id, sig):
        return _page("Link not valid", "<p>This unsubscribe link is broken or too old. "
                     "You can manage your alerts after logging in.</p>", 400)
    return None


@router.get("/alerts/{alert_id}/unsubscribe", response_class=HTMLResponse, include_in_schema=False)
def unsubscribe_page(alert_id: UUID, sig: str = ""):
    """Asks before switching off, because some email apps open links on their own."""
    bad = _check_link(alert_id, sig)
    if bad:
        return bad
    action = f"/api/alerts/{alert_id}/unsubscribe?sig={html.escape(sig)}"
    return _page("Stop this job alert?",
                 f'<form method="post" action="{action}"><button type="submit" '
                 'style="padding:10px 18px;font-size:16px">Yes, stop emails for this alert</button></form>')


@router.post("/alerts/{alert_id}/unsubscribe", response_class=HTMLResponse, include_in_schema=False)
def unsubscribe(alert_id: UUID, sig: str = "", conn: psycopg.Connection = Depends(get_conn)):
    """Switch the alert off (also used by Gmail's one-click Unsubscribe button)."""
    bad = _check_link(alert_id, sig)
    if bad:
        return bad
    conn.execute("update public.job_alerts set is_active = false where id = %s", (alert_id,))
    return _page("Alert stopped", "<p>You will not get emails for this alert any more. "
                 "You can switch it on again from your dashboard.</p>")
