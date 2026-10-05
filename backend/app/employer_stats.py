"""Employer stats: how each job post is doing (shown in results, views, apply clicks, saves).

Counts come from job_events (what candidates do). The employer's own clicks on their
own jobs are not counted, so they cannot inflate their numbers.
"""
from typing import Optional

import psycopg
from psycopg.rows import dict_row

STATS_SQL = """
select s.id as submission_id, s.title, s.status, s.created_at as posted_at,
       j.id as job_id, j.status as job_status,
       count(e.id) filter (where e.event_type = 'impression')  as shown_in_results,
       count(e.id) filter (where e.event_type = 'view')        as views,
       count(distinct coalesce(e.user_id::text, e.session_id))
             filter (where e.event_type = 'view')              as unique_viewers,
       count(e.id) filter (where e.event_type = 'click_apply') as apply_clicks,
       count(e.id) filter (where e.event_type = 'save')        as saves,
       count(e.id) filter (where e.event_type = 'view'
                             and e.created_at > now() - interval '7 days')        as views_7_days,
       count(e.id) filter (where e.event_type = 'click_apply'
                             and e.created_at > now() - interval '7 days')        as apply_clicks_7_days
from public.job_submissions s
left join public.jobs j on j.id = s.published_job_id
left join public.job_events e on e.job_id = j.id and e.user_id is distinct from s.employer_id
where s.employer_id = %s
group by s.id, j.id
order by s.created_at desc
"""

COUNTS = ("shown_in_results", "views", "unique_viewers", "apply_clicks", "saves",
          "views_7_days", "apply_clicks_7_days")


def apply_rate(apply_clicks: int, views: int) -> Optional[float]:
    """Percent of views that led to an apply click. None until there are views."""
    return round(100 * apply_clicks / views, 1) if views else None


def employer_stats(conn: psycopg.Connection, employer_id: str) -> dict:
    with conn.cursor(row_factory=dict_row) as cur:
        jobs = cur.execute(STATS_SQL, (employer_id,)).fetchall()
    for job in jobs:
        job["apply_rate"] = apply_rate(job["apply_clicks"], job["views"])
    totals = {name: sum(job[name] for job in jobs) for name in COUNTS}
    totals["apply_rate"] = apply_rate(totals["apply_clicks"], totals["views"])
    totals["live_jobs"] = sum(1 for job in jobs if job["job_status"] == "open")
    totals["posts"] = len(jobs)
    return {"totals": totals, "jobs": jobs}
