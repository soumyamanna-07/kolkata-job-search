"""Curriculum gap engine (Stage 1.4): compare what a syllabus teaches with what Kolkata jobs ask for.

Inputs: the syllabus subjects, each already linked to job skills (app.subject_skills), and the
live job market from our own database. Output: one report, ready for charts:

  - demand per skill: share of relevant open jobs that ask for it, with a 95% Wilson confidence
    interval (honest when job counts are small) and a trend (last 30 days vs the 60 days before,
    two-proportion z-test = the 2x2 chi-square test; "rising"/"falling" only when p < 0.05)
  - coverage per skill: how strongly the syllabus teaches it (0..1, from the subject links;
    a lab adds hands-on practice); elective-only skills are marked as such
  - gap score = demand share x (1 - coverage): what is asked for most and taught least
  - "learn now": the biggest gaps the market clearly wants (confidence interval above 2%)
  - per semester: how much of the market's demand is covered up to that semester
  - per subject: how many relevant jobs ask for what it teaches; foundation subjects listed apart

Adzuna jobs are never counted (their terms forbid aggregating their data).
"""
import math
import re
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

import psycopg

from .subject_skills import SubjectSkills

CACHE_SECONDS = 600
RECENT_DAYS = 30
OLDER_DAYS = 90                  # the "before" window is day 31..90
MIN_JOBS = 5                     # a skill needs at least this many jobs to be in the report
TOP_SKILLS = 30                  # the report looks at the most-asked skills only
MIN_TREND_JOBS = 20              # each window needs this many jobs before a trend is claimed
LEARN_NOW_MIN_SHARE = 0.02       # lower end of the confidence interval must be above 2%
LEARN_NOW_COUNT = 8
COVERED = 0.6                    # coverage at or above this = the syllabus teaches it properly
LAB_BONUS = 0.1                  # hands-on practice in a lab adds a little coverage

NEUTRAL = {"english", "hindi", "bengali"}     # languages: not something a syllabus "lacks"

# Skills that make a job a computing job. A CSE / IT / AI-ML syllabus is compared only with these jobs,
# not with sales or accounting jobs. Other departments are compared with all jobs.
COMPUTING = {
    "python", "java", "javascript", "typescript", "c", "c++", "c#", "go", "rust", "kotlin", "swift", "php",
    "ruby", "scala", "r", "matlab", "dart", "bash", "html", "css", "react", "angular", "vue", "next.js",
    "node.js", "express", "django", "flask", "fastapi", "spring boot", "spring", ".net", "laravel",
    "tailwind css", "bootstrap", "rest api", "graphql", "flutter", "react native", "android", "ios",
    "wordpress", "sql", "mysql", "postgresql", "mongodb", "oracle", "sql server", "redis", "elasticsearch",
    "power bi", "tableau", "pandas", "numpy", "spark", "hadoop", "kafka", "airflow", "etl", "data analysis",
    "data visualization", "statistics", "snowflake", "dbt", "machine learning", "deep learning", "nlp",
    "computer vision", "generative ai", "llm", "rag", "tensorflow", "pytorch", "scikit-learn", "langchain",
    "hugging face", "mlops", "aws", "azure", "gcp", "docker", "kubernetes", "terraform", "jenkins", "ci/cd",
    "linux", "git", "devops", "microservices", "selenium", "manual testing", "automation testing",
}
_COMPUTING_DEPT = re.compile(
    r"\b(cse|cs|it|computer|information|software|data|artificial intelligence|ai|ml|machine learning|"
    r"cyber|bca|mca)\b", re.I)


def field_for_department(department: Optional[str]) -> str:
    return "computing" if department and _COMPUTING_DEPT.search(department) else "all"


# ---------------------------------------------------------------- statistics
def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for a proportion k/n (good for small n, never outside 0..1)."""
    if n <= 0:
        return 0.0, 0.0
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def two_proportion_p(k1: int, n1: int, k2: int, n2: int) -> float:
    """Two-sided p-value: is k1/n1 different from k2/n2? (z-test; z squared is the 2x2 chi-square)"""
    if n1 <= 0 or n2 <= 0:
        return 1.0
    pooled = (k1 + k2) / (n1 + n2)
    se = math.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2))
    if se == 0:
        return 1.0
    z = (k1 / n1 - k2 / n2) / se
    return math.erfc(abs(z) / math.sqrt(2))


# ---------------------------------------------------------------- the job market
@dataclass
class SkillDemand:
    skill: str
    jobs: int                    # open relevant jobs asking for it
    fresher_jobs: int            # ... of them open to freshers (0-1 year)
    share: float                 # jobs / all open relevant jobs
    ci_low: float
    ci_high: float
    recent: int = 0              # relevant jobs posted in the last 30 days asking for it
    older: int = 0               # ... posted on day 31..90
    trend: str = "unknown"       # rising / falling / steady / unknown
    p_value: Optional[float] = None


@dataclass
class Market:
    field: str
    jobs: int                                  # open relevant jobs
    fresher_jobs: int
    recent_jobs: int                           # relevant jobs posted in the last 30 days
    older_jobs: int                            # ... on day 31..90
    skills: dict[str, SkillDemand]             # the most-asked skills only
    job_skills: list[frozenset[str]] = field(default_factory=list, repr=False)    # each open relevant job
    as_of: Optional[str] = None


def build_market(rows: Sequence[tuple], field_name: str, now: Optional[datetime] = None) -> Market:
    """rows: (skills, is_open, posted, experience_min) for every non-Adzuna job that is open
    or was posted in the last 90 days."""
    now = now or datetime.now(timezone.utc)
    recent_from, older_from = now - timedelta(days=RECENT_DAYS), now - timedelta(days=OLDER_DAYS)
    open_sets: list[frozenset[str]] = []
    fresher_sets: list[frozenset[str]] = []
    recent_sets: list[frozenset[str]] = []
    older_sets: list[frozenset[str]] = []
    for skills, is_open, posted, experience in rows:
        skills = frozenset(s for s in (skills or []) if s not in NEUTRAL)
        if field_name == "computing" and not skills & COMPUTING:
            continue
        if is_open:
            open_sets.append(skills)
            if experience is not None and float(experience) <= 1:
                fresher_sets.append(skills)
        if posted is not None:
            if posted >= recent_from:
                recent_sets.append(skills)
            elif posted >= older_from:
                older_sets.append(skills)

    def count(sets: list[frozenset[str]]) -> dict[str, int]:
        out: dict[str, int] = {}
        for skills in sets:
            for s in skills:
                out[s] = out.get(s, 0) + 1
        return out

    total = len(open_sets)
    counts, fresher, recent, older = count(open_sets), count(fresher_sets), count(recent_sets), count(older_sets)
    # for computing jobs, only computing skills are reported: a CSE syllabus does not "lack" sales
    reportable = [s for s, n in counts.items() if n >= MIN_JOBS and (field_name != "computing" or s in COMPUTING)]
    top = sorted(reportable, key=lambda s: (-counts[s], s))[:TOP_SKILLS]
    demand: dict[str, SkillDemand] = {}
    for s in top:
        low, high = wilson(counts[s], total)
        d = SkillDemand(s, counts[s], fresher.get(s, 0), counts[s] / total, low, high,
                        recent.get(s, 0), older.get(s, 0))
        if len(recent_sets) >= MIN_TREND_JOBS and len(older_sets) >= MIN_TREND_JOBS:
            d.p_value = two_proportion_p(d.recent, len(recent_sets), d.older, len(older_sets))
            if d.p_value < 0.05:
                d.trend = "rising" if d.recent / len(recent_sets) > d.older / len(older_sets) else "falling"
            else:
                d.trend = "steady"
        demand[s] = d
    return Market(field_name, total, len(fresher_sets), len(recent_sets), len(older_sets), demand,
                  open_sets, now.isoformat(timespec="minutes"))


_cache: dict[str, tuple[float, Market]] = {}
_cache_lock = threading.Lock()


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


def load_market(conn: psycopg.Connection, field_name: str) -> Market:
    """The live market for a field, kept for 10 minutes."""
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(field_name)
        if hit and now - hit[0] < CACHE_SECONDS:
            return hit[1]
    rows = conn.execute(
        """select skills, status = 'open', coalesce(posted_at, first_seen_at), experience_min
           from public.jobs
           where source <> 'adzuna'
             and (status = 'open' or coalesce(posted_at, first_seen_at) >= now() - make_interval(days => %s))""",
        (OLDER_DAYS,)).fetchall()
    market = build_market(rows, field_name)
    with _cache_lock:
        _cache[field_name] = (now, market)
    return market


# ---------------------------------------------------------------- the report
def _pct(x: float) -> float:
    return round(100 * x, 1)


def build_report(subjects: Sequence[dict], mapped: Sequence[SubjectSkills], market: Market,
                 current_semester: Optional[int] = None, chosen: Sequence[str] = ()) -> dict:
    """subjects: dicts with name, semester, kind (as read by the syllabus reader), in the same order as
    `mapped`. current_semester: the student's semester (skills taught later are marked "coming").
    chosen: elective choices the student took; those count as taught, other choices only as options."""
    chosen_keys = {c.strip().lower() for c in chosen if c and c.strip()}
    taught: dict[str, list[dict]] = {}
    for subject, result in zip(subjects, mapped):
        for link in result.links:
            elective = link.option is not None and link.option.lower() not in chosen_keys
            taught.setdefault(link.skill, []).append({
                "subject": result.name, "semester": subject.get("semester"), "kind": subject.get("kind"),
                "weight": link.weight, "source": link.source, "option": link.option, "elective": elective,
            })

    def coverage(skill: str, up_to: Optional[int] = None) -> float:
        best, lab = 0.0, False
        for t in taught.get(skill, []):
            if t["elective"] or (up_to is not None and (t["semester"] or 0) > up_to):
                continue
            best = max(best, t["weight"])
            lab = lab or t["kind"] == "lab"
        return min(1.0, best + LAB_BONUS) if best and lab else best

    skills = []
    for s, d in market.skills.items():
        cov_all = coverage(s)
        cov_now = coverage(s, current_semester) if current_semester else cov_all
        places = taught.get(s, [])
        if cov_all >= COVERED:
            status = "covered"
        elif cov_all > 0:
            status = "partial"
        elif places:
            status = "elective_only"
        else:
            status = "missing"
        later = [t["semester"] for t in places
                 if current_semester and not t["elective"] and (t["semester"] or 0) > current_semester]
        skills.append({
            "skill": s, "jobs": d.jobs, "fresher_jobs": d.fresher_jobs, "share": _pct(d.share),
            "ci": [_pct(d.ci_low), _pct(d.ci_high)], "trend": d.trend,
            "p_value": None if d.p_value is None else round(d.p_value, 4),
            "coverage": round(cov_all, 2), "coverage_now": round(cov_now, 2), "status": status,
            "coming_in_semester": min(later) if later and cov_now < COVERED else None,
            "gap_score": round(d.share * (1 - cov_now), 4),
            "taught_in": sorted(places, key=lambda t: (t["semester"] or 0, -t["weight"])),
        })
    skills.sort(key=lambda x: (-x["jobs"], x["skill"]))

    learn_now = sorted((x for x in skills if x["coverage_now"] < COVERED and x["ci"][0] >= 100 * LEARN_NOW_MIN_SHARE),
                       key=lambda x: (-x["gap_score"], x["skill"]))[:LEARN_NOW_COUNT]

    total_share = sum(d.share for d in market.skills.values()) or 1.0

    def weighted(up_to: Optional[int]) -> float:
        return sum(d.share * coverage(s, up_to) for s, d in market.skills.items()) / total_share

    semesters = sorted({s.get("semester") for s in subjects if s.get("semester")})
    by_semester = []
    for sem in semesters:
        in_sem = [r for s, r in zip(subjects, mapped) if s.get("semester") == sem]
        by_semester.append({"semester": sem, "subjects": len(in_sem),
                            "job_linked_subjects": sum(1 for r in in_sem if r.links),
                            "coverage_upto": _pct(weighted(sem))})

    per_subject, foundation = [], []
    for subject, result in zip(subjects, mapped):
        if not result.links:
            foundation.append({"name": result.name, "semester": subject.get("semester"), "kind": subject.get("kind")})
            continue
        core = set(result.skills)
        jobs = sum(1 for js in market.job_skills if js & core) if core else 0
        per_subject.append({"name": result.name, "semester": subject.get("semester"), "kind": subject.get("kind"),
                            "skills": result.skills, "options": result.option_skills,
                            "jobs": jobs, "share": _pct(jobs / market.jobs) if market.jobs else 0.0})

    counts = {k: sum(1 for x in skills if x["status"] == k) for k in ("covered", "partial", "elective_only", "missing")}
    return {
        "field": market.field,
        "market": {"jobs": market.jobs, "fresher_jobs": market.fresher_jobs, "recent_jobs": market.recent_jobs,
                   "older_jobs": market.older_jobs, "as_of": market.as_of},
        "summary": {"coverage": _pct(weighted(None)),
                    "coverage_now": _pct(weighted(current_semester)) if current_semester else None,
                    "skills_checked": len(skills), **counts,
                    "subjects": len(subjects), "foundation_subjects": len(foundation)},
        "skills": skills,
        "learn_now": [{"skill": x["skill"], "share": x["share"], "jobs": x["jobs"], "status": x["status"],
                       "trend": x["trend"], "coming_in_semester": x["coming_in_semester"]} for x in learn_now],
        "semesters": by_semester,
        "subjects": sorted(per_subject, key=lambda x: (-x["jobs"], x["semester"] or 0)),
        "foundation_subjects": foundation,
    }
