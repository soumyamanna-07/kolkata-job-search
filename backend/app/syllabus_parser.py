"""Read a college syllabus (PDF, Word or pasted text) into a list of subjects.

University syllabus PDFs are tables, and their text comes out messy: a subject code can be split
across lines ("PCCAIML" / "401", "ES-" / "EE191"), names wrap, and the L-T-P hours and credits
follow on separate lines. So we:

  1. join all the text into one line and find the SEMESTER headings
     ("First Semester", "Semester IV", "5th Semester" ...),
  2. find SUBJECT CODES with a pattern that allows those splits (letters, then 3 digits),
  3. take the subject NAME as the words between the code and its hours/credits ("3 0 0 3"),
  4. mark labs, projects and electives (with their choices: "Cloud Computing / Graph Theory"),
  5. if the syllabus also has the detailed part (Module 1 ... Unit 2 ...), keep those topics.

When this rule-based reader finds too few subjects (an unusual layout), read_with_llm() asks the
AI model to do the same job. The person always sees the subjects in an editable table before
anything is compared or saved, so mistakes can be fixed by hand.
"""
import io
import json
import logging
import re
import zipfile
from dataclasses import asdict, dataclass, field
from typing import Optional

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app import cv_parser, llm

logging.getLogger("pypdf").setLevel(logging.ERROR)
log = logging.getLogger("kjs.syllabus")

MAX_FILE_BYTES = 10 * 1024 * 1024        # 10 MB: full syllabi with every module are long
MAX_PDF_PAGES = 200
MIN_TEXT_CHARS = 100
MIN_SUBJECTS = 3                          # fewer than this: the layout was not understood
MAX_TOPIC_CHARS = 20000


class SyllabusError(ValueError):
    """A problem the user can fix (wrong file type, scanned image, empty file ...)."""


@dataclass
class Subject:
    name: str
    semester: Optional[int] = None
    code: Optional[str] = None
    kind: str = "theory"                 # theory / lab / project / other
    is_elective: bool = False
    options: list[str] = field(default_factory=list)
    credits: Optional[float] = None
    topics: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ParsedSyllabus:
    subjects: list[Subject]
    university: Optional[str] = None
    department: Optional[str] = None
    batch: Optional[str] = None
    method: str = "rules"                # rules / ai


# ---------------------------------------------------------------- text from the file
def _pdf_text(data: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise SyllabusError("This PDF is password-protected. Please upload an unlocked copy.")
        return "\n".join((page.extract_text() or "") for page in reader.pages[:MAX_PDF_PAGES])
    except SyllabusError:
        raise
    except (PdfReadError, ValueError, KeyError, TypeError) as error:
        raise SyllabusError("This PDF could not be read. Try saving it again as PDF.") from error


def extract_text(data: bytes) -> str:
    """Text of an uploaded syllabus (PDF or .docx). Raises SyllabusError with a friendly message."""
    if not data:
        raise SyllabusError("The file is empty.")
    if len(data) > MAX_FILE_BYTES:
        raise SyllabusError("The syllabus file is larger than 10 MB.")
    if data[:5] == b"%PDF-":
        text = _pdf_text(data)
    else:
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                is_docx = "word/document.xml" in z.namelist()
        except zipfile.BadZipFile:
            is_docx = False
        if not is_docx:
            raise SyllabusError("Please upload the syllabus as a PDF or Word (.docx) file, or paste its text.")
        try:
            text = cv_parser._docx_text(data)
        except cv_parser.CVError as error:
            raise SyllabusError(str(error).replace("CV", "syllabus")) from error
    if len(text.strip()) < MIN_TEXT_CHARS:
        raise SyllabusError("No text found in this file. If it is a scanned image, please paste the subject "
                            "list as text instead.")
    return text


# ---------------------------------------------------------------- patterns
DASHES = str.maketrans({ch: "-" for ch in "\x15\u2010\u2011\u2012\u2013\u2014\u2015\u2212"})
ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7,
            "eighth": 8, "ninth": 9, "tenth": 10}
ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7, "viii": 8, "ix": 9, "x": 10}
SEMESTER_RE = re.compile(
    r"\b(?:(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth)\s+semester"
    r"|(\d{1,2})(?:st|nd|rd|th)\s+semester"
    r"|semester\s*[-:]?\s*(x|ix|viii|vii|vi|iv|v|iii|ii|i|\d{1,2})\b)", re.I)
# letters (maybe with a dash), maybe a second group of letters, then 3 digits that may be split: PCCCS40 1
CODE_RE = re.compile(r"(?<![A-Za-z0-9])([A-Z]{2,9}-?)\s?([A-Z]{0,6})\s?(\d{1,3})(?:\s(\d{1,2}))?(?![\d.])")
CHOICE_RE = re.compile(r"^\(\s*[A-Z](?:\s*/\s*[A-Z])+\s*\)\s*")              # (A/B/C)
HOURS_RE = re.compile(r"\s(\d{1,2})\s+(\d{1,2})\s+(\d{1,2})\s+(\d{1,2}(?:\.\d)?)(?=\s|$)")   # L T P credits
CREDITS_ONLY_RE = re.compile(r"\s(\d{1,2}(?:\.\d)?)\s*$")
# section labels in capitals (THEORY / PRACTICAL) and "Total ..." rows are not part of a name;
# "Graph Theory" or "Game Theory" are, so only the capital labels are removed
NOISE_RE = re.compile(r"(\s(?:[Tt]otal|TOTAL)\b.*|\s(?:THEORY|PRACTICAL|SESSIONAL))$")
ELECTIVE_CODE_RE = re.compile(r"^(PE|OE|PEC|OEC|EL)", re.I)
LAB_RE = re.compile(r"\b(lab|laboratory|practical|workshop|sessional)\b", re.I)
PROJECT_RE = re.compile(r"^(project(?!\s+management)|internship|industrial training|seminar|dissertation|thesis)\b",
                        re.I)
TOPIC_RE = re.compile(r"\b(module|unit)\s*[-:]?\s*(\d|i{1,3}|iv|v)\b", re.I)
UNIVERSITY_RE = re.compile(r"([A-Z][A-Za-z .&]+University(?: of [A-Za-z ,]+)?)")
DEPARTMENT_RE = re.compile(r"(?:syllabus|curriculum)\s+(?:for|of)\s+"
                           r"(?:B\.?\s?Tech\.?|B\.?\s?E\.?|BCA|MCA|M\.?\s?Tech\.?)\s+(?:in|\(|-)\s*"
                           r"([A-Za-z&().\- ]{2,80}?)\s*(?:\(applicable|\n|$)", re.I)
BATCH_RE = re.compile(r"(?:applicable|effective)\s+from\s+(?:the\s+)?(?:academic\s+)?(?:session|year|batch)?\s*"
                      r"(\d{4}\s*-\s*\d{2,4})", re.I)


def _semester_value(match: re.Match) -> Optional[int]:
    word, number, label = match.group(1), match.group(2), match.group(3)
    if word:
        return ORDINALS[word.lower()]
    if number:
        return int(number)
    label = label.lower()
    return int(label) if label.isdigit() else ROMAN.get(label)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text.translate(DASHES)).strip()


def _code(match: re.Match) -> Optional[str]:
    letters, more, digits, rest = match.groups()
    digits = digits + (rest or "")
    if len(digits) != 3:
        return None
    return (letters + more + digits).replace(" ", "")


def _tidy_name(name: str) -> str:
    name = CHOICE_RE.sub("", name).strip(" -:,;")
    name = re.sub(r"\s*/\s*", " / ", name)
    name = re.sub(r"(?<=[a-z])(?=(?:and|of|in)[A-Z])", " ", name)       # "andNetwork" -> "and Network"
    return NOISE_RE.sub("", name).strip(" -:,;")


def _subject(code: str, chunk: str, semester: Optional[int]) -> Optional[Subject]:
    """chunk = the text after the code, up to the next code."""
    elective_choice = bool(CHOICE_RE.match(chunk))
    hours = HOURS_RE.search(" " + chunk)
    if hours:
        name, credits = chunk[:hours.start()], float(hours.group(4))
        practical_only = hours.group(1) == "0" and hours.group(3) != "0"
    else:
        tail = CREDITS_ONLY_RE.search(chunk[:200])
        name, credits = (chunk[:tail.start()], float(tail.group(1))) if tail else (chunk[:120], None)
        practical_only = False
    name = _tidy_name(name)
    if len(name) < 2 or not re.search(r"[A-Za-z]{2}", name):
        return None
    kind = ("project" if PROJECT_RE.search(name) or code.upper().startswith("PROJ") else
            "lab" if LAB_RE.search(name) or practical_only else "theory")
    options = [o.strip() for o in name.split(" / ") if o.strip()]
    is_elective = elective_choice or bool(ELECTIVE_CODE_RE.match(code)) or (len(options) > 1 and kind == "theory"
                                                                            and not re.search(r"\bII?\b /", name))
    if not is_elective or len(options) < 2:
        options = []
    return Subject(name=name[:300], semester=semester, code=code, kind=kind, is_elective=is_elective,
                   options=options, credits=credits)


def _details(text: str, codes: list[str]) -> dict[str, str]:
    """Topic text for subjects that also appear in the detailed part (Module 1 ... Unit 2 ...)."""
    found: dict[str, str] = {}
    marks = []
    for code in codes:
        pattern = re.compile(r"\s?".join(re.escape(ch) for ch in code.replace("-", "")).replace(r"\s?", r"[\s-]?"))
        for m in pattern.finditer(text):
            marks.append((m.start(), m.end(), code))
    marks.sort()
    for i, (start, end, code) in enumerate(marks):
        stop = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        body = text[end:stop]
        if len(body) > 300 and len(TOPIC_RE.findall(body)) >= 2 and code not in found:
            found[code] = _clean(body)[:MAX_TOPIC_CHARS]
    return found


def _department(raw: str) -> str:
    name = _clean(raw).strip(" -")
    if name.count("(") > name.count(")"):
        name += ")"
    return name[:120]


def _meta(text: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    head = text[:3000]
    university = UNIVERSITY_RE.search(head)
    department = DEPARTMENT_RE.search(head)
    batch = BATCH_RE.search(head)
    return (_clean(university.group(1))[:200] if university else None,
            _department(department.group(1)) if department else None,
            re.sub(r"\s+", "", batch.group(1)) if batch else None)


# ---------------------------------------------------------------- the rule-based reader
def read_with_rules(text: str) -> ParsedSyllabus:
    flat = _clean(text)
    semesters = [(m.start(), _semester_value(m)) for m in SEMESTER_RE.finditer(flat)]
    codes = []
    for m in CODE_RE.finditer(flat):
        code = _code(m)
        if code:
            codes.append((m.start(), m.end(), code))

    subjects: list[Subject] = []
    seen: set[str] = set()
    for i, (start, end, code) in enumerate(codes):
        stop = codes[i + 1][0] if i + 1 < len(codes) else min(len(flat), end + 400)
        chunk = flat[end:stop].strip()
        semester = None
        for position, value in semesters:
            if position > start:
                break
            semester = value
        key = code.replace("-", "").upper()
        if key in seen:                      # the same subject again (e.g. in the detailed part)
            continue
        subject = _subject(code, chunk[:600], semester)
        if subject:
            seen.add(key)
            subjects.append(subject)

    topics = _details(text.translate(DASHES), [s.code for s in subjects if s.code])
    for subject in subjects:
        subject.topics = topics.get(subject.code, "")
    university, department, batch = _meta(text)
    return ParsedSyllabus(subjects=subjects, university=university, department=department, batch=batch)


# ---------------------------------------------------------------- the AI reader (unusual layouts)
LLM_PROMPT = """You read college syllabus text and list its subjects.
Reply with JSON only, no other text, in this shape:
{"department": "...", "batch": "...", "subjects": [
  {"semester": 5, "code": "PCC-CS501", "name": "Operating System", "kind": "theory",
   "is_elective": false, "options": [], "credits": 3}
]}
Rules: kind is one of theory, lab, project, other. For an elective with choices, put each choice in
"options". Use null when something is not in the text. Never invent subjects."""


def read_with_llm(text: str) -> ParsedSyllabus:
    """Ask the AI model to list the subjects. Raises SyllabusError if it can't."""
    try:
        reply = llm.chat([{"role": "system", "content": LLM_PROMPT},
                          {"role": "user", "content": _clean(text)[:24000]}], max_tokens=4000, temperature=0)
    except llm.LLMError as error:
        raise SyllabusError(f"The AI reader is not available right now ({error}).") from error
    match = re.search(r"\{.*\}", reply, re.S)
    try:
        data = json.loads(match.group(0)) if match else {}
    except json.JSONDecodeError:
        data = {}
    subjects = []
    for item in (data.get("subjects") or [])[:200]:
        if not isinstance(item, dict) or not str(item.get("name") or "").strip():
            continue
        kind = item.get("kind") if item.get("kind") in ("theory", "lab", "project", "other") else "theory"
        semester = item.get("semester")
        credits = item.get("credits")
        subjects.append(Subject(
            name=str(item["name"]).strip()[:300],
            semester=semester if isinstance(semester, int) and 1 <= semester <= 10 else None,
            code=(str(item.get("code")).strip()[:40] or None) if item.get("code") else None,
            kind=kind, is_elective=bool(item.get("is_elective")),
            options=[str(o).strip()[:120] for o in (item.get("options") or []) if str(o).strip()][:10],
            credits=float(credits) if isinstance(credits, (int, float)) and 0 <= credits <= 40 else None))
    if not subjects:
        raise SyllabusError("We could not find the subjects in this syllabus. Please type them in the table.")
    department = str(data.get("department") or "").strip()[:120] or None
    batch = str(data.get("batch") or "").strip()[:40] or None
    return ParsedSyllabus(subjects=subjects, department=department, batch=batch, method="ai")


def read_syllabus(text: str, allow_ai: bool = True) -> ParsedSyllabus:
    """Rules first; the AI reader only when the rules find too few subjects."""
    parsed = read_with_rules(text)
    if len(parsed.subjects) >= MIN_SUBJECTS or not allow_ai or not llm.is_configured():
        return parsed
    try:
        return read_with_llm(text)
    except SyllabusError as error:
        log.info("AI syllabus reader failed: %s", error)
        return parsed
