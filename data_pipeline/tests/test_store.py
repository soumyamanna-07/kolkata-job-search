"""Database tests for pipeline.store and the full pipeline run.

Needs a TEST database with our migrations applied. NEVER point this at the
real Supabase database. Skipped unless TEST_DATABASE_URL is set.
"""
import os
import unittest
from unittest import mock

TEST_DB = os.getenv("TEST_DATABASE_URL")


@unittest.skipUnless(TEST_DB, "set TEST_DATABASE_URL to run database tests")
class TestPipelineEndToEnd(unittest.TestCase):
    def setUp(self):
        import psycopg
        self.conn = psycopg.connect(TEST_DB, autocommit=True)
        self.conn.execute("truncate public.jobs, public.companies, public.pipeline_runs cascade")
        self.lever_id = self.conn.execute(
            "insert into public.companies (name, normalized_name, ats_platform, ats_token) "
            "values ('ABC Tech', 'abc tech', 'lever', 'abctech') returning id::text").fetchone()[0]

    def tearDown(self):
        self.conn.close()

    def lever_jobs(self, *titles):
        return [{"id": f"id-{t}", "text": t, "hostedUrl": f"https://jobs.lever.co/abctech/{t}",
                 "categories": {"location": "Salt Lake, Kolkata", "commitment": "Full-time"},
                 "descriptionPlain": "2-4 years experience in Python and SQL"} for t in titles]

    def adzuna_page(self, *titles):
        return {"count": len(titles), "results": [
            {"id": t, "title": t, "company": {"display_name": "ABC Tech Pvt Ltd"},
             "location": {"display_name": "Kolkata, West Bengal"}, "redirect_url": f"https://adzuna.in/{t}",
             "description": "short", "salary_min": 500000, "salary_max": 700000, "salary_is_predicted": "0"}
            for t in titles]}

    def run_pipeline(self, lever_payload, adzuna_payload, adzuna_ok=True):
        import run_pipeline
        from pipeline.collectors import base

        def fake_get(url, params=None, timeout=None):
            resp = mock.Mock()
            resp.raise_for_status.return_value = None
            if "lever" in url:
                resp.json.return_value = lever_payload
            else:
                if not adzuna_ok:
                    raise base.requests.ConnectionError("down")
                page = int(url.rstrip("/").rsplit("/", 1)[1])
                resp.json.return_value = adzuna_payload if page == 1 else {"count": 0, "results": []}
            return resp

        session = mock.Mock()
        session.get.side_effect = fake_get
        env = {"DATABASE_URL": TEST_DB}
        with mock.patch.dict(os.environ, env), \
             mock.patch.object(run_pipeline, "make_session", return_value=session), \
             mock.patch.object(run_pipeline.config, "ADZUNA_APP_ID", "id"), \
             mock.patch.object(run_pipeline.config, "ADZUNA_APP_KEY", "key"), \
             mock.patch.object(run_pipeline, "DELAY_BETWEEN_COMPANIES", 0), \
             mock.patch("sys.argv", ["run_pipeline.py"]):
            return run_pipeline.main()

    def jobs(self):
        return self.conn.execute(
            "select title, source, status, salary_min, area from public.jobs order by title").fetchall()

    def test_full_lifecycle(self):
        # Run 1: Lever has 2 jobs, Adzuna has the same Data Analyst job + 1 other
        code = self.run_pipeline(self.lever_jobs("Data Analyst", "ML Engineer"),
                                 self.adzuna_page("Data Analyst", "Accountant"))
        self.assertEqual(code, 0)
        rows = self.jobs()
        self.assertEqual(len(rows), 3)                       # duplicate merged
        analyst = [r for r in rows if r[0] == "Data Analyst"][0]
        self.assertEqual(analyst[1], "lever")                # direct source wins
        self.assertEqual(analyst[4], "Salt Lake")

        run = self.conn.execute("select status, jobs_new, unique_count from public.pipeline_runs").fetchone()
        self.assertEqual(run, ("success", 3, 3))

        # Run 2: Lever removed ML Engineer -> must be closed; Adzuna unchanged
        self.run_pipeline(self.lever_jobs("Data Analyst"), self.adzuna_page("Data Analyst", "Accountant"))
        status = dict((r[0], r[2]) for r in self.jobs())
        self.assertEqual(status, {"Accountant": "open", "Data Analyst": "open", "ML Engineer": "closed"})

        # Run 3: Adzuna is DOWN -> its jobs must NOT be closed
        self.run_pipeline(self.lever_jobs("Data Analyst"), None, adzuna_ok=False)
        status = dict((r[0], r[2]) for r in self.jobs())
        self.assertEqual(status["Accountant"], "open")
        last = self.conn.execute("select status from public.pipeline_runs order by id desc limit 1").fetchone()[0]
        self.assertEqual(last, "partial")

        # Run 4: ML Engineer is posted again -> re-opened
        self.run_pipeline(self.lever_jobs("Data Analyst", "ML Engineer"), self.adzuna_page("Data Analyst", "Accountant"))
        status = dict((r[0], r[2]) for r in self.jobs())
        self.assertEqual(status["ML Engineer"], "open")

    def test_source_returning_nothing_is_suspicious(self):
        self.run_pipeline(self.lever_jobs("A1", "A2", "A3", "A4", "A5", "A6"), self.adzuna_page())
        self.run_pipeline([], self.adzuna_page())            # Lever suddenly empty
        open_count = self.conn.execute(
            "select count(*) from public.jobs where status = 'open' and source = 'lever'").fetchone()[0]
        self.assertEqual(open_count, 6)                      # nothing closed
        msg = self.conn.execute("select error_message from public.pipeline_runs order by id desc limit 1").fetchone()[0]
        self.assertIn("not closing", msg)


if __name__ == "__main__":
    unittest.main()
