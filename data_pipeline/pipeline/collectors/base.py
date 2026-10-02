"""Shared pieces for all collectors: the result type and a polite HTTP session."""
from dataclasses import dataclass, field
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from pipeline.models import RawJob

USER_AGENT = "KolkataLiveJobSearch/1.0 (+https://github.com/soumyamanna-07/kolkata-job-search)"
TIMEOUT_SECONDS = 30


@dataclass
class CollectResult:
    """What one collector run produced.

    complete=True means we got the FULL current list from this source/company,
    so jobs we did not see can safely be marked closed. If anything failed or
    was cut short, complete=False and nothing gets closed.
    """
    source: str
    scope: str                          # e.g. "adzuna" or "lever:company-slug"
    company_id: Optional[str] = None
    jobs: list[RawJob] = field(default_factory=list)
    complete: bool = False
    error: Optional[str] = None


def safe_error(error: Exception, secrets: tuple = ()) -> str:
    """Error text for logs and the database, with any secret (API keys) hidden."""
    text = f"{type(error).__name__}: {error}"
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    return text[:500]


def make_session() -> requests.Session:
    """HTTP session that retries on rate limits / server errors, with backoff."""
    retry = Retry(
        total=3,
        backoff_factor=2,                       # waits 2s, 4s, 8s
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
        respect_retry_after_header=True,
    )
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session
