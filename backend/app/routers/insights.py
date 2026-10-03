"""Market insights: what the Kolkata job market wants right now, from all CURRENT open jobs.

Public (guests too). Results are kept for 10 minutes, so busy pages don't hit the
database on every visit. Salaries use only jobs that state one (yearly INR,
middle of the min-max range).
"""
import threading
import time
from typing import Callable

import psycopg
from fastapi import APIRouter, Depends, HTTPException

from app.db import get_conn
from app.matching import NEUTRAL_SKILLS
from app.schemas import Count, MarketInsights, SalaryBand, SkillInsight
from app.skills import known_skill

router = APIRouter(prefix="/api/insights", tags=["insights"])
CACHE_SECONDS = 600
MIN_SALARY_SAMPLES = 5            # don't show a salary figure based on fewer jobs than this

_cache: dict[str, tuple[float, object]] = {}
_cache_lock = threading.Lock()

MIDPOINT = "((coalesce(salary_min, salary_max) + coalesce(salary_max, salary_min)) / 2.0)"
OPEN = "status = 'open'"


def _cached(key: str, build: Callable[[], object]) -> object:
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < CACHE_SECONDS:
            return hit[1]
    value = build()
    with _cache_lock:
        _cache[key] = (now, value)
    return value


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


def _counts(conn: psycopg.Connection, sql: str, params: tuple = ()) -> list[Count]:
    return [Count(value=str(v), count=c) for v, c in conn.execute(sql, params).fetchall()]


def _salary(conn: psycopg.Connection, where: str, params: tuple = ()) -> SalaryBand:
    n, p25, p50, p75 = conn.execute(
        f"""select count(*),
                   percentile_cont(0.25) within group (order by {MIDPOINT}),
                   percentile_cont(0.50) within group (order by {MIDPOINT}),
                   percentile_cont(0.75) within group (order by {MIDPOINT})
            from public.jobs where {where} and coalesce(salary_min, salary_max) is not null""", params).fetchone()
    if n < MIN_SALARY_SAMPLES:
        return SalaryBand(jobs_with_salary=n)
    return SalaryBand(jobs_with_salary=n, p25=round(p25), median=round(p50), p75=round(p75))


def _share(part: int, total: int) -> float:
    return round(100 * part / total, 1) if total else 0.0


def _market(conn: psycopg.Connection) -> MarketInsights:
    total = conn.execute(f"select count(*) from public.jobs where {OPEN}").fetchone()[0]
    neutral = sorted(NEUTRAL_SKILLS)
    top_skills = conn.execute(
        f"""select s, count(*) from public.jobs, unnest(skills) s
            where {OPEN} and s <> all(%s) group by s order by 2 desc, 1 limit 25""", (neutral,)).fetchall()
    fresher = conn.execute(f"select count(*) from public.jobs where {OPEN} and experience_min <= 1").fetchone()[0]
    return MarketInsights(
        open_jobs=total,
        fresher_friendly_jobs=fresher,
        fresher_friendly_share=_share(fresher, total),
        top_skills=[SkillInsight(skill=s, jobs=n, share=_share(n, total),
                                 salary=_salary(conn, f"{OPEN} and %s = any(skills)", (s,)))
                    for s, n in top_skills],
        top_companies=_counts(conn, f"select company_name, count(*) from public.jobs where {OPEN} "
                                    "group by 1 order by 2 desc, 1 limit 15"),
        by_area=_counts(conn, f"select area, count(*) from public.jobs where {OPEN} group by 1 order by 2 desc"),
        by_job_type=_counts(conn, f"select coalesce(job_type, 'not_stated'), count(*) from public.jobs "
                                  f"where {OPEN} group by 1 order by 2 desc"),
        salary=_salary(conn, OPEN),
        posted_per_day=_counts(conn, f"""select (posted_at at time zone 'Asia/Kolkata')::date, count(*)
                                         from public.jobs where {OPEN} and posted_at is not null
                                         group by 1 order by 1"""),
    )


def _skill(conn: psycopg.Connection, skill: str) -> SkillInsight:
    total = conn.execute(f"select count(*) from public.jobs where {OPEN}").fetchone()[0]
    has = f"{OPEN} and %s = any(skills)"
    n = conn.execute(f"select count(*) from public.jobs where {has}", (skill,)).fetchone()[0]
    fresher = conn.execute(f"select count(*) from public.jobs where {has} and experience_min <= 1",
                           (skill,)).fetchone()[0]
    return SkillInsight(
        skill=skill, jobs=n, share=_share(n, total), salary=_salary(conn, has, (skill,)),
        fresher_friendly_jobs=fresher,
        often_with=_counts(conn, f"""select s, count(*) from public.jobs, unnest(skills) s
                                     where {has} and s <> %s and s <> all(%s)
                                     group by s order by 2 desc, 1 limit 10""",
                           (skill, skill, sorted(NEUTRAL_SKILLS))),
        top_companies=_counts(conn, f"select company_name, count(*) from public.jobs where {has} "
                                    "group by 1 order by 2 desc, 1 limit 10", (skill,)),
    )


@router.get("", response_model=MarketInsights)
def market_insights(conn: psycopg.Connection = Depends(get_conn)):
    """Top skills (with typical salary), top hiring companies, areas, job types, salary range, daily posts."""
    return _cached("market", lambda: _market(conn))


@router.get("/skills/{skill}", response_model=SkillInsight)
def skill_insight(skill: str, conn: psycopg.Connection = Depends(get_conn)):
    """One skill: how many current jobs ask for it, typical salary, skills often asked with it, who hires."""
    name = skill.strip().lower()
    if not known_skill(name):
        raise HTTPException(404, "Unknown skill. Use a name from /api/jobs/filters, e.g. python, sql, power bi.")
    return _cached(f"skill:{name}", lambda: _skill(conn, name))
