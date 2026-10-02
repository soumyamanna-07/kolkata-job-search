"""CV upload and reading.

Guests: POST /api/cv/parse reads the CV and returns the result - nothing is stored.
Logged-in users (after accepting the privacy notice) can save the result, edit it
and delete it. Only skills, experience, education, job titles and an AI embedding
made from those fields are stored.
"""
import psycopg
from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from psycopg.rows import dict_row

from app.auth import CurrentUser, get_current_user
from app.cv_parser import MAX_FILE_BYTES, CVError, parse_cv
from app.db import get_conn
from app.embeddings import embed_cv
from app.schemas import CVParsed, CVSaved, CVUpdate

router = APIRouter(prefix="/api", tags=["cv"])

CV_COLUMNS = "id, file_name, skills, experience_years, education, job_titles, updated_at"


def _read_and_parse(file: UploadFile) -> CVParsed:
    data = file.file.read(MAX_FILE_BYTES + 1)        # never read more than the limit
    try:
        parsed = parse_cv(data)
    except CVError as error:
        raise HTTPException(422, str(error))
    return CVParsed(skills=parsed.skills, experience_years=parsed.experience_years,
                    education=parsed.education, job_titles=parsed.job_titles)


@router.post("/cv/parse", response_model=CVParsed)
def parse_only(file: UploadFile = File(..., description="CV as PDF or DOCX, max 5 MB")):
    """Read a CV without saving anything (works for guests)."""
    return _read_and_parse(file)


@router.post("/me/cv", response_model=CVSaved, status_code=status.HTTP_201_CREATED)
def upload_cv(file: UploadFile = File(...), user: CurrentUser = Depends(get_current_user),
              conn: psycopg.Connection = Depends(get_conn)):
    """Read and SAVE your CV details (replaces your previous CV). Needs privacy consent first."""
    if user.privacy_consent_at is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Please accept the privacy notice before saving your CV (POST /api/me/consent).")
    parsed = _read_and_parse(file)
    file_name = (file.filename or "cv")[:200]
    vec, vec_hash = embed_cv(parsed.job_titles, parsed.skills, parsed.education, parsed.experience_years)
    with conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
        cur.execute("delete from public.cvs where user_id = %s", (user.id,))   # keep only the latest
        row = cur.execute(
            f"""insert into public.cvs (user_id, file_name, skills, experience_years, education, job_titles,
                                        embedding, embedding_hash)
                values (%s, %s, %s, %s, %s, %s, %s::extensions.vector, %s) returning {CV_COLUMNS}""",
            (user.id, file_name, parsed.skills, parsed.experience_years, parsed.education,
             parsed.job_titles, vec, vec_hash)).fetchone()
    return CVSaved(**row)


@router.get("/me/cv", response_model=CVSaved)
def get_cv(user: CurrentUser = Depends(get_current_user), conn: psycopg.Connection = Depends(get_conn)):
    """Your saved CV details."""
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(f"select {CV_COLUMNS} from public.cvs where user_id = %s and is_active",
                          (user.id,)).fetchone()
    if row is None:
        raise HTTPException(404, "No CV saved yet")
    return CVSaved(**row)


@router.put("/me/cv", response_model=CVSaved)
def update_cv(body: CVUpdate, user: CurrentUser = Depends(get_current_user),
              conn: psycopg.Connection = Depends(get_conn)):
    """Correct your CV details (e.g. add a skill we missed)."""
    skills = sorted({s.strip().lower() for s in body.skills if s.strip()})
    titles = [t.strip() for t in body.job_titles if t.strip()]
    vec, vec_hash = embed_cv(titles, skills, body.education, body.experience_years)
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            f"""update public.cvs set skills = %s, experience_years = %s, education = %s, job_titles = %s,
                    embedding = %s::extensions.vector, embedding_hash = %s
                where user_id = %s and is_active returning {CV_COLUMNS}""",
            (skills, body.experience_years, body.education, titles, vec, vec_hash, user.id)).fetchone()
    if row is None:
        raise HTTPException(404, "No CV saved yet")
    return CVSaved(**row)


@router.delete("/me/cv", status_code=status.HTTP_204_NO_CONTENT)
def delete_cv(user: CurrentUser = Depends(get_current_user), conn: psycopg.Connection = Depends(get_conn)):
    """Delete everything we stored from your CV."""
    conn.execute("delete from public.cvs where user_id = %s", (user.id,))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
