"""CV -> job matching ("Best for You").

Step 1 (database): pgvector finds the 200 open jobs whose meaning is closest to the CV.
Step 2 (here): each of those gets a 0-100 match score from four signals, and the
reasons are kept so the app can say WHY a job matches:

    meaning similarity   45%   (AI embedding, cosine)
    skill overlap        30%   (job's skills that the CV has)
    experience fit       20%   (job's required years vs the CV)
    freshness             5%   (newer posts first)

If a job needs 2+ more years than the CV has, the score is also cut by 30%, so
senior roles don't crowd out jobs the candidate can actually get. When a job does
not state its experience, the title is used ("Senior" ~4 years, "Manager" ~5 ...).

These weights are version "v1.1-rules", tuned on real Kolkata jobs. Later, a model
trained on what users click and apply to can replace them (stored in model_versions).
"""
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

SCORING_VERSION = "v1.1-rules"
WEIGHTS = {"meaning": 0.45, "skills": 0.30, "experience": 0.20, "freshness": 0.05}
CANDIDATES = 200                      # how many nearest jobs pgvector returns before scoring
GAP_FROM_TOP = 50                     # skill gap is counted over this many best jobs ...
GAP_MIN_SCORE = 50                    # ... that are also real matches (score 50+)

# all-MiniLM-L6-v2 cosine between a CV profile and real jobs: unrelated ~0.2, strong match ~0.7-0.8
SIM_LOW, SIM_HIGH = 0.25, 0.80
SKILL_PRIOR = 2                       # a job listing only 1-2 skills is not a sure "100% skill match"
# languages and soft skills: CVs rarely list them, so they neither add nor cost points
NEUTRAL_SKILLS = {"english", "hindi", "bengali", "communication"}
TOO_SENIOR_GAP = 2.0                  # years short before the extra penalty applies
TOO_SENIOR_FACTOR = 0.7

# (pattern in the job title, usual minimum years) - checked in this order, first match wins
JUNIOR_TITLE = re.compile(r"\b(intern|internship|trainee|fresher|apprentice|graduate|junior|jr)\b", re.I)
SENIOR_TITLES = [
    (re.compile(r"\b(director|head of|vice president|vp|chief)\b", re.I), 10.0),
    (re.compile(r"\bsenior man(a)?ger\b", re.I), 8.0),          # "manger": a common typo in job titles
    (re.compile(r"\b(principal|architect)\b", re.I), 7.0),
    (re.compile(r"\bman(a)?ger\b", re.I), 5.0),
    (re.compile(r"\b(lead|staff)\b", re.I), 5.0),
    (re.compile(r"\b(senior|sr)\b", re.I), 4.0),
]


@dataclass
class CVProfile:
    skills: list[str]
    experience_years: Optional[float]


@dataclass
class Match:
    score: int
    meaning: float                  # 0..1 after scaling
    matched_skills: list[str] = field(default_factory=list)
    missing_skills: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def meaning_score(similarity: float) -> float:
    return _clamp((similarity - SIM_LOW) / (SIM_HIGH - SIM_LOW))


def skill_score(job_skills: list[str], cv_skills: set[str],
                meaning: float = 0.0) -> tuple[Optional[float], list[str], list[str]]:
    """Share of the job's skills the CV has, smoothed: with few listed skills the
    AI meaning score fills in the rest. None when the job lists no skills."""
    job_skills = [s for s in job_skills if s not in NEUTRAL_SKILLS]
    if not job_skills:
        return None, [], []
    matched = [s for s in job_skills if s in cv_skills]
    missing = [s for s in job_skills if s not in cv_skills]
    score = (len(matched) + SKILL_PRIOR * meaning) / (len(job_skills) + SKILL_PRIOR)
    return score, matched, missing


def title_min_years(title: str) -> Optional[float]:
    """Usual minimum experience for a title, when the job doesn't say. None = can't tell."""
    if JUNIOR_TITLE.search(title or ""):
        return 0.0
    for pattern, years in SENIOR_TITLES:
        if pattern.search(title or ""):
            return years
    return None


def experience_score(years: Optional[float], exp_min: Optional[float], exp_max: Optional[float]) -> float:
    if exp_min is None or years is None:
        return 0.7                                    # unknown - neither helps nor hurts much
    exp_min = float(exp_min)
    if years >= exp_min:
        if exp_max is not None and years > float(exp_max) + 3:
            return 0.7                                # much more experienced than needed
        return 1.0
    return _clamp(1.0 - (exp_min - years) / 3.0)      # each missing year costs a third


def freshness_score(posted_at: Optional[datetime], now: datetime) -> float:
    if posted_at is None:
        return 0.5
    days = (now - posted_at).total_seconds() / 86400
    if days <= 3:
        return 1.0
    return _clamp(1.0 - 0.7 * (days - 3) / 27)  # 1.0 at 3 days -> 0.3 at 30 days and older


def _years(x: float) -> str:
    return f"{x:g} year" + ("" if x == 1 else "s")


def score_job(job: dict, cv: CVProfile, now: Optional[datetime] = None) -> Match:
    """job needs: similarity, title, skills, experience_min, experience_max, posted_at."""
    now = now or datetime.now(timezone.utc)
    cv_skills = {s.lower() for s in cv.skills}
    meaning = meaning_score(float(job["similarity"]))
    skills, matched, missing = skill_score(job.get("skills") or [], cv_skills, meaning)

    stated_min = job.get("experience_min")
    exp_min = float(stated_min) if stated_min is not None else title_min_years(job.get("title", ""))
    exp = experience_score(cv.experience_years, exp_min, job.get("experience_max"))
    fresh = freshness_score(job.get("posted_at"), now)

    total = (WEIGHTS["meaning"] * meaning
             + WEIGHTS["skills"] * (skills if skills is not None else meaning)   # no skills listed: trust meaning
             + WEIGHTS["experience"] * exp
             + WEIGHTS["freshness"] * fresh)
    too_senior = (exp_min is not None and cv.experience_years is not None
                  and exp_min - cv.experience_years >= TOO_SENIOR_GAP)
    if too_senior:
        total *= TOO_SENIOR_FACTOR

    reasons = []
    if matched:
        reasons.append(f"You have {len(matched)} of {len(matched) + len(missing)} listed skills: "
                       f"{', '.join(matched[:5])}")
    if missing:
        reasons.append(f"Skills to add: {', '.join(missing[:5])}")
    if exp_min is not None and cv.experience_years is not None:
        if cv.experience_years >= exp_min:
            reasons.append(f"Experience fits (needs {_years(exp_min)}+)" if exp_min else "Open to freshers")
        elif stated_min is not None:
            reasons.append(f"Needs {_years(exp_min)}+, you have {_years(cv.experience_years)}")
        else:
            reasons.append(f"Senior role (usually {_years(exp_min)}+), you have {_years(cv.experience_years)}")
    if meaning >= 0.7:
        reasons.append("Very similar to your profile")
    return Match(score=round(100 * total), meaning=round(meaning, 3), matched_skills=matched,
                 missing_skills=missing, reasons=reasons)


def rank(jobs: list[dict], cv: CVProfile, limit: Optional[int] = None,
         now: Optional[datetime] = None) -> list[tuple[dict, Match]]:
    scored = [(job, score_job(job, cv, now)) for job in jobs]
    scored.sort(key=lambda pair: (pair[1].score, pair[0]["similarity"]), reverse=True)
    return scored[:limit] if limit else scored


def skill_gap(ranked: list[tuple[dict, Match]], top: int = 10) -> list[tuple[str, int]]:
    """Skills you don't have, counted over your best-matching jobs: what to learn next.
    Weak matches are left out, so an unrelated SAP job can't fill the list with "sap"."""
    good = [match for _, match in ranked[:GAP_FROM_TOP] if match.score >= GAP_MIN_SCORE]
    counts = Counter(skill for match in good for skill in match.missing_skills)
    return counts.most_common(top)


def candidate_sql(columns: str, where_extra: list[str]) -> str:
    """Nearest open jobs by meaning. %(vec)s is the CV vector as '[...]' text."""
    where = ["status = 'open'", "embedding is not null", *where_extra]
    return (f"select {columns}, "
            f"1 - (embedding operator(extensions.<=>) %(vec)s::extensions.vector) as similarity "
            f"from public.jobs where {' and '.join(where)} "
            f"order by embedding operator(extensions.<=>) %(vec)s::extensions.vector "
            f"limit {CANDIDATES}")
