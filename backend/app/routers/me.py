"""Endpoints for the logged-in user: profile, privacy consent, saved jobs, activity."""
from typing import Optional
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Response, status
from psycopg.rows import dict_row

from app.auth import CurrentUser, get_current_user, get_optional_user
from app.db import get_conn
from app.job_search import summary_columns
from app.schemas import JobEventIn, Profile, ProfileUpdate, SavedJob

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
