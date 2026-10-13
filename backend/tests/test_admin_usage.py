"""Admin usage numbers: accounts, active users, guest visitors, applications by stage."""
import os
import unittest
import uuid
from unittest import mock

TEST_DB = os.getenv("TEST_DATABASE_URL")


@unittest.skipUnless(TEST_DB, "set TEST_DATABASE_URL to run API tests")
class TestAdminUsage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        from fastapi.testclient import TestClient

        from app import auth, config
        from tests.test_auth_and_me import SUPABASE_URL, FakeJwks, make_token
        cls.patches = [mock.patch.object(config, "DATABASE_URL", TEST_DB),
                       mock.patch.object(config, "SUPABASE_URL", SUPABASE_URL),
                       mock.patch.object(config, "SUPABASE_JWT_SECRET", ""),
                       mock.patch.object(auth, "_jwks", lambda: FakeJwks())]
        for p in cls.patches:
            p.start()
        db = cls.db = psycopg.connect(TEST_DB, autocommit=True)
        db.execute("truncate public.jobs, public.job_events cascade")
        db.execute("delete from auth.users")
        cls.ids = {name: str(uuid.uuid4()) for name in ("admin", "asha", "ravi", "old")}
        for name, uid in cls.ids.items():
            db.execute("insert into auth.users (id, email) values (%s, %s)", (uid, f"{name}@usage.test"))
        db.execute("update public.profiles set role = 'admin' where id = %s", (cls.ids["admin"],))
        db.execute("update public.profiles set created_at = now() - interval '45 days' where id = %s",
                   (cls.ids["old"],))
        job = db.execute("insert into public.jobs (job_key, source, company_name, title, area, apply_url) "
                         "values ('u1', 'lever', 'ABC', 'Analyst', 'Kolkata', 'https://x/1') returning id").fetchone()[0]
        # Asha: active today (viewed + applied, now at interview); Ravi: saved a job 10 days ago
        db.execute("insert into public.job_events (user_id, job_id, event_type) values (%s, %s, 'view')",
                   (cls.ids["asha"], job))
        db.execute("insert into public.applications (user_id, job_id, status) values (%s, %s, 'interview')",
                   (cls.ids["asha"], job))
        db.execute("insert into public.saved_jobs (user_id, job_id, created_at) values (%s, %s, now() - interval '10 days')",
                   (cls.ids["ravi"], job))
        # two guests today, one of them twice; one guest 3 days ago
        for session, age in (("g1", "0"), ("g1", "0"), ("g2", "0"), ("g3", "3 days")):
            db.execute("insert into public.job_events (session_id, job_id, event_type, created_at) "
                       "values (%s, %s, 'view', now() - %s::interval)", (session, job, age))
        from app.main import app
        cls.cm = TestClient(app)
        cls.client = cls.cm.__enter__()
        cls.h = {name: {"Authorization": f"Bearer {make_token(uid)}"} for name, uid in cls.ids.items()}

    @classmethod
    def tearDownClass(cls):
        cls.cm.__exit__(None, None, None)
        cls.db.execute("truncate public.jobs, public.job_events cascade")
        cls.db.execute("delete from auth.users")
        cls.db.close()
        for p in cls.patches:
            p.stop()

    def test_admins_only(self):
        self.assertEqual(self.client.get("/api/admin/usage").status_code, 401)
        self.assertEqual(self.client.get("/api/admin/usage", headers=self.h["asha"]).status_code, 403)

    def test_numbers(self):
        u = self.client.get("/api/admin/usage", headers=self.h["admin"]).json()
        self.assertEqual(u["accounts_total"], 4)
        self.assertEqual(u["new_accounts"], {"today": 3, "days_7": 3, "days_30": 3})        # "old" is 45 days old
        self.assertEqual(u["active_users"], {"today": 1, "days_7": 1, "days_30": 2})        # Asha; + Ravi (10 days)
        self.assertEqual(u["visitors"], {"today": 2, "days_7": 3, "days_30": 3})
        self.assertEqual((u["applications_total"], u["applications_new_7_days"]), (1, 1))
        self.assertEqual(u["applications_by_stage"],
                         {"applied": 0, "interview": 1, "offer": 0, "rejected": 0, "no_reply": 0})
        self.assertEqual(len(u["daily"]), 30)
        today = u["daily"][-1]
        self.assertEqual((today["new_accounts"], today["active_users"], today["visitors"]), (3, 1, 2))


if __name__ == "__main__":
    unittest.main()
