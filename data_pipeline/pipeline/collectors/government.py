"""Government recruitment notices: reads the official "Recruitment" / "Jobs" page of a government
office or institute in and around Kolkata (WB Health Recruitment Board, ISI Kolkata, IIEST Shibpur ...).

These pages are not job boards: they are tables or lists of notices, usually a PDF link with a notice
date and a last date. One reader works for most of them:

  1. split the page into rows (<tr> table rows, or <li> list items),
  2. keep rows that have a link AND talk about recruitment (recruitment, vacancy, walk-in, posts of ...),
     and skip results, admit cards, answer keys, merit lists, corrigenda ...,
  3. read the dates in the row (31.10.2026, 31/10/2026, 31 October 2026, October 31, 2026),
  4. keep only CURRENT notices: the last date is today or later, or there is only one date and it is
     from the last 30 days. Rows with no date at all are skipped (we cannot tell if they are old).

When a notice's last date has passed, it is no longer kept, so the next run closes it (snapshot).
Polite like the career-page reader: obeys robots.txt, one page per office per run, clear User-Agent.

Many government websites run old web servers that modern Python refuses to talk to ("unsafe legacy
renegotiation", "handshake failure"). make_session() accepts those older connection settings, but it
still checks every website's certificate and name, so we always know we are reading the real site.
"""
import html
import re
import ssl
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from pipeline.collectors.base import TIMEOUT_SECONDS, USER_AGENT, CollectResult, safe_error
from pipeline.collectors.career_page import Robots
from pipeline.models import RawJob
from pipeline.normalize import clean_line

IST = timezone(timedelta(hours=5, minutes=30))
RECENT_DAYS = 30                       # a notice with only one date: kept if that date is this recent
OLD_ISSUE_DAYS = 50                    # issue date older than this but last date ahead: posted date left empty
TABLE_ROW = re.compile(r"<tr\b.*?</tr>", re.S | re.I)
LIST_ITEM = re.compile(r"<li\b.*?</li>", re.S | re.I)
TABLE_CELL = re.compile(r"<t[dh]\b.*?</t[dh]>", re.S | re.I)
LINK = re.compile(r"<a\b[^>]*?href\s*=\s*[\"']([^\"'#][^\"']*)[\"'][^>]*>(.*?)</a>", re.S | re.I)
RECRUITMENT = re.compile(
    r"recruit|vacanc|advertis|\badvt\b|walk[\s-]?in|engagement|appointment|posts? of|position|faculty|"
    r"\bjrf\b|\bsrf\b|research (associate|fellow|assistant)|project (associate|assistant|fellow|scientist|staff)|"
    r"apprentice|requirement of|hiring|empanel|contractual", re.I)
NOT_A_JOB = re.compile(
    r"result|admit card|answer key|merit list|\bpanel\b|re-?medical|selected candidates|shortlist|"
    r"interview schedule|schedule of interview|cancel|corrigendum|addendum|extension|extended|syllabus|"
    r"\bmarks\b|score|document verification|call letter|withdraw|postpone|rejected|provisional list|"
    r"final list|list of (eligible|candidates)|tender|quotation|admission|seminar|workshop on|conference", re.I)
GENERIC_LINK_TEXT = re.compile(
    r"^(click here|here|view|view details?|details|download|apply|apply online|apply now|pdf|more|read more|"
    r"new|notice|advertisement|link|open|see more)\W*$", re.I)
MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
MONTH = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
DATE_DMY = re.compile(r"(?<!\d)(\d{1,2})[./-](\d{1,2})[./-](\d{4})(?!\d)")
DATE_D_MON_Y = re.compile(rf"(?<!\d)(\d{{1,2}})(?:st|nd|rd|th)?[\s-]+{MONTH}[\s,-]+(\d{{4}})(?!\d)", re.I)
DATE_MON_D_Y = re.compile(rf"\b{MONTH}\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})(?!\d)", re.I)


class OldServerTLS(HTTPAdapter):
    """HTTPS for old government web servers. Certificates and host names are still checked."""
    def _context(self) -> ssl.SSLContext:
        context = ssl.create_default_context()
        context.options |= getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0x4)   # "unsafe legacy renegotiation"
        context.set_ciphers("DEFAULT:@SECLEVEL=1")                         # older key sizes and ciphers
        return context

    def init_poolmanager(self, *args, **kwargs):
        kwargs["ssl_context"] = self._context()
        return super().init_poolmanager(*args, **kwargs)

    def proxy_manager_for(self, *args, **kwargs):
        kwargs["ssl_context"] = self._context()
        return super().proxy_manager_for(*args, **kwargs)


def make_session(retries: bool = True) -> requests.Session:
    """Session for government pages: old-server HTTPS, our User-Agent, a couple of retries."""
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    retry = Retry(total=2, backoff_factor=2, status_forcelist=(429, 500, 502, 503, 504),
                  allowed_methods=("GET",)) if retries else Retry(total=0)
    session.mount("https://", OldServerTLS(max_retries=retry))
    session.mount("http://", HTTPAdapter(max_retries=retry))
    return session


def _safe_date(year: int, month: int, day: int) -> Optional[date]:
    try:
        found = date(year, month, day)
    except ValueError:
        return None
    return found if 2000 <= year <= 2100 else None


def dates_in(text: str) -> list[date]:
    """Every date written in the text (Indian day-month-year order for 31.10.2026 / 31/10/2026)."""
    found = []
    for d, m, y in DATE_DMY.findall(text):
        found.append(_safe_date(int(y), int(m), int(d)))
    for d, mon, y in DATE_D_MON_Y.findall(text):
        found.append(_safe_date(int(y), MONTHS[mon[:3].lower()], int(d)))
    for mon, d, y in DATE_MON_D_Y.findall(text):
        found.append(_safe_date(int(y), MONTHS[mon[:3].lower()], int(d)))
    return sorted({d for d in found if d})


def _rows(page: str) -> list[str]:
    rows = [r for r in TABLE_ROW.findall(page) if LINK.search(r)]
    return rows or [r for r in LIST_ITEM.findall(page) if LINK.search(r)]


def _no_dates(text: str) -> str:
    return re.sub(r"\s+", " ", DATE_MON_D_Y.sub("", DATE_D_MON_Y.sub("", DATE_DMY.sub("", text)))).strip()


def _title(links: list[tuple[str, str]], row: str) -> str:
    texts = [clean_line(html.unescape(text)) for _, text in links]
    good = [t for t in texts if len(t) >= 12 and not GENERIC_LINK_TEXT.match(t)]
    cells = [_no_dates(clean_line(c)) for c in TABLE_CELL.findall(row)]
    cells = [c for c in cells if len(c) >= 12 and not GENERIC_LINK_TEXT.match(c)]
    if good:
        title = max(good, key=len)
    elif cells:                            # links say only "View": use the table cell that describes the post
        title = max(cells, key=lambda c: (bool(RECRUITMENT.search(c)), len(c)))
    else:                                  # a list item: its text without the dates and the "Download" link words
        title = _no_dates(clean_line(LINK.sub(lambda m: "" if GENERIC_LINK_TEXT.match(clean_line(m.group(2)))
                                                   else m.group(0), row)))
    title = re.sub(r"^\s*\d{1,3}[.)]\s+", "", title)                    # "1. Recruitment of ..." -> "Recruitment of ..."
    title = re.sub(r"\s*(\(\s*\)|\bnew\b)\s*$", "", title, flags=re.I)  # trailing "new" badge text
    return re.sub(r"\s+", " ", title).strip(" -|:")[:200]


def _link(links: list[tuple[str, str]], page_url: str) -> Optional[str]:
    """The notice itself: prefer a PDF or a link with real words, then any link."""
    urls = [(urljoin(page_url, html.unescape(href.strip())), clean_line(text)) for href, text in links]
    urls = [(u, t) for u, t in urls if urlparse(u).scheme in ("http", "https")]
    for url, text in urls:
        if url.lower().split("?")[0].endswith(".pdf") or (len(text) >= 12 and not GENERIC_LINK_TEXT.match(text)):
            return url
    return urls[0][0] if urls else None


def notices(page: str, page_url: str, today: date) -> list[dict]:
    """Current recruitment notices on one page: [{title, url, issued, last_date, text}]."""
    out, seen = [], set()
    for row in _rows(page or ""):
        text = clean_line(row)
        if not RECRUITMENT.search(text) or NOT_A_JOB.search(text):
            continue
        dates = [d for d in dates_in(text) if d <= today + timedelta(days=365)]
        if not dates:
            continue                                   # undated: can't tell if it is still open
        first, last = dates[0], dates[-1]
        current = last >= today or (len(dates) == 1 and (today - first).days <= RECENT_DAYS)
        if not current:
            continue
        links = LINK.findall(row)
        url = _link(links, page_url)
        title = _title(links, row)
        if not url or len(title) < 8 or url in seen:
            continue
        seen.add(url)
        out.append({"title": title, "url": url, "issued": first if first <= today else None,
                    "last_date": last if last >= today else None, "text": text})
    return out


def _to_job(notice: dict, office: str, company_id: Optional[str], area: str, today: date) -> RawJob:
    issued, last = notice["issued"], notice["last_date"]
    lines = [notice["title"], "", f"Office: {office}"]
    if issued:
        lines.append(f"Notice date: {issued:%d %b %Y}")
    if last:
        lines.append(f"Last date / walk-in date: {last:%d %b %Y}")
    lines += ["", "Government recruitment notice. Read the official notice for eligibility, number of posts, "
                  "pay and how to apply.", "", notice["text"][:1500]]
    posted = issued if issued and (today - issued).days <= OLD_ISSUE_DAYS else None
    text = notice["text"].lower()
    job_type = "contract" if re.search(r"contract|project|temporary|walk[\s-]?in|tenure", text) else ""
    return RawJob(
        source="government",
        source_job_id=notice["url"],
        company_name=office,
        title=notice["title"],
        apply_url=notice["url"],
        locations=[office, area],          # "IIEST Shibpur Howrah" -> Howrah; otherwise the given area
        description="\n".join(lines),
        posted_at=datetime(posted.year, posted.month, posted.day, tzinfo=IST) if posted else None,
        company_id=company_id,
        job_type_hint=job_type,
        work_mode_hint="onsite",
    )


def collect(session: requests.Session, page_url: str, office: str, company_id: Optional[str],
            area: str = "Kolkata", now: Optional[datetime] = None) -> CollectResult:
    # snapshot=True: the page lists every current notice, so a notice we no longer keep
    # (its last date has passed, or it was taken down) is closed on the next run
    result = CollectResult(source="government", scope=f"government:{urlparse(page_url).netloc}",
                           company_id=company_id)
    today = (now or datetime.now(IST)).astimezone(IST).date()
    try:
        if not Robots(session).allowed(page_url):
            result.error = "robots.txt does not allow reading this page"
            return result
        resp = session.get(page_url, timeout=TIMEOUT_SECONDS, headers={"Accept": "text/html"})
        result.requests_made += 1
        resp.raise_for_status()
        for notice in notices(resp.text, page_url, today):
            result.jobs.append(_to_job(notice, office, company_id, area, today))
        result.complete = True
    except requests.RequestException as error:
        result.error = safe_error(error)                  # partial: never close notices on a failed read
    return result
