"""The common job format every collector produces."""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class RawJob:
    """A job exactly as one source gave it, before cleaning.

    Collectors fill this in; normalize.clean_job() turns it into a CleanJob.
    """
    source: str                          # greenhouse / lever / adzuna ...
    source_job_id: str                   # the job's id on that source
    company_name: str
    title: str
    apply_url: str
    locations: list[str] = field(default_factory=list)  # every location text the source gave
    description: str = ""                # may contain HTML
    posted_at: Optional[datetime] = None
    company_id: Optional[str] = None     # our companies.id, for company-based sources
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    salary_currency: Optional[str] = None
    salary_period: Optional[str] = None  # year / month / hour
    job_type_hint: str = ""              # source's own words, e.g. "Full-time", "Intern"
    work_mode_hint: str = ""             # e.g. "remote", "hybrid", "onsite"


@dataclass
class CleanJob:
    """A cleaned Kolkata job, ready to save in the jobs table."""
    job_key: str
    source: str
    source_job_id: str
    company_id: Optional[str]
    company_name: str
    title: str
    description: str
    location_raw: str
    area: str
    apply_url: str
    salary_min: Optional[int]
    salary_max: Optional[int]
    salary_period: str
    experience_min: Optional[float]
    experience_max: Optional[float]
    job_type: Optional[str]
    work_mode: Optional[str]
    skills: list[str]
    posted_at: Optional[datetime]
