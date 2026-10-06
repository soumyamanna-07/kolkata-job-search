"""Ask AI: any job or career question. Facts about current jobs come only from real job posts (RAG);
career advice may use the AI's general knowledge.

Works for guests. Logged-in users can add use_my_cv=true to get answers for their saved CV.
The question is not stored.
"""
import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request
from psycopg.rows import dict_row
from pydantic import BaseModel, Field

from app import config, llm
from app.assistant import (Turn, build_messages, cited_numbers, clean_rewrite, fallback_answer, follow_up,
                           market_snapshot, read_hints, retrieve, rewrite_messages)
from app.auth import CurrentUser, get_optional_user
from app.db import get_conn
from app.embeddings import cv_text
from app.ratelimit import DailyBudget, PerKeyLimiter
from app.schemas import AssistantAnswer, AssistantQuestion, AssistantSource

router = APIRouter(prefix="/api/assistant", tags=["assistant"])

per_visitor = PerKeyLimiter(config.ASSISTANT_PER_MINUTE, window=60)
daily_ai = DailyBudget(config.ASSISTANT_DAILY_AI_ANSWERS)
ANSWER_TOKENS = 2000          # reasoning models (gpt-oss) also spend tokens thinking: leave room for the answer
REWRITE_TOKENS = 800


class ChatTurn(BaseModel):
    """One earlier question and the answer it got, sent back by the page for follow-up questions."""
    question: str = Field(max_length=500)
    answer: str = Field(max_length=4000)


class AskIn(AssistantQuestion):
    history: list[ChatTurn] = Field(default=[], max_length=10, description="earlier turns of this chat, oldest first")


def _profile(conn: psycopg.Connection, user: CurrentUser) -> str:
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute("select skills, experience_years, education, job_titles from public.cvs "
                          "where user_id = %s and is_active", (user.id,)).fetchone()
    if row is None:
        raise HTTPException(404, "No CV saved yet. Upload one first, or ask without use_my_cv.")
    return cv_text(row["job_titles"], row["skills"], row["education"], row["experience_years"])


@router.post("/ask", response_model=AssistantAnswer)
def ask(body: AskIn, request: Request, conn: psycopg.Connection = Depends(get_conn),
        user: CurrentUser | None = Depends(get_optional_user)):
    """Ask any job or career question, e.g. "Which Python jobs in Salt Lake accept freshers?" or
    "How do I prepare for a data analyst interview?". Send `history` (earlier turns) for follow-ups."""
    visitor = user.id if user else (request.client.host if request.client else "unknown")
    if not per_visitor.allow(str(visitor)):
        raise HTTPException(429, "Too many questions. Please wait a minute and try again.")
    if body.use_my_cv and user is None:
        raise HTTPException(401, "Log in to use your CV.")
    profile = _profile(conn, user) if body.use_my_cv else None

    history = [Turn(t.question, t.answer) for t in body.history]
    standalone = None
    if history and llm.is_configured():
        # follow-up: let the LLM say what the user means ("what about Howrah?" -> full question), then search
        try:
            standalone = clean_rewrite(llm.chat(rewrite_messages(body.question, history),
                                                max_tokens=REWRITE_TOKENS, temperature=0), body.question)
        except llm.LLMError:
            standalone = None
    if standalone:
        search_text, hints = standalone, read_hints(standalone)
    else:
        search_text, hints = follow_up(body.question, history)      # no AI: simple rule instead
    jobs = retrieve(conn, search_text, hints)

    answer, ai_written, note = None, False, None
    if not llm.is_configured():
        note = "AI answers are not set up on this server."
    elif not daily_ai.take():
        note = "AI answers are paused for today (daily limit reached). Showing the matching jobs."
    else:
        try:
            # the AI is asked even when no job matches: it can still give career advice
            answer = llm.chat(build_messages(body.question, jobs, profile, market=market_snapshot(conn),
                                             history=history, standalone=standalone), max_tokens=ANSWER_TOKENS)
            ai_written = True
        except llm.LLMError as error:
            note = f"AI answer unavailable right now: {error}. Showing the matching jobs."
    if answer is None:
        answer = fallback_answer(jobs, hints)

    cited = set(cited_numbers(answer, len(jobs))) if ai_written else set()
    sources = [AssistantSource(**job, number=i, cited=i in cited) for i, job in enumerate(jobs, start=1)]
    return AssistantAnswer(answer=answer, ai_written=ai_written, sources=sources, note=note)
