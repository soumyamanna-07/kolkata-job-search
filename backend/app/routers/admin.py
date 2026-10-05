"""Admin Panel API: employers and job posts to review, user reports, users, pipeline health,
site stats, models and the audit log. Every decision is logged in admin_actions.

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
from app.schemas import (AdminAction, AdminEmployer, AdminReport, AdminStats, AdminSubmission, AdminUser,
                         EmployerReview, ModelVersion, PipelineRun, ReportResolve, SubmissionReview, UserBlock)

router = APIRouter(prefix="/api/admin", tags=["admin"])
admin_only = require_role("admin")
log = logging.getLogger("kjs.admin")

EMPLOYER_SQL = """
select e.user_id, e.company_name, e.official_email, e.website, e.gst_or_cin, e.account_kind,
       e.verification_status, e.rejection_reason, e.updated_at, e.created_at, u.email as login_email
from public.employer_profiles e left join auth.users u on u.id = e.user_id
"""
SUBMISSION_SQL = """
select s.id, s.title, s.description, s.hiring_for, s.skills, s.location, s.area, s.apply_url, s.salary_min,
       s.salary_max, s.experience_min, s.experience_max, s.job_type, s.work_mode, s.status, s.rejection_reason,
       s.published_job_id, s.created_at, s.updated_at, s.employer_id, s.spam_score, s.spam_reasons,
       e.company_name, e.official_email, e.account_kind, e.verification_status as employer_status, e.company_id
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
    """Copy an approved post into the live jobs table. Agency posts show the client company,
    with the agency in posted_by ("via <agency>")."""
    agency = sub["account_kind"] == "agency" and bool(sub["hiring_for"])
    company_name = sub["hiring_for"] if agency else sub["company_name"]
    return cur.execute(
        """insert into public.jobs (job_key, source, source_job_id, company_id, company_name, posted_by, title,
               description, location_raw, area, apply_url, salary_min, salary_max, experience_min, experience_max,
               job_type, work_mode, skills, posted_at, employer_id, status)
           values (%s, 'employer', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), %s, 'open')
           returning id""",
        (f"employer-{sub['id']}", str(sub["id"]), None if agency else sub["company_id"], company_name,
         sub["company_name"] if agency else None, sub["title"], sub["description"], sub["location"], sub["area"],
         sub["apply_url"], sub["salary_min"], sub["salary_max"], sub["experience_min"], sub["experience_max"],
         sub["job_type"], sub["work_mode"], sub["skills"], sub["employer_id"])).fetchone()["id"]


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


# ---------------------------------------------------------------- user reports
REPORT_SQL = """
select r.id, r.job_id, j.title as job_title, j.company_name, j.source as job_source, j.status as job_status,
       j.apply_url, r.reason, r.details, r.status, r.created_at,
       (select count(*) from public.job_reports r2 where r2.job_id = r.job_id and r2.status = 'open') as reports_for_job
from public.job_reports r join public.jobs j on j.id = r.job_id
"""


@router.get("/reports", response_model=list[AdminReport])
def list_reports(status: Literal["open", "resolved", "dismissed", "all"] = "open",
                 limit: int = Query(100, ge=1, le=500),
                 admin: CurrentUser = Depends(admin_only), conn: psycopg.Connection = Depends(get_conn)):
    """Jobs users reported. Jobs with the most reports first."""
    where, params = ("", []) if status == "all" else ("where r.status = %s", [status])
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(f"{REPORT_SQL} {where} order by reports_for_job desc, r.created_at limit %s",
                           (*params, limit)).fetchall()
    return [AdminReport(**r) for r in rows]


@router.post("/reports/{report_id}/resolve", response_model=AdminReport)
def resolve_report(report_id: UUID, body: ReportResolve, admin: CurrentUser = Depends(admin_only),
                   conn: psycopg.Connection = Depends(get_conn)):
    """close_job: take the job down and resolve ALL open reports on it. dismiss: the report was wrong."""
    with conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
        report = cur.execute("select job_id, status from public.job_reports where id = %s for update",
                             (report_id,)).fetchone()
        if report is None:
            raise HTTPException(404, "Report not found")
        if report["status"] != "open":
            raise HTTPException(409, f"This report is already {report['status']}.")
        if body.action == "close_job":
            cur.execute("update public.jobs set status = 'closed', closed_at = now() "
                        "where id = %s and status = 'open'", (report["job_id"],))
            cur.execute("""update public.job_reports set status = 'resolved', resolved_by = %s, resolved_at = now()
                           where job_id = %s and status = 'open'""", (admin.id, report["job_id"]))
        else:
            cur.execute("""update public.job_reports set status = 'dismissed', resolved_by = %s, resolved_at = now()
                           where id = %s""", (admin.id, report_id))
        _log(conn, admin, f"report_{body.action}", "job_reports", str(report_id),
             {"job_id": str(report["job_id"]), "note": body.note})
        row = cur.execute(f"{REPORT_SQL} where r.id = %s", (report_id,)).fetchone()
    return AdminReport(**row)


# ---------------------------------------------------------------- users
USER_SQL = """
select p.id, u.email, p.full_name, p.role, p.is_blocked, p.created_at,
       exists (select 1 from public.cvs c where c.user_id = p.id) as has_cv
from public.profiles p left join auth.users u on u.id = p.id
"""


@router.get("/users", response_model=list[AdminUser])
def list_users(q: Optional[str] = Query(None, max_length=100, description="part of an email or name"),
               role: Optional[Literal["candidate", "employer", "admin"]] = None,
               blocked: Optional[bool] = None, limit: int = Query(50, ge=1, le=200),
               admin: CurrentUser = Depends(admin_only), conn: psycopg.Connection = Depends(get_conn)):
    """Find users (newest first). The CV itself is never shown here, only whether one is saved."""
    where, params = [], []
    if q:
        like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        where.append("(u.email ilike %s or p.full_name ilike %s)")
        params += [like, like]
    if role:
        where.append("p.role = %s")
        params.append(role)
    if blocked is not None:
        where.append("p.is_blocked = %s")
        params.append(blocked)
    where_sql = ("where " + " and ".join(where)) if where else ""
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(f"{USER_SQL} {where_sql} order by p.created_at desc limit %s", (*params, limit)).fetchall()
    return [AdminUser(**r) for r in rows]


@router.post("/users/{user_id}/block", response_model=AdminUser)
def block_user(user_id: UUID, body: UserBlock, admin: CurrentUser = Depends(admin_only),
               conn: psycopg.Connection = Depends(get_conn)):
    """Block or unblock a user. A blocked user can't use any logged-in feature. Admins can't be blocked here."""
    if str(user_id) == admin.id:
        raise HTTPException(409, "You can't block yourself.")
    with conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
        target = cur.execute("select role from public.profiles where id = %s", (user_id,)).fetchone()
        if target is None:
            raise HTTPException(404, "User not found")
        if target["role"] == "admin":
            raise HTTPException(409, "Admins can't be blocked from the panel.")
        cur.execute("update public.profiles set is_blocked = %s where id = %s", (body.blocked, user_id))
        _log(conn, admin, "block_user" if body.blocked else "unblock_user", "profiles", str(user_id),
             {"reason": body.reason})
        row = cur.execute(f"{USER_SQL} where p.id = %s", (user_id,)).fetchone()
    return AdminUser(**row)


# ---------------------------------------------------------------- health, stats, models, audit
@router.get("/pipeline-runs", response_model=list[PipelineRun])
def pipeline_runs(limit: int = Query(20, ge=1, le=100), admin: CurrentUser = Depends(admin_only),
                  conn: psycopg.Connection = Depends(get_conn)):
    """Pipeline Health: the latest job-collection runs."""
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute("select * from public.pipeline_runs order by started_at desc limit %s", (limit,)).fetchall()
    return [PipelineRun(**r) for r in rows]


@router.get("/stats", response_model=AdminStats)
def stats(admin: CurrentUser = Depends(admin_only), conn: psycopg.Connection = Depends(get_conn)):
    """Numbers for the Admin Panel dashboard."""
    one = lambda sql: conn.execute(sql).fetchone()[0]
    with conn.cursor(row_factory=dict_row) as cur:
        last = cur.execute("select * from public.pipeline_runs order by started_at desc limit 1").fetchone()
    return AdminStats(
        open_jobs=one("select count(*) from public.jobs where status = 'open'"),
        open_jobs_by_source=dict(conn.execute("select source, count(*) from public.jobs where status = 'open' "
                                              "group by 1 order by 2 desc").fetchall()),
        new_jobs_7_days=one("select count(*) from public.jobs where first_seen_at >= now() - interval '7 days'"),
        jobs_without_embedding=one("select count(*) from public.jobs where status = 'open' and embedding is null"),
        users_by_role=dict(conn.execute("select role, count(*) from public.profiles group by 1").fetchall()),
        blocked_users=one("select count(*) from public.profiles where is_blocked"),
        saved_cvs=one("select count(*) from public.cvs"),
        pending_employers=one("select count(*) from public.employer_profiles where verification_status = 'pending'"),
        pending_job_posts=one("select count(*) from public.job_submissions where status = 'pending'"),
        open_reports=one("select count(*) from public.job_reports where status = 'open'"),
        last_pipeline_run=PipelineRun(**last) if last else None,
    )


@router.get("/models", response_model=list[ModelVersion])
def models(admin: CurrentUser = Depends(admin_only), conn: psycopg.Connection = Depends(get_conn)):
    """Model Monitoring: which model/rules version each AI feature uses."""
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute("select model_name, version, is_active, metrics, notes, trained_at "
                           "from public.model_versions order by model_name, trained_at desc").fetchall()
    return [ModelVersion(**r) for r in rows]


@router.get("/actions", response_model=list[AdminAction])
def audit_log(limit: int = Query(50, ge=1, le=500), admin: CurrentUser = Depends(admin_only),
              conn: psycopg.Connection = Depends(get_conn)):
    """Audit log: every admin decision, newest first."""
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute("""select a.id, u.email as admin_email, a.action, a.target_table, a.target_id,
                                     a.details, a.created_at
                              from public.admin_actions a left join auth.users u on u.id = a.admin_id
                              order by a.created_at desc, a.id desc limit %s""", (limit,)).fetchall()
    return [AdminAction(**r) for r in rows]
