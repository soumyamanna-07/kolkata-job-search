"""Admin Panel: "Update jobs now" - collect from every source and embed, without waiting for the schedule.

GET  /api/admin/job-update   is an update running? its last log lines
POST /api/admin/job-update   start one ({"mode": "quick"} or {"mode": "full"})
Only one update at a time, also counting a scheduled run that is still going. Every start is in the audit log.
"""
from datetime import datetime
from typing import Literal, Optional

import psycopg
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.auth import CurrentUser
from app.db import get_conn
from app.job_update import runner
from app.routers.admin import _log, admin_only

router = APIRouter(prefix="/api/admin/job-update", tags=["admin"])

BUSY = "An update is already running. Wait for it to finish, then try again."
# a pipeline run started in the last hour and not finished (for example the scheduled one) counts as busy
OTHER_RUN_SQL = """select exists (select 1 from public.pipeline_runs
                   where status = 'running' and started_at > now() - interval '1 hour')"""


class JobUpdateIn(BaseModel):
    mode: Literal["quick", "full"] = "quick"


class JobUpdateStatus(BaseModel):
    running: bool
    mode: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    exit_code: Optional[int] = None        # 0 = everything worked
    log_tail: list[str] = []
    other_run_active: bool = False         # a run not started from here (e.g. the schedule) is going


def _other_run(conn: psycopg.Connection) -> bool:
    return bool(conn.execute(OTHER_RUN_SQL).fetchone()[0])


@router.get("", response_model=JobUpdateStatus)
def job_update_status(admin: CurrentUser = Depends(admin_only), conn: psycopg.Connection = Depends(get_conn)):
    now = runner.status()
    return JobUpdateStatus(**now, other_run_active=not now["running"] and _other_run(conn))


@router.post("", response_model=JobUpdateStatus, status_code=status.HTTP_202_ACCEPTED)
def start_job_update(body: JobUpdateIn, admin: CurrentUser = Depends(admin_only),
                     conn: psycopg.Connection = Depends(get_conn)):
    if runner.status()["running"] or _other_run(conn):
        raise HTTPException(status.HTTP_409_CONFLICT, BUSY)
    if not runner.start(body.mode):
        raise HTTPException(status.HTTP_409_CONFLICT, BUSY)
    _log(conn, admin, "run_job_update", "pipeline_runs", None, {"mode": body.mode})
    return JobUpdateStatus(**runner.status())
