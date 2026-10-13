"""API tests against a TEST database (with our migrations applied).

NEVER point TEST_DATABASE_URL at the real Supabase database - these tests
delete and insert rows. Skipped unless TEST_DATABASE_URL is set.
"""
import os
import unittest
from unittest import mock

TEST_DB = os.getenv("TEST_DATABASE_URL")


@unittest.skipUnless(TEST_DB, "set TEST_DATABASE_URL to run API tests")
class TestJobsApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        from fastapi.testclient import TestClient

        from app import config
        cls.patch = mock.patch.object(config, "DATABASE_URL", TEST_DB)
        cls.patch.start()
        conn = psycopg.connect(TEST_DB, autocommit=True)
        conn.execute("truncate public.jobs cascade")
        rows = [
            # key, source, company, title, area, salary_min, salary_max, exp_min, type, mode, skills, days_ago, status
            ("k1", "lever", "ABC Tech", "Python Developer", "Salt Lake", 600000, 900000, 1, "full_time", "hybrid", ["python", "fastapi", "sql"], 1, "open"),
            ("k2", "adzuna", "XYZ Bank", "Data Analyst", "Kolkata", None, None, 0, "full_time", "onsite", ["sql", "excel", "power bi"], 3, "open"),
            ("k3", "adzuna", "ABC Tech", "Sales Executive", "New Town", 250000, 300000, 2, "full_time", None, ["sales"], 10, "open"),
            ("k4", "greenhouse", "Infra Ltd", "ML Intern", "Kolkata", 15000, 20000, 0, "internship", "remote", ["python", "machine learning"], 40, "open"),
            ("k5", "lever", "Old Co", "Python Developer (closed)", "Kolkata", None, None, None, None, None, ["python"], 2, "closed"),
        ]
        cls.ids = {}
        for key, src, comp, title, area, smin, smax, exp, jt, wm, sk, days, st in rows:
            cls.ids[key] = conn.execute(
                """insert into public.jobs (job_key, source, company_name, title, description, area, apply_url,
                       salary_min, salary_max, experience_min, job_type, work_mode, skills, posted_at, status)
                   values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, now() - make_interval(days => %s), %s)
                   returning id::text""",
                (key, src, comp, title, f"{title} role in Kolkata. Skills: {', '.join(sk)}.", area,
                 f"https://example.com/{key}", smin, smax, exp, jt, wm, sk, days, st)).fetchone()[0]
        conn.close()

        from app.main import app
        cls.client_cm = TestClient(app)
        cls.client = cls.client_cm.__enter__()      # runs startup (opens the pool)

    @classmethod
    def tearDownClass(cls):
        cls.client_cm.__exit__(None, None, None)
        cls.patch.stop()

    def titles(self, **params):
        r = self.client.get("/api/jobs", params=params)
        self.assertEqual(r.status_code, 200, r.text)
        return [j["title"] for j in r.json()["items"]]

    def test_health(self):
        self.assertEqual(self.client.get("/health").json(), {"status": "ok", "database": "ok"})

    def test_only_open_jobs_direct_apply_first_then_newest(self):
        # default sort: jobs that link straight to the employer (lever, greenhouse) first, then job sites
        self.assertEqual(self.titles(), ["Python Developer", "ML Intern", "Data Analyst", "Sales Executive"])
        self.assertEqual(self.titles(sort="newest"),
                         ["Python Developer", "Data Analyst", "Sales Executive", "ML Intern"])
        self.assertEqual(self.titles(direct_only="true"), ["Python Developer", "ML Intern"])

    def test_text_search(self):
        self.assertEqual(self.titles(q="python"), ["Python Developer", "ML Intern"])
        self.assertEqual(self.titles(q="analyst"), ["Data Analyst"])
        self.assertEqual(self.titles(q="abc tech"), ["Python Developer", "Sales Executive"])

    def test_filters(self):
        self.assertEqual(self.titles(area="Salt Lake,New Town"), ["Python Developer", "Sales Executive"])
        self.assertEqual(self.titles(company="ABC Tech"), ["Python Developer", "Sales Executive"])
        self.assertEqual(self.titles(skills="SQL"), ["Python Developer", "Data Analyst"])
        self.assertEqual(self.titles(job_type="internship"), ["ML Intern"])
        self.assertEqual(self.titles(work_mode="remote"), ["ML Intern"])
        self.assertEqual(self.titles(posted_within_days=5), ["Python Developer", "Data Analyst"])
        self.assertEqual(self.titles(experience_years=0), ["ML Intern", "Data Analyst"])

    def test_salary_filter(self):
        # undisclosed salaries included by default
        self.assertEqual(self.titles(salary_expected=500000), ["Python Developer", "Data Analyst"])
        self.assertEqual(self.titles(salary_expected=500000, include_undisclosed_salary=False), ["Python Developer"])

    def test_sorting(self):
        self.assertEqual(self.titles(sort="salary")[0], "Python Developer")
        # skill relevance: more matching skills first
        self.assertEqual(self.titles(skills="python,fastapi", sort="relevance")[0], "Python Developer")

    def test_paging(self):
        r = self.client.get("/api/jobs", params={"page_size": 3, "page": 2}).json()
        self.assertEqual((r["total"], r["pages"], len(r["items"])), (4, 2, 1))
        r = self.client.get("/api/jobs", params={"page_size": 3, "page": 9}).json()
        self.assertEqual((r["total"], len(r["items"])), (4, 0))

    def test_bad_input_rejected(self):
        self.assertEqual(self.client.get("/api/jobs", params={"area": "Mumbai"}).status_code, 422)
        self.assertEqual(self.client.get("/api/jobs", params={"page_size": 500}).status_code, 422)
        self.assertEqual(self.client.get("/api/jobs", params={"sort": "random"}).status_code, 422)

    def test_injection_attempt_is_harmless(self):
        self.assertEqual(self.titles(q="'; drop table public.jobs; --"), [])
        self.assertEqual(len(self.titles()), 4)

    def test_job_detail(self):
        r = self.client.get(f"/api/jobs/{self.ids['k1']}").json()
        self.assertEqual((r["title"], r["status"]), ("Python Developer", "open"))
        self.assertIn("Kolkata", r["description"])
        closed = self.client.get(f"/api/jobs/{self.ids['k5']}").json()
        self.assertEqual(closed["status"], "closed")
        self.assertEqual(self.client.get("/api/jobs/00000000-0000-0000-0000-000000000000").status_code, 404)
        self.assertEqual(self.client.get("/api/jobs/not-a-uuid").status_code, 422)

    def test_filter_options(self):
        r = self.client.get("/api/jobs/filters").json()
        self.assertEqual(r["total_open_jobs"], 4)
        self.assertEqual(r["companies"][0], {"value": "ABC Tech", "count": 2})
        self.assertIn({"value": "python", "count": 2}, r["skills"])
        self.assertEqual((r["salary_min"], r["salary_max"]), (15000, 900000))


if __name__ == "__main__":
    unittest.main()
