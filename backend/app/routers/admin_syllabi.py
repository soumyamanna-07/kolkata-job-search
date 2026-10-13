"""Admin: check syllabi that users sent, and the colleges they named (Stage 1.7).

Syllabi from logged-in users are used at once as "unverified" (not yet checked). Here the admin
compares the subject table with the text read from the file, fixes subjects and the
department / batch / semester, then approves it (checked) or removes it (rejected; kept for the record).
"Delete permanently" erases it completely. Approving archives the older approved syllabus for the same
college + department + batch + semester, and approves the college if it was new.
Syllabus links (Stage 1.9): links to the syllabus files colleges publish; the weekly fetcher
(scripts/fetch_syllabi.py) reads them and puts new files in the Waiting list.
Every decision is saved in the audit log.
"""
from typing import Literal, Optional
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Response
from psycopg.rows import dict_row
from pydantic import BaseModel, Field, model_validator

from app import embeddings
from app.auth import CurrentUser
from app.db import get_conn
from app.routers.admin import _log, admin_only
from app.routers.syllabus import MAX_SUBJECTS, SubjectIn, _college_by_name, _map, _subject_dict

router = APIRouter(prefix="/api/admin", tags=["admin"])

RAW_TEXT_SHOWN = 30000          # characters of the file's text shown to the admin

LIST_SQL = """
select s.id, s.college_id, c.name as college_name, c.status as college_status, s.department, s.program, s.batch,
       s.semester, s.source, s.status, s.source_url, s.file_name, s.review_note, s.created_at, s.reviewed_at,
       u.email as submitted_by_email,
       (select count(*) from public.syllabus_subjects x where x.syllabus_id = s.id) as subjects
from public.syllabi s join public.colleges c on c.id = s.college_id
left join auth.users u on u.id = s.submitted_by
"""


class SubjectsIn(BaseModel):
    subjects: list[SubjectIn] = Field(min_length=1, max_length=MAX_SUBJECTS)


class SyllabusReview(BaseModel):
    decision: Literal["approve", "reject"]
    note: Optional[str] = Field(None, max_length=1000)          # shown to the person who sent it
    department: Optional[str] = Field(None, min_length=2, max_length=120)
    batch: Optional[str] = Field(None, max_length=40)
    semester: Optional[int] = Field(None, ge=1, le=10)
    whole_course: bool = False                                   # True = set semester to "all semesters"

    @model_validator(mode="after")
    def _reason(self) -> "SyllabusReview":
        if self.decision == "reject" and len((self.note or "").strip()) < 3:
            raise ValueError("please give a reason for rejecting")
        return self


class CollegeUpdate(BaseModel):
    status: Optional[Literal["pending", "approved", "rejected"]] = None
    name: Optional[str] = Field(None, min_length=3, max_length=200)
    short_name: Optional[str] = Field(None, max_length=40)
    university: Optional[str] = Field(None, max_length=200)
    city: Optional[str] = Field(None, max_length=80)
    website: Optional[str] = Field(None, max_length=500, pattern=r"^https?://")
    syllabus_url: Optional[str] = Field(None, max_length=500, pattern=r"^https?://")


class SourceIn(BaseModel):
    college_id: Optional[UUID] = None                             # a college from the list, or
    college_name: Optional[str] = Field(None, min_length=3, max_length=200)   # any college name (added if new)
    url: str = Field(min_length=10, max_length=500, pattern=r"^https?://\S+$")
    department: str = Field(min_length=2, max_length=120)
    batch: Optional[str] = Field(None, max_length=40)
    semester: Optional[int] = Field(None, ge=1, le=10)            # empty = the whole course

    @model_validator(mode="after")
    def _college(self) -> "SourceIn":
        if self.college_id is None and not (self.college_name or "").strip():
            raise ValueError("choose a college or type its name")
        return self


class SourceUpdate(BaseModel):
    url: Optional[str] = Field(None, min_length=10, max_length=500, pattern=r"^https?://\S+$")
    department: Optional[str] = Field(None, min_length=2, max_length=120)
    batch: Optional[str] = Field(None, max_length=40)
    semester: Optional[int] = Field(None, ge=1, le=10)
    enabled: Optional[bool] = None


SOURCE_SQL = """
select s.id, s.college_id, c.name as college_name, s.url, s.department, s.batch, s.semester, s.enabled,
       s.last_checked_at, s.last_status, s.last_error, s.created_at
from public.syllabus_sources s join public.colleges c on c.id = s.college_id
"""


def _one(conn: psycopg.Connection, syllabus_id: UUID) -> dict:
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(LIST_SQL + " where s.id = %s", (syllabus_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Syllabus not found")
    return row


# ---------------------------------------------------------------- syllabi
@router.get("/syllabi")
def list_syllabi(status: Literal["unverified", "pending", "approved", "rejected", "archived", "all"] = "unverified",
                 admin: CurrentUser = Depends(admin_only), conn: psycopg.Connection = Depends(get_conn)):
    """Syllabi to check (oldest first for unverified / pending, newest first otherwise)."""
    where, order = ("", "s.created_at desc") if status == "all" else (" where s.status = %s", "s.created_at desc")
    if status in ("unverified", "pending"):
        order = "s.created_at"
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(f"{LIST_SQL}{where} order by {order} limit 200",
                           () if status == "all" else (status,)).fetchall()


@router.get("/syllabi/{syllabus_id}")
def get_syllabus(syllabus_id: UUID, admin: CurrentUser = Depends(admin_only),
                 conn: psycopg.Connection = Depends(get_conn)):
    """One syllabus: its details, its subject table (with the skills found) and the text read from the file."""
    row = _one(conn, syllabus_id)
    with conn.cursor(row_factory=dict_row) as cur:
        subjects = cur.execute("""select id, semester, code, name, kind, is_elective, options, credits::float as credits,
                                         coalesce(topics, '') as topics, skills
                                  from public.syllabus_subjects where syllabus_id = %s
                                  order by position""", (syllabus_id,)).fetchall()
        text = cur.execute("select coalesce(raw_text, '') as t from public.syllabi where id = %s",
                           (syllabus_id,)).fetchone()["t"]
    return {**row, "subject_list": subjects, "raw_text": text[:RAW_TEXT_SHOWN], "raw_text_length": len(text)}


@router.put("/syllabi/{syllabus_id}/subjects")
def replace_subjects(syllabus_id: UUID, body: SubjectsIn, admin: CurrentUser = Depends(admin_only),
                     conn: psycopg.Connection = Depends(get_conn)):
    """Save the corrected subject table (the skills are found again)."""
    row = _one(conn, syllabus_id)
    if row["status"] not in ("pending", "unverified", "approved"):
        raise HTTPException(409, f"This syllabus is {row['status']}; it cannot be edited")
    subjects = [_subject_dict(s) for s in body.subjects]
    mapped = _map(subjects)
    with conn.transaction():
        conn.execute("delete from public.syllabus_subjects where syllabus_id = %s", (syllabus_id,))
        with conn.cursor() as cur:
            cur.executemany(
                """insert into public.syllabus_subjects (syllabus_id, semester, code, name, kind, is_elective, options,
                                                         credits, topics, skills, embedding, position)
                   values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::extensions.vector, %s)""",
                [(syllabus_id, s["semester"], s["code"], s["name"], s["kind"], s["is_elective"], s["options"],
                  s["credits"], s["topics"] or None, sorted({l.skill for l in m.links}),
                  embeddings.to_pgvector(m.vector) if m.vector is not None else None, i)
                 for i, (s, m) in enumerate(zip(subjects, mapped))])
        conn.execute("update public.syllabi set updated_at = now() where id = %s", (syllabus_id,))
        _log(conn, admin, "edit_syllabus_subjects", "syllabi", str(syllabus_id), {"subjects": len(subjects)})
    return get_syllabus(syllabus_id, admin, conn)


@router.post("/syllabi/{syllabus_id}/review")
def review_syllabus(syllabus_id: UUID, body: SyllabusReview, admin: CurrentUser = Depends(admin_only),
                    conn: psycopg.Connection = Depends(get_conn)):
    """Approve (checked; used before unverified ones) or reject / remove (with a reason the sender sees)."""
    row = _one(conn, syllabus_id)
    if row["status"] not in ("pending", "unverified"):
        raise HTTPException(409, f"This syllabus is already {row['status']}")
    note = (body.note or "").strip() or None
    with conn.transaction():
        if body.decision == "reject":
            conn.execute("""update public.syllabi set status = 'rejected', review_note = %s, reviewed_by = %s,
                                   reviewed_at = now() where id = %s""", (note, admin.id, syllabus_id))
            _log(conn, admin, "reject_syllabus", "syllabi", str(syllabus_id), {"reason": note})
            return _one(conn, syllabus_id)

        if row["subjects"] == 0:
            raise HTTPException(422, "Add the subjects before approving")
        department = " ".join((body.department or row["department"]).split())
        batch = (body.batch if body.batch is not None else row["batch"] or "").strip() or None
        semester = None if body.whole_course else (body.semester if body.semester is not None else row["semester"])
        # the older approved syllabus for the same college + department + batch + semester is archived
        archived = conn.execute(
            """update public.syllabi set status = 'archived'
               where status = 'approved' and college_id = %s and lower(department) = lower(%s)
                 and lower(coalesce(batch, '')) = lower(coalesce(%s, '')) and coalesce(semester, 0) = coalesce(%s, 0)
               returning id""", (row["college_id"], department, batch, semester)).fetchall()
        conn.execute("""update public.syllabi set status = 'approved', department = %s, batch = %s, semester = %s,
                               review_note = %s, reviewed_by = %s, reviewed_at = now() where id = %s""",
                     (department, batch, semester, note, admin.id, syllabus_id))
        if row["college_status"] == "pending":
            conn.execute("update public.colleges set status = 'approved' where id = %s", (row["college_id"],))
        _log(conn, admin, "approve_syllabus", "syllabi", str(syllabus_id),
             {"archived": [str(a[0]) for a in archived], "college_approved": row["college_status"] == "pending"})
    return _one(conn, syllabus_id)


@router.delete("/syllabi/{syllabus_id}", status_code=204)
def delete_syllabus(syllabus_id: UUID, admin: CurrentUser = Depends(admin_only),
                    conn: psycopg.Connection = Depends(get_conn)):
    """Delete a syllabus for good: the row, its subjects and the text read from the file
    (e.g. a test upload, or a file someone asked to take down). Kept in the audit log by id only."""
    row = _one(conn, syllabus_id)
    with conn.transaction():
        conn.execute("delete from public.syllabi where id = %s", (syllabus_id,))
        _log(conn, admin, "delete_syllabus", "syllabi", str(syllabus_id),
             {"college": row["college_name"], "department": row["department"], "status": row["status"]})
    return Response(status_code=204)


# ---------------------------------------------------------------- syllabus links (fetched weekly)
def _source(conn: psycopg.Connection, source_id: UUID) -> dict:
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(SOURCE_SQL + " where s.id = %s", (source_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Syllabus link not found")
    return row


def _tidy(changes: dict) -> dict:
    if changes.get("department") is not None:
        changes["department"] = " ".join(changes["department"].split())
    if "batch" in changes:
        changes["batch"] = (changes["batch"] or "").strip() or None
    if changes.get("url") is not None:
        changes["url"] = changes["url"].strip()
    return changes


def _source_college(conn: psycopg.Connection, admin: CurrentUser, college_id: Optional[UUID],
                    college_name: Optional[str]) -> UUID:
    if college_id is not None:
        row = conn.execute("select status from public.colleges where id = %s", (college_id,)).fetchone()
        if row is None or row[0] == "rejected":
            raise HTTPException(404, "College not found")
        return college_id
    name = " ".join(college_name.split())
    found = _college_by_name(conn, name)
    if found is not None:
        return found
    if conn.execute("select 1 from public.colleges where lower(name) = lower(%s)", (name,)).fetchone():
        raise HTTPException(409, "This college name was rejected. Approve it in Colleges below first.")
    new_id = conn.execute("""insert into public.colleges (name, city, status, created_by)
                             values (%s, 'Kolkata', 'approved', %s) returning id""", (name, admin.id)).fetchone()[0]
    _log(conn, admin, "add_college", "colleges", str(new_id), {"name": name})
    return new_id


@router.get("/syllabus-sources")
def list_sources(admin: CurrentUser = Depends(admin_only), conn: psycopg.Connection = Depends(get_conn)):
    """Links to college syllabus files, with what the last weekly check found."""
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(SOURCE_SQL + " order by c.name, lower(s.department), s.created_at").fetchall()


@router.post("/syllabus-sources", status_code=201)
def add_source(body: SourceIn, admin: CurrentUser = Depends(admin_only),
               conn: psycopg.Connection = Depends(get_conn)):
    """Add a link to a syllabus PDF / Word file; the next weekly check reads it.
    A college typed by name that is not in the list yet is added (approved, since an admin added it)."""
    data = _tidy(body.model_dump())
    try:
        with conn.transaction():
            data["college_id"] = _source_college(conn, admin, data["college_id"], data["college_name"])
            sid = conn.execute(
                """insert into public.syllabus_sources (college_id, url, department, batch, semester, created_by)
                   values (%s, %s, %s, %s, %s, %s) returning id""",
                (data["college_id"], data["url"], data["department"], data["batch"], data["semester"],
                 admin.id)).fetchone()[0]
            _log(conn, admin, "add_syllabus_source", "syllabus_sources", str(sid), {"url": data["url"]})
    except psycopg.errors.UniqueViolation:
        raise HTTPException(409, "This college already has this link")
    return _source(conn, sid)


@router.patch("/syllabus-sources/{source_id}")
def update_source(source_id: UUID, body: SourceUpdate, admin: CurrentUser = Depends(admin_only),
                  conn: psycopg.Connection = Depends(get_conn)):
    """Change a link, or switch it off / on."""
    changes = _tidy(body.model_dump(exclude_unset=True))
    for key in ("url", "department", "enabled"):
        if key in changes and changes[key] is None:
            raise HTTPException(422, f"{key} cannot be empty")
    if not changes:
        raise HTTPException(422, "Nothing to change")
    _source(conn, source_id)
    sets = ", ".join(f"{k} = %s" for k in changes)
    try:
        with conn.transaction():
            conn.execute(f"update public.syllabus_sources set {sets} where id = %s", (*changes.values(), source_id))
            _log(conn, admin, "update_syllabus_source", "syllabus_sources", str(source_id), changes)
    except psycopg.errors.UniqueViolation:
        raise HTTPException(409, "This college already has this link")
    return _source(conn, source_id)


@router.delete("/syllabus-sources/{source_id}", status_code=204)
def delete_source(source_id: UUID, admin: CurrentUser = Depends(admin_only),
                  conn: psycopg.Connection = Depends(get_conn)):
    """Remove a link. Syllabi already fetched from it stay (they have their own status)."""
    row = _source(conn, source_id)
    with conn.transaction():
        conn.execute("delete from public.syllabus_sources where id = %s", (source_id,))
        _log(conn, admin, "delete_syllabus_source", "syllabus_sources", str(source_id), {"url": row["url"]})
    return Response(status_code=204)


# ---------------------------------------------------------------- colleges
@router.get("/colleges")
def list_colleges(status: Literal["pending", "approved", "rejected", "all"] = "all",
                  admin: CurrentUser = Depends(admin_only), conn: psycopg.Connection = Depends(get_conn)):
    """Colleges, with how many syllabi each has."""
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(
            f"""select c.id, c.name, c.short_name, c.university, c.city, c.website, c.syllabus_url, c.status,
                       c.created_at,
                       (select count(*) from public.syllabi s where s.college_id = c.id and s.status = 'approved')
                       as approved_syllabi,
                       (select count(*) from public.syllabi s where s.college_id = c.id
                          and s.status in ('pending', 'unverified')) as pending_syllabi
                from public.colleges c {'' if status == 'all' else 'where c.status = %s'}
                order by c.status = 'pending' desc, c.name""", () if status == "all" else (status,)).fetchall()


@router.patch("/colleges/{college_id}")
def update_college(college_id: UUID, body: CollegeUpdate, admin: CurrentUser = Depends(admin_only),
                   conn: psycopg.Connection = Depends(get_conn)):
    """Fix a college's details, or approve / reject a college name a user typed."""
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(422, "Nothing to change")
    for key in ("name", "short_name", "university", "city"):
        if key in changes and changes[key] is not None:
            changes[key] = " ".join(changes[key].split()) or None
    sets = ", ".join(f"{k} = %s" for k in changes)
    try:
        with conn.cursor(row_factory=dict_row) as cur:
            row = cur.execute(f"update public.colleges set {sets} where id = %s returning id, name, short_name, "
                              "university, city, website, syllabus_url, status",
                              (*changes.values(), college_id)).fetchone()
    except psycopg.errors.UniqueViolation:
        raise HTTPException(409, "Another college already has this name")
    if row is None:
        raise HTTPException(404, "College not found")
    _log(conn, admin, "update_college", "colleges", str(college_id), changes)
    return row
