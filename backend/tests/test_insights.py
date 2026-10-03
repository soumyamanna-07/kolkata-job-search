"""Tests for the market insights endpoints, on a small known set of jobs."""
import os
import unittest
from unittest import mock

TEST_DB = os.getenv("TEST_DATABASE_URL")


@unittest.skipUnless(TEST_DB, "set TEST_DATABASE_URL to run API tests")
class TestInsights(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        from fastapi.testclient import TestClient

        from app import config
        from app.routers import insights

        cls.patch = mock.patch.object(config, "DATABASE_URL", TEST_DB)
        cls.patch.start()
        insights.clear_cache()
        db = psycopg.connect(TEST_DB, autocommit=True)
        db.execute("truncate public.jobs cascade")
        jobs = []
        # 6 Python jobs with salaries 3..8 lakh, 2 of them for freshers; 2 SQL-only jobs; 1 closed job
        for i in range(6):
            jobs.append((f"py{i}", "Python Developer", "ABC Tech" if i < 4 else "XYZ Ltd", "Salt Lake",
                         ["python", "sql", "english"], (3 + i) * 100000, (3 + i) * 100000, 0 if i < 2 else 3, "open"))
        jobs.append(("sq1", "Data Analyst", "XYZ Ltd", "Kolkata", ["sql", "excel"], None, None, None, "open"))
        jobs.append(("sq2", "MIS Executive", "Bank Co", "Howrah", ["sql"], None, None, 1, "open"))
        jobs.append(("old", "Old Python Job", "Old Co", "Kolkata", ["python"], 9000000, 9000000, 0, "closed"))
        for key, title, company, area, skills, smin, smax, exp, status in jobs:
            db.execute("""insert into public.jobs (job_key, source, company_name, title, area, apply_url, skills,
                              salary_min, salary_max, experience_min, status, posted_at, job_type)
                          values (%s, 'adzuna', %s, %s, %s, 'https://x.in', %s, %s, %s, %s, %s, now(), 'full_time')""",
                       (key, company, title, area, skills, smin, smax, exp, status))
        db.close()
        from app.main import app
        cls.cm = TestClient(app)
        cls.client = cls.cm.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.cm.__exit__(None, None, None)
        cls.patch.stop()

    def test_market(self):
        m = self.client.get("/api/insights").json()
        self.assertEqual(m["open_jobs"], 8)                                   # closed job not counted
        self.assertEqual((m["fresher_friendly_jobs"], m["fresher_friendly_share"]), (3, 37.5))
        skills = {s["skill"]: s for s in m["top_skills"]}
        self.assertEqual([s["skill"] for s in m["top_skills"][:2]], ["sql", "python"])
        self.assertNotIn("english", skills)                                   # languages left out
        self.assertEqual((skills["python"]["jobs"], skills["python"]["share"]), (6, 75.0))
        self.assertEqual(skills["python"]["salary"]["median"], 550000)       # 3..8 lakh -> 5.5 lakh
        self.assertIsNone(skills["excel"]["salary"]["median"])                # too few salaries to show
        self.assertEqual(m["top_companies"][0], {"value": "ABC Tech", "count": 4})
        self.assertEqual(m["by_area"][0], {"value": "Salt Lake", "count": 6})
        self.assertEqual(m["salary"]["jobs_with_salary"], 6)
        self.assertEqual(sum(d["count"] for d in m["posted_per_day"]), 8)

    def test_one_skill(self):
        s = self.client.get("/api/insights/skills/Python").json()
        self.assertEqual((s["skill"], s["jobs"], s["fresher_friendly_jobs"]), ("python", 6, 2))
        self.assertEqual(s["often_with"], [{"value": "sql", "count": 6}])
        self.assertEqual(s["top_companies"][0], {"value": "ABC Tech", "count": 4})
        self.assertEqual(self.client.get("/api/insights/skills/not-a-skill").status_code, 404)


if __name__ == "__main__":
    unittest.main()
