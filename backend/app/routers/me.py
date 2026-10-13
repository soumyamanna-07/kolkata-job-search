"""Endpoints for the logged-in user: profile, privacy consent, delete account, saved jobs, applications, activity."""
from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Response, status
from psycopg.rows import dict_row
from pydantic import BaseModel, Field

from app import account
from app.auth import CurrentUser, get_current_user, get_optional_user
from app.db import get_conn
from app.job_search import summary_columns
from app.schemas import JobEventIn, JobSummary, Profile, ProfileUpdate, SavedJob

router = APIRouter(prefix="/api", tags=["me"])


def _profile(user: CurrentUser) -> Profile:
    return Profile(id=user.id, email=user.email, full_name=user.full_name, role=user.role,
                   privacy_consent_at=user.privacy_consent_at)


@router.get("/me", response_model=Profile)
def get_me(user: CurrentUser = Depends(get_current_user)):
    """The logged-in user's profile."""
    return _profile(user)


@router.patch("/me", response_model=Profile)
def update_me(body: ProfileUpdate, user: CurrentUser = Depends(get_current_user),
              conn: psycopg.Connection = Depends(get_conn)):
    """Change your display name."""
    conn.execute("update public.profiles set full_name = %s where id = %s", (body.full_name.strip(), user.id))
    user.full_name = body.full_name.strip()
    return _profile(user)


@router.post("/me/consent", response_model=Profile)
def give_consent(user: CurrentUser = Depends(get_current_user), conn: psycopg.Connection = Depends(get_conn)):
    """Record that the user accepted the privacy notice (needed before saving a CV)."""
    row = conn.execute(
        "update public.profiles set privacy_consent_at = coalesce(privacy_consent_at, now()) "
        "where id = %s returning privacy_consent_at", (user.id,)).fetchone()
    user.privacy_consent_at = row[0]
    return _profile(user)


class AccountDelete(BaseModel):
    confirm: Literal["DELETE MY ACCOUNT"]          # typed on purpose, so nobody deletes by accident


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
def delete_me(body: AccountDelete, user: CurrentUser = Depends(get_current_user),
              conn: psycopg.Connection = Depends(get_conn)):
    """Delete your account and everything personal we stored: CV data, saved jobs, alerts.
    Employers: your open jobs are closed. This cannot be undone."""
    try:
        account.delete_account(conn, user.id)
    except account.CannotDelete as exc:
        raise HTTPException(409, str(exc))
    except LookupError:
        raise HTTPException(404, "Account not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------- saved jobs
@router.get("/me/saved-jobs", response_model=list[SavedJob])
def list_saved_jobs(user: CurrentUser = Depends(get_current_user), conn: psycopg.Connection = Depends(get_conn)):
    """Your saved jobs, newest first. Closed jobs stay in the list with status = closed."""
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(
            f"""select {summary_columns("j")}, j.status, s.created_at as saved_at
                from public.saved_jobs s join public.jobs j on j.id = s.job_id
                where s.user_id = %s
                order by s.created_at desc""", (user.id,)).fetchall()
    return [SavedJob(**r) for r in rows]


@router.put("/me/saved-jobs/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
def save_job(job_id: UUID, user: CurrentUser = Depends(get_current_user),
             conn: psycopg.Connection = Depends(get_conn)):
    """Save a job (saving twice is fine)."""
    if conn.execute("select 1 from public.jobs where id = %s", (job_id,)).fetchone() is None:
        raise HTTPException(404, "Job not found")
    inserted = conn.execute(
        "insert into public.saved_jobs (user_id, job_id) values (%s, %s) on conflict do nothing returning 1",
        (user.id, job_id)).fetchone()
    if inserted:
        conn.execute("insert into public.job_events (user_id, job_id, event_type) values (%s, %s, 'save')",
                     (user.id, job_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/me/saved-jobs/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
def unsave_job(job_id: UUID, user: CurrentUser = Depends(get_current_user),
               conn: psycopg.Connection = Depends(get_conn)):
    """Remove a saved job."""
    deleted = conn.execute("delete from public.saved_jobs where user_id = %s and job_id = %s returning 1",
                           (user.id, job_id)).fetchone()
    if deleted:
        conn.execute("insert into public.job_events (user_id, job_id, event_type) values (%s, %s, 'unsave')",
                     (user.id, job_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------- my applications
ApplicationStatus = Literal["applied", "interview", "offer", "rejected", "no_reply"]


class Application(JobSummary):
    status: str                                # the job itself: open / closed
    application_status: ApplicationStatus      # where the user is: applied, interview, offer ...
    note: Optional[str] = None
    applied_at: datetime
    updated_at: datetime


class ApplicationUpdate(BaseModel):
    status: Optional[ApplicationStatus] = None
    note: Optional[str] = Field(default=None, max_length=500)


APPLICATION_SQL = f"""select {summary_columns("j")}, j.status, a.status as application_status, a.note,
                             a.applied_at, a.updated_at
                      from public.applications a join public.jobs j on j.id = a.job_id
                      where a.user_id = %s"""


def _application(conn: psycopg.Connection, user_id: str, job_id: UUID) -> Application:
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(APPLICATION_SQL + " and a.job_id = %s", (user_id, job_id)).fetchone()
    if row is None:
        raise HTTPException(404, "This job is not in your applications")
    return Application(**row)


@router.get("/me/applications", response_model=list[Application])
def list_applications(user: CurrentUser = Depends(get_current_user), conn: psycopg.Connection = Depends(get_conn)):
    """Your applications, most recently changed first. Closed jobs stay in the list."""
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(APPLICATION_SQL + " order by a.updated_at desc limit 500", (user.id,)).fetchall()
    return [Application(**r) for r in rows]


@router.put("/me/applications/{job_id}", response_model=Application)
def add_application(job_id: UUID, user: CurrentUser = Depends(get_current_user),
                    conn: psycopg.Connection = Depends(get_conn)):
    """Add a job to your applications (done when you press Apply). Pressing again keeps your status."""
    if conn.execute("select 1 from public.jobs where id = %s", (job_id,)).fetchone() is None:
        raise HTTPException(404, "Job not found")
    conn.execute("insert into public.applications (user_id, job_id) values (%s, %s) on conflict do nothing",
                 (user.id, job_id))
    return _application(conn, user.id, job_id)


@router.patch("/me/applications/{job_id}", response_model=Application)
def update_application(job_id: UUID, body: ApplicationUpdate, user: CurrentUser = Depends(get_current_user),
                       conn: psycopg.Connection = Depends(get_conn)):
    """Move an application to another stage (interview, offer, rejected, no reply) and/or change its note."""
    changes, params = [], {"u": user.id, "j": job_id}
    if body.status is not None:
        changes.append("status = %(status)s")
        params["status"] = body.status
    if "note" in body.model_fields_set:
        changes.append("note = %(note)s")
        params["note"] = (body.note or "").strip() or None
    if not changes:
        raise HTTPException(422, "Send a status or a note to change")
    updated = conn.execute(f"update public.applications set {', '.join(changes)} "
                           "where user_id = %(u)s and job_id = %(j)s returning 1", params).fetchone()
    if updated is None:
        raise HTTPException(404, "This job is not in your applications")
    return _application(conn, user.id, job_id)


@router.delete("/me/applications/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_application(job_id: UUID, user: CurrentUser = Depends(get_current_user),
                       conn: psycopg.Connection = Depends(get_conn)):
    """Remove a job from your applications."""
    conn.execute("delete from public.applications where user_id = %s and job_id = %s", (user.id, job_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------- activity
@router.post("/events", status_code=status.HTTP_204_NO_CONTENT)
def record_event(event: JobEventIn, user: Optional[CurrentUser] = Depends(get_optional_user),
                 conn: psycopg.Connection = Depends(get_conn)):
    """Record a view / apply click / impression. Works for guests (anonymous session id)."""
    if user is None and not event.session_id:
        raise HTTPException(422, "session_id is required for guests")
    try:
        conn.execute(
            """insert into public.job_events
                 (user_id, session_id, job_id, event_type, source_page, rank_position, match_score)
               values (%s, %s, %s, %s, %s, %s, %s)""",
            (user.id if user else None, None if user else event.session_id, event.job_id, event.event_type,
             event.source_page, event.rank_position, event.match_score))
    except psycopg.errors.ForeignKeyViolation:
        raise HTTPException(404, "Job not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me/applied", response_model=list[SavedJob])
def applied_history(user: CurrentUser = Depends(get_current_user), conn: psycopg.Connection = Depends(get_conn)):
    """Jobs you clicked "Apply" on (latest click per job), newest first."""
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(
            f"""select {summary_columns("j")}, j.status, e.clicked_at as saved_at
                from (select job_id, max(created_at) as clicked_at from public.job_events
                      where user_id = %s and event_type = 'click_apply' group by job_id) e
                join public.jobs j on j.id = e.job_id
                order by e.clicked_at desc limit 200""", (user.id,)).fetchall()
    return [SavedJob(**r) for r in rows]
