"""Ask AI: questions about current Kolkata jobs, answered only from real job posts.

Works for guests. Logged-in users can add use_my_cv=true to get answers for their saved CV.
The question is not stored.
"""
import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request
from psycopg.rows import dict_row

from app import config, llm
from app.assistant import build_messages, cited_numbers, fallback_answer, read_hints, retrieve
from app.auth import CurrentUser, get_optional_user
from app.db import get_conn
from app.embeddings import cv_text
from app.ratelimit import DailyBudget, PerKeyLimiter
from app.schemas import AssistantAnswer, AssistantQuestion, AssistantSource

router = APIRouter(prefix="/api/assistant", tags=["assistant"])

per_visitor = PerKeyLimiter(config.ASSISTANT_PER_MINUTE, window=60)
daily_ai = DailyBudget(config.ASSISTANT_DAILY_AI_ANSWERS)


def _profile(conn: psycopg.Connection, user: CurrentUser) -> str:
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute("select skills, experience_years, education, job_titles from public.cvs "
                          "where user_id = %s and is_active", (user.id,)).fetchone()
    if row is None:
        raise HTTPException(404, "No CV saved yet. Upload one first, or ask without use_my_cv.")
    return cv_text(row["job_titles"], row["skills"], row["education"], row["experience_years"])


@router.post("/ask", response_model=AssistantAnswer)
def ask(body: AssistantQuestion, request: Request, conn: psycopg.Connection = Depends(get_conn),
        user: CurrentUser | None = Depends(get_optional_user)):
    """Ask about current Kolkata jobs, e.g. "Which Python jobs in Salt Lake accept freshers?"."""
    visitor = user.id if user else (request.client.host if request.client else "unknown")
    if not per_visitor.allow(str(visitor)):
        raise HTTPException(429, "Too many questions. Please wait a minute and try again.")
    if body.use_my_cv and user is None:
        raise HTTPException(401, "Log in to use your CV.")
    profile = _profile(conn, user) if body.use_my_cv else None

    hints = read_hints(body.question)
    jobs = retrieve(conn, body.question, hints)

    answer, ai_written, note = None, False, None
    if not jobs:
        note = None                                      # nothing to talk about: no need to call the AI
    elif not llm.is_configured():
        note = "AI answers are not set up on this server."
    elif not daily_ai.take():
        note = "AI answers are paused for today (daily limit reached). Showing the matching jobs."
    else:
        try:
            answer = llm.chat(build_messages(body.question, jobs, profile))
            ai_written = True
        except llm.LLMError as error:
            note = f"AI answer unavailable right now: {error}. Showing the matching jobs."
    if answer is None:
        answer = fallback_answer(jobs, hints)

    cited = set(cited_numbers(answer, len(jobs))) if ai_written else set()
    sources = [AssistantSource(**job, number=i, cited=i in cited) for i, job in enumerate(jobs, start=1)]
    return AssistantAnswer(answer=answer, ai_written=ai_written, sources=sources, note=note)
