"""Shapes of the data the API sends back (shown in /docs)."""
from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class JobSummary(BaseModel):
    """One job in a search result list."""
    id: UUID
    title: str
    company_name: str
    area: str
    location_raw: Optional[str] = None
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None
    salary_period: str = "year"
    experience_min: Optional[float] = None
    experience_max: Optional[float] = None
    job_type: Optional[str] = None
    work_mode: Optional[str] = None
    skills: list[str] = []
    posted_at: Optional[datetime] = None
    apply_url: str
    source: str                      # show "Jobs by Adzuna" when source == "adzuna"
    snippet: str = ""                # first part of the description


class JobDetail(JobSummary):
    """Full job page."""
    description: Optional[str] = None
    status: str                      # open / closed
    closed_at: Optional[datetime] = None


class JobSearchResponse(BaseModel):
    items: list[JobSummary]
    total: int
    page: int
    page_size: int
    pages: int


class FacetCount(BaseModel):
    value: str
    count: int


class JobFilters(BaseModel):
    """Options for the filter dropdowns, built from the jobs that are open right now."""
    total_open_jobs: int
    areas: list[FacetCount]
    companies: list[FacetCount]
    skills: list[FacetCount]
    job_types: list[FacetCount]
    work_modes: list[FacetCount]
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None


class Profile(BaseModel):
    id: UUID
    email: Optional[str] = None
    full_name: Optional[str] = None
    role: str
    privacy_consent_at: Optional[datetime] = None


class ProfileUpdate(BaseModel):
    full_name: str = Field(min_length=1, max_length=100)


class SavedJob(JobSummary):
    status: str                      # open / closed - saved jobs can close later
    saved_at: datetime


class JobEventIn(BaseModel):
    """Something a user did with a job (feeds history, analytics and the ranking model)."""
    job_id: UUID
    event_type: Literal["impression", "view", "click_apply", "hide"]
    source_page: Optional[Literal["search", "cv_match", "recommendations", "alert", "assistant", "job_page"]] = None
    rank_position: Optional[int] = Field(default=None, ge=1, le=1000)
    match_score: Optional[float] = Field(default=None, ge=0, le=100)
    session_id: Optional[str] = Field(default=None, max_length=64)   # anonymous id for guests
