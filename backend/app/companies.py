"""Company List helpers for the Admin Panel.

- normalize_company: the SAME name rule as the pipeline (data_pipeline/pipeline/normalize.py),
  so "ABC Tech Pvt. Ltd." and "ABC Tech" count as one company.
- check_board: looks at a company's Greenhouse / Lever job board before an admin saves it,
  so a wrong board code is caught at once (and shows how many jobs are in Kolkata).
"""
import re
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import quote

import httpx

PLATFORMS = ("greenhouse", "lever", "ashby", "smartrecruiters", "workable",
             "zoho_recruit", "freshteam", "keka", "darwinbox", "other")
COLLECTED_PLATFORMS = ("greenhouse", "lever")          # the pipeline collects these today
TOKEN_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$"   # board code: letters, digits, - _ .

COMPANY_SUFFIXES = re.compile(
    r"\b(private|pvt|limited|ltd|llp|inc|incorporated|corp|corporation|co|company|plc|india)\b"
)
KOLKATA_WORDS = re.compile(r"(?<![a-z])(kolkata|calcutta|salt ?lake|bidhan ?nagar|sector v|sector 5|"
                           r"new ?town|rajarhat|howrah)(?![a-z])")
BOARD_URLS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{token}/jobs",
    "lever": "https://api.lever.co/v0/postings/{token}?mode=json",
}
USER_AGENT = "KolkataLiveJobSearch/1.0 (+https://github.com/soumyamanna-07/kolkata-job-search)"


def normalize_company(name: str) -> str:
    name = name.lower().replace("&", " and ")
    name = re.sub(r"[^a-z0-9 ]+", " ", name)
    name = COMPANY_SUFFIXES.sub(" ", name)
    return re.sub(r"\s+", " ", name).strip()


@dataclass
class BoardCheck:
    ok: bool
    jobs: int = 0
    kolkata_jobs: int = 0
    sample_titles: list[str] = field(default_factory=list)   # Kolkata jobs first, else any
    error: Optional[str] = None


def _jobs_and_locations(platform: str, data) -> list[tuple[str, list[str]]]:
    """[(title, [location, ...]), ...] from a board's JSON."""
    out = []
    if platform == "greenhouse":
        for item in data.get("jobs", []):
            locs = [(item.get("location") or {}).get("name", "")]
            locs += [o.get("location") or o.get("name") or "" for o in item.get("offices") or []]
            out.append((item.get("title", ""), locs))
    else:
        if not isinstance(data, list):
            raise ValueError("unexpected answer")
        for item in data:
            cats = item.get("categories") or {}
            out.append((item.get("text", ""), [cats.get("location") or ""] + list(cats.get("allLocations") or [])))
    return out


def make_client() -> httpx.Client:
    return httpx.Client(timeout=10, follow_redirects=True, headers={"User-Agent": USER_AGENT})


def check_board(client, platform: str, token: str) -> BoardCheck:
    if platform not in BOARD_URLS:
        return BoardCheck(ok=False, error="Only Greenhouse and Lever boards can be checked (and collected) for now.")
    if not re.match(TOKEN_PATTERN, token or ""):
        return BoardCheck(ok=False, error="The board code can only have letters, digits, - _ and .")
    try:
        response = client.get(BOARD_URLS[platform].format(token=quote(token, safe="")))
    except httpx.HTTPError:
        return BoardCheck(ok=False, error="Could not reach the job board. Please try again later.")
    if response.status_code == 404:
        return BoardCheck(ok=False, error="No job board with this code. Check the spelling: it is the part after "
                                          "boards.greenhouse.io/ or jobs.lever.co/ in the careers link.")
    if response.status_code != 200:
        return BoardCheck(ok=False, error=f"The job board answered with error {response.status_code}.")
    try:
        jobs = _jobs_and_locations(platform, response.json())
    except (ValueError, AttributeError):
        return BoardCheck(ok=False, error="The job board sent something we could not read.")
    kolkata = [title for title, locs in jobs if any(KOLKATA_WORDS.search(loc.lower()) for loc in locs)]
    return BoardCheck(ok=True, jobs=len(jobs), kolkata_jobs=len(kolkata),
                      sample_titles=(kolkata or [title for title, _ in jobs])[:5])
