"""Tests for shared job links: users / TPOs submit, admins review, approved links go live."""
import os
import unittest
import uuid
from unittest import mock

from app import config

TEST_DB = os.getenv("TEST_DATABASE_URL")
DESC = "Campus drive for 2026 batch B.Tech students. Roles in software testing and Python support, Salt Lake."


@unittest.skipUnless(TEST_DB, "set TEST_DATABASE_URL to run API tests")
class TestJobLinks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        from fastapi.testclient import TestClient

        from app import auth, embeddings
        from app.ratelimit import PerKeyLimiter
        from app.routers import job_links
        from tests.test_auth_and_me import SUPABASE_URL, FakeJwks, make_token
        from tests.test_embeddings import FakeEmbedder
        embeddings.set_embedder(FakeEmbedder())
        cls.patches = [mock.patch.object(config, "DATABASE_URL", TEST_DB),
                       mock.patch.object(config, "SUPABASE_URL", SUPABASE_URL),
                       mock.patch.object(auth, "_jwks", lambda: FakeJwks()),
                       mock.patch.object(job_links, "links_per_day", PerKeyLimiter(1000, window=86400))]
        for p in cls.patches:
            p.start()
        cls.db = psycopg.connect(TEST_DB, autocommit=True)
        cls.tag = uuid.uuid4().hex[:8]
        cls.ids = {"user": str(uuid.uuid4()), "tpo": str(uuid.uuid4()), "admin": str(uuid.uuid4())}
        for name, uid in cls.ids.items():
            cls.db.execute("insert into auth.users (id, email) values (%s, %s)", (uid, f"link-{name}-{cls.tag}@test.in"))
        cls.db.execute("update public.profiles set role = 'admin' where id = %s", (cls.ids["admin"],))
        cls.auth = {name: {"Authorization": f"Bearer {make_token(uid)}"} for name, uid in cls.ids.items()}
        from app.main import app
        cls.cm = TestClient(app)
        cls.client = cls.cm.__enter__()

    @classmethod
    def tearDownClass(cls):
        from app import embeddings
        cls.cm.__exit__(None, None, None)
        cls.db.execute("delete from public.jobs where job_key like 'link-%%' and apply_url like %s", (f"%{cls.tag}%",))
        cls.db.execute("delete from auth.users where id = any(%s::uuid[])", (list(cls.ids.values()),))
        cls.db.close()
        for p in cls.patches:
            p.stop()
        embeddings.set_embedder(None)

    def share(self, who, url, **extra):
        return self.client.post("/api/job-links", json={"url": url, **extra}, headers=self.auth[who])

    def review(self, link_id, **body):
        return self.client.post(f"/api/admin/job-links/{link_id}/review", json=body, headers=self.auth["admin"])

    def test_share_review_publish(self):
        c, h, t = self.client, self.auth, self.tag
        self.assertEqual(c.post("/api/job-links", json={"url": f"https://a.in/{t}"}).status_code, 401)
        self.assertEqual(self.share("user", "https://bit.ly/abc").status_code, 422)          # full links only
        self.assertEqual(self.share("user", "not a link").status_code, 422)
        user_link = self.share("user", f"https://careers.abc.in/{t}/1", company_name="ABC").json()
        self.assertEqual(user_link["status"], "pending")
        self.assertEqual(self.share("tpo", f"https://careers.abc.in/{t}/1").status_code, 409)  # already shared
        tpo_link = self.share("tpo", f"https://college.ac.in/{t}/drive", submitter_type="tpo", note="Drive 20 Oct").json()

        self.assertEqual(c.get("/api/admin/job-links", headers=h["user"]).status_code, 403)   # admins only
        queue = [x["id"] for x in c.get("/api/admin/job-links", headers=h["admin"]).json()
                 if t in x["url"]]
        self.assertEqual(queue, [tpo_link["id"], user_link["id"]])                            # TPO links first

        self.assertEqual(self.review(tpo_link["id"], decision="approve").status_code, 422)    # details needed
        r = self.review(tpo_link["id"], decision="approve", title="Graduate Engineer Trainee", company_name="XYZ Ltd",
                        description=DESC, area="Salt Lake", job_type="full_time", experience_min=0)
        self.assertEqual(r.status_code, 200, r.text)
        job_id = r.json()["published_job_id"]
        job = c.get(f"/api/jobs/{job_id}").json()
        self.assertEqual((job["source"], job["status"], job["company_name"], job["apply_url"]),
                         ("campus", "open", "XYZ Ltd", f"https://college.ac.in/{t}/drive"))
        self.assertIn("python", job["skills"])
        has_vec = self.db.execute("select embedding is not null from public.jobs where id = %s", (job_id,)).fetchone()[0]
        self.assertTrue(has_vec)
        self.assertEqual(self.review(tpo_link["id"], decision="reject", reason="x").status_code, 409)
        self.assertEqual(self.share("user", f"https://college.ac.in/{t}/drive").status_code, 409)  # now live

        self.assertEqual(self.review(user_link["id"], decision="reject").status_code, 422)    # reason needed
        r = self.review(user_link["id"], decision="reject", reason="Job is in Pune, not Kolkata")
        self.assertEqual(r.json()["status"], "rejected")
        mine = c.get("/api/me/job-links", headers=h["user"]).json()
        self.assertEqual((mine[0]["status"], mine[0]["rejection_reason"]), ("rejected", "Job is in Pune, not Kolkata"))
        log = self.db.execute("select action from public.admin_actions where admin_id = %s order by id",
                              (self.ids["admin"],)).fetchall()
        self.assertEqual([a[0] for a in log], ["approve_job_link", "reject_job_link"])


if __name__ == "__main__":
    unittest.main()
