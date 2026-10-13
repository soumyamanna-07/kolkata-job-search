"""College Curriculum Gap Report API (Stage 1.6) - for students and faculty.

Three ways in:
  1. Saved syllabus first: type or pick the college, department and semester -> GET /api/syllabus/lookup.
     If a syllabus is in use for them, POST /api/syllabus/report with its id.
     If not, the answer says "please upload your syllabus".
  2. Quick check (guests too, NOTHING is stored): POST /api/syllabus/read with the PDF/Word file,
     correct the subject table if needed, then POST /api/syllabus/report with the subjects.
  3. Save it for everyone (login): POST /api/me/syllabi stores it as "unverified" and it is used for
     everyone at once, shown as "not yet checked". An admin later approves or removes it.
     When an approved and an unverified syllabus both match, the approved one is used.

The report = curriculum gap engine (app.curriculum_gap) + extra classes (app.extra_classes),
compared with live Kolkata jobs (Adzuna jobs never counted).
"""
import json
import logging
from typing import Literal, Optional
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile, status
from psycopg.rows import dict_row
from pydantic import BaseModel, Field, TypeAdapter, ValidationError, field_validator, model_validator

from app import curriculum_gap, embeddings, extra_classes, subject_skills
from app.auth import CurrentUser, get_current_user, get_optional_user
from app.db import get_conn
from app.ratelimit import PerKeyLimiter
from app.syllabus_parser import MAX_FILE_BYTES, SyllabusError, extract_text, read_syllabus

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["syllabus"])

reads_per_minute = PerKeyLimiter(6, window=60)          # reading a file may call the AI reader
reports_per_minute = PerKeyLimiter(20, window=60)
submissions_per_day = PerKeyLimiter(5, window=86400)

MAX_SUBJECTS = 150
IN_USE = ("approved", "unverified")          # syllabi used for everyone (unverified = not yet checked)
FOUND = "Showing the approved syllabus. Upload your own syllabus for a more accurate result."
FOUND_UNVERIFIED = ("Showing a syllabus another student sent (not yet checked by an admin). "
                    "Upload your own syllabus for a more accurate result.")
NOT_FOUND = "We don't have this syllabus yet. Please upload your syllabus."


# ---------------------------------------------------------------- models
class SubjectIn(BaseModel):
    name: str = Field(min_length=2, max_length=300)
    semester: Optional[int] = Field(None, ge=1, le=10)
    code: Optional[str] = Field(None, max_length=40)
    kind: Literal["theory", "lab", "project", "other"] = "theory"
    is_elective: bool = False
    options: list[str] = Field(default_factory=list, max_length=10)
    credits: Optional[float] = Field(None, ge=0, le=40)
    topics: Optional[str] = Field(None, max_length=20000)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = " ".join(v.split())
        if len(v) < 2:
            raise ValueError("subject name is too short")
        return v

    @field_validator("options")
    @classmethod
    def _options(cls, v: list[str]) -> list[str]:
        return [" ".join(o.split())[:120] for o in v if o and o.strip()]


SubjectList = TypeAdapter(list[SubjectIn])


class ReportIn(BaseModel):
    syllabus_id: Optional[UUID] = None                   # an approved syllabus ...
    subjects: Optional[list[SubjectIn]] = Field(None, max_length=MAX_SUBJECTS)    # ... or a quick check
    department: Optional[str] = Field(None, max_length=120)
    current_semester: Optional[int] = Field(None, ge=1, le=10)
    chosen: list[str] = Field(default_factory=list, max_length=20)     # elective choices the student took

    @model_validator(mode="after")
    def _one_source(self) -> "ReportIn":
        if (self.syllabus_id is None) == (not self.subjects):
            raise ValueError("send either syllabus_id or subjects")
        return self


def _visitor(request: Request, user: Optional[CurrentUser]) -> str:
    return user.id if user else (request.client.host if request.client else "unknown")


def _subject_dict(s) -> dict:
    return {"name": s.name, "semester": s.semester, "code": s.code, "kind": s.kind, "is_elective": s.is_elective,
            "options": list(s.options or []), "credits": s.credits, "topics": s.topics or ""}


def _map(subjects: list[dict]) -> list[subject_skills.SubjectSkills]:
    """Link subjects to skills; if the AI model cannot load, the named + table layers still work."""
    try:
        return subject_skills.map_subjects(subjects)
    except Exception:                       # noqa: BLE001 - the report must not fail because of the AI layer
        log.exception("AI layer of the subject mapper failed; continuing without it")
        return subject_skills.map_subjects(subjects, use_ai=False)


# ---------------------------------------------------------------- colleges and approved syllabi
SYLLABUS_META = """s.id, s.department, s.program, s.batch, s.semester, s.source, s.status, s.reviewed_at as approved_at,
                   c.id as college_id, c.name as college_name, c.short_name as college_short_name,
                   c.university, (select count(*) from public.syllabus_subjects x where x.syllabus_id = s.id)
                   as subjects"""


@router.get("/syllabus/colleges")
def colleges(conn: psycopg.Connection = Depends(get_conn)):
    """Colleges people can pick (any college can also be typed), each with the departments /
    semesters that have a syllabus in use. Rejected college names are left out."""
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute("""select id, name, short_name, university, city from public.colleges
                              where status <> 'rejected' order by name""").fetchall()
        syl = cur.execute("""select college_id, department, batch, semester, status from public.syllabi
                             where status = any(%s) order by department, semester nulls first""",
                          (list(IN_USE),)).fetchall()
    by_college: dict = {}
    for s in syl:
        by_college.setdefault(s["college_id"], []).append(
            {"department": s["department"], "batch": s["batch"], "semester": s["semester"],
             "checked": s["status"] == "approved"})
    return [{**r, "syllabi": by_college.get(r["id"], [])} for r in rows]


def _college_by_name(conn: psycopg.Connection, name: str) -> Optional[UUID]:
    name = " ".join(name.split())
    row = conn.execute("""select id from public.colleges where status <> 'rejected'
                          and (lower(name) = lower(%s) or lower(short_name) = lower(%s))
                          order by status = 'approved' desc limit 1""", (name, name)).fetchone()
    return row[0] if row else None


@router.get("/syllabus/lookup")
def lookup(college_id: Optional[UUID] = None, college_name: Optional[str] = Query(None, max_length=200),
           department: str = Query(..., min_length=2, max_length=120),
           semester: Optional[int] = Query(None, ge=1, le=10), conn: psycopg.Connection = Depends(get_conn)):
    """The syllabus in use for this college + department: approved before not-yet-checked, the semester's
    own one before the whole-course one, newest first. Not found -> ask the user to upload theirs.
    The college can be given by id or by the name the user typed."""
    if college_id is None:
        college_id = _college_by_name(conn, college_name or "") if (college_name or "").strip() else None
        if college_id is None:
            return {"found": False, "syllabus": None, "college_id": None, "message": NOT_FOUND}
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            f"""select {SYLLABUS_META} from public.syllabi s join public.colleges c on c.id = s.college_id
                where s.status = any(%s) and s.college_id = %s and lower(s.department) = lower(%s)
                  and (%s::int is null or s.semester is null or s.semester = %s::int)
                order by s.status = 'approved' desc, (s.semester is not null and s.semester = %s::int) desc,
                         coalesce(s.reviewed_at, s.created_at) desc
                limit 1""", (list(IN_USE), college_id, " ".join(department.split()), semester, semester,
                             semester)).fetchone()
    if row is None:
        return {"found": False, "syllabus": None, "college_id": college_id, "message": NOT_FOUND}
    return {"found": True, "syllabus": row, "college_id": college_id,
            "message": FOUND if row["status"] == "approved" else FOUND_UNVERIFIED}


# ---------------------------------------------------------------- quick check (nothing stored)
def _read_file(file: UploadFile):
    data = file.file.read(MAX_FILE_BYTES + 1)          # never read more than the limit
    try:
        text = extract_text(data)
        return text, read_syllabus(text)
    except SyllabusError as error:
        raise HTTPException(422, str(error))


@router.post("/syllabus/read")
def read_file(request: Request, file: UploadFile = File(..., description="Syllabus as PDF or Word (.docx), max 10 MB"),
              user: Optional[CurrentUser] = Depends(get_optional_user)):
    """Read a syllabus file and return its subjects for checking. Nothing is stored."""
    if not reads_per_minute.allow(_visitor(request, user)):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many files at once. Please wait a minute.")
    _, parsed = _read_file(file)
    subjects = [_subject_dict(s) for s in parsed.subjects][:MAX_SUBJECTS]
    return {"subjects": subjects, "university": parsed.university, "department": parsed.department,
            "batch": parsed.batch, "method": parsed.method,
            "semesters": sorted({s["semester"] for s in subjects if s["semester"]})}


def _approved(conn: psycopg.Connection, syllabus_id: UUID) -> tuple[dict, list[dict]]:
    with conn.cursor(row_factory=dict_row) as cur:
        meta = cur.execute(f"""select {SYLLABUS_META} from public.syllabi s
                               join public.colleges c on c.id = s.college_id
                               where s.id = %s and s.status = any(%s)""", (syllabus_id, list(IN_USE))).fetchone()
        if meta is None:
            raise HTTPException(404, "This syllabus is not available")
        subjects = cur.execute("""select name, semester, code, kind, is_elective, options, credits::float as credits,
                                         coalesce(topics, '') as topics
                                  from public.syllabus_subjects where syllabus_id = %s
                                  order by semester nulls first, position""", (syllabus_id,)).fetchall()
    return meta, subjects


@router.post("/syllabus/report")
def report(body: ReportIn, request: Request, user: Optional[CurrentUser] = Depends(get_optional_user),
           conn: psycopg.Connection = Depends(get_conn)):
    """The gap report + extra classes, for an approved syllabus or for subjects from a quick check."""
    if not reports_per_minute.allow(_visitor(request, user)):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many reports at once. Please wait a minute.")
    if body.syllabus_id is not None:
        meta, subjects = _approved(conn, body.syllabus_id)
        department, source = meta["department"], "saved"
    else:
        meta, subjects = None, [_subject_dict(s) for s in body.subjects]
        department, source = body.department, "quick"
    mapped = _map(subjects)
    market = curriculum_gap.load_market(conn, curriculum_gap.field_for_department(department))
    gap = curriculum_gap.build_report(subjects, mapped, market, body.current_semester, body.chosen)
    classes = extra_classes.suggest_classes(gap, market, mapped)
    return {"source": source, "syllabus": meta, "department": department,
            "current_semester": body.current_semester, "report": gap, "classes": classes}


# ---------------------------------------------------------------- share a syllabus (login, admin approves)
def _college_id(conn: psycopg.Connection, user: CurrentUser, college_id: Optional[UUID],
                college_name: Optional[str]) -> UUID:
    if college_id is not None:
        row = conn.execute("select id from public.colleges where id = %s and status <> 'rejected'",
                           (college_id,)).fetchone()
        if row is None:
            raise HTTPException(422, "Unknown college")
        return row[0]
    name = " ".join((college_name or "").split())
    if not 3 <= len(name) <= 200:
        raise HTTPException(422, "Choose your college, or type its full name")
    found = _college_by_name(conn, name)
    if found is not None:
        return found
    row = conn.execute("select id from public.colleges where lower(name) = lower(%s)", (name,)).fetchone()
    if row is not None:                                      # the name exists but was rejected by an admin
        raise HTTPException(422, "This college name was not accepted. Please choose it from the list.")
    return conn.execute("""insert into public.colleges (name, city, status, created_by)
                           values (%s, 'Kolkata', 'pending', %s) returning id""", (name, user.id)).fetchone()[0]


@router.post("/me/syllabi", status_code=status.HTTP_201_CREATED)
def submit(file: UploadFile = File(..., description="The syllabus PDF or Word file (kept for the admin to check)"),
           department: str = Form(..., min_length=2, max_length=120),
           college_id: Optional[UUID] = Form(None),
           college_name: Optional[str] = Form(None, max_length=200),
           batch: Optional[str] = Form(None, max_length=40),
           semester: Optional[int] = Form(None, ge=1, le=10),
           subjects_json: Optional[str] = Form(None, max_length=500_000,
                                               description="The corrected subject table (JSON list); "
                                                           "if left out, the subjects read from the file"),
           user: CurrentUser = Depends(get_current_user), conn: psycopg.Connection = Depends(get_conn)):
    """Save your syllabus for everyone. It is used at once, shown as "not yet checked" until an admin
    approves it (an admin can also remove it)."""
    if not submissions_per_day.allow(user.id):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "You can send up to 5 syllabi a day.")
    text, parsed = _read_file(file)
    if subjects_json:
        try:
            subjects = [_subject_dict(s) for s in SubjectList.validate_python(json.loads(subjects_json))]
        except (ValueError, ValidationError):
            raise HTTPException(422, "The subject table is not valid")
    else:
        subjects = [_subject_dict(s) for s in parsed.subjects]
    if semester is not None:
        subjects = [s for s in subjects if s["semester"] in (None, semester)]
    if not subjects:
        raise HTTPException(422, "No subjects to save. Please add them in the table.")
    subjects = subjects[:MAX_SUBJECTS]
    mapped = _map(subjects)

    with conn.transaction():
        cid = _college_id(conn, user, college_id, college_name)
        sid = conn.execute(
            """insert into public.syllabi (college_id, department, batch, semester, source, status, file_name,
                                           raw_text, submitted_by)
               values (%s, %s, %s, %s, 'upload', 'unverified', %s, %s, %s) returning id""",
            (cid, " ".join(department.split()), (batch or "").strip() or parsed.batch, semester,
             (file.filename or "syllabus")[:200], text[:400000], user.id)).fetchone()[0]
        with conn.cursor() as cur:
            cur.executemany(
                """insert into public.syllabus_subjects (syllabus_id, semester, code, name, kind, is_elective, options,
                                                         credits, topics, skills, embedding, position)
                   values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::extensions.vector, %s)""",
                [(sid, s["semester"], s["code"], s["name"], s["kind"], s["is_elective"], s["options"], s["credits"],
                  s["topics"] or None, sorted({l.skill for l in m.links}),
                  embeddings.to_pgvector(m.vector) if m.vector is not None else None, i)
                 for i, (s, m) in enumerate(zip(subjects, mapped))])
    return {"id": str(sid), "status": "unverified", "subjects": len(subjects),
            "message": "Saved. Classmates who choose the same college and department now get this syllabus."}


@router.get("/me/syllabi")
def my_syllabi(user: CurrentUser = Depends(get_current_user), conn: psycopg.Connection = Depends(get_conn)):
    """The syllabi you sent and their status (unverified = in use, not yet checked / approved / rejected)."""
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(
            """select s.id, c.name as college_name, s.department, s.batch, s.semester, s.status, s.review_note,
                      s.created_at, (select count(*) from public.syllabus_subjects x where x.syllabus_id = s.id)
                      as subjects
               from public.syllabi s join public.colleges c on c.id = s.college_id
               where s.submitted_by = %s order by s.created_at desc""", (user.id,)).fetchall()


@router.delete("/me/syllabi/{syllabus_id}", status_code=status.HTTP_204_NO_CONTENT)
def withdraw(syllabus_id: UUID, user: CurrentUser = Depends(get_current_user),
             conn: psycopg.Connection = Depends(get_conn)):
    """Take back a syllabus you sent, until an admin has approved it."""
    row = conn.execute("""delete from public.syllabi where id = %s and submitted_by = %s
                          and status in ('pending', 'unverified') returning id""", (syllabus_id, user.id)).fetchone()
    if row is None:
        raise HTTPException(404, "No syllabus of yours that can still be taken back has this id")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
