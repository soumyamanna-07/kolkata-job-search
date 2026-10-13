"""Public job endpoints - work without login (guest mode)."""
import math
from typing import Annotated, Literal, Optional
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg.rows import dict_row

from app.db import get_conn
from app.job_search import AREAS, JOB_TYPES, SUMMARY_COLUMNS, WORK_MODES, JobFiltersIn, build_search_query
from app.schemas import JobDetail, JobFilters, JobSearchResponse, JobSummary

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

CsvList = Annotated[Optional[str], Query(description="comma-separated, e.g. python,sql")]


def _split(value: Optional[str], lower: bool = False) -> list[str]:
    items = [v.strip() for v in (value or "").split(",") if v.strip()]
    return [v.lower() for v in items] if lower else items


def _check_allowed(name: str, values: list[str], allowed: tuple) -> None:
    bad = [v for v in values if v not in allowed]
    if bad:
        raise HTTPException(422, f"Invalid {name}: {', '.join(bad)}. Allowed: {', '.join(allowed)}")


@router.get("", response_model=JobSearchResponse)
def search_jobs(
    conn: psycopg.Connection = Depends(get_conn),
    q: Annotated[Optional[str], Query(max_length=200, description="search text")] = None,
    area: CsvList = None,
    company: CsvList = None,
    skills: CsvList = None,
    salary_expected: Annotated[Optional[int], Query(ge=0, le=100_000_000, description="yearly INR")] = None,
    include_undisclosed_salary: bool = True,
    experience_years: Annotated[Optional[float], Query(ge=0, le=50)] = None,
    job_type: CsvList = None,
    work_mode: CsvList = None,
    posted_within_days: Annotated[Optional[int], Query(ge=1, le=365)] = None,
    direct_only: Annotated[bool, Query(description="only jobs that link straight to the employer")] = False,
    sort: Literal["relevance", "newest", "salary"] = "relevance",
    page: Annotated[int, Query(ge=1, le=1000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=50)] = 20,
):
    """Search OPEN Kolkata jobs with filters. Works for guests and logged-in users."""
    filters = JobFiltersIn(
        q=q, areas=_split(area), companies=_split(company), skills=_split(skills, lower=True),
        salary_expected=salary_expected, include_undisclosed_salary=include_undisclosed_salary,
        experience_years=experience_years, job_types=_split(job_type), work_modes=_split(work_mode),
        posted_within_days=posted_within_days, direct_only=direct_only, sort=sort, page=page, page_size=page_size,
    )
    _check_allowed("area", filters.areas, AREAS)
    _check_allowed("job_type", filters.job_types, JOB_TYPES)
    _check_allowed("work_mode", filters.work_modes, WORK_MODES)

    list_sql, count_sql, params = build_search_query(filters)
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(list_sql, params).fetchall()
        # empty page (e.g. page number too high): still report the real total
        total = rows[0]["total_count"] if rows else cur.execute(count_sql, params).fetchone()["total_count"]
    return JobSearchResponse(
        items=[JobSummary(**r) for r in rows],
        total=total, page=page, page_size=page_size,
        pages=math.ceil(total / page_size) if total else 0,
    )


@router.get("/filters", response_model=JobFilters)
def job_filters(conn: psycopg.Connection = Depends(get_conn)):
    """Options for the filter dropdowns (areas, companies, skills...) with job counts."""
    def facet(sql: str) -> list[dict]:
        return [{"value": r[0], "count": r[1]} for r in conn.execute(sql).fetchall()]

    total, sal_min, sal_max = conn.execute(
        "select count(*), min(coalesce(salary_min, salary_max)), max(coalesce(salary_max, salary_min)) "
        "from public.jobs where status = 'open'").fetchone()
    return JobFilters(
        total_open_jobs=total,
        areas=facet("select area, count(*) from public.jobs where status = 'open' group by 1 order by 2 desc"),
        companies=facet("select company_name, count(*) from public.jobs where status = 'open' "
                        "group by 1 order by 2 desc, 1 limit 200"),
        skills=facet("select s, count(*) from public.jobs, unnest(skills) s where status = 'open' "
                     "group by 1 order by 2 desc, 1 limit 100"),
        job_types=facet("select job_type, count(*) from public.jobs where status = 'open' "
                        "and job_type is not null group by 1 order by 2 desc"),
        work_modes=facet("select work_mode, count(*) from public.jobs where status = 'open' "
                         "and work_mode is not null group by 1 order by 2 desc"),
        salary_min=sal_min, salary_max=sal_max,
    )


@router.get("/{job_id}", response_model=JobDetail)
def get_job(job_id: UUID, conn: psycopg.Connection = Depends(get_conn)):
    """One job with its full description. Closed jobs are returned too (status = closed),
    so saved jobs can show "this job has closed"."""
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            f"select {SUMMARY_COLUMNS}, description, status, closed_at from public.jobs where id = %s",
            (job_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Job not found")
    return JobDetail(**row)
