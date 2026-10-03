"""Builds the SQL for job search from the user's filters.

Kept separate from the web layer so it can be unit-tested without a database.
Every user value goes in as a query PARAMETER (never pasted into SQL), so
search text cannot break or inject into the query.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

SORTS = ("relevance", "newest", "salary")
AREAS = ("Kolkata", "Salt Lake", "New Town", "Howrah")
JOB_TYPES = ("full_time", "part_time", "internship", "contract", "temporary")
WORK_MODES = ("onsite", "hybrid", "remote")

_SUMMARY_FIELDS = ("id", "title", "company_name", "area", "location_raw", "salary_min", "salary_max",
                   "salary_period", "experience_min", "experience_max", "job_type", "work_mode", "skills",
                   "posted_at", "apply_url", "source")


def summary_columns(alias: str = "") -> str:
    """SELECT list for a job summary. alias="j" gives j.id, j.title, ... for joins."""
    p = f"{alias}." if alias else ""
    cols = [f"{p}{name}" for name in _SUMMARY_FIELDS]
    cols.append(f"left(regexp_replace(coalesce({p}description, ''), '\\s+', ' ', 'g'), 300) as snippet")
    return ", ".join(cols)


SUMMARY_COLUMNS = summary_columns()


@dataclass
class JobFiltersIn:
    q: Optional[str] = None                       # free text: title, company, skills, description
    areas: list[str] = field(default_factory=list)
    companies: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    salary_expected: Optional[int] = None         # yearly INR the candidate wants
    include_undisclosed_salary: bool = True
    experience_years: Optional[float] = None      # candidate's experience
    job_types: list[str] = field(default_factory=list)
    work_modes: list[str] = field(default_factory=list)
    posted_within_days: Optional[int] = None
    seen_since: Optional[datetime] = None         # job alerts: only jobs we first saw after this time
    sort: str = "relevance"
    page: int = 1
    page_size: int = 20


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def build_search_query(f: JobFiltersIn) -> tuple[str, str, dict]:
    """Return (list_sql, count_sql, params)."""
    where = ["status = 'open'"]
    params: dict = {}
    rank_parts = []

    q = (f.q or "").strip()
    if q:
        params["q"] = q
        params["q_like"] = f"%{_escape_like(q)}%"
        where.append("(search_vector @@ websearch_to_tsquery('english', %(q)s)"
                     " or title ilike %(q_like)s or company_name ilike %(q_like)s)")
        rank_parts.append("ts_rank(search_vector, websearch_to_tsquery('english', %(q)s))")
        rank_parts.append("extensions.similarity(title, %(q)s)")

    if f.areas:
        params["areas"] = f.areas
        where.append("area = any(%(areas)s)")

    if f.companies:
        params["companies"] = f.companies
        where.append("company_name = any(%(companies)s)")

    if f.skills:
        params["skills"] = [s.lower() for s in f.skills]
        where.append("skills && %(skills)s::text[]")
        # more matching skills = more relevant
        rank_parts.append("cardinality(array(select unnest(skills) intersect select unnest(%(skills)s::text[]))) * 0.5")

    if f.salary_expected:
        params["salary_expected"] = f.salary_expected
        salary_ok = "coalesce(salary_max, salary_min) >= %(salary_expected)s"
        if f.include_undisclosed_salary:
            salary_ok = f"({salary_ok} or (salary_min is null and salary_max is null))"
        where.append(salary_ok)

    if f.experience_years is not None:
        params["experience_years"] = f.experience_years
        where.append("(experience_min is null or experience_min <= %(experience_years)s)")

    if f.job_types:
        params["job_types"] = f.job_types
        where.append("job_type = any(%(job_types)s)")

    if f.work_modes:
        params["work_modes"] = f.work_modes
        where.append("work_mode = any(%(work_modes)s)")

    if f.posted_within_days:
        params["posted_within_days"] = f.posted_within_days
        where.append("coalesce(posted_at, first_seen_at) >= now() - make_interval(days => %(posted_within_days)s)")

    if f.seen_since:
        params["seen_since"] = f.seen_since
        where.append("first_seen_at > %(seen_since)s")

    newest = "coalesce(posted_at, first_seen_at) desc"
    if f.sort == "salary":
        order = f"coalesce(salary_max, salary_min) desc nulls last, {newest}"
    elif f.sort == "relevance" and rank_parts:
        order = f"({' + '.join(rank_parts)}) desc, {newest}"
    else:
        order = newest                             # "newest", or relevance with nothing to rank by

    params["limit"] = f.page_size
    params["offset"] = (f.page - 1) * f.page_size
    where_sql = " and ".join(where)
    list_sql = f"""
        select {SUMMARY_COLUMNS}, count(*) over () as total_count
        from public.jobs
        where {where_sql}
        order by {order}, id
        limit %(limit)s offset %(offset)s
    """
    count_sql = f"select count(*) as total_count from public.jobs where {where_sql}"
    return list_sql, count_sql, params
