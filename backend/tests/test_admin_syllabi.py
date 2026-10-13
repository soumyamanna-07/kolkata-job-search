"""Admin approval of syllabi and colleges (made-up syllabus, no real college syllabus in the tests)."""
import json
import os
import unittest
import uuid
from unittest import mock

from tests.test_syllabus_api import FlatEmbedder, docx
from tests.test_syllabus_parser import SAMPLE

TEST_DB = os.getenv("TEST_DATABASE_URL")


@unittest.skipUnless(TEST_DB, "set TEST_DATABASE_URL to run API tests")
class TestAdminSyllabi(unittest.TestCase):
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
                       mock.patch.object(llm, "is_configured", lambda: False)]
        for p in cls.patches:
            p.start()
        embeddings.set_embedder(FlatEmbedder())
        subject_skills.clear_cache()
        curriculum_gap.clear_cache()
        syllabus.submissions_per_day._calls.clear()
        db = cls.db = psycopg.connect(TEST_DB, autocommit=True)
        db.execute("delete from public.syllabi")
        db.execute("delete from public.syllabus_sources")
        db.execute("delete from public.colleges where name <> 'Techno Main Salt Lake'")
        tag = uuid.uuid4().hex[:6]
        cls.ids = {name: str(uuid.uuid4()) for name in ("admin", "asha")}
        for name, uid in cls.ids.items():
            db.execute("insert into auth.users (id, email) values (%s, %s)", (uid, f"{name}-{tag}@syl.test"))
        db.execute("update public.profiles set role = 'admin' where id = %s", (cls.ids["admin"],))
        cls.email = f"asha-{tag}@syl.test"
        cls.tmsl = str(db.execute("select id from public.colleges where name = 'Techno Main Salt Lake'").fetchone()[0])
        from app.main import app
        cls.cm = TestClient(app)
        cls.client = cls.cm.__enter__()
        cls.h = {name: {"Authorization": f"Bearer {make_token(uid)}"} for name, uid in cls.ids.items()}

    @classmethod
    def tearDownClass(cls):
        from app import embeddings
        cls.cm.__exit__(None, None, None)
        cls.db.execute("delete from public.syllabi")
        cls.db.execute("delete from public.syllabus_sources")
        cls.db.execute("delete from public.colleges where name <> 'Techno Main Salt Lake'")
        cls.db.execute("delete from auth.users where id = any(%s::uuid[])", (list(cls.ids.values()),))
        cls.db.close()
        embeddings.set_embedder(None)
        for p in cls.patches:
            p.stop()

    def send(self, **data):
        files = {"file": ("syllabus.docx", docx(SAMPLE),
                          "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
        r = self.client.post("/api/me/syllabi", files=files, data=data, headers=self.h["asha"])
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()["id"]

    def test_1_only_admins(self):
        for method, url in (("get", "/api/admin/syllabi"), ("get", "/api/admin/colleges")):
            self.assertEqual(getattr(self.client, method)(url).status_code, 401)
            self.assertEqual(getattr(self.client, method)(url, headers=self.h["asha"]).status_code, 403)

    def test_2_review_flow(self):
        c, h = self.client, self.h["admin"]
        first = self.send(college_id=self.tmsl, department="CSE (Data Science)", batch="2024-28")

        pending = c.get("/api/admin/syllabi", headers=h).json()
        self.assertEqual([(p["id"], p["submitted_by_email"], p["subjects"]) for p in pending], [(first, self.email, 8)])

        one = c.get(f"/api/admin/syllabi/{first}", headers=h).json()
        self.assertEqual(len(one["subject_list"]), 8)
        self.assertIn("Example Technical University", one["raw_text"])
        dbms = [s for s in one["subject_list"] if s["name"] == "Database Management Systems"][0]
        self.assertIn("sql", dbms["skills"])

        # the admin fixes the table: drops the project, renames a subject
        table = [{k: s[k] for k in ("semester", "code", "name", "kind", "is_elective", "options", "credits", "topics")}
                 for s in one["subject_list"] if s["kind"] != "project"]
        table[0]["name"] = "Calculus and Linear Algebra (fixed)"
        r = c.put(f"/api/admin/syllabi/{first}/subjects", json={"subjects": table}, headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(len(r.json()["subject_list"]), 7)
        self.assertEqual(r.json()["subject_list"][0]["name"], "Calculus and Linear Algebra (fixed)")
        self.assertEqual(c.put(f"/api/admin/syllabi/{first}/subjects", json={"subjects": []}, headers=h).status_code, 422)

        self.assertEqual(c.post(f"/api/admin/syllabi/{first}/review", json={"decision": "reject"},
                                headers=h).status_code, 422)                                 # reason needed
        r = c.post(f"/api/admin/syllabi/{first}/review",
                   json={"decision": "approve", "department": "CSE (Data Science)", "whole_course": True}, headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()["status"], r.json()["semester"]), ("approved", None))
        self.assertEqual(c.post(f"/api/admin/syllabi/{first}/review", json={"decision": "approve"},
                                headers=h).status_code, 409)                                 # already done
        found = c.get("/api/syllabus/lookup", params={"college_id": self.tmsl, "department": "cse (data science)"})
        self.assertEqual(found.json()["syllabus"]["id"], first)

        # a newer one for the same college + department + batch replaces it; the old one is archived
        second = self.send(college_id=self.tmsl, department="CSE (Data Science)", batch="2024-28")
        c.post(f"/api/admin/syllabi/{second}/review", json={"decision": "approve", "whole_course": True}, headers=h)
        status = dict(self.db.execute("select id::text, status from public.syllabi").fetchall())
        self.assertEqual((status[first], status[second]), ("archived", "approved"))
        self.assertEqual(c.put(f"/api/admin/syllabi/{first}/subjects", json={"subjects": table},
                               headers=h).status_code, 409)                                  # archived: locked

        # rejecting: the sender sees the reason
        third = self.send(college_id=self.tmsl, department="ECE")
        r = c.post(f"/api/admin/syllabi/{third}/review", json={"decision": "reject", "note": "This is the old syllabus."},
                   headers=h)
        self.assertEqual(r.json()["status"], "rejected")
        mine = {m["id"]: m for m in c.get("/api/me/syllabi", headers=self.h["asha"]).json()}
        self.assertEqual((mine[third]["status"], mine[third]["review_note"]), ("rejected", "This is the old syllabus."))
        # delete permanently: row, subjects and file text are gone; only admins may do it
        self.assertEqual(c.delete(f"/api/admin/syllabi/{third}", headers=self.h["asha"]).status_code, 403)
        r = c.delete(f"/api/admin/syllabi/{third}", headers=h)
        self.assertEqual(r.status_code, 204, r.text)
        self.assertEqual(self.db.execute("select count(*) from public.syllabi where id = %s", (third,)).fetchone()[0], 0)
        self.assertEqual(self.db.execute("select count(*) from public.syllabus_subjects where syllabus_id = %s",
                                         (third,)).fetchone()[0], 0)
        self.assertEqual(c.delete(f"/api/admin/syllabi/{third}", headers=h).status_code, 404)
        actions = self.db.execute("select action from public.admin_actions where target_table = 'syllabi'").fetchall()
        self.assertIn(("delete_syllabus",), actions)
        self.assertIn(("approve_syllabus",), actions)
        self.assertIn(("reject_syllabus",), actions)

    def test_3_new_college_approved_with_its_syllabus(self):
        c, h = self.client, self.h["admin"]
        sid = self.send(college_name="Example College of Engineering", department="IT",
                        subjects_json=json.dumps([{"name": "Python Programming", "semester": 3}]))
        colleges = {x["name"]: x for x in c.get("/api/admin/colleges", headers=h).json()}
        new = colleges["Example College of Engineering"]
        self.assertEqual((new["status"], new["pending_syllabi"]), ("pending", 1))
        self.assertEqual(c.get("/api/admin/colleges", params={"status": "pending"}, headers=h).json()[0]["id"], new["id"])

        r = c.patch(f"/api/admin/colleges/{new['id']}", json={"short_name": "ECE-K", "university": "MAKAUT",
                                                              "syllabus_url": "https://example.edu/syllabus.pdf"},
                    headers=h)
        self.assertEqual((r.json()["short_name"], r.json()["status"]), ("ECE-K", "pending"))
        self.assertEqual(c.patch(f"/api/admin/colleges/{new['id']}", json={"website": "ftp://x"}, headers=h).status_code, 422)
        self.assertEqual(c.patch(f"/api/admin/colleges/{new['id']}", json={"name": "Techno Main Salt Lake"},
                                 headers=h).status_code, 409)
        self.assertEqual(c.patch(f"/api/admin/colleges/{new['id']}", json={}, headers=h).status_code, 422)

        c.post(f"/api/admin/syllabi/{sid}/review", json={"decision": "approve"}, headers=h)
        listed = [x["name"] for x in c.get("/api/syllabus/colleges").json()]
        self.assertIn("Example College of Engineering", listed)                     # approved with its syllabus

    def test_4_syllabus_links(self):
        c, h = self.client, self.h["admin"]
        url = "https://example.edu/syllabus/cse-r22.pdf"
        body = {"college_id": self.tmsl, "url": url, "department": "  CSE   (AI & ML) ", "batch": " ", "semester": None}
        self.assertEqual(c.get("/api/admin/syllabus-sources", headers=self.h["asha"]).status_code, 403)
        self.assertEqual(c.post("/api/admin/syllabus-sources", json=body, headers=self.h["asha"]).status_code, 403)
        r = c.post("/api/admin/syllabus-sources", json=body, headers=h)
        self.assertEqual(r.status_code, 201, r.text)
        link = r.json()
        self.assertEqual((link["department"], link["batch"], link["enabled"], link["last_status"], link["college_name"]),
                         ("CSE (AI & ML)", None, True, None, "Techno Main Salt Lake"))
        self.assertEqual(c.post("/api/admin/syllabus-sources", json={**body, "url": url.upper().replace("HTTPS", "https")},
                                headers=h).status_code, 409)                         # same link twice
        for bad in ({"url": "ftp://example.edu/x.pdf"}, {"url": "https://exa mple.edu/x.pdf"}, {"semester": 11},
                    {"college_id": str(uuid.uuid4())}):
            self.assertIn(c.post("/api/admin/syllabus-sources", json={**body, **bad}, headers=h).status_code, (404, 422))

        r = c.patch(f"/api/admin/syllabus-sources/{link['id']}", json={"enabled": False, "semester": 5}, headers=h)
        self.assertEqual((r.json()["enabled"], r.json()["semester"]), (False, 5))
        self.assertEqual(c.patch(f"/api/admin/syllabus-sources/{link['id']}", json={"url": None}, headers=h).status_code, 422)
        self.assertEqual(c.patch(f"/api/admin/syllabus-sources/{link['id']}", json={}, headers=h).status_code, 422)
        self.assertEqual([x["id"] for x in c.get("/api/admin/syllabus-sources", headers=h).json()], [link["id"]])

        self.assertEqual(c.delete(f"/api/admin/syllabus-sources/{link['id']}", headers=h).status_code, 204)
        self.assertEqual(c.delete(f"/api/admin/syllabus-sources/{link['id']}", headers=h).status_code, 404)
        self.assertEqual(c.get("/api/admin/syllabus-sources", headers=h).json(), [])
        actions = [a[0] for a in self.db.execute("select action from public.admin_actions "
                                                 "where target_table = 'syllabus_sources'").fetchall()]
        for action in ("add_syllabus_source", "update_syllabus_source", "delete_syllabus_source"):
            self.assertIn(action, actions)

        # any college can be typed: a new name is added (approved), a known name or short name is reused
        typed = {"url": "https://iiests.example/it.pdf", "department": "IT"}
        r = c.post("/api/admin/syllabus-sources", json={**typed, "college_name": "  Example  Institute of Technology "},
                   headers=h)
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual(r.json()["college_name"], "Example Institute of Technology")
        status = self.db.execute("select status from public.colleges where name = 'Example Institute of Technology'")
        self.assertEqual(status.fetchone()[0], "approved")
        r = c.post("/api/admin/syllabus-sources", json={**typed, "url": "https://x.example/cse.pdf", "college_name": "tmsl"},
                   headers=h)
        self.assertEqual(r.json()["college_id"], self.tmsl)
        self.db.execute("insert into public.colleges (name, status) values ('Fake Name College', 'rejected')")
        self.assertEqual(c.post("/api/admin/syllabus-sources", json={**typed, "college_name": "fake name college"},
                                headers=h).status_code, 409)
        self.assertEqual(c.post("/api/admin/syllabus-sources", json={k: v for k, v in body.items() if k != "college_id"},
                                headers=h).status_code, 422)                 # no college at all


if __name__ == "__main__":
    unittest.main()
