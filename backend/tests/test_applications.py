"""My applications tracker: add on Apply, move through stages, notes, privacy between users."""
import os
import unittest
import uuid
from unittest import mock

TEST_DB = os.getenv("TEST_DATABASE_URL")


@unittest.skipUnless(TEST_DB, "set TEST_DATABASE_URL to run API tests")
class TestApplications(unittest.TestCase):
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
        cls.db = psycopg.connect(TEST_DB, autocommit=True)
        tag = uuid.uuid4().hex[:6]
        cls.ids = {"asha": str(uuid.uuid4()), "ravi": str(uuid.uuid4())}
        for name, uid in cls.ids.items():
            cls.db.execute("insert into auth.users (id, email) values (%s, %s)", (uid, f"app-{name}-{tag}@test.in"))
        cls.job_id = cls.db.execute(
            "insert into public.jobs (job_key, source, company_name, title, area, apply_url, skills) "
            "values (%s, 'lever', 'ABC', 'Data Analyst', 'Kolkata', 'https://x/1', '{sql}') returning id::text",
            (f"app-{tag}",)).fetchone()[0]
        from app.main import app
        cls.cm = TestClient(app)
        cls.client = cls.cm.__enter__()
        cls.h = {name: {"Authorization": f"Bearer {make_token(uid)}"} for name, uid in cls.ids.items()}

    @classmethod
    def tearDownClass(cls):
        cls.cm.__exit__(None, None, None)
        cls.db.execute("delete from public.jobs where id = %s", (cls.job_id,))
        cls.db.execute("delete from auth.users where id = any(%s::uuid[])", (list(cls.ids.values()),))
        cls.db.close()
        for p in cls.patches:
            p.stop()

    def test_track_an_application(self):
        c, h, url = self.client, self.h, f"/api/me/applications/{self.job_id}"
        self.assertEqual(c.get("/api/me/applications").status_code, 401)            # login needed
        self.assertEqual(c.put(url).status_code, 401)

        r = c.put(url, headers=h["asha"])
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()["application_status"], r.json()["title"]), ("applied", "Data Analyst"))

        r = c.patch(url, json={"status": "interview", "note": "  Round 1 on Monday  "}, headers=h["asha"])
        self.assertEqual((r.json()["application_status"], r.json()["note"]), ("interview", "Round 1 on Monday"))
        self.assertEqual(c.put(url, headers=h["asha"]).json()["application_status"], "interview")  # Apply again keeps it

        self.assertEqual(c.patch(url, json={"status": "hired"}, headers=h["asha"]).status_code, 422)
        self.assertEqual(c.patch(url, json={}, headers=h["asha"]).status_code, 422)
        self.assertIsNone(c.patch(url, json={"note": ""}, headers=h["asha"]).json()["note"])

        mine = c.get("/api/me/applications", headers=h["asha"]).json()
        self.assertEqual([a["id"] for a in mine], [self.job_id])
        self.assertEqual(c.get("/api/me/applications", headers=h["ravi"]).json(), [])     # private to Asha
        self.assertEqual(c.patch(url, json={"status": "offer"}, headers=h["ravi"]).status_code, 404)

        self.assertEqual(c.delete(url, headers=h["asha"]).status_code, 204)
        self.assertEqual(c.get("/api/me/applications", headers=h["asha"]).json(), [])

    def test_unknown_job(self):
        r = self.client.put(f"/api/me/applications/{uuid.uuid4()}", headers=self.h["ravi"])
        self.assertEqual(r.status_code, 404)


if __name__ == "__main__":
    unittest.main()
