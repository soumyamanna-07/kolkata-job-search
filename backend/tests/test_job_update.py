"""Tests for "Update jobs now" in the admin panel. The real update is never run: a tiny fake command is used."""
import os
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest import mock

from app import config
from app.job_update import JobUpdateRunner, update_command

TEST_DB = os.getenv("TEST_DATABASE_URL")


def fake_runner(seconds=0.6, code=0):
    """A runner whose 'update' prints two lines, waits a moment and ends with the given exit code."""
    script = f"import sys, time; print('collecting'); print('done'); time.sleep({seconds}); sys.exit({code})"
    log = Path(tempfile.mkdtemp()) / "update.log"
    return JobUpdateRunner(command=lambda mode: [sys.executable, "-c", script], log_file=log)


def wait_until_done(runner, limit=10):
    end = time.time() + limit
    while runner.status()["running"] and time.time() < end:
        time.sleep(0.1)
    return runner.status()


class TestRunner(unittest.TestCase):
    def test_real_command(self):
        cmd = update_command("full")
        self.assertEqual(cmd[1:], ["-u", "-m", "scripts.update_jobs", "--adzuna-mode", "full", "--trigger", "manual"])
        self.assertIn("recent", update_command("quick"))

    def test_one_at_a_time_then_finished(self):
        runner = fake_runner()
        self.assertEqual(runner.status()["running"], False)
        self.assertTrue(runner.start("quick"))
        self.assertTrue(runner.status()["running"])
        self.assertFalse(runner.start("full"))                  # already running
        done = wait_until_done(runner)
        self.assertEqual((done["running"], done["exit_code"], done["mode"]), (False, 0, "quick"))
        self.assertEqual(done["log_tail"], ["collecting", "done"])
        self.assertIsNotNone(done["finished_at"])
        self.assertTrue(runner.start("full"))                   # can start again once finished
        wait_until_done(runner)

    def test_failure_is_reported(self):
        runner = fake_runner(seconds=0, code=3)
        runner.start("full")
        self.assertEqual(wait_until_done(runner)["exit_code"], 3)

    def test_unknown_mode(self):
        with self.assertRaises(ValueError):
            fake_runner().start("everything")


@unittest.skipUnless(TEST_DB, "set TEST_DATABASE_URL to run API tests")
class TestJobUpdateApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        from fastapi.testclient import TestClient

        from app import auth
        from app.routers import admin_job_update
        from tests.test_auth_and_me import SUPABASE_URL, FakeJwks, make_token
        cls.runner = fake_runner(seconds=0.8)
        cls.patches = [mock.patch.object(config, "DATABASE_URL", TEST_DB),
                       mock.patch.object(config, "SUPABASE_URL", SUPABASE_URL),
                       mock.patch.object(auth, "_jwks", lambda: FakeJwks()),
                       mock.patch.object(admin_job_update, "runner", cls.runner)]
        for p in cls.patches:
            p.start()
        cls.db = psycopg.connect(TEST_DB, autocommit=True)
        cls.tag = uuid.uuid4().hex[:6]
        cls.ids = {"admin": str(uuid.uuid4()), "user": str(uuid.uuid4())}
        for name, uid in cls.ids.items():
            cls.db.execute("insert into auth.users (id, email) values (%s, %s)", (uid, f"ju-{name}-{cls.tag}@test.in"))
        cls.db.execute("update public.profiles set role = 'admin' where id = %s", (cls.ids["admin"],))
        cls.auth = {name: {"Authorization": f"Bearer {make_token(uid)}"} for name, uid in cls.ids.items()}
        from app.main import app
        cls.cm = TestClient(app)
        cls.client = cls.cm.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.cm.__exit__(None, None, None)
        wait_until_done(cls.runner)
        cls.db.execute("delete from public.admin_actions where admin_id = %s", (cls.ids["admin"],))
        cls.db.execute("delete from auth.users where id = any(%s::uuid[])", (list(cls.ids.values()),))
        cls.db.close()
        for p in cls.patches:
            p.stop()

    def test_admin_starts_one_update(self):
        c, h = self.client, self.auth
        self.assertEqual(c.post("/api/admin/job-update", json={"mode": "quick"}, headers=h["user"]).status_code, 403)
        self.assertEqual(c.post("/api/admin/job-update", json={"mode": "all"}, headers=h["admin"]).status_code, 422)

        r = c.post("/api/admin/job-update", json={"mode": "full"}, headers=h["admin"])
        self.assertEqual(r.status_code, 202, r.text)
        self.assertEqual((r.json()["running"], r.json()["mode"]), (True, "full"))
        self.assertEqual(c.post("/api/admin/job-update", json={"mode": "quick"}, headers=h["admin"]).status_code, 409)

        wait_until_done(self.runner)
        s = c.get("/api/admin/job-update", headers=h["admin"]).json()
        self.assertEqual((s["running"], s["exit_code"], s["log_tail"]), (False, 0, ["collecting", "done"]))
        logged = self.db.execute("select details->>'mode' from public.admin_actions where admin_id = %s "
                                 "and action = 'run_job_update'", (self.ids["admin"],)).fetchall()
        self.assertEqual(logged, [("full",)])

    def test_busy_while_a_scheduled_run_is_going(self):
        wait_until_done(self.runner)
        run_id = self.db.execute("insert into public.pipeline_runs (trigger_type) values ('schedule') "
                                 "returning id").fetchone()[0]
        try:
            s = self.client.get("/api/admin/job-update", headers=self.auth["admin"]).json()
            self.assertTrue(s["other_run_active"])
            r = self.client.post("/api/admin/job-update", json={"mode": "quick"}, headers=self.auth["admin"])
            self.assertEqual(r.status_code, 409)
        finally:
            self.db.execute("delete from public.pipeline_runs where id = %s", (run_id,))


if __name__ == "__main__":
    unittest.main()
