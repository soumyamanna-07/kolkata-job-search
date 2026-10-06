"""Tests for the Admin Company List: name rule, board check (faked), add / edit / deactivate."""
import os
import unittest
import uuid
from unittest import mock

import httpx

from app import companies, config
from app.companies import check_board, normalize_company

TEST_DB = os.getenv("TEST_DATABASE_URL")

GREENHOUSE = {"jobs": [
    {"title": "Data Analyst", "location": {"name": "Kolkata, India"}},
    {"title": "Backend Engineer", "location": {"name": "Remote"}, "offices": [{"name": "Salt Lake Sector V"}]},
    {"title": "Sales Lead", "location": {"name": "Mumbai"}},
]}
LEVER = [{"text": "ML Engineer", "categories": {"location": "Bengaluru", "allLocations": ["Bengaluru", "New Town"]}},
         {"text": "Designer", "categories": {"location": "Pune"}}]


class FakeResponse:
    def __init__(self, status_code, data=None):
        self.status_code, self._data = status_code, data

    def json(self):
        if self._data is None:
            raise ValueError("not json")
        return self._data


class FakeClient:
    """Answers from a dict: url -> FakeResponse, or an exception to raise."""
    def __init__(self, routes):
        self.routes, self.urls = routes, []

    def get(self, url):
        self.urls.append(url)
        answer = self.routes.get(url, FakeResponse(404))      # unknown board: "not found"
        if isinstance(answer, Exception):
            raise answer
        return answer

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass


GH_URL = "https://boards-api.greenhouse.io/v1/boards/{}/jobs"
LV_URL = "https://api.lever.co/v0/postings/{}?mode=json"
AB_URL = "https://api.ashbyhq.com/posting-api/job-board/{}"
WK_URL = "https://www.workable.com/api/accounts/{}"


class TestCompanyHelpers(unittest.TestCase):
    def test_name_rule_matches_pipeline(self):
        self.assertEqual(normalize_company("ABC Tech Pvt. Ltd."), "abc tech")
        self.assertEqual(normalize_company("Tata Consultancy Services Limited"), "tata consultancy services")
        self.assertEqual(normalize_company("R&D India Private Limited"), "r and d")

    def test_greenhouse_board(self):
        r = check_board(FakeClient({GH_URL.format("abctech"): FakeResponse(200, GREENHOUSE)}), "greenhouse", "abctech")
        self.assertEqual((r.ok, r.jobs, r.kolkata_jobs), (True, 3, 2))
        self.assertEqual(r.sample_titles, ["Data Analyst", "Backend Engineer"])     # Kolkata jobs shown first

    def test_lever_board(self):
        r = check_board(FakeClient({LV_URL.format("xyz"): FakeResponse(200, LEVER)}), "lever", "xyz")
        self.assertEqual((r.ok, r.jobs, r.kolkata_jobs, r.sample_titles), (True, 2, 1, ["ML Engineer"]))

    def test_ashby_and_workable_boards(self):
        ashby = {"jobs": [{"title": "Data Engineer", "location": "Remote", "isListed": True,
                           "secondaryLocations": [{"location": "Kolkata"}]},
                          {"title": "Hidden", "location": "Kolkata", "isListed": False}]}
        workable = {"jobs": [{"title": "QA Engineer", "location": {"location_str": "Salt Lake, Kolkata, India"}},
                             {"title": "Support", "city": "Pune", "state": "MH"}]}
        client = FakeClient({AB_URL.format("x"): FakeResponse(200, ashby),
                             WK_URL.format("y"): FakeResponse(200, workable)})
        self.assertEqual(check_board(client, "ashby", "x").__dict__,
                         {"ok": True, "jobs": 1, "kolkata_jobs": 1, "sample_titles": ["Data Engineer"], "error": None})
        r = check_board(client, "workable", "y")
        self.assertEqual((r.jobs, r.kolkata_jobs, r.sample_titles), (2, 1, ["QA Engineer"]))
        empty = FakeClient({WK_URL.format("ghost"): FakeResponse(200, {"jobs": []}),
                            WK_URL.format("real"): FakeResponse(200, {"name": "Real Co", "jobs": []})})
        self.assertIn("No job board", check_board(empty, "workable", "ghost").error)   # unknown account
        self.assertEqual(check_board(empty, "workable", "real").ok, True)              # real, just no jobs today

    def test_problems(self):
        client = FakeClient({GH_URL.format("nope"): FakeResponse(404), GH_URL.format("down"): FakeResponse(503),
                             GH_URL.format("odd"): FakeResponse(200, None), LV_URL.format("odd"): FakeResponse(200, {}),
                             GH_URL.format("far"): httpx.ConnectError("no route")})
        self.assertIn("No job board with this code", check_board(client, "greenhouse", "nope").error)
        self.assertIn("error 503", check_board(client, "greenhouse", "down").error)
        self.assertIn("could not read", check_board(client, "greenhouse", "odd").error)
        self.assertIn("could not read", check_board(client, "lever", "odd").error)
        self.assertIn("Could not reach", check_board(client, "greenhouse", "far").error)
        self.assertFalse(check_board(client, "smartrecruiters", "abc").ok)          # not supported
        self.assertFalse(check_board(client, "greenhouse", "../admin").ok)          # unsafe code never sent
        self.assertNotIn("../admin", " ".join(client.urls))


@unittest.skipUnless(TEST_DB, "set TEST_DATABASE_URL to run API tests")
class TestCompanyListApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        from fastapi.testclient import TestClient

        from app import auth
        from tests.test_auth_and_me import SUPABASE_URL, FakeJwks, make_token
        cls.patches = [mock.patch.object(config, "DATABASE_URL", TEST_DB),
                       mock.patch.object(config, "SUPABASE_URL", SUPABASE_URL),
                       mock.patch.object(auth, "_jwks", lambda: FakeJwks()),
                       mock.patch.object(companies, "make_client", lambda: FakeClient(
                           {GH_URL.format("abctech"): FakeResponse(200, GREENHOUSE)}))]
        for p in cls.patches:
            p.start()
        cls.db = psycopg.connect(TEST_DB, autocommit=True)
        cls.tag = uuid.uuid4().hex[:6]
        cls.ids = {"admin": str(uuid.uuid4()), "user": str(uuid.uuid4())}
        for name, uid in cls.ids.items():
            cls.db.execute("insert into auth.users (id, email) values (%s, %s)", (uid, f"co-{name}-{cls.tag}@test.in"))
        cls.db.execute("update public.profiles set role = 'admin' where id = %s", (cls.ids["admin"],))
        cls.auth = {name: {"Authorization": f"Bearer {make_token(uid)}"} for name, uid in cls.ids.items()}
        from app.main import app
        cls.cm = TestClient(app)
        cls.client = cls.cm.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.cm.__exit__(None, None, None)
        cls.db.execute("delete from public.jobs where job_key like %s", (f"co-{cls.tag}%",))
        cls.db.execute("delete from public.companies where name like %s", (f"%{cls.tag}%",))
        cls.db.execute("delete from auth.users where id = any(%s::uuid[])", (list(cls.ids.values()),))
        cls.db.close()
        for p in cls.patches:
            p.stop()

    def body(self, **extra):
        return {"name": f"ABC Tech {self.tag} Pvt Ltd", "website": "https://abctech.in",
                "ats_platform": "greenhouse", "ats_token": f"abc{self.tag}", **extra}

    def test_access_and_check_board(self):
        c, h = self.client, self.auth
        self.assertEqual(c.get("/api/admin/companies", headers=h["user"]).status_code, 403)
        r = c.post("/api/admin/companies/check-board", json={"ats_platform": "greenhouse", "ats_token": "abctech"},
                   headers=h["admin"])
        self.assertEqual((r.json()["ok"], r.json()["kolkata_jobs"]), (True, 2))
        bad = c.post("/api/admin/companies/check-board", json={"ats_platform": "greenhouse", "ats_token": "a/b"},
                     headers=h["admin"])
        self.assertEqual(bad.status_code, 422)

    def test_add_edit_deactivate(self):
        c, h = self.client, self.auth
        self.assertEqual(c.post("/api/admin/companies", json=self.body(ats_token=None), headers=h["admin"])
                         .status_code, 422)                                     # greenhouse needs a board code
        r = c.post("/api/admin/companies", json=self.body(), headers=h["admin"])
        self.assertEqual(r.status_code, 201, r.text)
        company = r.json()
        self.assertEqual((company["collected"], company["open_jobs"]), (True, 0))
        again = c.post("/api/admin/companies", json=self.body(name=f"abc tech {self.tag}", ats_token=None,
                                                              ats_platform="other"), headers=h["admin"])
        self.assertEqual(again.status_code, 409)                                # same company, other spelling

        self.db.execute("""insert into public.jobs (job_key, source, company_id, company_name, title, apply_url)
                           values (%s, 'greenhouse', %s, 'ABC', 'Analyst', 'https://x.in')""",
                        (f"co-{self.tag}-1", company["id"]))
        listed = c.get("/api/admin/companies", params={"q": self.tag}, headers=h["admin"]).json()
        self.assertEqual([x["open_jobs"] for x in listed], [1])

        r = c.put(f"/api/admin/companies/{company['id']}", json=self.body(is_active=False), headers=h["admin"])
        self.assertEqual((r.json()["is_active"], r.json()["collected"], r.json()["open_jobs"]), (False, False, 0))
        reason = self.db.execute("select close_reason from public.jobs where job_key = %s",
                                 (f"co-{self.tag}-1",)).fetchone()[0]
        self.assertEqual(reason, "company_removed")
        self.assertEqual(c.put(f"/api/admin/companies/{uuid.uuid4()}", json=self.body(), headers=h["admin"])
                         .status_code, 404)
        log = self.db.execute("select action from public.admin_actions where admin_id = %s order by id",
                              (self.ids["admin"],)).fetchall()
        self.assertEqual([a[0] for a in log][-2:], ["add_company", "update_company"])


if __name__ == "__main__":
    unittest.main()
