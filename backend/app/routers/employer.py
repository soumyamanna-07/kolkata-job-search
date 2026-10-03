"""Employer portal: company details and job posts.

Flow: sign up as employer -> fill company details -> an admin approves the company
-> post jobs -> automatic spam check -> an admin approves each job -> it goes live.
"""
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, status
from psycopg.rows import dict_row

from app import spam
from app.auth import CurrentUser, require_role
from app.db import get_conn
from app.ratelimit import PerKeyLimiter
from app.schemas import EmployerProfile, EmployerProfileIn, JobSubmission, JobSubmissionIn
from app.skills import extract_skills

router = APIRouter(prefix="/api/employer", tags=["employer"])
employer_only = require_role("employer")
posts_per_day = PerKeyLimiter(20, window=86400)

PROFILE_COLUMNS = ("company_name, official_email, website, gst_or_cin, verification_status, "
                   "rejection_reason, updated_at")
SUBMISSION_COLUMNS = ("id, title, description, skills, location, area, apply_url, salary_min, salary_max, "
                      "experience_min, experience_max, job_type, work_mode, status, rejection_reason, "
                      "published_job_id, created_at, updated_at")
NOT_APPROVED = {
    "pending": "Your company details are waiting for admin approval. You can post jobs once approved.",
    "rejected": "Your company details were not approved. Please correct them (PUT /api/employer/profile).",
    "blocked": "This employer account is blocked.",
}


def _profile_row(conn: psycopg.Connection, user_id: str):
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(f"select {PROFILE_COLUMNS} from public.employer_profiles where user_id = %s",
                           (user_id,)).fetchone()


def _approved_profile(conn: psycopg.Connection, user_id: str) -> dict:
    row = _profile_row(conn, user_id)
    if row is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Add your company details first (PUT /api/employer/profile).")
    if row["verification_status"] != "approved":
        raise HTTPException(status.HTTP_403_FORBIDDEN, NOT_APPROVED[row["verification_status"]])
    return row


def _skills(body: JobSubmissionIn) -> list[str]:
    """The employer's skills plus any known skills found in the title and description."""
    given = {s.strip().lower() for s in body.skills if s.strip()}
    return sorted(given | set(extract_skills(f"{body.title}\n{body.description}")))[:30]


def _spam(body: JobSubmissionIn, profile: dict) -> spam.SpamResult:
    return spam.check(body.title, body.description, body.apply_url, profile["official_email"],
                      profile["website"], body.salary_max, body.experience_max)


def _job_values(body: JobSubmissionIn) -> tuple:
    return (body.title.strip(), body.description.strip(), _skills(body), body.location, body.area, body.apply_url,
            body.salary_min, body.salary_max, body.experience_min, body.experience_max, body.job_type, body.work_mode)


# ---------------------------------------------------------------- company details
@router.get("/profile", response_model=EmployerProfile)
def get_profile(user: CurrentUser = Depends(employer_only), conn: psycopg.Connection = Depends(get_conn)):
    """Your company details and their approval status."""
    row = _profile_row(conn, user.id)
    if row is None:
        raise HTTPException(404, "No company details yet")
    return EmployerProfile(**row)


@router.put("/profile", response_model=EmployerProfile)
def save_profile(body: EmployerProfileIn, user: CurrentUser = Depends(employer_only),
                 conn: psycopg.Connection = Depends(get_conn)):
    """Add or change your company details. Any change is checked again by an admin."""
    old = _profile_row(conn, user.id)
    if old and old["verification_status"] == "blocked":
        raise HTTPException(status.HTTP_403_FORBIDDEN, NOT_APPROVED["blocked"])
    new = body.model_dump()
    if old and all(old[k] == v for k, v in new.items()):
        return EmployerProfile(**old)                    # nothing changed: keep the current status
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            f"""insert into public.employer_profiles (user_id, company_name, official_email, website, gst_or_cin)
                values (%(uid)s, %(company_name)s, %(official_email)s, %(website)s, %(gst_or_cin)s)
                on conflict (user_id) do update set
                    company_name = excluded.company_name, official_email = excluded.official_email,
                    website = excluded.website, gst_or_cin = excluded.gst_or_cin,
                    verification_status = 'pending', rejection_reason = null,
                    reviewed_by = null, reviewed_at = null
                returning {PROFILE_COLUMNS}""",
            {"uid": user.id, **new}).fetchone()
    return EmployerProfile(**row)


# ---------------------------------------------------------------- job posts
@router.post("/jobs", response_model=JobSubmission, status_code=status.HTTP_201_CREATED)
def submit_job(body: JobSubmissionIn, user: CurrentUser = Depends(employer_only),
               conn: psycopg.Connection = Depends(get_conn)):
    """Post a job. It is checked automatically, then reviewed by an admin before it goes live."""
    profile = _approved_profile(conn, user.id)
    if not posts_per_day.allow(user.id):
        raise HTTPException(429, "You can post up to 20 jobs a day. Please try again tomorrow.")
    check = _spam(body, profile)
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            f"""insert into public.job_submissions (employer_id, title, description, skills, location, area,
                    apply_url, salary_min, salary_max, experience_min, experience_max, job_type, work_mode,
                    spam_score, spam_reasons)
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                returning {SUBMISSION_COLUMNS}""",
            (user.id, *_job_values(body), check.score, check.reasons)).fetchone()
    return JobSubmission(**row)


@router.get("/jobs", response_model=list[JobSubmission])
def my_jobs(user: CurrentUser = Depends(employer_only), conn: psycopg.Connection = Depends(get_conn)):
    """All your job posts, newest first, with their review status."""
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(f"select {SUBMISSION_COLUMNS} from public.job_submissions where employer_id = %s "
                           "order by created_at desc", (user.id,)).fetchall()
    return [JobSubmission(**r) for r in rows]


def _own_submission(conn: psycopg.Connection, user_id: str, job_id: UUID) -> dict:
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(f"select {SUBMISSION_COLUMNS} from public.job_submissions "
                          "where id = %s and employer_id = %s", (job_id, user_id)).fetchone()
    if row is None:
        raise HTTPException(404, "Job post not found")
    return row


@router.get("/jobs/{job_id}", response_model=JobSubmission)
def get_my_job(job_id: UUID, user: CurrentUser = Depends(employer_only),
               conn: psycopg.Connection = Depends(get_conn)):
    return JobSubmission(**_own_submission(conn, user.id, job_id))


@router.put("/jobs/{job_id}", response_model=JobSubmission)
def edit_job(job_id: UUID, body: JobSubmissionIn, user: CurrentUser = Depends(employer_only),
             conn: psycopg.Connection = Depends(get_conn)):
    """Edit a post that is waiting for review or was rejected. It goes back to the review queue."""
    profile = _approved_profile(conn, user.id)
    old = _own_submission(conn, user.id, job_id)
    if old["status"] not in ("pending", "rejected"):
        raise HTTPException(409, "Only posts waiting for review or rejected ones can be edited. "
                                 "To change a live job, close it and post it again.")
    check = _spam(body, profile)
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            f"""update public.job_submissions set title = %s, description = %s, skills = %s, location = %s,
                    area = %s, apply_url = %s, salary_min = %s, salary_max = %s, experience_min = %s,
                    experience_max = %s, job_type = %s, work_mode = %s, spam_score = %s, spam_reasons = %s,
                    status = 'pending', rejection_reason = null, reviewed_by = null, reviewed_at = null
                where id = %s and employer_id = %s
                returning {SUBMISSION_COLUMNS}""",
            (*_job_values(body), check.score, check.reasons, job_id, user.id)).fetchone()
    return JobSubmission(**row)


@router.post("/jobs/{job_id}/close", response_model=JobSubmission)
def close_job(job_id: UUID, user: CurrentUser = Depends(employer_only),
              conn: psycopg.Connection = Depends(get_conn)):
    """Take a live job down (position filled), or withdraw a post that is waiting for review."""
    old = _own_submission(conn, user.id, job_id)
    if old["status"] not in ("pending", "approved"):
        raise HTTPException(409, f"This post is already {old['status']}.")
    with conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
        if old["published_job_id"]:
            cur.execute("update public.jobs set status = 'closed', closed_at = now() "
                        "where id = %s and employer_id = %s", (old["published_job_id"], user.id))
        row = cur.execute(f"update public.job_submissions set status = 'closed' where id = %s "
                          f"returning {SUBMISSION_COLUMNS}", (job_id,)).fetchone()
    return JobSubmission(**row)
