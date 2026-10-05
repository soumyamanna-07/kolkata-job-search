"""Delete my account (right to erasure, DPDP Act 2023).

Deleting the Supabase login (auth.users) removes everything personal, because every
table points to it with ON DELETE CASCADE / SET NULL:
    removed       : profile, CV data, saved jobs, job alerts, employer profile, job posts
    kept, anonymous: clicks/views (user_id -> null), job reports (reporter -> null)
An employer's live jobs are closed first, so no job stays open without an owner.
"""
from dataclasses import dataclass

import psycopg


class CannotDelete(Exception):
    pass


@dataclass
class Deleted:
    cvs: int
    saved_jobs: int
    alerts: int
    closed_jobs: int


def delete_account(conn: psycopg.Connection, user_id: str) -> Deleted:
    with conn.transaction():
        row = conn.execute("select role from public.profiles where id = %s for update", (user_id,)).fetchone()
        if row is None:
            raise LookupError("account not found")
        if row[0] == "admin":
            raise CannotDelete("Admin accounts cannot be deleted here. Ask another admin to remove your admin role first.")
        counts = conn.execute(
            """select (select count(*) from public.cvs where user_id = %(u)s),
                      (select count(*) from public.saved_jobs where user_id = %(u)s),
                      (select count(*) from public.job_alerts where user_id = %(u)s)""", {"u": user_id}).fetchone()
        closed = conn.execute(
            """update public.jobs set status = 'closed', closed_at = now()
               where employer_id = %s and status = 'open' returning id""", (user_id,)).fetchall()
        conn.execute("delete from auth.users where id = %s", (user_id,))
    return Deleted(cvs=counts[0], saved_jobs=counts[1], alerts=counts[2], closed_jobs=len(closed))
