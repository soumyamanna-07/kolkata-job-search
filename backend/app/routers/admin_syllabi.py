"""Admin: check syllabi that users sent, and the colleges they named (Stage 1.7).

A syllabus is used for everyone only after an admin approves it here. Before approving, the admin
can compare the subject table with the text read from the file, fix subjects, and fix the
department / batch / semester. Approving archives the older approved syllabus for the same
college + department + batch + semester, and approves the college if it was new.
Every decision is saved in the audit log.
"""
from typing import Literal, Optional
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException
from psycopg.rows import dict_row
from pydantic import BaseModel, Field, model_validator

from app import embeddings
from app.auth import CurrentUser
from app.db import get_conn
from app.routers.admin import _log, admin_only
from app.routers.syllabus import MAX_SUBJECTS, SubjectIn, _map, _subject_dict

router = APIRouter(prefix="/api/admin", tags=["admin"])

RAW_TEXT_SHOWN = 30000          # characters of the file's text shown to the admin

LIST_SQL = """
select s.id, s.college_id, c.name as college_name, c.status as college_status, s.department, s.program, s.batch,
       s.semester, s.source, s.status, s.file_name, s.review_note, s.created_at, s.reviewed_at,
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


def _one(conn: psycopg.Connection, syllabus_id: UUID) -> dict:
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(LIST_SQL + " where s.id = %s", (syllabus_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Syllabus not found")
    return row


# ---------------------------------------------------------------- syllabi
@router.get("/syllabi")
def list_syllabi(status: Literal["pending", "approved", "rejected", "archived", "all"] = "pending",
                 admin: CurrentUser = Depends(admin_only), conn: psycopg.Connection = Depends(get_conn)):
    """Syllabi to check (oldest first for pending, newest first otherwise)."""
    where, order = ("", "s.created_at desc") if status == "all" else (" where s.status = %s", "s.created_at desc")
    if status == "pending":
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
    if row["status"] not in ("pending", "approved"):
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
    """Approve (it is then used for everyone) or reject (with a reason the sender sees)."""
    row = _one(conn, syllabus_id)
    if row["status"] != "pending":
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
                       (select count(*) from public.syllabi s where s.college_id = c.id and s.status = 'pending')
                       as pending_syllabi
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
