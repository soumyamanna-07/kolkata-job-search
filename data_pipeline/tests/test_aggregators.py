"""Tests for the Jooble and Careerjet collectors and the salary-text reader (fake answers, no internet)."""
import unittest
from datetime import datetime, timezone
from unittest import mock

import requests

from pipeline.collectors import careerjet, jooble
from pipeline.collectors.salary_text import parse_salary

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)


def fake_response(payload, status=200):
    resp = mock.Mock()
    resp.status_code = status
    resp.json.return_value = payload
    if status >= 400:
        resp.raise_for_status.side_effect = requests.HTTPError(f"{status} Error")
    else:
        resp.raise_for_status.return_value = None
    return resp


class TestSalaryText(unittest.TestCase):
    def test_common_forms(self):
        self.assertEqual(parse_salary("Rs 3,00,000 - 5,00,000 a year"),
                         {"min": 300000, "max": 500000, "currency": "INR", "period": "year"})
        self.assertEqual(parse_salary("15k-20k per month"),
                         {"min": 15000, "max": 20000, "currency": "INR", "period": "month"})
        self.assertEqual(parse_salary("6-8 LPA"), {"min": 600000, "max": 800000, "currency": "INR", "period": "year"})
        self.assertEqual(parse_salary("\u20b925,000 monthly")["min"], 25000)
        self.assertEqual(parse_salary("$50,000 - $70,000 a year")["currency"], "USD")

    def test_no_salary(self):
        for text in (None, "", "Competitive", "2 years experience", "5 days a week"):
            self.assertEqual(parse_salary(text), {}, text)


class TestJooble(unittest.TestCase):
    ITEM = {"title": "Data Analyst", "location": "Kolkata, West Bengal", "snippet": "SQL and Excel",
            "salary": "Rs 25,000 - 35,000 per month", "type": "Full-time", "link": "https://jooble.org/desc/1",
            "company": "ABC Tech", "updated": "2026-10-01T09:30:00.0000000", "id": 111}

    def test_no_key_skips(self):
        session = mock.Mock()
        r = jooble.collect(session, "")
        self.assertFalse(r.complete)
        self.assertIn("not set", r.error)
        session.post.assert_not_called()

    @mock.patch.object(jooble.time, "sleep")
    def test_pages_until_total(self, _sleep):
        second = dict(self.ITEM, id=222, title="Sales Executive", salary="")
        session = mock.Mock()
        session.post.side_effect = [fake_response({"totalCount": 2, "jobs": [self.ITEM]}),
                                    fake_response({"totalCount": 2, "jobs": [second]})]
        r = jooble.collect(session, "SECRETKEY", now=NOW)
        self.assertTrue(r.complete)
        self.assertFalse(r.snapshot)                          # search results never close jobs
        self.assertEqual((len(r.jobs), r.requests_made), (2, 2))
        url, = session.post.call_args_list[0].args
        body = session.post.call_args_list[0].kwargs["json"]
        self.assertEqual(url, "https://jooble.org/api/SECRETKEY")
        self.assertEqual((body["location"], body["page"], body["datecreatedfrom"]), ("Kolkata", "1", "2026-09-06"))
        job = r.jobs[0]
        self.assertEqual((job.source, job.source_job_id, job.company_name), ("jooble", "111", "ABC Tech"))
        self.assertEqual((job.salary_min, job.salary_max, job.salary_period), (25000, 35000, "month"))
        self.assertEqual(job.posted_at, datetime(2026, 10, 1, 9, 30, tzinfo=timezone.utc))
        self.assertIsNone(r.jobs[1].salary_min)

    def test_error_hides_key(self):
        session = mock.Mock()
        session.post.side_effect = requests.ConnectionError("failed: https://jooble.org/api/SECRETKEY")
        r = jooble.collect(session, "SECRETKEY")
        self.assertFalse(r.complete)
        self.assertNotIn("SECRETKEY", r.error)
        self.assertIn("***", r.error)


class TestCareerjet(unittest.TestCase):
    def item(self, n, date):
        return {"title": f"Job {n}", "company": "XYZ Ltd", "url": f"https://www.careerjet.co.in/jobad/{n}",
                "locations": "Kolkata, West Bengal", "description": "Python", "date": date,
                "salary_min": 300000, "salary_max": 500000, "salary_type": "Y", "salary_currency_code": "INR"}

    def test_no_key_skips(self):
        session = mock.Mock()
        r = careerjet.collect(session, "")
        self.assertIn("not set", r.error)
        session.get.assert_not_called()

    def test_reads_and_stops_at_old_jobs(self):
        session = mock.Mock()
        session.get.return_value = fake_response({"type": "JOBS", "hits": 50, "jobs": [
            self.item(1, "Mon, 05 Oct 2026 08:30:00 GMT"),
            dict(self.item(2, "2026-10-04T10:00:00Z"), salary_type="W"),          # weekly pay: not kept
            self.item(3, "Tue, 01 Aug 2026 08:30:00 GMT")]})                         # older than 30 days
        r = careerjet.collect(session, "SECRETKEY", user_ip="203.0.113.5", now=NOW)
        self.assertTrue(r.complete)
        self.assertFalse(r.snapshot)
        self.assertEqual([j.title for j in r.jobs], ["Job 1", "Job 2"])
        self.assertEqual(session.get.call_count, 1)                                  # no second page needed
        kwargs = session.get.call_args.kwargs
        self.assertEqual(kwargs["auth"], ("SECRETKEY", ""))
        self.assertEqual((kwargs["params"]["locale_code"], kwargs["params"]["location"], kwargs["params"]["page"],
                          kwargs["params"]["user_ip"]), ("en_IN", "Kolkata", 1, "203.0.113.5"))
        self.assertEqual((r.jobs[0].salary_min, r.jobs[0].salary_period), (300000, "year"))
        self.assertEqual((r.jobs[1].salary_min, r.jobs[1].salary_period), (None, None))
        self.assertEqual(r.jobs[0].posted_at, datetime(2026, 10, 5, 8, 30, tzinfo=timezone.utc))

    @mock.patch.object(careerjet.time, "sleep")
    def test_next_page_and_limit(self, _sleep):
        full_page = {"type": "JOBS", "hits": 5000,
                     "jobs": [self.item(i, "Mon, 05 Oct 2026 08:30:00 GMT") for i in range(careerjet.PAGE_SIZE)]}
        session = mock.Mock()
        session.get.return_value = fake_response(full_page)
        r = careerjet.collect(session, "KEY", now=NOW)
        self.assertEqual(session.get.call_count, careerjet.MAX_PAGES)
        self.assertEqual(session.get.call_args.kwargs["params"]["user_ip"], "127.0.0.1")
        self.assertTrue(r.complete)

    def test_wrong_location_answer(self):
        session = mock.Mock()
        session.get.return_value = fake_response({"type": "LOCATIONS", "locations": ["Kolkata, WB"]})
        r = careerjet.collect(session, "SECRETKEY", now=NOW)
        self.assertFalse(r.complete)
        self.assertIn("LOCATIONS", r.error)

    def test_http_error(self):
        session = mock.Mock()
        session.get.return_value = fake_response({}, status=401)
        r = careerjet.collect(session, "SECRETKEY", now=NOW)
        self.assertFalse(r.complete)
        self.assertIn("401", r.error)


if __name__ == "__main__":
    unittest.main()
