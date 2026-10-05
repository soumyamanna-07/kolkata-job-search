"""Tests for employer stats: counts per job post, own clicks ignored, other employers' data private."""
import os
import unittest
import uuid
from unittest import mock

from app import config
from app.employer_stats import apply_rate, employer_stats

TEST_DB = os.getenv("TEST_DATABASE_URL")


class TestApplyRate(unittest.TestCase):
    def test_rate(self):
        self.assertEqual(apply_rate(1, 8), 12.5)
        self.assertIsNone(apply_rate(0, 0))                     # no views yet: no rate


@unittest.skipUnless(TEST_DB, "set TEST_DATABASE_URL to run database tests")
class TestEmployerStats(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        cls.db = psycopg.connect(TEST_DB, autocommit=True)
        cls.ids = {name: str(uuid.uuid4()) for name in ("emp", "other", "cand1", "cand2")}
        for name, uid in cls.ids.items():
            meta = '{"account_type": "employer"}' if name in ("emp", "other") else '{}'
            cls.db.execute("insert into auth.users (id, email, raw_user_meta_data) values (%s, %s, %s)",
                           (uid, f"stats-{name}-{uid[:6]}@test.in", meta))
        emp = cls.ids["emp"]
        cls.job = cls.db.execute(
            """insert into public.jobs (job_key, source, company_name, title, apply_url, employer_id)
               values (%s, 'employer', 'ABC', 'Python Developer', 'https://x.in', %s) returning id""",
            (f"employer-stats-{emp[:8]}", emp)).fetchone()[0]
        cls.live = cls.db.execute(
            """insert into public.job_submissions (employer_id, title, description, apply_url, status, published_job_id)
               values (%s, 'Python Developer', 'desc', 'https://x.in', 'approved', %s) returning id""",
            (emp, cls.job)).fetchone()[0]
        cls.pending = cls.db.execute(
            """insert into public.job_submissions (employer_id, title, description, apply_url)
               values (%s, 'Data Analyst', 'desc', 'https://x.in') returning id""", (emp,)).fetchone()[0]

        def event(user, kind, session=None, days_ago=0):
            cls.db.execute("""insert into public.job_events (user_id, session_id, job_id, event_type, created_at)
                              values (%s, %s, %s, %s, now() - make_interval(days => %s))""",
                           (user, session, cls.job, kind, days_ago))
        c1, c2 = cls.ids["cand1"], cls.ids["cand2"]
        for kind in ["impression", "impression", "impression", "view", "view", "click_apply", "save"]:
            event(c1, kind)
        event(c2, "view", days_ago=10)                          # older than 7 days
        event(None, "view", session="guest-abc")                # a guest
        event(emp, "view")                                      # employer's own view: not counted
        event(emp, "click_apply")

    @classmethod
    def tearDownClass(cls):
        cls.db.execute("delete from public.jobs where id = %s", (cls.job,))
        cls.db.execute("delete from auth.users where id = any(%s::uuid[])", (list(cls.ids.values()),))
        cls.db.close()

    def test_counts(self):
        stats = employer_stats(self.db, self.ids["emp"])
        by_id = {job["submission_id"]: job for job in stats["jobs"]}
        live = by_id[self.live]
        self.assertEqual((live["shown_in_results"], live["views"], live["unique_viewers"], live["apply_clicks"],
                          live["saves"]), (3, 4, 3, 1, 1))
        self.assertEqual((live["views_7_days"], live["apply_clicks_7_days"]), (3, 1))
        self.assertEqual(live["apply_rate"], 25.0)
        self.assertEqual(live["job_status"], "open")
        pending = by_id[self.pending]
        self.assertEqual((pending["views"], pending["job_id"], pending["apply_rate"]), (0, None, None))
        t = stats["totals"]
        self.assertEqual((t["posts"], t["live_jobs"], t["views"], t["apply_clicks"], t["apply_rate"]),
                         (2, 1, 4, 1, 25.0))

    def test_other_employer_sees_nothing(self):
        stats = employer_stats(self.db, self.ids["other"])
        self.assertEqual((stats["jobs"], stats["totals"]["posts"], stats["totals"]["apply_rate"]), ([], 0, None))


@unittest.skipUnless(TEST_DB, "set TEST_DATABASE_URL to run API tests")
class TestEmployerStatsApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        from fastapi.testclient import TestClient

        from app import auth
        from tests.test_auth_and_me import SUPABASE_URL, FakeJwks, make_token
        cls.patches = [mock.patch.object(config, "DATABASE_URL", TEST_DB),
                       mock.patch.object(config, "SUPABASE_URL", SUPABASE_URL),
                       mock.patch.object(auth, "_jwks", lambda: FakeJwks())]
        for p in cls.patches:
            p.start()
        cls.db = psycopg.connect(TEST_DB, autocommit=True)
        cls.ids = {"emp": str(uuid.uuid4()), "cand": str(uuid.uuid4())}
        cls.db.execute("insert into auth.users (id, email, raw_user_meta_data) values (%s, %s, %s), (%s, %s, '{}')",
                       (cls.ids["emp"], f"sa-{cls.ids['emp'][:6]}@test.in", '{"account_type": "employer"}',
                        cls.ids["cand"], f"sa-{cls.ids['cand'][:6]}@test.in"))
        cls.auth = {name: {"Authorization": f"Bearer {make_token(uid)}"} for name, uid in cls.ids.items()}
        from app.main import app
        cls.cm = TestClient(app)
        cls.client = cls.cm.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.cm.__exit__(None, None, None)
        cls.db.execute("delete from auth.users where id = any(%s::uuid[])", (list(cls.ids.values()),))
        cls.db.close()
        for p in cls.patches:
            p.stop()

    def test_access(self):
        self.assertEqual(self.client.get("/api/employer/stats").status_code, 401)
        self.assertEqual(self.client.get("/api/employer/stats", headers=self.auth["cand"]).status_code, 403)
        r = self.client.get("/api/employer/stats", headers=self.auth["emp"])
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()["totals"]["posts"], r.json()["jobs"]), (0, []))


if __name__ == "__main__":
    unittest.main()
