"""Admin Panel: Company List - the Kolkata companies whose own job boards the pipeline reads.

Add a company with its Greenhouse / Lever / Ashby / Workable board code, and the next pipeline run
collects its Kolkata jobs directly (better quality than aggregators). Check the board code first
with POST /api/admin/companies/check-board. Any other company with a careers_url is read by the
career-page reader (Google-Jobs tags); a "government" office's careers_url is its official recruitment
page, read daily for current notices. Every change is written to the audit log.
"""
from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query, status
from psycopg.rows import dict_row
from pydantic import BaseModel, Field, model_validator

from app import companies
from app.auth import CurrentUser
from app.db import get_conn
from app.routers.admin import _log, admin_only

router = APIRouter(prefix="/api/admin", tags=["admin"])
Platform = Literal["greenhouse", "lever", "ashby", "smartrecruiters", "workable",
                   "zoho_recruit", "freshteam", "keka", "darwinbox", "government", "other"]


class CompanyIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    website: Optional[str] = Field(default=None, max_length=300, pattern=r"^https?://\S+$")
    careers_url: Optional[str] = Field(default=None, max_length=500, pattern=r"^https?://\S+$")
    ats_platform: Platform = "other"
    ats_token: Optional[str] = Field(default=None, max_length=100, pattern=companies.TOKEN_PATTERN,
                                     description="board code, e.g. 'abctech' from boards.greenhouse.io/abctech")
    notes: Optional[str] = Field(default=None, max_length=500)
    is_active: bool = True

    @model_validator(mode="after")
    def _board_code(self) -> "CompanyIn":
        self.name = self.name.strip()
        if self.ats_platform in companies.COLLECTED_PLATFORMS and not self.ats_token:
            raise ValueError(f"add the {self.ats_platform} board code (ats_token), or the pipeline can't collect it")
        if self.ats_platform == "government" and not self.careers_url:
            raise ValueError("add the office's official recruitment page (careers_url)")
        return self


class Company(CompanyIn):
    id: UUID
    collected: bool                       # True = the daily pipeline reads its job board or careers page
    open_jobs: int = 0
    last_job_seen_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class BoardCheckIn(BaseModel):
    ats_platform: Literal["greenhouse", "lever", "ashby", "workable"]
    ats_token: str = Field(min_length=1, max_length=100, pattern=companies.TOKEN_PATTERN)


class BoardCheckOut(BaseModel):
    ok: bool
    jobs: int = 0                         # all open jobs on the board
    kolkata_jobs: int = 0                 # of those, in Kolkata / Salt Lake / New Town / Howrah
    sample_titles: list[str] = []
    error: Optional[str] = None


LIST_SQL = """
select c.id, c.name, c.website, c.careers_url, c.ats_platform, c.ats_token, c.notes, c.is_active,
       c.created_at, c.updated_at,
       (c.is_active and ((c.ats_token is not null and c.ats_platform = any(%(collected)s))
                         or (c.careers_url is not null and c.ats_platform <> all(%(collected)s)))) as collected,
       count(j.id) filter (where j.status = 'open') as open_jobs,
       max(j.last_seen_at) as last_job_seen_at
from public.companies c left join public.jobs j on j.company_id = c.id
{where}
group by c.id
order by c.name
"""


def _one(conn: psycopg.Connection, company_id) -> dict:
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(LIST_SQL.format(where="where c.id = %(id)s"),
                          {"id": company_id, "collected": list(companies.COLLECTED_PLATFORMS)}).fetchone()
    if row is None:
        raise HTTPException(404, "Company not found")
    return row


DUPLICATE = "This company (or this board code) is already in the list."


@router.get("/companies", response_model=list[Company])
def list_companies(q: Optional[str] = Query(None, max_length=100), platform: Optional[Platform] = None,
                   active: Optional[bool] = None, admin: CurrentUser = Depends(admin_only),
                   conn: psycopg.Connection = Depends(get_conn)):
    """The Company List, A-Z, with how many open jobs each company has right now."""
    where, params = [], {"collected": list(companies.COLLECTED_PLATFORMS)}
    if q:
        where.append("c.name ilike %(q)s")
        params["q"] = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    if platform:
        where.append("c.ats_platform = %(platform)s")
        params["platform"] = platform
    if active is not None:
        where.append("c.is_active = %(active)s")
        params["active"] = active
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(LIST_SQL.format(where=("where " + " and ".join(where)) if where else ""),
                           params).fetchall()


@router.post("/companies/check-board", response_model=BoardCheckOut)
def check_board(body: BoardCheckIn, admin: CurrentUser = Depends(admin_only)):
    """Look at a job board before adding it: does the code work, how many Kolkata jobs?"""
    with companies.make_client() as client:
        return companies.check_board(client, body.ats_platform, body.ats_token).__dict__


@router.post("/companies", response_model=Company, status_code=status.HTTP_201_CREATED)
def add_company(body: CompanyIn, admin: CurrentUser = Depends(admin_only),
                conn: psycopg.Connection = Depends(get_conn)):
    """Add a company. With a Greenhouse / Lever / Ashby / Workable board code, the next pipeline run collects
    its jobs."""
    try:
        with conn.transaction():
            new_id = conn.execute(
                """insert into public.companies (name, normalized_name, website, careers_url, ats_platform,
                                                 ats_token, notes, is_active, added_by)
                   values (%s, %s, %s, %s, %s, %s, %s, %s, %s) returning id""",
                (body.name, companies.normalize_company(body.name), body.website, body.careers_url,
                 body.ats_platform, body.ats_token, body.notes, body.is_active, admin.id)).fetchone()[0]
            _log(conn, admin, "add_company", "companies", str(new_id),
                 {"name": body.name, "platform": body.ats_platform, "token": body.ats_token})
    except psycopg.errors.UniqueViolation:
        raise HTTPException(409, DUPLICATE)
    return _one(conn, new_id)


@router.put("/companies/{company_id}", response_model=Company)
def update_company(company_id: UUID, body: CompanyIn, admin: CurrentUser = Depends(admin_only),
                   conn: psycopg.Connection = Depends(get_conn)):
    """Change a company (send all fields). is_active=false stops collecting it and closes its
    collected jobs at once (jobs posted by recruiters are not touched)."""
    try:
        with conn.transaction():
            updated = conn.execute(
                """update public.companies set name = %s, normalized_name = %s, website = %s, careers_url = %s,
                          ats_platform = %s, ats_token = %s, notes = %s, is_active = %s
                   where id = %s returning id""",
                (body.name, companies.normalize_company(body.name), body.website, body.careers_url,
                 body.ats_platform, body.ats_token, body.notes, body.is_active, company_id)).fetchone()
            if updated is None:
                raise HTTPException(404, "Company not found")
            closed = 0
            if not body.is_active:
                closed = len(conn.execute(
                    """update public.jobs set status = 'closed', closed_at = now(), close_reason = 'company_removed'
                       where company_id = %s and status = 'open' and source <> 'employer' returning id""",
                    (company_id,)).fetchall())
            _log(conn, admin, "update_company", "companies", str(company_id),
                 {"name": body.name, "platform": body.ats_platform, "token": body.ats_token,
                  "is_active": body.is_active, "jobs_closed": closed})
    except psycopg.errors.UniqueViolation:
        raise HTTPException(409, DUPLICATE)
    return _one(conn, company_id)
