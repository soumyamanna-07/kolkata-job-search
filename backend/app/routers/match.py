"""CV -> job matching: "Best for You" ranking with reasons and skill gap.

Guests: POST /api/cv/match - upload a CV, get ranked jobs, nothing is stored.
Logged-in users: GET /api/me/matches - uses the CV they saved.
"""
from typing import Annotated, Optional

import psycopg
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from psycopg.rows import dict_row

from app.auth import CurrentUser, get_current_user
from app.db import get_conn
from app.embeddings import cv_text, embed_cv, text_hash
from app.job_search import AREAS, JOB_TYPES, SUMMARY_COLUMNS, WORK_MODES
from app.matching import SCORING_VERSION, CVProfile, candidate_sql, rank, skill_gap
from app.routers.cv import _read_and_parse
from app.routers.jobs import _check_allowed, _split
from app.schemas import CVParsed, MatchedJob, MatchResponse, SkillGapItem

router = APIRouter(prefix="/api", tags=["match"])

CsvList = Annotated[Optional[str], Query(description="comma-separated")]
Limit = Annotated[int, Query(ge=1, le=50, description="how many jobs to return")]

NOTHING_TO_MATCH = "We could not find skills or job titles in this CV, so we cannot match it yet."


def _filters(area: Optional[str], job_type: Optional[str], work_mode: Optional[str]) -> tuple[list[str], dict]:
    areas, types, modes = _split(area), _split(job_type), _split(work_mode)
    _check_allowed("area", areas, AREAS)
    _check_allowed("job_type", types, JOB_TYPES)
    _check_allowed("work_mode", modes, WORK_MODES)
    where, params = [], {}
    for column, key, values in (("area", "areas", areas), ("job_type", "types", types),
                                ("work_mode", "modes", modes)):
        if values:
            where.append(f"{column} = any(%({key})s)")
            params[key] = values
    return where, params


def _best_jobs(conn: psycopg.Connection, vec: str, cv: CVParsed, where: list[str], params: dict,
               limit: int) -> MatchResponse:
    with conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
        cur.execute("set local hnsw.ef_search = 400")    # let the index return all 200 candidates
        rows = cur.execute(candidate_sql(SUMMARY_COLUMNS, where), {**params, "vec": vec}).fetchall()
    ranked = rank(rows, CVProfile(skills=cv.skills, experience_years=cv.experience_years))
    items = [MatchedJob(**{k: v for k, v in job.items() if k != "similarity"},
                        match_score=m.score, meaning_score=m.meaning, matched_skills=m.matched_skills,
                        missing_skills=m.missing_skills, reasons=m.reasons)
             for job, m in ranked[:limit]]
    gap = [SkillGapItem(skill=s, jobs=n) for s, n in skill_gap(ranked)]
    return MatchResponse(cv=cv, items=items, skill_gap=gap, scoring_version=SCORING_VERSION)


@router.post("/cv/match", response_model=MatchResponse)
def match_uploaded_cv(file: UploadFile = File(..., description="CV as PDF or DOCX, max 5 MB"),
                      area: CsvList = None, job_type: CsvList = None, work_mode: CsvList = None,
                      limit: Limit = 20, conn: psycopg.Connection = Depends(get_conn)):
    """Best jobs for a CV (works for guests - nothing is stored)."""
    where, params = _filters(area, job_type, work_mode)
    cv = _read_and_parse(file)
    vec, _ = embed_cv(cv.job_titles, cv.skills, cv.education, cv.experience_years)
    if vec is None:
        raise HTTPException(422, NOTHING_TO_MATCH)
    return _best_jobs(conn, vec, cv, where, params, limit)


@router.get("/me/matches", response_model=MatchResponse)
def my_matches(area: CsvList = None, job_type: CsvList = None, work_mode: CsvList = None,
               limit: Limit = 20, user: CurrentUser = Depends(get_current_user),
               conn: psycopg.Connection = Depends(get_conn)):
    """Best jobs for your saved CV."""
    where, params = _filters(area, job_type, work_mode)
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            """select id, skills, experience_years, education, job_titles, embedding_hash,
                      embedding::text as embedding
               from public.cvs where user_id = %s and is_active""", (user.id,)).fetchone()
    if row is None:
        raise HTTPException(404, "No CV saved yet. Upload one with POST /api/me/cv.")
    cv = CVParsed(skills=row["skills"], experience_years=row["experience_years"],
                  education=row["education"], job_titles=row["job_titles"])
    current_hash = text_hash(cv_text(cv.job_titles, cv.skills, cv.education, cv.experience_years))
    vec = row["embedding"]
    if vec is None or row["embedding_hash"] != current_hash:          # e.g. after a model upgrade
        vec, vec_hash = embed_cv(cv.job_titles, cv.skills, cv.education, cv.experience_years)
        if vec is None:
            raise HTTPException(422, NOTHING_TO_MATCH)
        conn.execute("update public.cvs set embedding = %s::extensions.vector, embedding_hash = %s where id = %s",
                     (vec, vec_hash, row["id"]))
    return _best_jobs(conn, vec, cv, where, params, limit)
