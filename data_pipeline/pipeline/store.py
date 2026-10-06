"""Everything the pipeline writes to / reads from the database."""
import json
from dataclasses import asdict

import psycopg

from pipeline.collectors.base import CollectResult
from pipeline.models import CleanJob
from pipeline.normalize import MAX_JOB_AGE_DAYS

# Higher number wins when two sources describe the same job (same job_key)
PRIORITY_SQL = """case {col}
    when 'employer' then 3
    when 'greenhouse' then 2 when 'lever' then 2 when 'ashby' then 2
    when 'smartrecruiters' then 2 when 'workable' then 2
    else 1 end"""

UPSERT_SQL = f"""
insert into public.jobs (
    job_key, source, source_job_id, company_id, company_name, title, description,
    location_raw, area, apply_url, salary_min, salary_max, salary_period,
    experience_min, experience_max, job_type, work_mode, skills, posted_at,
    last_seen_at, status, closed_at)
values (
    %(job_key)s, %(source)s, %(source_job_id)s, %(company_id)s, %(company_name)s, %(title)s,
    %(description)s, %(location_raw)s, %(area)s, %(apply_url)s, %(salary_min)s, %(salary_max)s,
    %(salary_period)s, %(experience_min)s, %(experience_max)s, %(job_type)s, %(work_mode)s,
    %(skills)s, %(posted_at)s, now(), 'open', null)
on conflict (job_key) do update set
    source = excluded.source, source_job_id = excluded.source_job_id,
    company_id = coalesce(excluded.company_id, jobs.company_id),
    company_name = excluded.company_name, title = excluded.title,
    description = excluded.description, location_raw = excluded.location_raw,
    area = excluded.area, apply_url = excluded.apply_url,
    salary_min = excluded.salary_min, salary_max = excluded.salary_max,
    salary_period = excluded.salary_period,
    experience_min = excluded.experience_min, experience_max = excluded.experience_max,
    job_type = excluded.job_type, work_mode = excluded.work_mode, skills = excluded.skills,
    posted_at = coalesce(excluded.posted_at, jobs.posted_at),
    last_seen_at = now(), status = 'open', closed_at = null
where {PRIORITY_SQL.format(col='excluded.source')} >= {PRIORITY_SQL.format(col='jobs.source')}
returning (xmax = 0) as inserted
"""

# Jobs seen this run but owned by a higher-priority source: just mark them as still open.
TOUCH_SQL = """
update public.jobs
set last_seen_at = now(), status = 'open', closed_at = null
where job_key = any(%s) and source <> 'employer'
"""

CLOSE_SQL = """
update public.jobs
set status = 'closed', closed_at = now()
where status = 'open'
  and source = %s
  and company_id is not distinct from %s
  and last_seen_at < %s
returning id
"""

# "Current jobs only": close anything posted (or first seen, if no date) more than
# MAX_JOB_AGE_DAYS ago. Employer-posted jobs are managed by the employer, so they are skipped.
EXPIRE_SQL = """
update public.jobs
set status = 'closed', closed_at = now()
where status = 'open'
  and source <> 'employer'
  and coalesce(posted_at, first_seen_at) < now() - make_interval(days => %s)
returning id
"""

COUNT_OPEN_SQL = """
select count(*) from public.jobs
where status = 'open' and source = %s and company_id is not distinct from %s
"""

# If a source suddenly returns zero jobs but we have at least this many open,
# assume the source is broken rather than "every job closed at once".
SUSPICIOUS_EMPTY_THRESHOLD = 5


def load_companies(conn: psycopg.Connection) -> list[dict]:
    """Active companies that have a job-board code on a platform we can collect from."""
    rows = conn.execute(
        """select id::text, name, ats_platform, ats_token from public.companies
           where is_active and ats_token is not null
             and ats_platform in ('greenhouse', 'lever', 'ashby', 'workable')
           order by name"""
    ).fetchall()
    return [dict(id=r[0], name=r[1], ats_platform=r[2], ats_token=r[3]) for r in rows]


def start_run(conn: psycopg.Connection, trigger: str):
    """Create the pipeline_runs row. Returns (run_id, started_at)."""
    return conn.execute(
        "insert into public.pipeline_runs (trigger_type) values (%s) returning id, started_at",
        (trigger,),
    ).fetchone()


def finish_run(conn: psycopg.Connection, run_id: int, status: str, stats: dict, error: str = None) -> None:
    conn.execute(
        """update public.pipeline_runs set
             finished_at = now(), status = %s, total_collected = %s, kolkata_count = %s,
             unique_count = %s, jobs_new = %s, jobs_updated = %s, jobs_closed = %s,
             source_stats = %s, error_message = %s
           where id = %s""",
        (status, stats.get("total_collected", 0), stats.get("kolkata_count", 0),
         stats.get("unique_count", 0), stats.get("jobs_new", 0), stats.get("jobs_updated", 0),
         stats.get("jobs_closed", 0), json.dumps(stats.get("source_stats", {})),
         (error or "")[:2000] or None, run_id),
    )


def save_jobs(conn: psycopg.Connection, jobs: list[CleanJob]) -> tuple[int, int]:
    """Insert new jobs and update existing ones. Returns (new_count, updated_count)."""
    if not jobs:
        return 0, 0
    params = [asdict(job) for job in jobs]
    new = updated = 0
    with conn.cursor() as cur:
        cur.executemany(UPSERT_SQL, params, returning=True)
        while True:
            row = cur.fetchone()
            if row is not None:
                if row[0]:
                    new += 1
                else:
                    updated += 1
            if not cur.nextset():
                break
        cur.execute(TOUCH_SQL, ([job.job_key for job in jobs],))
    return new, updated


def close_missing(conn: psycopg.Connection, results: list[CollectResult], run_started_at) -> tuple[int, list[str]]:
    """Close open jobs that a COMPLETE source/company no longer lists.

    Returns (closed_count, warnings).
    """
    closed = 0
    warnings = []
    for r in results:
        if not r.complete or not r.snapshot:
            continue                                # never close on partial, failed or "recent only" data
        open_now = conn.execute(COUNT_OPEN_SQL, (r.source, r.company_id)).fetchone()[0]
        if not r.jobs and open_now >= SUSPICIOUS_EMPTY_THRESHOLD:
            warnings.append(f"{r.scope}: returned 0 jobs but {open_now} are open - not closing (check source)")
            continue
        closed += len(conn.execute(CLOSE_SQL, (r.source, r.company_id, run_started_at)).fetchall())
    return closed, warnings


def close_expired(conn: psycopg.Connection, max_age_days: int = MAX_JOB_AGE_DAYS) -> int:
    """Close open jobs that are older than max_age_days. Returns how many were closed."""
    return len(conn.execute(EXPIRE_SQL, (max_age_days,)).fetchall())
