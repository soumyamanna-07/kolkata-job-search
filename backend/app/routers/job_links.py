"""Submit a job link: students and college TPOs share Kolkata jobs they found (placement drives,
company career pages, notices). An admin opens the link, fills in the details and approves it;
only then does it go live (source "campus" for TPOs, "community" for everyone else).

Users:  POST /api/job-links, GET /api/me/job-links
Admins: GET /api/admin/job-links, POST /api/admin/job-links/{id}/review
"""
from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query, status
from psycopg.rows import dict_row
from pydantic import BaseModel, Field, model_validator

from app.auth import CurrentUser, get_current_user
from app.db import get_conn
from app.ratelimit import PerKeyLimiter
from app.routers.admin import _embed_now, _log, admin_only
from app.schemas import Area, JobType, WorkMode
from app.skills import extract_skills
from app.spam import LINK_SHORTENERS, _host

router = APIRouter(prefix="/api", tags=["job links"])
links_per_day = PerKeyLimiter(10, window=86400)
URL_PATTERN = r"^https?://\S+$"


class JobLinkIn(BaseModel):
    url: str = Field(max_length=500, pattern=URL_PATTERN, description="link to the job post or notice")
    company_name: Optional[str] = Field(default=None, max_length=120)
    title: Optional[str] = Field(default=None, max_length=120)
    note: Optional[str] = Field(default=None, max_length=500, description="e.g. 'campus drive on 20 Oct, 2025 batch'")
    submitter_type: Literal["user", "tpo"] = "user"     # "tpo" = college placement officer (admin verifies)


class JobLink(JobLinkIn):
    id: UUID
    status: str                       # pending / approved / rejected
    rejection_reason: Optional[str] = None
    published_job_id: Optional[UUID] = None
    created_at: datetime


class AdminJobLink(JobLink):
    submitted_by_email: Optional[str] = None


class JobLinkReview(BaseModel):
    """To approve, the admin opens the link and fills in the job details."""
    decision: Literal["approve", "reject"]
    reason: Optional[str] = Field(default=None, max_length=500)
    title: Optional[str] = Field(default=None, min_length=3, max_length=120)
    company_name: Optional[str] = Field(default=None, min_length=2, max_length=120)
    description: Optional[str] = Field(default=None, min_length=30, max_length=8000)
    area: Area = "Kolkata"
    job_type: Optional[JobType] = None
    work_mode: Optional[WorkMode] = None
    salary_min: Optional[int] = Field(default=None, ge=0, le=100_000_000)
    salary_max: Optional[int] = Field(default=None, ge=0, le=100_000_000)
    experience_min: Optional[float] = Field(default=None, ge=0, le=50)
    experience_max: Optional[float] = Field(default=None, ge=0, le=50)

    @model_validator(mode="after")
    def _details(self) -> "JobLinkReview":
        if self.decision == "reject" and not (self.reason or "").strip():
            raise ValueError("Please give a reason (the person who shared it will see it)")
        if self.decision == "approve" and not (self.title and self.company_name and self.description):
            raise ValueError("To approve, fill in title, company_name and description from the job page")
        return self


COLUMNS = ("l.id, l.url, l.company_name, l.title, l.note, l.submitter_type, l.status, l.rejection_reason, "
           "l.published_job_id, l.created_at")


# ---------------------------------------------------------------- users
@router.post("/job-links", response_model=JobLink, status_code=status.HTTP_201_CREATED)
def submit_link(body: JobLinkIn, user: CurrentUser = Depends(get_current_user),
                conn: psycopg.Connection = Depends(get_conn)):
    """Share a Kolkata job link. It goes live after an admin checks it."""
    url = body.url.strip()
    if _host(url) in LINK_SHORTENERS:
        raise HTTPException(422, "Please share the full link, not a shortened one (bit.ly etc.).")
    if conn.execute("select 1 from public.jobs where apply_url = %s and status = 'open'", (url,)).fetchone():
        raise HTTPException(409, "This job is already on the site. Thank you!")
    if conn.execute("select 1 from public.job_link_submissions where url = %s and status in ('pending', 'approved')",
                    (url,)).fetchone():
        raise HTTPException(409, "Someone already shared this link. Thank you!")
    if not links_per_day.allow(user.id):
        raise HTTPException(429, "You can share up to 10 links a day. Please try again tomorrow.")
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(
            f"""insert into public.job_link_submissions as l (submitted_by, submitter_type, url, company_name,
                                                           title, note)
                values (%s, %s, %s, %s, %s, %s) returning {COLUMNS}""",
            (user.id, body.submitter_type, url, (body.company_name or "").strip() or None,
             (body.title or "").strip() or None, (body.note or "").strip() or None)).fetchone()


@router.get("/me/job-links", response_model=list[JobLink])
def my_links(user: CurrentUser = Depends(get_current_user), conn: psycopg.Connection = Depends(get_conn)):
    """Links you shared, newest first, with their review status."""
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(f"select {COLUMNS} from public.job_link_submissions l where l.submitted_by = %s "
                           "order by l.created_at desc", (user.id,)).fetchall()


# ---------------------------------------------------------------- admins
ADMIN_SQL = f"""select {COLUMNS}, u.email as submitted_by_email
                from public.job_link_submissions l left join auth.users u on u.id = l.submitted_by"""


@router.get("/admin/job-links", response_model=list[AdminJobLink])
def list_links(status_filter: Literal["pending", "approved", "rejected", "all"] = Query("pending", alias="status"),
               limit: int = Query(50, ge=1, le=200), admin: CurrentUser = Depends(admin_only),
               conn: psycopg.Connection = Depends(get_conn)):
    """Shared links to review, oldest first. TPO links first: they are usually campus drives."""
    where, params = ("", []) if status_filter == "all" else ("where l.status = %s", [status_filter])
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(f"{ADMIN_SQL} {where} order by (l.submitter_type = 'tpo') desc, l.created_at limit %s",
                           (*params, limit)).fetchall()


@router.post("/admin/job-links/{link_id}/review", response_model=AdminJobLink)
def review_link(link_id: UUID, body: JobLinkReview, admin: CurrentUser = Depends(admin_only),
                conn: psycopg.Connection = Depends(get_conn)):
    """Approve (the job goes live at once, with the details you filled in) or reject (with a reason)."""
    published_id, job = None, None
    with conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
        link = cur.execute("select * from public.job_link_submissions where id = %s for update", (link_id,)).fetchone()
        if link is None:
            raise HTTPException(404, "Link not found")
        if link["status"] != "pending":
            raise HTTPException(409, f"This link is already {link['status']}.")
        if body.decision == "approve":
            job = {"title": body.title.strip(), "skills": extract_skills(f"{body.title}\n{body.description}"),
                   "description": body.description.strip()}
            published_id = cur.execute(
                """insert into public.jobs (job_key, source, source_job_id, company_name, title, description, area,
                       apply_url, salary_min, salary_max, experience_min, experience_max, job_type, work_mode, skills,
                       posted_at, status)
                   values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), 'open') returning id""",
                (f"link-{link_id}", "campus" if link["submitter_type"] == "tpo" else "community", str(link_id),
                 body.company_name.strip(), job["title"], job["description"], body.area, link["url"],
                 body.salary_min, body.salary_max, body.experience_min, body.experience_max, body.job_type,
                 body.work_mode, job["skills"])).fetchone()["id"]
            cur.execute("""update public.job_link_submissions set status = 'approved', reviewed_by = %s,
                               reviewed_at = now(), published_job_id = %s,
                               title = coalesce(title, %s), company_name = coalesce(company_name, %s)
                           where id = %s""", (admin.id, published_id, job["title"], body.company_name, link_id))
        else:
            cur.execute("""update public.job_link_submissions set status = 'rejected', rejection_reason = %s,
                               reviewed_by = %s, reviewed_at = now() where id = %s""",
                        (body.reason.strip(), admin.id, link_id))
        _log(conn, admin, f"{body.decision}_job_link", "job_link_submissions", str(link_id),
             {"reason": body.reason, "published_job_id": str(published_id) if published_id else None})
    if published_id:
        _embed_now(conn, published_id, job)
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(f"{ADMIN_SQL} where l.id = %s", (link_id,)).fetchone()
