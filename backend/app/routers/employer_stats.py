"""Employer portal: stats for your job posts (views, apply clicks, saves)."""
from datetime import datetime
from typing import Optional
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth import CurrentUser
from app.db import get_conn
from app.employer_stats import employer_stats
from app.routers.employer import employer_only

router = APIRouter(prefix="/api/employer", tags=["employer"])


class PostCounts(BaseModel):
    shown_in_results: int = 0        # how often it appeared in search / match lists
    views: int = 0                   # job page opened
    unique_viewers: int = 0
    apply_clicks: int = 0            # "Apply" clicked (goes to your apply link)
    saves: int = 0
    views_7_days: int = 0
    apply_clicks_7_days: int = 0
    apply_rate: Optional[float] = None   # % of views that clicked Apply


class PostStats(PostCounts):
    submission_id: UUID
    title: str
    status: str                      # pending / approved / rejected / closed
    posted_at: datetime
    job_id: Optional[UUID] = None    # the live job, once approved
    job_status: Optional[str] = None # open / closed


class EmployerTotals(PostCounts):
    posts: int = 0
    live_jobs: int = 0


class EmployerStats(BaseModel):
    totals: EmployerTotals
    jobs: list[PostStats]


@router.get("/stats", response_model=EmployerStats)
def my_stats(user: CurrentUser = Depends(employer_only), conn: psycopg.Connection = Depends(get_conn)):
    """How your job posts are doing. Your own clicks on your own jobs are not counted."""
    return employer_stats(conn, user.id)
