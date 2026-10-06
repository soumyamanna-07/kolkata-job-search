"""Unit tests for the search query builder (no database needed)."""
import unittest

from app.job_search import JobFiltersIn, build_search_query


class TestBuildSearchQuery(unittest.TestCase):
    def test_default_only_open_jobs_newest_first(self):
        sql, count_sql, params = build_search_query(JobFiltersIn())
        self.assertIn("status = 'open'", sql)
        self.assertIn("coalesce(posted_at, first_seen_at) desc", sql)
        self.assertEqual(params["limit"], 20)
        self.assertEqual(params["offset"], 0)
        self.assertIn("status = 'open'", count_sql)

    def test_user_text_is_a_parameter_not_sql(self):
        evil = "x'; drop table jobs; --"
        sql, _, params = build_search_query(JobFiltersIn(q=evil))
        self.assertNotIn("drop table", sql)
        self.assertEqual(params["q"], evil)

    def test_like_wildcards_escaped(self):
        _, _, params = build_search_query(JobFiltersIn(q="100%_sure"))
        self.assertEqual(params["q_like"], r"%100\%\_sure%")

    def test_filters_and_paging(self):
        f = JobFiltersIn(areas=["Salt Lake"], skills=["Python"], salary_expected=500000,
                         include_undisclosed_salary=False, experience_years=1,
                         job_types=["full_time"], work_modes=["hybrid"], posted_within_days=7,
                         page=3, page_size=10)
        sql, _, params = build_search_query(f)
        for part in ["area = any", "skills && ", "coalesce(salary_max, salary_min) >= ",
                     "experience_min <= ", "job_type = any", "work_mode = any", "make_interval"]:
            self.assertIn(part, sql)
        self.assertNotIn("salary_min is null and salary_max is null", sql)
        self.assertEqual(params["skills"], ["python"])
        self.assertEqual(params["offset"], 20)

    def test_undisclosed_salary_included_by_default(self):
        sql, _, _ = build_search_query(JobFiltersIn(salary_expected=500000))
        self.assertIn("salary_min is null and salary_max is null", sql)

    def test_sorts(self):
        self.assertIn("coalesce(salary_max, salary_min) desc nulls last",
                      build_search_query(JobFiltersIn(sort="salary"))[0])
        self.assertIn("ts_rank", build_search_query(JobFiltersIn(q="python", sort="relevance"))[0])
        self.assertNotIn("ts_rank", build_search_query(JobFiltersIn(q="python", sort="newest"))[0])

    def test_direct_apply_first_and_filter(self):
        sql, _, params = build_search_query(JobFiltersIn())            # default sort = relevance
        self.assertIn("(source = any(%(aggregators)s)), coalesce(posted_at", sql)
        self.assertEqual(params["aggregators"], ["adzuna", "jooble", "careerjet"])
        sql, _, _ = build_search_query(JobFiltersIn(q="python"))
        self.assertIn("(source = any(%(aggregators)s)), (ts_rank", sql)
        self.assertNotIn("source = any", build_search_query(JobFiltersIn(sort="newest"))[0])
        sql, count_sql, _ = build_search_query(JobFiltersIn(direct_only=True, sort="newest"))
        self.assertIn("source <> all(%(aggregators)s)", sql)
        self.assertIn("source <> all(%(aggregators)s)", count_sql)


if __name__ == "__main__":
    unittest.main()
