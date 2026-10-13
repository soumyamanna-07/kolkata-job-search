"""Career-page reader: jobs from any company website that tags them for Google Jobs
(schema.org "JobPosting" inside <script type="application/ld+json">).

Many Indian hiring tools (Zoho Recruit, Keka, Freshteam, Darwinbox ...) add these tags
to their career pages, so one reader covers lots of local companies.

Polite by design: obeys robots.txt, sends a clear User-Agent, waits between pages and
reads at most MAX_JOB_PAGES job pages per company.
"""
import html
import json
import re
import time
from datetime import datetime, timezone
from typing import Iterator, Optional
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests

from pipeline.collectors.base import TIMEOUT_SECONDS, USER_AGENT, CollectResult, safe_error
from pipeline.models import RawJob

MAX_JOB_PAGES = 30
PAGE_DELAY = 1.0                       # seconds between pages of the same site
LD_JSON = re.compile(r"<script[^>]*type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>", re.S | re.I)
HREF = re.compile(r"href=[\"']([^\"'#\s]+)[\"']", re.I)
JOB_LINK = re.compile(r"job|career|opening|position|vacanc|opportunit|requisition", re.I)
SALARY_PERIOD = {"YEAR": "year", "MONTH": "month", "HOUR": "hour"}


# ---------------------------------------------------------------- reading the tags
def _postings(node) -> Iterator[dict]:
    """Every JobPosting inside a JSON-LD block (plain, list, @graph or ItemList)."""
    if isinstance(node, list):
        for item in node:
            yield from _postings(item)
    elif isinstance(node, dict):
        kind = node.get("@type")
        kinds = kind if isinstance(kind, list) else [kind]
        if "JobPosting" in kinds:
            yield node
        for key in ("@graph", "itemListElement", "item"):
            if key in node:
                yield from _postings(node[key])


def postings_in(page: str) -> list[dict]:
    found = []
    for block in LD_JSON.findall(page or ""):
        for text in (block.strip(), html.unescape(block.strip())):
            try:
                found.extend(_postings(json.loads(text)))
                break
            except ValueError:
                continue
    return found


def _text(value) -> str:
    if isinstance(value, dict):
        return str(value.get("name") or value.get("value") or "")
    return str(value or "")


def _locations(posting: dict) -> list[str]:
    places = posting.get("jobLocation") or []
    out = []
    for place in places if isinstance(places, list) else [places]:
        if not isinstance(place, dict):
            out.append(_text(place))
            continue
        address = place.get("address") or {}
        if isinstance(address, str):
            out.append(address)
            continue
        out.append(", ".join(filter(None, [_text(address.get(k)) for k in
                                           ("streetAddress", "addressLocality", "addressRegion", "addressCountry")])))
    if str(posting.get("jobLocationType", "")).upper() == "TELECOMMUTE":
        out.append("Remote")
    return [l for l in out if l]


def _salary(posting: dict) -> dict:
    base = posting.get("baseSalary")
    if not isinstance(base, dict):
        return {}
    value = base.get("value") if isinstance(base.get("value"), dict) else {"value": base.get("value")}
    low = value.get("minValue", value.get("value"))
    high = value.get("maxValue", value.get("value"))
    try:
        low = float(low) if low not in (None, "") else None
        high = float(high) if high not in (None, "") else None
    except (TypeError, ValueError):
        return {}
    unit = str(value.get("unitText") or base.get("unitText") or "YEAR").upper()
    return {"min": low, "max": high, "currency": base.get("currency"), "period": SALARY_PERIOD.get(unit, "year")}


def _date(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def to_raw(posting: dict, page_url: str, company_name: str, company_id: Optional[str],
           now: Optional[datetime] = None) -> Optional[RawJob]:
    """RawJob from one JobPosting, or None if it has expired (validThrough in the past) or has no title."""
    title = _text(posting.get("title"))
    valid_through = _date(posting.get("validThrough"))
    if not title or (valid_through and valid_through < (now or datetime.now(timezone.utc))):
        return None
    url = urljoin(page_url, _text(posting.get("url")) or page_url)
    identifier = posting.get("identifier")
    salary = _salary(posting)
    employment = posting.get("employmentType") or ""
    return RawJob(
        source="career_page",
        source_job_id=_text(identifier) or url,
        company_id=company_id,
        company_name=_text(posting.get("hiringOrganization")) or company_name,
        title=title,
        apply_url=url,
        locations=_locations(posting),
        description=str(posting.get("description") or ""),
        posted_at=_date(posting.get("datePosted")),
        salary_min=salary.get("min"),
        salary_max=salary.get("max"),
        salary_currency=salary.get("currency"),
        salary_period=salary.get("period"),
        job_type_hint=" ".join(employment) if isinstance(employment, list) else str(employment),
        work_mode_hint="remote" if str(posting.get("jobLocationType", "")).upper() == "TELECOMMUTE" else "",
    )


# ---------------------------------------------------------------- polite fetching
class Robots:
    """robots.txt answers, one file per website."""
    def __init__(self, session: requests.Session):
        self.session, self.cache = session, {}

    def allowed(self, url: str) -> bool:
        parts = urlparse(url)
        root = f"{parts.scheme}://{parts.netloc}"
        if root not in self.cache:
            parser = RobotFileParser()
            try:
                resp = self.session.get(root + "/robots.txt", timeout=TIMEOUT_SECONDS)
                lines = resp.text.splitlines() if resp.status_code == 200 else []
            except requests.RequestException:
                lines = []                               # no robots.txt reachable: allowed, like search engines
            parser.parse(lines)
            self.cache[root] = parser
        return self.cache[root].can_fetch(USER_AGENT, url)


def job_links(page: str, page_url: str) -> list[str]:
    """Links on the careers page that look like job pages on the same website."""
    host = urlparse(page_url).netloc
    links = []
    for href in HREF.findall(page or ""):
        url = urljoin(page_url, html.unescape(href))
        if urlparse(url).netloc == host and url != page_url and JOB_LINK.search(urlparse(url).path):
            links.append(url)
    return list(dict.fromkeys(links))[:MAX_JOB_PAGES]


def collect(session: requests.Session, careers_url: str, company_name: str, company_id: Optional[str],
            delay: float = PAGE_DELAY) -> CollectResult:
    result = CollectResult(source="career_page", scope=f"career_page:{urlparse(careers_url).netloc}",
                           company_id=company_id)
    robots = Robots(session)
    try:
        if not robots.allowed(careers_url):
            result.error = "robots.txt does not allow reading this careers page"
            return result
        resp = session.get(careers_url, timeout=TIMEOUT_SECONDS, headers={"Accept": "text/html"})
        result.requests_made += 1
        resp.raise_for_status()
        pages = [(careers_url, resp.text)]
        postings = postings_in(resp.text)
        if not postings:                                  # list page without tags: open the job pages
            for link in job_links(resp.text, careers_url):
                if not robots.allowed(link):
                    continue
                time.sleep(delay)
                page = session.get(link, timeout=TIMEOUT_SECONDS, headers={"Accept": "text/html"})
                result.requests_made += 1
                page.raise_for_status()
                pages.append((link, page.text))
        seen = set()
        for page_url, page in pages:
            for posting in postings_in(page):
                job = to_raw(posting, page_url, company_name, company_id)
                if job and (job.title, job.apply_url) not in seen:
                    seen.add((job.title, job.apply_url))
                    result.jobs.append(job)
        result.complete = True
    except requests.RequestException as error:
        result.error = safe_error(error)                  # partial: never close jobs on a failed read
    return result
