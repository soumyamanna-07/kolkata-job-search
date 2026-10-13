"""Curriculum gap API: quick check (nothing stored), approved-first lookup, sending a syllabus for approval.
Uses the MADE-UP syllabus from test_syllabus_parser (no real college syllabus in the tests)."""
import io
import json
import os
import unittest
import uuid
import zipfile
from unittest import mock

from tests.test_syllabus_parser import SAMPLE

TEST_DB = os.getenv("TEST_DATABASE_URL")


def docx(text: str) -> bytes:
    body = "".join(f"<w:p><w:r><w:t>{line}</w:t></w:r></w:p>" for line in text.splitlines())
    xml = ('<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/'
           f'main"><w:body>{body}</w:body></w:document>').replace("&", "&amp;")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr("word/document.xml", xml)
    return buffer.getvalue()


class FlatEmbedder:
    """Fake model: every text gets its own direction, so the AI layer never links anything."""

    def __init__(self):
        self.n = 0

    def embed(self, texts):
        out = []
        for _ in texts:
            v = [0.0] * 384
            v[self.n % 384] = 1.0
            self.n += 1
            out.append(v)
        return out


@unittest.skipUnless(TEST_DB, "set TEST_DATABASE_URL to run API tests")
class TestSyllabusApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        from fastapi.testclient import TestClient

        from app import auth, config, curriculum_gap, embeddings, llm, subject_skills
        from app.routers import syllabus
        from tests.test_auth_and_me import SUPABASE_URL, FakeJwks, make_token
        cls.patches = [mock.patch.object(config, "DATABASE_URL", TEST_DB),
                       mock.patch.object(config, "SUPABASE_URL", SUPABASE_URL),
                       mock.patch.object(config, "SUPABASE_JWT_SECRET", ""),
                       mock.patch.object(auth, "_jwks", lambda: FakeJwks()),
                       mock.patch.object(llm, "is_configured", lambda: False)]      # never call the AI reader
        for p in cls.patches:
            p.start()
        embeddings.set_embedder(FlatEmbedder())
        subject_skills.clear_cache()
        curriculum_gap.clear_cache()
        for limiter in (syllabus.reads_per_minute, syllabus.reports_per_minute, syllabus.submissions_per_day):
            limiter._calls.clear()
        cls.db = psycopg.connect(TEST_DB, autocommit=True)
        db = cls.db
        db.execute("truncate public.jobs cascade")
        db.execute("delete from public.syllabi")
        db.execute("delete from public.colleges where name <> 'Techno Main Salt Lake'")
        jobs = [["sql", "python"]] * 30 + [["docker", "kubernetes"]] * 20 + [["react", "javascript"]] * 10
        for i, skills in enumerate(jobs):
            db.execute("""insert into public.jobs (job_key, source, company_name, title, apply_url, skills, status,
                                                   posted_at, job_type)
                          values (%s, 'jooble', 'Co', 'Developer', 'https://x.in', %s, 'open', now(), 'full_time')""",
                       (f"syl{i}", skills))
        cls.college = str(db.execute("select id from public.colleges where name = 'Techno Main Salt Lake'").fetchone()[0])
        tag = uuid.uuid4().hex[:6]
        cls.ids = {"asha": str(uuid.uuid4()), "ravi": str(uuid.uuid4())}
        for name, uid in cls.ids.items():
            db.execute("insert into auth.users (id, email) values (%s, %s)", (uid, f"syl-{name}-{tag}@test.in"))
        from app.main import app
        cls.cm = TestClient(app)
        cls.client = cls.cm.__enter__()
        cls.h = {name: {"Authorization": f"Bearer {make_token(uid)}"} for name, uid in cls.ids.items()}

    @classmethod
    def tearDownClass(cls):
        from app import embeddings
        cls.cm.__exit__(None, None, None)
        cls.db.execute("delete from public.syllabi")
        cls.db.execute("delete from public.colleges where name <> 'Techno Main Salt Lake'")
        cls.db.execute("truncate public.jobs cascade")
        cls.db.execute("delete from auth.users where id = any(%s::uuid[])", (list(cls.ids.values()),))
        cls.db.close()
        embeddings.set_embedder(None)
        for p in cls.patches:
            p.stop()

    def upload(self, url, headers=None, data=None, content=None):
        files = {"file": ("syllabus.docx", content or docx(SAMPLE),
                          "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
        return self.client.post(url, files=files, data=data or {}, headers=headers or {})

    def count(self, table):
        return self.db.execute(f"select count(*) from public.{table}").fetchone()[0]

    def test_1_quick_check_stores_nothing(self):
        r = self.upload("/api/syllabus/read")                                  # guests may use it
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(len(body["subjects"]), 8)
        self.assertEqual(body["department"], "Computer Science (Data Science)")
        self.assertEqual(body["semesters"], [1, 4, 5])
        self.assertEqual(self.count("syllabi"), 0)

        bad = self.upload("/api/syllabus/read", content=b"not a syllabus")
        self.assertEqual(bad.status_code, 422)
        self.assertIn("PDF or Word", bad.json()["detail"])

        r = self.client.post("/api/syllabus/report", json={"subjects": body["subjects"],
                                                           "department": body["department"],
                                                           "current_semester": 5})
        self.assertEqual(r.status_code, 200, r.text)
        out = r.json()
        self.assertEqual((out["source"], out["report"]["field"]), ("quick", "computing"))
        skills = {s["skill"]: s for s in out["report"]["skills"]}
        self.assertEqual(skills["sql"]["status"], "covered")                    # DBMS + Database Lab
        self.assertEqual(skills["docker"]["status"], "elective_only")           # Cloud Computing choice
        self.assertIn("docker", [c["skills"][0]["skill"] for c in out["classes"]["classes"]])
        self.assertEqual(self.count("syllabi"), 0)                             # still nothing stored

    def test_2_report_input_checks(self):
        c = self.client
        self.assertEqual(c.post("/api/syllabus/report", json={}).status_code, 422)
        self.assertEqual(c.post("/api/syllabus/report", json={"subjects": []}).status_code, 422)
        both = {"syllabus_id": str(uuid.uuid4()), "subjects": [{"name": "Python"}]}
        self.assertEqual(c.post("/api/syllabus/report", json=both).status_code, 422)
        self.assertEqual(c.post("/api/syllabus/report", json={"syllabus_id": str(uuid.uuid4())}).status_code, 404)

    def test_3_submit_lookup_and_approve(self):
        c, h = self.client, self.h
        lookup = {"college_id": self.college, "department": "Computer Science (Data Science)", "semester": 4}
        r = c.get("/api/syllabus/lookup", params=lookup).json()
        self.assertEqual((r["found"], r["message"]), (False, "We don't have an approved syllabus for this yet. "
                                                           "Please upload your syllabus."))

        self.assertEqual(self.upload("/api/me/syllabi", data={"department": "CSE"}).status_code, 401)  # login

        r = self.upload("/api/me/syllabi", headers=h["asha"],
                        data={"college_id": self.college, "department": "Computer Science (Data Science)",
                              "batch": "2024-28"})
        self.assertEqual(r.status_code, 201, r.text)
        sid = r.json()["id"]
        self.assertEqual(r.json()["status"], "pending")
        row = self.db.execute("select status, submitted_by::text, length(raw_text) > 100 from public.syllabi "
                              "where id = %s", (sid,)).fetchone()
        self.assertEqual(row, ("pending", self.ids["asha"], True))
        skills = self.db.execute("select skills from public.syllabus_subjects where syllabus_id = %s "
                                 "and name = 'Database Management Systems'", (sid,)).fetchone()[0]
        self.assertIn("sql", skills)

        # pending: not used for anyone yet
        self.assertFalse(c.get("/api/syllabus/lookup", params=lookup).json()["found"])
        self.assertEqual(c.post("/api/syllabus/report", json={"syllabus_id": sid}).status_code, 404)

        mine = c.get("/api/me/syllabi", headers=h["asha"]).json()
        self.assertEqual([(m["id"], m["status"], m["subjects"]) for m in mine], [(sid, "pending", 8)])
        self.assertEqual(c.get("/api/me/syllabi", headers=h["ravi"]).json(), [])

        # an admin approves it (the admin page comes in Stage 1.7)
        self.db.execute("update public.syllabi set status = 'approved', reviewed_at = now() where id = %s", (sid,))
        r = c.get("/api/syllabus/lookup", params=lookup).json()
        self.assertTrue(r["found"])
        self.assertEqual((r["syllabus"]["id"], r["syllabus"]["subjects"]), (sid, 8))
        self.assertIn("more accurate", r["message"])
        other_dept = c.get("/api/syllabus/lookup", params={**lookup, "department": "Mechanical"}).json()
        self.assertFalse(other_dept["found"])

        r = c.post("/api/syllabus/report", json={"syllabus_id": sid, "current_semester": 4,
                                                 "chosen": ["Cloud Computing"]})
        self.assertEqual(r.status_code, 200, r.text)
        out = r.json()
        self.assertEqual((out["source"], out["syllabus"]["college_name"]), ("approved", "Techno Main Salt Lake"))
        docker = [s for s in out["report"]["skills"] if s["skill"] == "docker"][0]
        self.assertEqual(docker["status"], "partial")                          # chosen elective counts

        listed = [x for x in c.get("/api/syllabus/colleges").json() if x["id"] == self.college][0]
        self.assertEqual(listed["syllabi"], [{"department": "Computer Science (Data Science)",
                                              "batch": "2024-28", "semester": None}])
        self.assertEqual(c.delete(f"/api/me/syllabi/{sid}", headers=h["asha"]).status_code, 404)  # approved: stays

    def test_4_new_college_edited_table_and_withdraw(self):
        c, h = self.client, self.h
        table = [{"name": "Python Programming", "semester": 3}, {"name": "Web Technology", "semester": 3},
                 {"name": "Physics", "semester": 1}]
        r = self.upload("/api/me/syllabi", headers=h["ravi"],
                        data={"college_name": "  Example   Institute of Technology ", "department": "IT",
                              "semester": "3", "subjects_json": json.dumps(table)})
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual(r.json()["subjects"], 2)                              # only semester 3 kept
        college = self.db.execute("select name, status from public.colleges where lower(name) = "
                                  "'example institute of technology'").fetchone()
        self.assertEqual(college, ("Example Institute of Technology", "pending"))
        colleges = [x["name"] for x in c.get("/api/syllabus/colleges").json()]
        self.assertNotIn("Example Institute of Technology", colleges)          # pending colleges are not listed

        bad = self.upload("/api/me/syllabi", headers=h["ravi"],
                          data={"college_id": self.college, "department": "IT", "subjects_json": "[{\"x\": 1}]"})
        self.assertEqual(bad.status_code, 422)
        no_college = self.upload("/api/me/syllabi", headers=h["ravi"], data={"department": "IT"})
        self.assertEqual(no_college.status_code, 422)

        sid = r.json()["id"]
        self.assertEqual(c.delete(f"/api/me/syllabi/{sid}", headers=h["asha"]).status_code, 404)   # not hers
        self.assertEqual(c.delete(f"/api/me/syllabi/{sid}", headers=h["ravi"]).status_code, 204)
        self.assertEqual(self.db.execute("select count(*) from public.syllabi where id = %s", (sid,)).fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
