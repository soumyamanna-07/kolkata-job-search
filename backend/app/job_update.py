"""Runs the full job update in the background when an admin clicks "Update jobs now".

It is the same command you run by hand from the backend/ folder:
    python -m scripts.update_jobs --adzuna-mode recent|full
which collects from every source (company boards, Adzuna, Jooble ...), closes old jobs and then
creates the AI embeddings, so new jobs show up for users in search, Best for You and Ask AI.

Only one update runs at a time. Its output goes to a log file, and the admin panel shows the last lines.
"""
import os
import subprocess
import sys
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

BACKEND_DIR = Path(__file__).resolve().parents[1]
LOG_FILE = Path(tempfile.gettempdir()) / "kjs_job_update.log"
MODES = {"quick": "recent", "full": "full"}     # quick: new Adzuna jobs + Jooble; full: all Adzuna jobs + Jooble
TAIL_LINES = 30


def update_command(mode: str) -> list[str]:
    return [sys.executable, "-u", "-m", "scripts.update_jobs", "--adzuna-mode", MODES[mode], "--trigger", "manual"]


class JobUpdateRunner:
    def __init__(self, command: Callable[[str], list[str]] = update_command, log_file: Path = LOG_FILE,
                 cwd: Path = BACKEND_DIR):
        self.command, self.log_file, self.cwd = command, Path(log_file), cwd
        self._lock = threading.Lock()
        self._proc: Optional[subprocess.Popen] = None
        self.mode: Optional[str] = None
        self.started_at: Optional[datetime] = None
        self.finished_at: Optional[datetime] = None
        self.exit_code: Optional[int] = None

    def _check(self) -> bool:
        """True while the update is running. Notes the end time the first time it sees it finished."""
        if self._proc is None:
            return False
        code = self._proc.poll()
        if code is None:
            return True
        if self.exit_code is None:
            self.exit_code, self.finished_at = code, datetime.now(timezone.utc)
        return False

    def start(self, mode: str) -> bool:
        """Start an update. Returns False if one is already running."""
        if mode not in MODES:
            raise ValueError(f"unknown mode {mode!r}")
        with self._lock:
            if self._check():
                return False
            log = open(self.log_file, "w", encoding="utf-8")
            try:
                self._proc = subprocess.Popen(
                    self.command(mode), cwd=self.cwd, stdout=log, stderr=subprocess.STDOUT,
                    env={**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"})
            finally:
                log.close()                            # the update keeps its own copy of the file
            self.mode, self.started_at = mode, datetime.now(timezone.utc)
            self.finished_at = self.exit_code = None
            return True

    def status(self) -> dict:
        with self._lock:
            running = self._check()
            return {"running": running, "mode": self.mode, "started_at": self.started_at,
                    "finished_at": self.finished_at, "exit_code": self.exit_code, "log_tail": self._tail()}

    def _tail(self) -> list[str]:
        if self._proc is None:
            return []
        try:
            lines = self.log_file.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return []
        return lines[-TAIL_LINES:]


runner = JobUpdateRunner()
