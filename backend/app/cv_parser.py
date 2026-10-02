"""Read a CV (PDF or DOCX) and pull out what job matching needs.

Privacy: we keep only skills, years of experience, highest education and past
job titles. The CV text, name, phone, email and address are NOT stored.
"""
import io
import logging
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date
from typing import Optional
from xml.etree import ElementTree

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.skills import extract_skills

logging.getLogger("pypdf").setLevel(logging.ERROR)   # don't flood logs with warnings about odd PDFs

MAX_FILE_BYTES = 5 * 1024 * 1024        # 5 MB
MAX_PDF_PAGES = 10
MAX_DOCX_XML_BYTES = 10 * 1024 * 1024   # protects against "zip bombs"
MIN_TEXT_CHARS = 50

PDF_TYPE = "application/pdf"
DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class CVError(ValueError):
    """A problem with the uploaded file that the user should be told about."""


@dataclass
class ParsedCV:
    skills: list[str] = field(default_factory=list)
    experience_years: Optional[float] = None
    education: Optional[str] = None
    job_titles: list[str] = field(default_factory=list)
    file_type: str = ""


# ---------------------------------------------------------------- text extraction
def detect_type(data: bytes) -> str:
    if data[:5] == b"%PDF-":
        return PDF_TYPE
    if data[:4] == b"PK\x03\x04":
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                if "word/document.xml" in z.namelist():
                    return DOCX_TYPE
        except zipfile.BadZipFile:
            pass
    raise CVError("Please upload your CV as a PDF or Word (.docx) file.")


def _pdf_text(data: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise CVError("This PDF is password-protected. Please upload an unlocked copy.")
        pages = reader.pages[:MAX_PDF_PAGES]
        return "\n".join((page.extract_text() or "") for page in pages)
    except CVError:
        raise
    except (PdfReadError, ValueError, KeyError, TypeError) as error:
        raise CVError("This PDF could not be read. Try saving it again as PDF.") from error


W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _docx_text(data: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            info = z.getinfo("word/document.xml")
            if info.file_size > MAX_DOCX_XML_BYTES:
                raise CVError("This Word file is too large to read.")
            xml = z.read(info)
    except (zipfile.BadZipFile, KeyError) as error:
        raise CVError("This Word file could not be read.") from error
    if b"<!DOCTYPE" in xml or b"<!ENTITY" in xml:
        raise CVError("This Word file could not be read.")       # blocks XML entity attacks
    root = ElementTree.fromstring(xml)
    lines = []
    for para in root.iter(f"{W}p"):
        parts = []
        for node in para.iter():
            if node.tag == f"{W}t" and node.text:
                parts.append(node.text)
            elif node.tag in (f"{W}tab",):
                parts.append(" ")
            elif node.tag in (f"{W}br", f"{W}cr"):
                parts.append("\n")
        lines.append("".join(parts))
    return "\n".join(lines)


def extract_text(data: bytes) -> tuple[str, str]:
    """Return (text, file_type). Raises CVError with a user-friendly message."""
    if len(data) > MAX_FILE_BYTES:
        raise CVError("CV file is larger than 5 MB.")
    if not data:
        raise CVError("The file is empty.")
    file_type = detect_type(data)
    text = _pdf_text(data) if file_type == PDF_TYPE else _docx_text(data)
    if len(text.strip()) < MIN_TEXT_CHARS:
        raise CVError("No text found in this CV. If it is a scanned image, please upload a text-based PDF or DOCX.")
    return text, file_type


# ---------------------------------------------------------------- sections
HEADINGS = {
    "experience": r"(work |professional |employment |relevant )?(experience|employment history|work history|internships?)",
    "education": r"education(al qualifications?)?|academic (details|qualifications?|background)|qualifications?",
    "other": r"projects?|skills|technical skills|certifications?|achievements?|awards?|summary|objective|"
             r"profile|hobbies|interests|languages|personal (details|information)|declaration|publications?|"
             r"extra[- ]curricular( activities)?|activities|references|positions? of responsibility",
}
HEADING_RE = {name: re.compile(rf"^\s*({pattern})\s*:?\s*$", re.I) for name, pattern in HEADINGS.items()}


# Some PDFs (e.g. made with LaTeX) give odd characters for the dash in "May 2026 - Aug 2026",
# like \x15. Turn every kind of dash into a plain "-" before reading dates.
DASHES = str.maketrans({ch: "-" for ch in "\x15\u2010\u2011\u2012\u2013\u2014\u2015\u2212"})


def split_sections(text: str) -> dict[str, str]:
    """Group CV lines under the heading they appear in ('top' = before any heading)."""
    text = text.translate(DASHES)
    sections: dict[str, list[str]] = {"top": []}
    current = "top"
    for line in text.splitlines():
        stripped = line.strip()
        matched = None
        if 0 < len(stripped) <= 45:
            for name, regex in HEADING_RE.items():
                if regex.match(stripped):
                    matched = name
                    break
        if matched:
            current = matched
            sections.setdefault(current, [])
        else:
            sections.setdefault(current, []).append(line)
    return {name: "\n".join(lines) for name, lines in sections.items()}


# ---------------------------------------------------------------- experience
MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
MONTH_RE = r"(?:(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s*,?\s*)?"
DATE_RANGE = re.compile(
    rf"{MONTH_RE}((?:19|20)\d\d)\s*(?:-|\u2013|\u2014|to|till|until)\s*"
    rf"(?:(present|current|now|till date|ongoing)|{MONTH_RE}((?:19|20)\d\d))", re.I)
NUMERIC_RANGE = re.compile(
    r"(\d{1,2})/((?:19|20)\d\d)\s*(?:-|\u2013|to)\s*(?:(present|current|now)|(\d{1,2})/((?:19|20)\d\d))", re.I)
STATED_YEARS = re.compile(r"(\d{1,2}(?:\.\d)?)\+?\s*(?:years?|yrs?)\s+(?:of\s+)?(?:\w+\s+){0,2}experience", re.I)


def _month(name: Optional[str], default: int) -> int:
    return MONTHS.get(name.lower()[:3], default) if name else default


def _ranges(text: str, today: date) -> list[tuple[int, int]]:
    """Date ranges as (start_month_index, end_month_index), month_index = year*12 + month."""
    now = today.year * 12 + today.month
    out = []
    for m in DATE_RANGE.finditer(text):
        start = int(m.group(2)) * 12 + _month(m.group(1), 1)
        end = now if m.group(3) else int(m.group(5)) * 12 + _month(m.group(4), 12)
        out.append((start, min(end, now)))
    for m in NUMERIC_RANGE.finditer(text):
        start = int(m.group(2)) * 12 + int(m.group(1))
        end = now if m.group(3) else int(m.group(5)) * 12 + int(m.group(4))
        out.append((start, min(end, now)))
    return [(s, e) for s, e in out if 1980 * 12 <= s <= e]


def _merged_months(ranges: list[tuple[int, int]]) -> int:
    """Total months covered, counting overlapping jobs only once."""
    total, cur_s, cur_e = 0, None, None
    for s, e in sorted(ranges):
        if cur_e is None or s > cur_e:
            if cur_e is not None:
                total += cur_e - cur_s + 1
            cur_s, cur_e = s, e
        else:
            cur_e = max(cur_e, e)
    if cur_e is not None:
        total += cur_e - cur_s + 1
    return total


def extract_experience(sections: dict[str, str], today: Optional[date] = None) -> Optional[float]:
    """Years of work experience. Only dates in the EXPERIENCE section count, so
    college years (2023 - 2027 B.Tech) are not mistaken for work experience."""
    today = today or date.today()
    exp_text = sections.get("experience", "")
    if exp_text.strip():
        months = _merged_months(_ranges(exp_text, today))
        if months:
            return round(months / 12, 1)
    stated = [float(m.group(1)) for m in STATED_YEARS.finditer("\n".join(sections.values()))]
    stated = [y for y in stated if y <= 40]
    if stated:
        return max(stated)
    return 0.0 if exp_text.strip() == "" else None


# ---------------------------------------------------------------- education
EDUCATION_LEVELS = [   # highest first
    ("PhD", r"ph\.?\s?d|doctorate"),
    ("Master's (M.Tech / M.E.)", r"m\.?\s?tech|\bm\.e\.?(?=\s|$|,)|master of (technology|engineering)"),
    ("MCA", r"\bm\.?\s?c\.?\s?a\b|master of computer applications"),
    ("MBA", r"\bm\.?\s?b\.?\s?a\b|master of business administration|\bpgdm\b"),
    ("Master's (M.Sc / M.Com / M.A.)", r"\bm\.?\s?sc\b|\bm\.?\s?com\b|\bm\.a\.|master of (science|commerce|arts)"),
    ("B.Tech / B.E.", r"b\.?\s?tech|\bb\.e\.?(?=\s|$|,)|bachelor of (technology|engineering)"),
    ("BCA", r"\bb\.?\s?c\.?\s?a\b|bachelor of computer applications"),
    ("BBA", r"\bb\.?\s?b\.?\s?a\b|bachelor of business administration"),
    ("Bachelor's (B.Sc / B.Com / B.A.)", r"\bb\.?\s?sc\b|\bb\.?\s?com\b|\bb\.a\.|bachelor of (science|commerce|arts)"),
    ("Diploma", r"\bdiploma\b|polytechnic"),
    ("Higher Secondary (12th)", r"higher secondary|\bhs\b|12th|class xii|\bxii\b|intermediate|\bisc\b|\bcbse\b"),
]
EDUCATION_RE = [(label, re.compile(pattern, re.I)) for label, pattern in EDUCATION_LEVELS]


def extract_education(text: str) -> Optional[str]:
    for label, regex in EDUCATION_RE:
        if regex.search(text):
            return label
    return None


# ---------------------------------------------------------------- job titles
TITLE_WORDS = re.compile(
    r"\b(engineer|developer|analyst|intern|manager|executive|consultant|designer|scientist|associate|"
    r"specialist|lead|officer|accountant|architect|administrator|programmer|trainee|tester|"
    r"coordinator|representative|assistant|technician|teacher|lecturer)\b", re.I)


def extract_job_titles(sections: dict[str, str], limit: int = 5) -> list[str]:
    """Role names only, e.g. 'Machine Learning Intern'. Company, city and
    '(Hybrid)' that come after the role word are cut off."""
    titles = []
    for line in sections.get("experience", "").splitlines():
        clean = NUMERIC_RANGE.sub("", DATE_RANGE.sub("", line)).strip(" |,-\t\u2022")
        if not clean or clean.endswith(".") or len(clean) > 90:
            continue                                   # sentences / descriptions, not titles
        words = list(TITLE_WORDS.finditer(clean))
        if not words:
            continue
        clean = clean[:words[-1].end()].strip(" |,-\t\u2022")
        if 3 <= len(clean) <= 60:
            if clean.lower() not in (t.lower() for t in titles):
                titles.append(clean)
        if len(titles) >= limit:
            break
    return titles


# ---------------------------------------------------------------- main
def parse_cv(data: bytes, today: Optional[date] = None) -> ParsedCV:
    text, file_type = extract_text(data)
    sections = split_sections(text)
    return ParsedCV(
        skills=extract_skills(text),
        experience_years=extract_experience(sections, today),
        education=extract_education(sections.get("education", "") or text),
        job_titles=extract_job_titles(sections),
        file_type=file_type,
    )
