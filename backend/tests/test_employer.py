"""Tests for the spam check and the employer -> admin -> live job flow."""
import os
import unittest
import uuid
from unittest import mock

from app import spam

TEST_DB = os.getenv("TEST_DATABASE_URL")

GOOD_DESC = ("We are hiring a Python developer for our Salt Lake office to build REST APIs with FastAPI and "
             "PostgreSQL. You will work with a small team on products used by schools across West Bengal.")


class TestSpamCheck(unittest.TestCase):
    def test_genuine_post_scores_low(self):
        r = spam.check("Python Developer", GOOD_DESC, "https://careers.abctech.in/jobs/12",
                       "hr@abctech.in", "https://www.abctech.in", 600000, 3)
        self.assertEqual((r.score, r.reasons), (0, []))

    def test_scam_post_scores_high(self):
        r = spam.check("DATA ENTRY - WORK FROM HOME!!", "URGENT!! Earn Rs 5000 per day. Pay a small registration "
                       "fee of Rs 500. Contact on WhatsApp!!", "https://bit.ly/abc", "jobs4u@gmail.com", None,
                       5_000_000, 0)
        self.assertEqual(r.score, 100)
        for reason in ["asks_for_fee", "easy_money_promise", "link_shortener", "free_email_domain",
                       "chat_app_contact", "unrealistic_salary", "very_short_description", "shouting_text"]:
            self.assertIn(reason, r.reasons)
        self.assertEqual(r.reasons[0], "asks_for_fee")                 # biggest risk first

    def test_apply_links(self):
        on_board = spam.check("Analyst", GOOD_DESC, "https://jobs.lever.co/abc/1", "hr@abctech.in", None)
        self.assertNotIn("apply_link_on_other_site", on_board.reasons)       # known job board
        elsewhere = spam.check("Analyst", GOOD_DESC, "https://random-site.xyz/apply", "hr@abctech.in",
                               "https://abctech.in")
        self.assertEqual(elsewhere.reasons, ["apply_link_on_other_site"])


@unittest.skipUnless(TEST_DB, "set TEST_DATABASE_URL to run API tests")
class TestEmployerFlow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        from fastapi.testclient import TestClient

        from app import auth, config, embeddings
        from app.routers import employer
        from app.ratelimit import PerKeyLimiter
        from tests.test_auth_and_me import SUPABASE_URL, FakeJwks, make_token
        from tests.test_embeddings import FakeEmbedder

        embeddings.set_embedder(FakeEmbedder())
        cls.patches = [mock.patch.object(config, "DATABASE_URL", TEST_DB),
                       mock.patch.object(config, "SUPABASE_URL", SUPABASE_URL),
                       mock.patch.object(auth, "_jwks", lambda: FakeJwks()),
                       mock.patch.object(employer, "posts_per_day", PerKeyLimiter(1000, window=86400))]
        for p in cls.patches:
            p.start()
        cls.db = psycopg.connect(TEST_DB, autocommit=True)
        cls.ids = {name: str(uuid.uuid4()) for name in ("emp", "emp2", "cand", "admin")}
        for name, uid in cls.ids.items():
            meta = '{"account_type": "employer"}' if name.startswith("emp") else '{}'
            cls.db.execute("insert into auth.users (id, email, raw_user_meta_data) values (%s, %s, %s)",
                           (uid, f"{name}@test.in", meta))
        cls.db.execute("update public.profiles set role = 'admin' where id = %s", (cls.ids["admin"],))
        cls.auth = {name: {"Authorization": f"Bearer {make_token(uid)}"} for name, uid in cls.ids.items()}

        from app.main import app
        cls.cm = TestClient(app)
        cls.client = cls.cm.__enter__()

    @classmethod
    def tearDownClass(cls):
        from app import embeddings
        cls.cm.__exit__(None, None, None)
        cls.db.execute("delete from public.jobs where employer_id = any(%s::uuid[])", (list(cls.ids.values()),))
        cls.db.execute("delete from auth.users where id = any(%s::uuid[])", (list(cls.ids.values()),))
        cls.db.close()
        for p in cls.patches:
            p.stop()
        embeddings.set_embedder(None)

    def job(self, **extra):
        return {"title": "Python Developer", "description": GOOD_DESC, "skills": ["Python"], "area": "Salt Lake",
                "apply_url": "https://careers.abctech.in/jobs/1", "salary_min": 400000, "salary_max": 600000,
                "experience_min": 0, "experience_max": 2, "job_type": "full_time", **extra}

    def profile(self, who="emp", **extra):
        body = {"company_name": "ABC Tech", "official_email": "hr@abctech.in", "website": "https://abctech.in",
                **extra}
        return self.client.put("/api/employer/profile", json=body, headers=self.auth[who])

    def review(self, path, decision, reason=None, who="admin"):
        return self.client.post(path, json={"decision": decision, "reason": reason}, headers=self.auth[who])

    def test_full_flow_from_signup_to_live_job(self):
        c, h = self.client, self.auth
        self.assertEqual(c.get("/api/employer/profile", headers=h["cand"]).status_code, 403)   # candidates can't
        self.assertEqual(self.profile().json()["verification_status"], "pending")
        r = c.post("/api/employer/jobs", json=self.job(), headers=h["emp"])
        self.assertEqual(r.status_code, 403)                                    # company not approved yet
        self.assertIn("waiting for admin approval", r.json()["detail"])

        # only admins can review
        emp_id = self.ids["emp"]
        self.assertEqual(self.review(f"/api/admin/employers/{emp_id}/review", "approve", who="emp").status_code, 403)
        pending = c.get("/api/admin/employers", headers=h["admin"]).json()
        self.assertIn(emp_id, [e["user_id"] for e in pending])
        self.assertEqual(self.review(f"/api/admin/employers/{emp_id}/review", "approve").json()
                         ["verification_status"], "approved")
        self.assertEqual(self.profile().json()["verification_status"], "approved")   # same details: unchanged

        r = c.post("/api/employer/jobs", json=self.job(), headers=h["emp"])
        self.assertEqual(r.status_code, 201, r.text)
        sub = r.json()
        self.assertEqual(sub["status"], "pending")
        self.assertIn("fastapi", sub["skills"])                          # found in the description
        self.assertIn("python", sub["skills"])
        live = self.db.execute("select count(*) from public.jobs where employer_id = %s", (self.ids["emp"],)).fetchone()[0]
        self.assertEqual(live, 0)                                           # nothing public before approval

        queue = c.get("/api/admin/submissions", headers=h["admin"]).json()
        mine = [s for s in queue if s["id"] == sub["id"]][0]
        self.assertEqual((mine["company_name"], mine["spam_score"]), ("ABC Tech", 0.0))

        r = self.review(f"/api/admin/submissions/{sub['id']}/review", "approve")
        self.assertEqual(r.status_code, 200, r.text)
        live_id = r.json()["published_job_id"]
        job = c.get(f"/api/jobs/{live_id}").json()
        self.assertEqual((job["source"], job["status"], job["company_name"], job["area"]),
                         ("employer", "open", "ABC Tech", "Salt Lake"))
        has_vec = self.db.execute("select embedding is not null from public.jobs where id = %s", (live_id,)).fetchone()[0]
        self.assertTrue(has_vec)                                            # ready for AI matching at once
        actions = self.db.execute("select action from public.admin_actions where admin_id = %s order by id",
                                  (self.ids["admin"],)).fetchall()
        self.assertEqual([a[0] for a in actions][-2:], ["approve_employer", "approve_submission"])

        # live jobs can't be edited, only closed
        self.assertEqual(c.put(f"/api/employer/jobs/{sub['id']}", json=self.job(), headers=h["emp"]).status_code, 409)
        self.assertEqual(c.post(f"/api/employer/jobs/{sub['id']}/close", headers=h["emp"]).json()["status"], "closed")
        self.assertEqual(c.get(f"/api/jobs/{live_id}").json()["status"], "closed")

    def test_reject_edit_resubmit_and_block(self):
        c, h = self.client, self.auth
        emp2 = self.ids["emp2"]
        self.profile("emp2", company_name="Quick Money Ltd", official_email="quick@gmail.com", website=None)
        self.assertEqual(self.review(f"/api/admin/employers/{emp2}/review", "reject").status_code, 422)  # no reason
        self.review(f"/api/admin/employers/{emp2}/review", "approve")

        scam = self.job(title="Data entry work from home", description="Earn Rs 3000 per day! Pay a registration fee "
                        "of Rs 499 to start. WhatsApp us now. Daily payment guaranteed for everyone.",
                        apply_url="https://bit.ly/x1")
        sub = c.post("/api/employer/jobs", json=scam, headers=h["emp2"]).json()
        queue = c.get("/api/admin/submissions", headers=h["admin"]).json()
        mine = [s for s in queue if s["id"] == sub["id"]][0]
        self.assertGreaterEqual(mine["spam_score"], 90)
        self.assertIn("asks_for_fee", mine["spam_reasons"])
        self.assertNotIn("spam_score", sub)                                  # employers never see the score

        r = self.review(f"/api/admin/submissions/{sub['id']}/review", "reject", "Asks candidates for a fee")
        self.assertEqual((r.json()["status"], r.json()["rejection_reason"]), ("rejected", "Asks candidates for a fee"))
        mine = c.get(f"/api/employer/jobs/{sub['id']}", headers=h["emp2"]).json()
        self.assertEqual(mine["rejection_reason"], "Asks candidates for a fee")

        fixed = c.put(f"/api/employer/jobs/{sub['id']}", json=self.job(), headers=h["emp2"]).json()
        self.assertEqual((fixed["status"], fixed["rejection_reason"]), ("pending", None))     # back in the queue
        self.assertEqual(self.review(f"/api/admin/submissions/{sub['id']}/review", "approve").status_code, 200)

        # blocking takes the employer's live jobs down and stops new posts
        self.review(f"/api/admin/employers/{emp2}/review", "block", "Repeated scam posts")
        open_jobs = self.db.execute("select count(*) from public.jobs where employer_id = %s and status = 'open'",
                                    (emp2,)).fetchone()[0]
        self.assertEqual(open_jobs, 0)
        self.assertEqual(c.post("/api/employer/jobs", json=self.job(), headers=h["emp2"]).status_code, 403)
        self.assertEqual(self.profile("emp2").status_code, 403)

    def test_validation(self):
        c, h = self.client, self.auth
        self.assertEqual(self.profile(official_email="not-an-email").status_code, 422)
        bad = self.job(salary_min=900000, salary_max=100000)
        self.assertEqual(c.post("/api/employer/jobs", json=bad, headers=h["emp"]).status_code, 422)
        self.assertEqual(c.post("/api/employer/jobs", json=self.job(area="Delhi"), headers=h["emp"]).status_code, 422)
        self.assertEqual(c.post("/api/employer/jobs", json=self.job(description="too short"),
                                headers=h["emp"]).status_code, 422)


if __name__ == "__main__":
    unittest.main()
