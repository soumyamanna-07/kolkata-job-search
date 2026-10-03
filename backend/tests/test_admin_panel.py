"""Tests for 'Report this job' and the Admin Panel (reports, users, health, stats, models, audit log)."""
import os
import unittest
import uuid
from unittest import mock

TEST_DB = os.getenv("TEST_DATABASE_URL")


@unittest.skipUnless(TEST_DB, "set TEST_DATABASE_URL to run API tests")
class TestAdminPanel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        from fastapi.testclient import TestClient

        from app import auth, config
        from tests.test_auth_and_me import SUPABASE_URL, FakeJwks, make_token

        cls.patches = [mock.patch.object(config, "DATABASE_URL", TEST_DB),
                       mock.patch.object(config, "SUPABASE_URL", SUPABASE_URL),
                       mock.patch.object(auth, "_jwks", lambda: FakeJwks())]
        for p in cls.patches:
            p.start()
        cls.db = psycopg.connect(TEST_DB, autocommit=True)
        cls.tag = uuid.uuid4().hex[:8]
        cls.ids = {name: str(uuid.uuid4()) for name in ("u1", "u2", "admin", "admin2")}
        for name, uid in cls.ids.items():
            cls.db.execute("insert into auth.users (id, email, raw_user_meta_data) values (%s, %s, %s)",
                           (uid, f"{name}-{cls.tag}@test.in", '{"full_name": "Test %s"}' % name))
        cls.db.execute("update public.profiles set role = 'admin' where id = any(%s::uuid[])",
                       ([cls.ids["admin"], cls.ids["admin2"]],))
        cls.auth = {name: {"Authorization": f"Bearer {make_token(uid)}"} for name, uid in cls.ids.items()}
        cls.job_id = str(cls.db.execute(
            """insert into public.jobs (job_key, source, company_name, title, apply_url, posted_at)
               values (%s, 'adzuna', 'Scam Co', 'Easy Money Job', 'https://x.in/1', now()) returning id""",
            (f"rep-{cls.tag}",)).fetchone()[0])
        cls.db.execute("insert into public.pipeline_runs (status, trigger_type, jobs_new) values ('success', 'manual', 24)")

        from app.main import app
        cls.cm = TestClient(app)
        cls.client = cls.cm.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.cm.__exit__(None, None, None)
        cls.db.execute("delete from public.jobs where job_key = %s", (f"rep-{cls.tag}",))
        cls.db.execute("delete from auth.users where id = any(%s::uuid[])", (list(cls.ids.values()),))
        cls.db.close()
        for p in cls.patches:
            p.stop()

    def report(self, who, reason="fake"):
        return self.client.post(f"/api/jobs/{self.job_id}/report", json={"reason": reason, "details": "asks for money"},
                                headers=self.auth.get(who, {}))

    def test_reports_flow(self):
        c, h = self.client, self.auth
        self.assertEqual(self.report("guest").status_code, 401)                 # login needed
        self.assertEqual(self.report("u1").status_code, 204)
        self.assertEqual(self.report("u1").status_code, 409)                    # one report per user per job
        self.assertEqual(self.report("u2", "spam").status_code, 204)
        self.assertEqual(c.post(f"/api/jobs/{uuid.uuid4()}/report", json={"reason": "fake"},
                                headers=h["u1"]).status_code, 404)
        self.assertEqual(self.report("u2", "made_up_reason").status_code, 422)

        self.assertEqual(c.get("/api/admin/reports", headers=h["u1"]).status_code, 403)    # admins only
        mine = [r for r in c.get("/api/admin/reports", headers=h["admin"]).json() if r["job_id"] == self.job_id]
        self.assertEqual(len(mine), 2)
        self.assertEqual(mine[0]["reports_for_job"], 2)
        self.assertEqual(mine[0]["company_name"], "Scam Co")

        r = c.post(f"/api/admin/reports/{mine[0]['id']}/resolve", json={"action": "close_job", "note": "fee scam"},
                   headers=h["admin"])
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(c.get(f"/api/jobs/{self.job_id}").json()["status"], "closed")
        statuses = self.db.execute("select status from public.job_reports where job_id = %s", (self.job_id,)).fetchall()
        self.assertEqual({s[0] for s in statuses}, {"resolved"})                # both reports resolved at once
        self.assertEqual(c.post(f"/api/admin/reports/{mine[1]['id']}/resolve", json={"action": "dismiss"},
                                headers=h["admin"]).status_code, 409)

    def test_users_and_blocking(self):
        c, h = self.client, self.auth
        found = c.get("/api/admin/users", params={"q": f"u1-{self.tag}"}, headers=h["admin"]).json()
        self.assertEqual([u["email"] for u in found], [f"u1-{self.tag}@test.in"])
        self.assertEqual(found[0]["has_cv"], False)
        admins = c.get("/api/admin/users", params={"role": "admin", "q": self.tag}, headers=h["admin"]).json()
        self.assertEqual(len(admins), 2)

        body = {"blocked": True, "reason": "abusive reports"}
        self.assertEqual(c.post(f"/api/admin/users/{self.ids['u2']}/block", json=body, headers=h["admin"])
                         .json()["is_blocked"], True)
        self.assertEqual(c.get("/api/me", headers=h["u2"]).status_code, 403)    # blocked users are locked out
        c.post(f"/api/admin/users/{self.ids['u2']}/block", json={"blocked": False, "reason": "appeal accepted"},
               headers=h["admin"])
        self.assertEqual(c.get("/api/me", headers=h["u2"]).status_code, 200)

        self.assertEqual(c.post(f"/api/admin/users/{self.ids['admin']}/block", json=body,
                                headers=h["admin"]).status_code, 409)           # not yourself
        self.assertEqual(c.post(f"/api/admin/users/{self.ids['admin2']}/block", json=body,
                                headers=h["admin"]).status_code, 409)           # not other admins
        self.assertEqual(c.post(f"/api/admin/users/{self.ids['u1']}/block", json={"blocked": True},
                                headers=h["admin"]).status_code, 422)           # reason needed

    def test_health_stats_models_and_audit(self):
        c, h = self.client, self.auth
        runs = c.get("/api/admin/pipeline-runs", headers=h["admin"]).json()
        self.assertEqual(runs[0]["jobs_new"], 24)
        s = c.get("/api/admin/stats", headers=h["admin"]).json()
        for key in ["open_jobs", "open_jobs_by_source", "new_jobs_7_days", "jobs_without_embedding", "users_by_role",
                    "pending_employers", "pending_job_posts", "open_reports", "last_pipeline_run"]:
            self.assertIn(key, s)
        self.assertGreaterEqual(s["users_by_role"]["admin"], 2)
        names = {m["model_name"] for m in c.get("/api/admin/models", headers=h["admin"]).json()}
        self.assertTrue({"match_score", "spam_check", "assistant_llm", "text_embedding"} <= names)

        c.post(f"/api/admin/users/{self.ids['u1']}/block", json={"blocked": False, "reason": "audit test"},
               headers=h["admin"])
        log = c.get("/api/admin/actions", params={"limit": 5}, headers=h["admin"]).json()
        self.assertEqual((log[0]["action"], log[0]["admin_email"]), ("unblock_user", f"admin-{self.tag}@test.in"))
        for path in ["/api/admin/stats", "/api/admin/pipeline-runs", "/api/admin/models", "/api/admin/actions",
                     "/api/admin/users"]:
            self.assertEqual(c.get(path, headers=h["u1"]).status_code, 403)


if __name__ == "__main__":
    unittest.main()
