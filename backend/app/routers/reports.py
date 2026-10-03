"""'Report this job': logged-in users flag a job (spam, fake, already closed ...).
Admins see the reports in the Admin Panel (/api/admin/reports)."""
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.auth import CurrentUser, get_current_user
from app.db import get_conn
from app.schemas import JobReportIn

router = APIRouter(prefix="/api", tags=["jobs"])


@router.post("/jobs/{job_id}/report", status_code=status.HTTP_204_NO_CONTENT)
def report_job(job_id: UUID, body: JobReportIn, user: CurrentUser = Depends(get_current_user),
               conn: psycopg.Connection = Depends(get_conn)):
    """Report a job. One report per user per job."""
    if conn.execute("select 1 from public.jobs where id = %s", (job_id,)).fetchone() is None:
        raise HTTPException(404, "Job not found")
    try:
        conn.execute("insert into public.job_reports (job_id, reporter_id, reason, details) values (%s, %s, %s, %s)",
                     (job_id, user.id, body.reason, (body.details or "").strip() or None))
    except psycopg.errors.UniqueViolation:
        raise HTTPException(409, "You have already reported this job. Thank you!")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
