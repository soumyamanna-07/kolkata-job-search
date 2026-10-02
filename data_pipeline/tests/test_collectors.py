"""Tests for the collectors, using fake API responses (no internet needed)."""
import unittest
from unittest import mock

import requests

from pipeline.collectors import adzuna, greenhouse, lever


def fake_response(payload, status=200):
    resp = mock.Mock()
    resp.status_code = status
    resp.json.return_value = payload
    if status >= 400:
        resp.raise_for_status.side_effect = requests.HTTPError(f"{status} Error")
    else:
        resp.raise_for_status.return_value = None
    return resp


class TestGreenhouse(unittest.TestCase):
    def test_parses_jobs(self):
        session = mock.Mock()
        session.get.return_value = fake_response({"jobs": [{
            "id": 123, "title": "Data Analyst", "absolute_url": "https://boards.greenhouse.io/abc/jobs/123",
            "location": {"name": "Kolkata, India"}, "content": "&lt;p&gt;SQL&lt;/p&gt;",
            "updated_at": "2026-09-30T10:00:00-04:00", "offices": [{"name": "Salt Lake Office"}]}]})
        r = greenhouse.collect(session, "abc", "ABC", "company-uuid")
        self.assertTrue(r.complete)
        self.assertEqual(len(r.jobs), 1)
        job = r.jobs[0]
        self.assertEqual(job.source_job_id, "123")
        self.assertEqual(job.company_id, "company-uuid")
        self.assertIn("Kolkata, India", job.locations)
        self.assertEqual(job.posted_at.year, 2026)

    def test_error_is_not_complete(self):
        session = mock.Mock()
        session.get.return_value = fake_response({}, status=404)
        r = greenhouse.collect(session, "wrong", "ABC", "id")
        self.assertFalse(r.complete)
        self.assertIn("404", r.error)


class TestLever(unittest.TestCase):
    def test_parses_jobs(self):
        session = mock.Mock()
        session.get.return_value = fake_response([{
            "id": "abc-1", "text": "ML Engineer", "hostedUrl": "https://jobs.lever.co/x/abc-1",
            "categories": {"location": "Kolkata", "commitment": "Full-time", "allLocations": ["Kolkata", "Pune"]},
            "descriptionPlain": "PyTorch", "lists": [{"text": "Requirements", "content": "<li>Python</li>"}],
            "createdAt": 1727000000000, "workplaceType": "hybrid",
            "salaryRange": {"min": 50000, "max": 70000, "currency": "INR", "interval": "per-month-salary"}}])
        r = lever.collect(session, "x", "X Corp", "cid")
        self.assertTrue(r.complete)
        job = r.jobs[0]
        self.assertEqual(job.title, "ML Engineer")
        self.assertEqual(job.salary_period, "month")
        self.assertEqual(job.work_mode_hint, "hybrid")
        self.assertIn("Python", job.description)

    def test_bad_format(self):
        session = mock.Mock()
        session.get.return_value = fake_response({"ok": False})
        r = lever.collect(session, "x", "X", "cid")
        self.assertFalse(r.complete)


class TestAdzuna(unittest.TestCase):
    def item(self, i, predicted="0"):
        return {"id": str(i), "title": f"Job {i}", "company": {"display_name": "Co"},
                "location": {"display_name": "Kolkata, West Bengal", "area": ["India", "West Bengal", "Kolkata"]},
                "redirect_url": f"https://adzuna/{i}", "description": "desc", "created": "2026-10-01T05:00:00Z",
                "salary_min": 300000, "salary_max": 400000, "salary_is_predicted": predicted,
                "contract_time": "full_time"}

    def test_paginates_until_all_fetched(self):
        session = mock.Mock()
        session.get.side_effect = [
            fake_response({"count": 3, "results": [self.item(1), self.item(2)]}),
            fake_response({"count": 3, "results": [self.item(3, predicted="1")]}),
        ]
        r = adzuna.collect(session, "id", "key")
        self.assertTrue(r.complete)
        self.assertEqual(len(r.jobs), 3)
        self.assertEqual(r.jobs[0].salary_min, 300000)
        self.assertIsNone(r.jobs[2].salary_min)   # predicted salary dropped

    def test_missing_keys_skips(self):
        r = adzuna.collect(mock.Mock(), "", "")
        self.assertFalse(r.complete)
        self.assertIn("not set", r.error)

    def test_error_hides_api_key(self):
        session = mock.Mock()
        session.get.side_effect = requests.ConnectionError(
            "HTTPSConnectionPool: Max retries exceeded with url: /search/1?app_id=MYID&app_key=SECRETKEY")
        r = adzuna.collect(session, "MYID", "SECRETKEY")
        self.assertFalse(r.complete)
        self.assertNotIn("SECRETKEY", r.error)
        self.assertNotIn("MYID", r.error)

    def test_partial_when_page_limit_hit(self):
        session = mock.Mock()
        session.get.return_value = fake_response({"count": 999999, "results": [self.item(1)]})
        with mock.patch.object(adzuna, "MAX_PAGES", 2):
            r = adzuna.collect(session, "id", "key")
        self.assertFalse(r.complete)
        self.assertIn("stopped", r.error)


if __name__ == "__main__":
    unittest.main()
