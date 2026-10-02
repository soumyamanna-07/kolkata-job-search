"""CV upload endpoints, against a TEST database. Skipped unless TEST_DATABASE_URL is set."""
import os
import unittest
import uuid
from unittest import mock

from tests.test_auth_and_me import SUPABASE_URL, FakeJwks, make_token
from tests.test_cv_parser import STUDENT_CV, make_pdf

TEST_DB = os.getenv("TEST_DATABASE_URL")


@unittest.skipUnless(TEST_DB, "set TEST_DATABASE_URL to run API tests")
class TestCvApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        from fastapi.testclient import TestClient

        from app import auth, config, embeddings
        from tests.test_embeddings import FakeEmbedder
        embeddings.set_embedder(FakeEmbedder())            # no real AI model needed in tests
        cls.patches = [mock.patch.object(config, "DATABASE_URL", TEST_DB),
                       mock.patch.object(config, "SUPABASE_URL", SUPABASE_URL),
                       mock.patch.object(auth, "_jwks", lambda: FakeJwks())]
        for p in cls.patches:
            p.start()
        cls.db = psycopg.connect(TEST_DB, autocommit=True)
        cls.user_id = str(uuid.uuid4())
        cls.db.execute("insert into auth.users (id, email) values (%s, 'cv@x.com')", (cls.user_id,))

        from app.main import app
        cls.cm = TestClient(app)
        cls.client = cls.cm.__enter__()
        cls.auth = {"Authorization": f"Bearer {make_token(cls.user_id)}"}
        cls.pdf = make_pdf(STUDENT_CV)

    @classmethod
    def tearDownClass(cls):
        cls.cm.__exit__(None, None, None)
        cls.db.execute("delete from auth.users where id = %s", (cls.user_id,))
        cls.db.close()
        for p in cls.patches:
            p.stop()
        from app import embeddings
        embeddings.set_embedder(None)

    def upload(self, url, data=None, headers=None, name="cv.pdf"):
        return self.client.post(url, files={"file": (name, data or self.pdf, "application/pdf")}, headers=headers)

    def test_guest_parse_stores_nothing(self):
        before = self.db.execute("select count(*) from public.cvs").fetchone()[0]
        r = self.upload("/api/cv/parse")
        self.assertEqual(r.status_code, 200)
        self.assertIn("python", r.json()["skills"])
        self.assertEqual(r.json()["education"], "B.Tech / B.E.")
        self.assertEqual(self.db.execute("select count(*) from public.cvs").fetchone()[0], before)

    def test_bad_file_message(self):
        r = self.upload("/api/cv/parse", data=b"\x89PNG not a cv" * 10, name="photo.png")
        self.assertEqual(r.status_code, 422)
        self.assertIn("PDF or Word", r.json()["detail"])

    def test_save_edit_delete_lifecycle(self):
        self.assertEqual(self.upload("/api/me/cv").status_code, 401)                       # login needed
        self.db.execute("update public.profiles set privacy_consent_at = null where id = %s", (self.user_id,))
        self.assertEqual(self.upload("/api/me/cv", headers=self.auth).status_code, 403)    # consent needed
        self.client.post("/api/me/consent", headers=self.auth)

        r = self.upload("/api/me/cv", headers=self.auth)
        self.assertEqual(r.status_code, 201)
        self.assertIn("sql", r.json()["skills"])
        has_vec = self.db.execute("select embedding is not null and embedding_hash is not null from public.cvs "
                                  "where user_id = %s", (self.user_id,)).fetchone()[0]
        self.assertTrue(has_vec)                                                          # AI embedding saved
        self.upload("/api/me/cv", headers=self.auth, name="new.pdf")                        # replaces old CV
        rows = self.db.execute("select file_name from public.cvs where user_id = %s", (self.user_id,)).fetchall()
        self.assertEqual(rows, [("new.pdf",)])

        edit = {"skills": ["Python", "Docker", "python"], "experience_years": 1, "education": "B.Tech / B.E.",
                "job_titles": ["ML Intern"]}
        r = self.client.put("/api/me/cv", json=edit, headers=self.auth)
        self.assertEqual((r.json()["skills"], r.json()["experience_years"]), (["docker", "python"], 1.0))
        self.assertEqual(self.client.get("/api/me/cv", headers=self.auth).json()["skills"], ["docker", "python"])
        too_many = {**edit, "skills": [f"s{i}" for i in range(61)]}
        self.assertEqual(self.client.put("/api/me/cv", json=too_many, headers=self.auth).status_code, 422)

        self.assertEqual(self.client.delete("/api/me/cv", headers=self.auth).status_code, 204)
        self.assertEqual(self.client.get("/api/me/cv", headers=self.auth).status_code, 404)

    def test_no_contact_details_stored(self):
        self.client.post("/api/me/consent", headers=self.auth)
        self.upload("/api/me/cv", headers=self.auth)
        row = self.db.execute("select (to_jsonb(c) - 'embedding' - 'embedding_hash')::text from public.cvs c where user_id = %s",
                              (self.user_id,)).fetchone()[0]                     # AI numbers skipped
        for private in ["test@example.com", "90000", "Soumya Test"]:
            self.assertNotIn(private, row)


if __name__ == "__main__":
    unittest.main()
