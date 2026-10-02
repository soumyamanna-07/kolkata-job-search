"""Tests for pipeline.normalize. Run from data_pipeline/:  python -m unittest -v"""
import unittest
from datetime import datetime, timezone

from pipeline.models import RawJob
from pipeline.normalize import (
    clean_job, clean_text, deduplicate, detect_job_type, detect_work_mode,
    extract_experience, extract_skills, find_area, make_job_key, normalize_company,
)


def raw(**kw) -> RawJob:
    base = dict(source="lever", source_job_id="1", company_name="ABC Tech Pvt Ltd",
                title="Data Analyst", apply_url="https://jobs.example.com/1",
                locations=["Kolkata, West Bengal"])
    base.update(kw)
    return RawJob(**base)


class TestArea(unittest.TestCase):
    def test_kolkata_areas(self):
        self.assertEqual(find_area(["Kolkata, India"]), "Kolkata")
        self.assertEqual(find_area(["Salt Lake Sector V, Kolkata"]), "Salt Lake")
        self.assertEqual(find_area(["Bidhannagar"]), "Salt Lake")
        self.assertEqual(find_area(["Newtown, Rajarhat"]), "New Town")
        self.assertEqual(find_area(["Howrah, WB"]), "Howrah")
        self.assertEqual(find_area(["Calcutta"]), "Kolkata")

    def test_not_kolkata(self):
        self.assertIsNone(find_area(["Bengaluru, Karnataka"]))
        self.assertIsNone(find_area(["West Bengal"]))
        self.assertIsNone(find_area(["Remote, India"]))
        self.assertIsNone(find_area([]))

    def test_any_of_many_locations(self):
        self.assertEqual(find_area(["Pune", "Kolkata"]), "Kolkata")


class TestText(unittest.TestCase):
    def test_html_cleaned(self):
        text = clean_text("&lt;p&gt;Know &lt;b&gt;SQL&lt;/b&gt;&amp;nbsp;well&lt;/p&gt;&lt;ul&gt;&lt;li&gt;Python&lt;/li&gt;&lt;/ul&gt;")
        self.assertIn("Know SQL well", text)
        self.assertIn("- Python", text)
        self.assertNotIn("<", text)

    def test_company_normalized(self):
        self.assertEqual(normalize_company("ABC Tech Pvt. Ltd."), "abc tech")
        self.assertEqual(normalize_company("ABC Tech Private Limited"), "abc tech")
        self.assertEqual(normalize_company("Tata Consultancy Services"), "tata consultancy services")


class TestJobKey(unittest.TestCase):
    def test_same_job_different_spelling(self):
        a = make_job_key("ABC Tech Pvt Ltd", "Data Analyst (Kolkata)")
        b = make_job_key("ABC Tech Private Limited", "data analyst")
        self.assertEqual(a, b)

    def test_different_title_different_job(self):
        self.assertNotEqual(make_job_key("ABC", "Data Analyst"), make_job_key("ABC", "Data Engineer"))


class TestExperience(unittest.TestCase):
    def test_range(self):
        self.assertEqual(extract_experience("", "We need 2-4 years of experience in SQL"), (2.0, 4.0))
        self.assertEqual(extract_experience("", "Experience: 3 to 5 yrs"), (3.0, 5.0))

    def test_single(self):
        self.assertEqual(extract_experience("", "Minimum 3+ years experience required"), (3.0, None))

    def test_fresher(self):
        self.assertEqual(extract_experience("Fresher - Data Entry", ""), (0.0, 1.0))

    def test_ignores_company_age(self):
        self.assertEqual(extract_experience("", "We have served clients for 25 years."), (None, None))


class TestTypeAndMode(unittest.TestCase):
    def test_job_type(self):
        self.assertEqual(detect_job_type("Python Intern", ""), "internship")
        self.assertEqual(detect_job_type("Analyst", "Full-time"), "full_time")
        self.assertEqual(detect_job_type("Analyst", "part_time"), "part_time")
        self.assertEqual(detect_job_type("Analyst", "Contract"), "contract")
        self.assertIsNone(detect_job_type("Analyst", ""))

    def test_work_mode(self):
        self.assertEqual(detect_work_mode("Analyst", [], "remote"), "remote")
        self.assertEqual(detect_work_mode("Analyst (Hybrid)", ["Kolkata"], ""), "hybrid")
        self.assertEqual(detect_work_mode("Analyst", ["Kolkata / Remote"], ""), "remote")
        self.assertIsNone(detect_work_mode("Analyst", ["Kolkata"], "unspecified"))


class TestSkills(unittest.TestCase):
    def test_basic(self):
        skills = extract_skills("Python Developer", "Build REST APIs with FastAPI, PostgreSQL and Docker on AWS.")
        for s in ["python", "fastapi", "postgresql", "docker", "aws", "rest api"]:
            self.assertIn(s, skills)

    def test_no_false_matches(self):
        skills = extract_skills("JavaScript Developer", "Use HTML, CSS and React. Drag and drop UI.")
        self.assertIn("javascript", skills)
        self.assertNotIn("java", skills)       # java must not match javascript
        self.assertNotIn("machine learning", skills)  # 'ml' inside 'html' must not match
        self.assertNotIn("rag", skills)        # 'rag' inside 'drag'

    def test_symbols(self):
        skills = extract_skills("", "C++, C# and .NET developer; Node.js experience")
        for s in ["c++", "c#", ".net", "node.js"]:
            self.assertIn(s, skills)


class TestCleanJob(unittest.TestCase):
    def test_full_job(self):
        job = clean_job(raw(
            description="<p>2-3 years experience with Python and SQL.</p>",
            salary_min=400000, salary_max=600000, salary_currency="INR", salary_period="year",
            job_type_hint="Full-time", work_mode_hint="hybrid",
            posted_at=datetime(2026, 10, 1, tzinfo=timezone.utc)))
        self.assertIsNotNone(job)
        self.assertEqual(job.area, "Kolkata")
        self.assertEqual((job.salary_min, job.salary_max), (400000, 600000))
        self.assertEqual((job.experience_min, job.experience_max), (2.0, 3.0))
        self.assertEqual(job.job_type, "full_time")
        self.assertEqual(job.work_mode, "hybrid")
        self.assertIn("python", job.skills)

    def test_rejects(self):
        self.assertIsNone(clean_job(raw(locations=["Mumbai"])))
        self.assertIsNone(clean_job(raw(apply_url="not-a-link")))
        self.assertIsNone(clean_job(raw(title="  ")))

    def test_monthly_salary_to_yearly(self):
        job = clean_job(raw(salary_min=30000, salary_max=40000, salary_period="month"))
        self.assertEqual((job.salary_min, job.salary_max), (360000, 480000))

    def test_foreign_currency_dropped(self):
        job = clean_job(raw(salary_min=50000, salary_max=70000, salary_currency="USD"))
        self.assertEqual((job.salary_min, job.salary_max), (None, None))


class TestDeduplicate(unittest.TestCase):
    def test_prefers_direct_source(self):
        a = clean_job(raw(source="adzuna", apply_url="https://adzuna/1", salary_min=400000))
        b = clean_job(raw(source="lever", apply_url="https://lever/1",
                          company_name="ABC Tech Private Limited", locations=["Kolkata, India"]))
        result = deduplicate([a, b])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].source, "lever")


if __name__ == "__main__":
    unittest.main()
