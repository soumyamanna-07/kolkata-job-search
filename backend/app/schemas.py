"""Shapes of the data the API sends back (shown in /docs)."""
from datetime import datetime
from typing import Annotated, Literal, Optional
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


class CVParsed(BaseModel):
    """What we read from a CV. No name, email, phone or address is kept."""
    skills: list[str]
    experience_years: Optional[float] = None
    education: Optional[str] = None
    job_titles: list[str] = []


class CVSaved(CVParsed):
    id: UUID
    file_name: Optional[str] = None
    updated_at: datetime


class CVUpdate(BaseModel):
    """The user can correct what we read from their CV."""
    skills: list[Annotated[str, Field(min_length=1, max_length=40)]] = Field(max_length=60)
    experience_years: Optional[float] = Field(default=None, ge=0, le=50)
    education: Optional[str] = Field(default=None, max_length=60)
    job_titles: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(default=[], max_length=10)


class MatchedJob(JobSummary):
    """A job ranked for a CV, with the reasons behind its score."""
    match_score: int = Field(ge=0, le=100)
    meaning_score: float             # 0..1, how close the AI thinks the job is to the CV
    matched_skills: list[str] = []
    missing_skills: list[str] = []
    reasons: list[str] = []


class SkillGapItem(BaseModel):
    skill: str
    jobs: int                        # how many of your best-matching jobs ask for it


class MatchResponse(BaseModel):
    cv: CVParsed
    items: list[MatchedJob]
    skill_gap: list[SkillGapItem]    # skills to learn next, most useful first
    scoring_version: str
