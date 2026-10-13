"""Turn a RawJob from any source into a clean, standard Kolkata job.

Steps: Kolkata filter -> too-old filter -> clean text -> salary/experience/job
type/work mode -> skills -> job_key (for de-duplication across sources).
"""
import hashlib
import html
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from pipeline.models import CleanJob, RawJob
from pipeline.skills import SKILLS

MAX_DESCRIPTION_CHARS = 20000
# A job is "live" only if it is still listed by its source AND was posted in the last 60 days.
# Older posts are not shown, even if a job board still lists them (store.close_expired closes
# them). On the site, people can narrow this down further (last 7, 15, 30, 40, 50 days ...).
MAX_JOB_AGE_DAYS = 60

# word in a location -> our standard area name (checked in this order)
KOLKATA_AREAS: list[tuple[str, str]] = [
    ("salt lake", "Salt Lake"),
    ("saltlake", "Salt Lake"),
    ("bidhannagar", "Salt Lake"),
    ("bidhan nagar", "Salt Lake"),
    ("sector v", "Salt Lake"),
    ("sector 5", "Salt Lake"),
    ("new town", "New Town"),
    ("newtown", "New Town"),
    ("rajarhat", "New Town"),
    ("howrah", "Howrah"),
    ("kolkata", "Kolkata"),
    ("kolkatta", "Kolkata"),       # common misspelling (Jooble India uses it)
    ("calcutta", "Kolkata"),
]

# work-from-home jobs open to people in India (collected on purpose, e.g. Jobicy, Jooble "work from home")
# are kept even though they are not in Kolkata; they get this area instead of a Kolkata one
REMOTE_AREA = "Work from home"

# Salt Lake City is also a city in Utah, USA: a location that says it is in the USA is never Kolkata
ABROAD_PATTERN = re.compile(r"(?<![a-z])(utah|usa|u\.s\.a?|united states)(?![a-z])|salt lake city,?\s*ut(?![a-z])")

# If a job TITLE names one of these cities (and not Kolkata), the job is not in
# Kolkata even if a source tagged it so. e.g. "Operations Manager - Kochi".
OTHER_CITIES = [
    "mumbai", "bombay", "navi mumbai", "thane", "delhi", "new delhi", "noida", "gurgaon",
    "gurugram", "faridabad", "ghaziabad", "bangalore", "bengaluru", "hyderabad",
    "secunderabad", "chennai", "madras", "pune", "kochi", "cochin", "ahmedabad",
    "jaipur", "lucknow", "chandigarh", "mohali", "indore", "bhopal", "bhubaneswar",
    "cuttack", "guwahati", "patna", "ranchi", "jamshedpur", "coimbatore", "madurai",
    "vizag", "visakhapatnam", "vijayawada", "nagpur", "nashik", "surat", "vadodara",
    "rajkot", "thiruvananthapuram", "trivandrum", "mysore", "mysuru", "mangalore",
    "mangaluru", "siliguri", "durgapur", "asansol", "goa", "dehradun", "raipur",
    "kanpur", "varanasi", "agra", "ludhiana", "amritsar",
]
OTHER_CITY_PATTERN = re.compile(r"(?<![a-z])(" + "|".join(OTHER_CITIES) + r")(?![a-z])")

COMPANY_SUFFIXES = re.compile(
    r"\b(private|pvt|limited|ltd|llp|inc|incorporated|corp|corporation|co|company|plc|india)\b"
)


# ---------------------------------------------------------------- location
def find_area(locations: list[str]) -> Optional[str]:
    """Return our standard Kolkata area, or None if no location is in Kolkata."""
    for loc in locations:
        text = (loc or "").lower()
        if ABROAD_PATTERN.search(text):
            continue                                   # e.g. "Salt Lake City, UT, USA"
        for word, area in KOLKATA_AREAS:
            if re.search(rf"(?<![a-z]){re.escape(word)}(?![a-z])", text):
                return area
    return None


def title_says_other_city(title: str) -> bool:
    """True if the title names another city and does not mention Kolkata."""
    text = (title or "").lower()
    return bool(OTHER_CITY_PATTERN.search(text)) and find_area([text]) is None


# ---------------------------------------------------------------- text
def clean_text(text: str) -> str:
    """HTML -> readable plain text with paragraph breaks kept."""
    text = html.unescape(text or "")
    text = html.unescape(text)  # some sources escape twice
    text = re.sub(r"(?i)<\s*(br|/p|/div|/li|/h[1-6])\s*/?>", "\n", text)
    text = re.sub(r"(?i)<\s*li[^>]*>", "\n- ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()[:MAX_DESCRIPTION_CHARS]


def clean_line(text: str) -> str:
    """One-line field (title, company): no HTML, single spaces."""
    return re.sub(r"\s+", " ", clean_text(text)).strip()


# ---------------------------------------------------------------- keys
def normalize_company(name: str) -> str:
    name = name.lower().replace("&", " and ")
    name = re.sub(r"[^a-z0-9 ]+", " ", name)
    name = COMPANY_SUFFIXES.sub(" ", name)
    return re.sub(r"\s+", " ", name).strip()


def normalize_title(title: str) -> str:
    title = title.lower()
    title = re.sub(r"\(.*?\)|\[.*?\]", " ", title)          # drop "(Kolkata)", "[Remote]"
    title = re.sub(r"[^a-z0-9+#]+", " ", title)
    return re.sub(r"\s+", " ", title).strip()


def make_job_key(company: str, title: str) -> str:
    """Same company + same title = same job, whichever source it came from.

    Area is NOT part of the key: one site says "Salt Lake", another says
    "Kolkata" for the very same job, and every job here is in Kolkata anyway.
    """
    raw = f"{normalize_company(company)}|{normalize_title(title)}|kolkata"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


# ---------------------------------------------------------------- salary
PERIOD_TO_YEAR = {"year": 1, "month": 12, "hour": 2080}


def normalize_salary(raw: RawJob) -> tuple[Optional[int], Optional[int]]:
    """Return yearly INR (min, max). Anything not in INR is dropped."""
    currency = (raw.salary_currency or "INR").upper()
    if currency != "INR":
        return None, None
    factor = PERIOD_TO_YEAR.get(raw.salary_period or "year", 1)
    values = []
    for v in (raw.salary_min, raw.salary_max):
        try:
            v = float(v) if v is not None else None
        except (TypeError, ValueError):
            v = None
        values.append(int(round(v * factor)) if v and v > 0 else None)
    lo, hi = values
    if lo and hi and lo > hi:
        lo, hi = hi, lo
    # ignore nonsense values (below Rs 10,000 or above Rs 10 crore a year)
    if lo and not 10_000 <= lo <= 100_000_000:
        lo = None
    if hi and not 10_000 <= hi <= 100_000_000:
        hi = None
    return lo, hi


# ---------------------------------------------------------------- experience
EXP_RANGE = re.compile(
    r"(\d{1,2}(?:\.\d)?)\s*\+?\s*(?:-|\u2013|to)\s*(\d{1,2}(?:\.\d)?)\s*\+?\s*(?:years?|yrs?)", re.I)
EXP_SINGLE = re.compile(r"(\d{1,2}(?:\.\d)?)\s*\+?\s*(?:years?|yrs?)", re.I)
FRESHER = re.compile(r"\b(fresher|freshers|no prior experience|no experience required)\b", re.I)


def _near_experience(text: str, start: int, end: int) -> bool:
    """True if the word 'experience'/'exp' is close to the match (avoids '25 years of history')."""
    window = text[max(0, start - 40):end + 40].lower()
    return "exp" in window


def extract_experience(title: str, description: str) -> tuple[Optional[float], Optional[float]]:
    """Years of experience asked for, e.g. '2-4 years experience' -> (2.0, 4.0)."""
    text = f"{title}\n{description}"
    for m in EXP_RANGE.finditer(text):
        lo, hi = float(m.group(1)), float(m.group(2))
        if lo <= hi <= 30 and _near_experience(text, m.start(), m.end()):
            return lo, hi
    for m in EXP_SINGLE.finditer(text):
        years = float(m.group(1))
        if years <= 30 and _near_experience(text, m.start(), m.end()):
            return years, None
    if FRESHER.search(text):
        return 0.0, 1.0
    return None, None


# ---------------------------------------------------------------- job type / work mode
def detect_job_type(title: str, hint: str) -> Optional[str]:
    text = f"{title} {hint}".lower()
    if re.search(r"\bintern(ship)?\b|\btrainee\b", text):
        return "internship"
    if re.search(r"part[\s_-]?time", text):
        return "part_time"
    if re.search(r"\bcontract(ual|or)?\b|\bfreelance\b", text):
        return "contract"
    if re.search(r"\btemporary\b|\btemp\b", text):
        return "temporary"
    if re.search(r"full[\s_-]?time|\bpermanent\b|\bregular\b", text):
        return "full_time"
    return None


def detect_work_mode(title: str, locations: list[str], hint: str) -> Optional[str]:
    hint = (hint or "").lower()
    if hint in ("remote", "hybrid", "onsite"):
        return hint
    if hint in ("on-site", "on site", "office"):
        return "onsite"
    text = " ".join([title, *locations]).lower()
    if "hybrid" in text:
        return "hybrid"
    if re.search(r"\bremote\b|work from home|\bwfh\b", text):
        return "remote"
    return None


# ---------------------------------------------------------------- skills
def _compile_skill_patterns() -> list[tuple[str, re.Pattern]]:
    patterns = []
    for skill, aliases in SKILLS.items():
        parts = sorted({re.escape(a.lower()) for a in aliases}, key=len, reverse=True)
        patterns.append((skill, re.compile(rf"(?<![a-z0-9])(?:{'|'.join(parts)})(?![a-z0-9+#])")))
    return patterns


SKILL_PATTERNS = _compile_skill_patterns()


def extract_skills(title: str, description: str) -> list[str]:
    text = f"{title}\n{description}".lower()
    return sorted(skill for skill, pattern in SKILL_PATTERNS if pattern.search(text))


# ---------------------------------------------------------------- main
def is_too_old(posted_at: Optional[datetime], now: Optional[datetime] = None) -> bool:
    if posted_at is None:
        return False                                   # unknown date: keep it
    if posted_at.tzinfo is None:
        posted_at = posted_at.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    return now - posted_at > timedelta(days=MAX_JOB_AGE_DAYS)


def clean_job(raw: RawJob, now: Optional[datetime] = None) -> Optional[CleanJob]:
    """Return a CleanJob, or None if the job is not in Kolkata (or work from home), too old, or unusable."""
    area = find_area(raw.locations) or (REMOTE_AREA if raw.remote_from_india else None)
    title = clean_line(raw.title)
    company = clean_line(raw.company_name)
    apply_url = (raw.apply_url or "").strip()
    if not area or not title or not company or not apply_url.startswith(("http://", "https://")):
        return None
    if title_says_other_city(title):
        return None
    if is_too_old(raw.posted_at, now):
        return None

    description = clean_text(raw.description)
    salary_min, salary_max = normalize_salary(raw)
    exp_min, exp_max = extract_experience(title, description)

    return CleanJob(
        job_key=make_job_key(company, title),
        source=raw.source,
        source_job_id=str(raw.source_job_id),
        company_id=raw.company_id,
        company_name=company,
        title=title,
        description=description,
        location_raw="; ".join(dict.fromkeys(l.strip() for l in raw.locations if l and l.strip())),
        area=area,
        apply_url=apply_url,
        salary_min=salary_min,
        salary_max=salary_max,
        salary_period="year",
        experience_min=exp_min,
        experience_max=exp_max,
        job_type=detect_job_type(title, raw.job_type_hint),
        work_mode="remote" if raw.remote_from_india else detect_work_mode(title, raw.locations, raw.work_mode_hint),
        skills=extract_skills(title, description),
        posted_at=raw.posted_at,
    )


SOURCE_PRIORITY = {"employer": 3, "greenhouse": 2, "lever": 2, "ashby": 2,
                   "smartrecruiters": 2, "workable": 2}


def deduplicate(jobs: list[CleanJob]) -> list[CleanJob]:
    """Keep one job per job_key: prefer direct company sources, then the copy with salary."""
    best: dict[str, CleanJob] = {}
    for job in jobs:
        old = best.get(job.job_key)
        if old is None:
            best[job.job_key] = job
            continue
        new_rank = (SOURCE_PRIORITY.get(job.source, 1), job.salary_min is not None, len(job.description))
        old_rank = (SOURCE_PRIORITY.get(old.source, 1), old.salary_min is not None, len(old.description))
        if new_rank > old_rank:
            best[job.job_key] = job
    return list(best.values())
