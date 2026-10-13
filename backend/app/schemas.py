"""Shapes of the data the API sends back (shown in /docs)."""
from datetime import datetime
from typing import Annotated, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


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
    posted_by: Optional[str] = None  # recruitment agency that posted it: show "via <name>"
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


class AssistantQuestion(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    use_my_cv: bool = False          # logged-in users: let the AI consider their saved CV


class AssistantSource(JobSummary):
    number: int                      # the [n] used in the answer
    cited: bool                      # True if the answer mentions this job


class AssistantAnswer(BaseModel):
    answer: str
    ai_written: bool                 # False = AI not available, jobs listed without an AI answer
    sources: list[AssistantSource]   # the real jobs the answer is based on
    note: Optional[str] = None       # e.g. why the AI answer is missing


# ---------------------------------------------------------------- employer portal
Area = Literal["Kolkata", "Salt Lake", "New Town", "Howrah"]
JobType = Literal["full_time", "part_time", "internship", "contract", "temporary"]
WorkMode = Literal["onsite", "hybrid", "remote"]


class EmployerProfileIn(BaseModel):
    """Company details of a recruiter. An admin checks them before any job can be posted.
    account_kind "agency" = a recruitment agency that posts jobs for client companies."""
    company_name: str = Field(min_length=2, max_length=120)
    official_email: str = Field(max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    website: Optional[str] = Field(default=None, max_length=300, pattern=r"^https?://\S+$")
    gst_or_cin: Optional[str] = Field(default=None, max_length=25, pattern=r"^[A-Za-z0-9]+$")
    account_kind: Literal["company", "agency"] = "company"   # in-house HR, or a recruitment agency


class EmployerProfile(EmployerProfileIn):
    verification_status: str          # pending / approved / rejected / blocked
    rejection_reason: Optional[str] = None
    updated_at: datetime


class JobSubmissionIn(BaseModel):
    """A job an employer wants to publish. It goes live only after an admin approves it."""
    title: str = Field(min_length=3, max_length=120)
    description: str = Field(min_length=50, max_length=8000)
    hiring_for: Optional[str] = Field(default=None, min_length=2, max_length=120)  # agencies: the client company
    skills: list[Annotated[str, Field(min_length=1, max_length=40)]] = Field(default=[], max_length=30)
    location: Optional[str] = Field(default=None, max_length=120)
    area: Area = "Kolkata"
    apply_url: str = Field(max_length=500, pattern=r"^https?://\S+$")
    salary_min: Optional[int] = Field(default=None, ge=0, le=100_000_000)   # yearly INR
    salary_max: Optional[int] = Field(default=None, ge=0, le=100_000_000)
    experience_min: Optional[float] = Field(default=None, ge=0, le=50)
    experience_max: Optional[float] = Field(default=None, ge=0, le=50)
    job_type: Optional[JobType] = None
    work_mode: Optional[WorkMode] = None

    @model_validator(mode="after")
    def ranges_make_sense(self):
        if self.salary_min is not None and self.salary_max is not None and self.salary_min > self.salary_max:
            raise ValueError("salary_min must not be more than salary_max")
        if (self.experience_min is not None and self.experience_max is not None
                and self.experience_min > self.experience_max):
            raise ValueError("experience_min must not be more than experience_max")
        return self


class JobSubmission(JobSubmissionIn):
    id: UUID
    status: str                       # pending / approved / rejected / closed
    rejection_reason: Optional[str] = None
    published_job_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------- admin review
class AdminEmployer(EmployerProfile):
    user_id: UUID
    login_email: Optional[str] = None  # the email they log in with (can differ from official_email)
    created_at: datetime


class AdminSubmission(JobSubmission):
    employer_id: UUID
    company_name: str
    account_kind: str = "company"
    official_email: str
    employer_status: str
    spam_score: Optional[float] = None
    spam_reasons: list[str] = []


class EmployerReview(BaseModel):
    decision: Literal["approve", "reject", "block"]
    reason: Optional[str] = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def reason_needed(self):
        if self.decision != "approve" and not (self.reason or "").strip():
            raise ValueError("Please give a reason (the employer will see it)")
        return self


class SubmissionReview(BaseModel):
    decision: Literal["approve", "reject"]
    reason: Optional[str] = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def reason_needed(self):
        if self.decision == "reject" and not (self.reason or "").strip():
            raise ValueError("Please give a reason (the employer will see it)")
        return self


# ---------------------------------------------------------------- reports and admin panel
class JobReportIn(BaseModel):
    """'Report this job' from a user."""
    reason: Literal["spam", "fake", "already_closed", "wrong_location", "wrong_details", "other"]
    details: Optional[str] = Field(default=None, max_length=1000)


class AdminReport(BaseModel):
    id: UUID
    job_id: UUID
    job_title: str
    company_name: str
    job_source: str
    job_status: str
    apply_url: str
    reason: str
    details: Optional[str] = None
    reports_for_job: int             # how many open reports this job has
    status: str                      # open / resolved / dismissed
    created_at: datetime


class ReportResolve(BaseModel):
    action: Literal["close_job", "dismiss"]
    note: Optional[str] = Field(default=None, max_length=500)


class AdminUser(BaseModel):
    id: UUID
    email: Optional[str] = None
    full_name: Optional[str] = None
    role: str
    is_blocked: bool
    has_cv: bool
    created_at: datetime


class UserBlock(BaseModel):
    blocked: bool
    reason: str = Field(min_length=3, max_length=500)


class PipelineRun(BaseModel):
    id: int
    started_at: datetime
    finished_at: Optional[datetime] = None
    status: str
    trigger_type: str
    total_collected: int
    kolkata_count: int
    unique_count: int
    jobs_new: int
    jobs_updated: int
    jobs_closed: int
    source_stats: dict
    error_message: Optional[str] = None


class AdminAction(BaseModel):
    id: int
    admin_email: Optional[str] = None
    action: str
    target_table: Optional[str] = None
    target_id: Optional[str] = None
    details: dict
    created_at: datetime


class ModelVersion(BaseModel):
    model_name: str
    version: str
    is_active: bool
    metrics: dict
    notes: Optional[str] = None
    trained_at: datetime


class AdminStats(BaseModel):
    open_jobs: int
    open_jobs_by_source: dict[str, int]
    new_jobs_7_days: int
    jobs_without_embedding: int
    users_by_role: dict[str, int]
    blocked_users: int
    saved_cvs: int
    pending_employers: int
    pending_job_posts: int
    open_reports: int
    last_pipeline_run: Optional[PipelineRun] = None


# ---------------------------------------------------------------- market insights
class Count(BaseModel):
    value: str
    count: int


class SalaryBand(BaseModel):
    """Yearly INR, from jobs that state a salary. Empty when too few jobs state one."""
    jobs_with_salary: int
    p25: Optional[int] = None
    median: Optional[int] = None
    p75: Optional[int] = None


class SkillInsight(BaseModel):
    skill: str
    jobs: int
    share: float                     # % of all open jobs that ask for it
    salary: SalaryBand
    fresher_friendly_jobs: Optional[int] = None
    often_with: list[Count] = []     # skills asked together with this one
    top_companies: list[Count] = []


class MarketInsights(BaseModel):
    open_jobs: int
    fresher_friendly_jobs: int       # experience needed: 1 year or less
    fresher_friendly_share: float
    top_skills: list[SkillInsight]
    top_companies: list[Count]
    by_area: list[Count]
    by_job_type: list[Count]
    salary: SalaryBand
    posted_per_day: list[Count]      # value = date (YYYY-MM-DD)
