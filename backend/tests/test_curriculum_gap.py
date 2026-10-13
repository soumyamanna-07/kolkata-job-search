"""Tests for the curriculum gap engine, on a MADE-UP syllabus and a made-up job market."""
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from app import curriculum_gap as cg
from app.subject_skills import map_subjects

NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)
TEST_DB = os.getenv("TEST_DATABASE_URL")


def day(n):
    return NOW - timedelta(days=n)


def market_rows():
    """100 open computing jobs + 10 sales jobs + older closed jobs for the trend."""
    rows = []
    for i in range(100):
        skills = ["sql"]                                   # every job: sql
        if i < 60:
            skills.append("python")                        # 60%: python
        if i < 30:
            skills.append("docker")                        # 30%: docker
        if i < 12:
            skills.append("english")                       # a language: never in the report
        if i < 3:
            skills.append("kafka")                         # only 3 jobs: too few to report
        rows.append((skills, True, day(i % 30), 0 if i % 2 else 3))   # all posted in the last 30 days
    for i in range(10):
        rows.append((["sales", "excel"], True, day(5), 1))            # not a computing job
    for i in range(60):                                    # day 31..90: docker was rare back then
        rows.append((["sql", "python"] + (["docker"] if i < 3 else []), False, day(40 + i % 40), 2))
    return rows


SUBJECTS = [
    {"name": "Physics-I", "semester": 1, "kind": "theory"},
    {"name": "Database Management Systems", "semester": 4, "kind": "theory"},
    {"name": "Database Management Systems Lab", "semester": 4, "kind": "lab"},
    {"name": "Python Programming", "semester": 5, "kind": "theory"},
    {"name": "Cloud Computing / Graph Theory", "semester": 6, "kind": "theory",
     "options": ["Cloud Computing", "Graph Theory"], "is_elective": True},
]


class TestStatistics(unittest.TestCase):
    def test_wilson(self):
        low, high = cg.wilson(50, 100)
        self.assertAlmostEqual(low, 0.404, places=3)
        self.assertAlmostEqual(high, 0.596, places=3)
        self.assertEqual(cg.wilson(0, 0), (0.0, 0.0))
        self.assertEqual(cg.wilson(0, 10)[0], 0.0)

    def test_two_proportions(self):
        self.assertLess(cg.two_proportion_p(30, 100, 3, 60), 0.001)
        self.assertGreater(cg.two_proportion_p(30, 100, 18, 60), 0.5)
        self.assertEqual(cg.two_proportion_p(1, 0, 1, 10), 1.0)

    def test_field(self):
        self.assertEqual(cg.field_for_department("CSE (Artificial Intelligence & Machine Learning)"), "computing")
        self.assertEqual(cg.field_for_department("Information Technology"), "computing")
        self.assertEqual(cg.field_for_department("Mechanical Engineering"), "all")
        self.assertEqual(cg.field_for_department(None), "all")


class TestMarket(unittest.TestCase):
    def setUp(self):
        self.m = cg.build_market(market_rows(), "computing", now=NOW)

    def test_counts(self):
        self.assertEqual(self.m.jobs, 100)                 # the sales jobs are not computing jobs
        self.assertEqual(self.m.fresher_jobs, 50)
        self.assertEqual((self.m.recent_jobs, self.m.older_jobs), (100, 60))
        self.assertEqual([s for s in self.m.skills], ["sql", "python", "docker"])
        self.assertNotIn("english", self.m.skills)
        self.assertNotIn("kafka", self.m.skills)           # fewer than MIN_JOBS
        self.assertAlmostEqual(self.m.skills["python"].share, 0.6)

    def test_trend(self):
        self.assertEqual(self.m.skills["docker"].trend, "rising")     # 30% now vs 5% before
        self.assertEqual(self.m.skills["sql"].trend, "steady")
        self.assertEqual(self.m.skills["python"].trend, "falling")    # 60% now vs 100% before
        self.assertLess(self.m.skills["docker"].p_value, 0.05)

    def test_computing_report_leaves_out_other_skills(self):
        rows = [(["python", "sales"], True, day(1), 0) for _ in range(10)]
        m = cg.build_market(rows, "computing", now=NOW)
        self.assertEqual((m.jobs, list(m.skills)), (10, ["python"]))   # the job counts, "sales" is not reported

    def test_all_field_includes_sales(self):
        m = cg.build_market(market_rows(), "all", now=NOW)
        self.assertEqual(m.jobs, 110)
        self.assertIn("sales", m.skills)

    def test_no_trend_with_few_jobs(self):
        m = cg.build_market(market_rows()[:100], "computing", now=NOW)
        self.assertEqual(m.skills["docker"].trend, "unknown")
        self.assertIsNone(m.skills["docker"].p_value)


class TestReport(unittest.TestCase):
    def setUp(self):
        self.market = cg.build_market(market_rows(), "computing", now=NOW)
        self.mapped = map_subjects(SUBJECTS, use_ai=False)

    def skill(self, report, name):
        return [x for x in report["skills"] if x["skill"] == name][0]

    def test_report(self):
        r = cg.build_report(SUBJECTS, self.mapped, self.market)
        sql, python, docker = (self.skill(r, s) for s in ("sql", "python", "docker"))
        self.assertEqual((sql["status"], sql["coverage"]), ("covered", 1.0))        # 0.9 + lab practice
        self.assertEqual(python["status"], "covered")
        self.assertEqual(docker["status"], "elective_only")                         # only in Cloud Computing
        self.assertEqual(docker["taught_in"][0]["option"], "Cloud Computing")
        self.assertEqual(r["learn_now"][0]["skill"], "docker")
        self.assertEqual(r["summary"]["foundation_subjects"], 1)
        self.assertEqual(r["foundation_subjects"][0]["name"], "Physics-I")
        self.assertEqual(r["summary"]["elective_only"], 1)
        # demand-weighted coverage: (sql 1.0 x 100% + python 1.0 x 60% + docker 0 x 30%) / 190%
        self.assertEqual(r["summary"]["coverage"], round(100 * 1.6 / 1.9, 1))
        dbms = [s for s in r["subjects"] if s["name"] == "Database Management Systems"][0]
        self.assertEqual((dbms["jobs"], dbms["share"]), (100, 100.0))
        self.assertEqual([s["coverage_upto"] for s in r["semesters"]][0], 0.0)      # sem 1: physics only

    def test_chosen_elective_counts(self):
        r = cg.build_report(SUBJECTS, self.mapped, self.market, chosen=["cloud computing"])
        docker = self.skill(r, "docker")
        self.assertEqual((docker["status"], docker["coverage"]), ("partial", 0.4))  # 0.4 from the elective
        self.assertFalse(docker["taught_in"][0]["elective"])

    def test_current_semester(self):
        r = cg.build_report(SUBJECTS, self.mapped, self.market, current_semester=3)
        python = self.skill(r, "python")
        self.assertEqual(python["coverage_now"], 0.0)
        self.assertEqual(python["coming_in_semester"], 5)
        self.assertEqual(r["summary"]["coverage_now"], 0.0)
        self.assertIn("python", [x["skill"] for x in r["learn_now"]])

    def test_empty_market(self):
        r = cg.build_report(SUBJECTS, self.mapped, cg.build_market([], "computing", now=NOW))
        self.assertEqual((r["skills"], r["learn_now"], r["summary"]["coverage"]), ([], [], 0.0))


@unittest.skipUnless(TEST_DB, "set TEST_DATABASE_URL to run database tests")
class TestLoadMarket(unittest.TestCase):
    def test_load(self):
        import psycopg

        from app import config
        with mock.patch.object(config, "DATABASE_URL", TEST_DB):
            db = psycopg.connect(TEST_DB, autocommit=True)
            db.execute("truncate public.jobs cascade")
            jobs = [(f"j{i}", "jooble", ["python", "sql"], "open", 1) for i in range(6)]
            jobs += [(f"a{i}", "adzuna", ["java"], "open", 1) for i in range(6)]           # never counted
            jobs += [("old", "jooble", ["java"], "closed", 400)]                            # too old
            for key, source, skills, status, age in jobs:
                db.execute("""insert into public.jobs (job_key, source, company_name, title, apply_url, skills,
                                  status, posted_at, job_type)
                              values (%s, %s, 'Co', 'Developer', 'https://x.in', %s, %s,
                                      now() - make_interval(days => %s), 'full_time')""",
                           (key, source, skills, status, age))
            cg.clear_cache()
            m = cg.load_market(db, "computing")
            db.close()
        self.assertEqual(m.jobs, 6)
        self.assertEqual(sorted(m.skills), ["python", "sql"])
        self.assertNotIn("java", m.skills)


if __name__ == "__main__":
    unittest.main()
