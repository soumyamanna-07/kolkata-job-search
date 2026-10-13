"""Admin Panel: how many people use the site - for the dashboard, and later for ads and sponsors.

GET /api/admin/usage
  accounts      : all accounts, and new ones today / last 7 / last 30 days
  active_users  : logged-in people who did something with a job (viewed, applied, saved, tracked)
  visitors      : guests (not logged in), counted by their anonymous browser id
  applications  : how many jobs people track in "My applications", by stage
  daily         : the last 30 days, one row per day (India time)
Days are counted in India time. Only totals are returned - never who did what.
"""
from datetime import date

import psycopg
from fastapi import APIRouter, Depends
from psycopg.rows import dict_row
from pydantic import BaseModel

from app.auth import CurrentUser
from app.db import get_conn
from app.routers.admin import admin_only

router = APIRouter(prefix="/api/admin/usage", tags=["admin"])

IST = "Asia/Kolkata"
STAGES = ("applied", "interview", "offer", "rejected", "no_reply")

# one row per logged-in user action, from every place a user leaves a trace
ACTIVITY_SQL = """
    select user_id, created_at as at from public.job_events where user_id is not null
    union all select user_id, updated_at from public.applications
    union all select user_id, created_at from public.saved_jobs
"""


class Window(BaseModel):
    today: int
    days_7: int
    days_30: int


class Day(BaseModel):
    day: date
    new_accounts: int
    active_users: int
    visitors: int


class Usage(BaseModel):
    accounts_total: int
    new_accounts: Window
    active_users: Window
    visitors: Window
    applications_total: int
    applications_new_7_days: int
    applications_by_stage: dict[str, int]
    daily: list[Day]


def _window(conn: psycopg.Connection, sql: str) -> Window:
    """sql selects (id, at); counts distinct ids since the start of today, and in the last 7 / 30 days (IST)."""
    row = conn.execute(f"""
        with t as ({sql}), start as (select (date_trunc('day', now() at time zone '{IST}')) at time zone '{IST}' as today)
        select count(distinct id) filter (where at >= (select today from start)),
               count(distinct id) filter (where at >= now() - interval '7 days'),
               count(distinct id) filter (where at >= now() - interval '30 days')
        from t""").fetchone()
    return Window(today=row[0], days_7=row[1], days_30=row[2])


@router.get("", response_model=Usage)
def usage(admin: CurrentUser = Depends(admin_only), conn: psycopg.Connection = Depends(get_conn)):
    """Site usage totals for the admin dashboard."""
    accounts = "select id, created_at as at from public.profiles"
    active = f"select user_id as id, at from ({ACTIVITY_SQL}) a"
    guests = "select session_id as id, created_at as at from public.job_events where session_id is not null"

    by_stage = dict(conn.execute("select status, count(*) from public.applications group by 1").fetchall())
    apps_total, apps_new = conn.execute(
        "select count(*), count(*) filter (where applied_at >= now() - interval '7 days') "
        "from public.applications").fetchone()

    with conn.cursor(row_factory=dict_row) as cur:
        daily = cur.execute(f"""
            with days as (
                select generate_series((now() at time zone '{IST}')::date - 29, (now() at time zone '{IST}')::date,
                                       interval '1 day')::date as day),
            acc as (select (created_at at time zone '{IST}')::date as day, count(*) as n
                    from public.profiles group by 1),
            act as (select (at at time zone '{IST}')::date as day, count(distinct user_id) as n
                    from ({ACTIVITY_SQL}) a group by 1),
            vis as (select (created_at at time zone '{IST}')::date as day, count(distinct session_id) as n
                    from public.job_events where session_id is not null group by 1)
            select d.day, coalesce(acc.n, 0) as new_accounts, coalesce(act.n, 0) as active_users,
                   coalesce(vis.n, 0) as visitors
            from days d left join acc using (day) left join act using (day) left join vis using (day)
            order by d.day""").fetchall()

    return Usage(
        accounts_total=conn.execute("select count(*) from public.profiles").fetchone()[0],
        new_accounts=_window(conn, accounts),
        active_users=_window(conn, active),
        visitors=_window(conn, guests),
        applications_total=apps_total,
        applications_new_7_days=apps_new,
        applications_by_stage={stage: by_stage.get(stage, 0) for stage in STAGES},
        daily=[Day(**d) for d in daily],
    )
