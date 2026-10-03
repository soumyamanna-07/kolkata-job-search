"""Admin review: approve employers and their job posts. Every decision is logged in admin_actions.

Making someone an admin is done only in the database (never through the API):
    update public.profiles set role = 'admin' where id = '<user id>';
"""
import json
import logging
from typing import Literal, Optional
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg.rows import dict_row

from app.auth import CurrentUser, require_role
from app.db import get_conn
from app.embeddings import embed_one, job_text, text_hash, to_pgvector
from app.schemas import AdminEmployer, AdminSubmission, EmployerReview, SubmissionReview

router = APIRouter(prefix="/api/admin", tags=["admin"])
admin_only = require_role("admin")
log = logging.getLogger("kjs.admin")

EMPLOYER_SQL = """
select e.user_id, e.company_name, e.official_email, e.website, e.gst_or_cin, e.verification_status,
       e.rejection_reason, e.updated_at, e.created_at, u.email as login_email
from public.employer_profiles e left join auth.users u on u.id = e.user_id
"""
SUBMISSION_SQL = """
select s.id, s.title, s.description, s.skills, s.location, s.area, s.apply_url, s.salary_min, s.salary_max,
       s.experience_min, s.experience_max, s.job_type, s.work_mode, s.status, s.rejection_reason,
       s.published_job_id, s.created_at, s.updated_at, s.employer_id, s.spam_score, s.spam_reasons,
       e.company_name, e.official_email, e.verification_status as employer_status, e.company_id
from public.job_submissions s join public.employer_profiles e on e.user_id = s.employer_id
"""


def _log(conn: psycopg.Connection, admin: CurrentUser, action: str, table: str, target: str,
         details: Optional[dict] = None) -> None:
    conn.execute("insert into public.admin_actions (admin_id, action, target_table, target_id, details) "
                 "values (%s, %s, %s, %s, %s)", (admin.id, action, table, target, json.dumps(details or {})))


# ---------------------------------------------------------------- employers
@router.get("/employers", response_model=list[AdminEmployer])
def list_employers(status: Literal["pending", "approved", "rejected", "blocked", "all"] = "pending",
                   admin: CurrentUser = Depends(admin_only), conn: psycopg.Connection = Depends(get_conn)):
    """Employer accounts to review (oldest first)."""
    where, params = ("", ()) if status == "all" else ("where e.verification_status = %s", (status,))
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(f"{EMPLOYER_SQL} {where} order by e.updated_at", params).fetchall()
    return [AdminEmployer(**r) for r in rows]


@router.post("/employers/{user_id}/review", response_model=AdminEmployer)
def review_employer(user_id: UUID, body: EmployerReview, admin: CurrentUser = Depends(admin_only),
                    conn: psycopg.Connection = Depends(get_conn)):
    """Approve, reject or block an employer. Blocking also takes all their live jobs down."""
    new_status = {"approve": "approved", "reject": "rejected", "block": "blocked"}[body.decision]
    with conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
        updated = cur.execute(
            """update public.employer_profiles set verification_status = %s, rejection_reason = %s,
                   reviewed_by = %s, reviewed_at = now()
               where user_id = %s returning user_id""",
            (new_status, None if body.decision == "approve" else body.reason, admin.id, user_id)).fetchone()
        if updated is None:
            raise HTTPException(404, "Employer not found")
        if body.decision == "block":
            cur.execute("update public.jobs set status = 'closed', closed_at = now() "
                        "where employer_id = %s and status = 'open'", (user_id,))
            cur.execute("update public.job_submissions set status = 'closed' "
                        "where employer_id = %s and status in ('pending', 'approved')", (user_id,))
        _log(conn, admin, f"{body.decision}_employer", "employer_profiles", str(user_id), {"reason": body.reason})
        row = cur.execute(f"{EMPLOYER_SQL} where e.user_id = %s", (user_id,)).fetchone()
    return AdminEmployer(**row)


# ---------------------------------------------------------------- job posts
@router.get("/submissions", response_model=list[AdminSubmission])
def list_submissions(status: Literal["pending", "approved", "rejected", "closed", "all"] = "pending",
                     limit: int = Query(50, ge=1, le=200),
                     admin: CurrentUser = Depends(admin_only), conn: psycopg.Connection = Depends(get_conn)):
    """Job posts to review. Riskiest first (highest spam score), then oldest."""
    where, params = ("", []) if status == "all" else ("where s.status = %s", [status])
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(f"{SUBMISSION_SQL} {where} order by s.spam_score desc nulls last, s.created_at "
                           "limit %s", (*params, limit)).fetchall()
    return [AdminSubmission(**r) for r in rows]


def _publish(cur, sub: dict) -> UUID:
    """Copy an approved post into the live jobs table."""
    return cur.execute(
        """insert into public.jobs (job_key, source, source_job_id, company_id, company_name, title, description,
               location_raw, area, apply_url, salary_min, salary_max, experience_min, experience_max, job_type,
               work_mode, skills, posted_at, employer_id, status)
           values (%s, 'employer', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), %s, 'open')
           returning id""",
        (f"employer-{sub['id']}", str(sub["id"]), sub["company_id"], sub["company_name"], sub["title"],
         sub["description"], sub["location"], sub["area"], sub["apply_url"], sub["salary_min"], sub["salary_max"],
         sub["experience_min"], sub["experience_max"], sub["job_type"], sub["work_mode"], sub["skills"],
         sub["employer_id"])).fetchone()["id"]


def _embed_now(conn: psycopg.Connection, job_id: UUID, sub: dict) -> None:
    """Give the new job its AI embedding right away. If that fails, the daily update does it."""
    try:
        text = job_text(sub["title"], sub["skills"], sub["description"])
        conn.execute("update public.jobs set embedding = %s::extensions.vector, embedding_hash = %s where id = %s",
                     (to_pgvector(embed_one(text)), text_hash(text), job_id))
    except Exception as error:                       # never fail the approval because of this
        log.warning("could not embed job %s now: %s", job_id, error)


@router.post("/submissions/{submission_id}/review", response_model=AdminSubmission)
def review_submission(submission_id: UUID, body: SubmissionReview, admin: CurrentUser = Depends(admin_only),
                      conn: psycopg.Connection = Depends(get_conn)):
    """Approve (the job goes live at once) or reject (the employer sees the reason)."""
    published_id = None
    with conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
        sub = cur.execute(f"{SUBMISSION_SQL} where s.id = %s for update of s", (submission_id,)).fetchone()
        if sub is None:
            raise HTTPException(404, "Job post not found")
        if sub["status"] != "pending":
            raise HTTPException(409, f"This post is already {sub['status']}.")
        if body.decision == "approve":
            if sub["employer_status"] != "approved":
                raise HTTPException(409, "Approve the employer's company details first.")
            published_id = _publish(cur, sub)
            cur.execute("""update public.job_submissions set status = 'approved', reviewed_by = %s,
                               reviewed_at = now(), published_job_id = %s where id = %s""",
                        (admin.id, published_id, submission_id))
        else:
            cur.execute("""update public.job_submissions set status = 'rejected', rejection_reason = %s,
                               reviewed_by = %s, reviewed_at = now() where id = %s""",
                        (body.reason, admin.id, submission_id))
        _log(conn, admin, f"{body.decision}_submission", "job_submissions", str(submission_id),
             {"reason": body.reason, "published_job_id": str(published_id) if published_id else None,
              "spam_score": float(sub["spam_score"]) if sub["spam_score"] is not None else None})
    if published_id:
        _embed_now(conn, published_id, sub)
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(f"{SUBMISSION_SQL} where s.id = %s", (submission_id,)).fetchone()
    return AdminSubmission(**row)
