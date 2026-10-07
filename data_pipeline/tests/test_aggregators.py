"""Tests for the Jooble and Careerjet collectors and the salary-text reader (fake answers, no internet)."""
import unittest
from datetime import datetime, timezone
from unittest import mock

import requests

from pipeline.collectors import careerjet, jobicy, jooble
from pipeline.collectors.salary_text import parse_salary
from pipeline.normalize import clean_job

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
    @mock.patch.object(jooble, "RESULTS_PER_PAGE", 2)
    @mock.patch.object(jooble, "REMOTE_KEYWORDS", [])
    @mock.patch.object(jooble, "KEYWORDS", ["data", "sales"])
    def test_keywords_pages_and_duplicates(self, _sleep):
        second = dict(self.ITEM, id=222, title="Sales Executive", salary="")
        third = dict(self.ITEM, id=333, title="Sales Manager")
        old = dict(self.ITEM, id=444, title="Old Job", updated="2026-08-01T09:30:00.0000000")
        session = mock.Mock()
        session.post.side_effect = [
            fake_response({"totalCount": 3, "jobs": [self.ITEM, second]}),   # "data", page 1 (full page)
            fake_response({"totalCount": 3, "jobs": [old]}),                 # "data", page 2 (last page)
            fake_response({"totalCount": 2, "jobs": [second, third]}),       # "sales": 222 seen already
        ]
        r = jooble.collect(session, "SECRETKEY", now=NOW)
        self.assertTrue(r.complete)
        self.assertFalse(r.snapshot)                          # search results never close jobs
        self.assertEqual([j.source_job_id for j in r.jobs], ["111", "222", "333"])   # no duplicate, no old job
        self.assertEqual(r.requests_made, 3)
        url, = session.post.call_args_list[0].args
        bodies = [c.kwargs["json"] for c in session.post.call_args_list]
        self.assertEqual(url, "https://in.jooble.org/api/SECRETKEY")
        self.assertEqual([(b["keywords"], b["page"]) for b in bodies], [("data", "1"), ("data", "2"), ("sales", "1")])
        self.assertEqual(bodies[0]["location"], "Kolkata")
        job = r.jobs[0]
        self.assertEqual((job.source, job.source_job_id, job.company_name), ("jooble", "111", "ABC Tech"))
        self.assertEqual((job.salary_min, job.salary_max, job.salary_period), (25000, 35000, "month"))
        self.assertEqual(job.posted_at, datetime(2026, 10, 1, 9, 30, tzinfo=timezone.utc))
        self.assertIsNone(r.jobs[1].salary_min)

    @mock.patch.object(jooble.time, "sleep")
    @mock.patch.object(jooble, "MAX_REQUESTS", 2)
    def test_request_limit(self, _sleep):
        session = mock.Mock()
        session.post.return_value = fake_response({"totalCount": 0, "jobs": []})
        r = jooble.collect(session, "KEY", now=NOW)
        self.assertEqual(session.post.call_count, 2)
        self.assertTrue(r.complete)

    def test_jooble_spellings_pass_kolkata_filter(self):
        # Jooble India writes "Kolkatta" and "Saltlake"; both must count as Kolkata
        for place, area in (("Kolkatta", "Kolkata"), ("Saltlake", "Salt Lake")):
            job = clean_job(jooble._to_job(dict(self.ITEM, location=place)), now=NOW)
            self.assertIsNotNone(job, place)
            self.assertEqual(job.area, area)

    @mock.patch.object(jooble.time, "sleep")
    @mock.patch.object(jooble, "REMOTE_KEYWORDS", [])
    @mock.patch.object(jooble, "KEYWORDS", ["data", "sales"])
    def test_server_error_is_tried_again(self, sleep):
        session = mock.Mock()
        session.post.side_effect = [fake_response({}, 500),                                  # "data" fails once
                                    fake_response({"totalCount": 1, "jobs": [self.ITEM]}),   # ... then works
                                    fake_response({"totalCount": 0, "jobs": []})]            # "sales"
        r = jooble.collect(session, "KEY", now=NOW)
        self.assertTrue(r.complete)
        self.assertIsNone(r.error)
        self.assertEqual([j.source_job_id for j in r.jobs], ["111"])
        self.assertEqual(r.requests_made, 3)
        sleep.assert_any_call(jooble.RETRY_WAITS[0])

    @mock.patch.object(jooble.time, "sleep")
    @mock.patch.object(jooble, "REMOTE_KEYWORDS", [])
    @mock.patch.object(jooble, "KEYWORDS", ["data", "sales"])
    def test_keyword_that_keeps_failing_is_skipped(self, _sleep):
        session = mock.Mock()
        session.post.side_effect = [fake_response({}, 500)] * 3 + [   # "data": first try + 2 retries
            fake_response({"totalCount": 1, "jobs": [self.ITEM]})]    # "sales" still collected
        r = jooble.collect(session, "SECRETKEY", now=NOW)
        self.assertFalse(r.complete)                                  # partial: one search was skipped
        self.assertEqual(len(r.jobs), 1)
        self.assertIn("1 of 2 searches skipped: data", r.error)
        self.assertNotIn("SECRETKEY", r.error)

    @mock.patch.object(jooble.time, "sleep")
    @mock.patch.object(jooble, "KEYWORDS", ["data"])
    @mock.patch.object(jooble, "REMOTE_KEYWORDS", ["work from home"])
    def test_work_from_home_search(self, _sleep):
        wfh = dict(self.ITEM, id=555, title="Customer Support (Work From Home)", location="Bengaluru")
        office = dict(self.ITEM, id=666, title="Office Assistant", location="Pune")
        hybrid = dict(self.ITEM, id=777, title="Remote / Hybrid Analyst", location="Mumbai")
        session = mock.Mock()
        session.post.side_effect = [fake_response({"totalCount": 1, "jobs": [self.ITEM]}),          # Kolkata
                                    fake_response({"totalCount": 3, "jobs": [wfh, office, hybrid]})]  # India WFH
        r = jooble.collect(session, "KEY", now=NOW)
        bodies = [c.kwargs["json"] for c in session.post.call_args_list]
        self.assertEqual([(b["keywords"], b["location"]) for b in bodies],
                         [("data", "Kolkata"), ("work from home", "India")])
        self.assertEqual([(j.source_job_id, j.remote_from_india) for j in r.jobs], [("111", False), ("555", True)])
        job = clean_job(r.jobs[1], now=NOW)
        self.assertEqual((job.area, job.work_mode), ("Work from home", "remote"))

    @mock.patch.object(jooble.time, "sleep")
    def test_wrong_key_stops_without_retry(self, _sleep):
        session = mock.Mock()
        session.post.return_value = fake_response({}, 403)
        r = jooble.collect(session, "KEY", now=NOW)
        self.assertEqual(session.post.call_count, 1)
        self.assertFalse(r.complete)
        self.assertIn("403", r.error)

    @mock.patch.object(jooble.time, "sleep")
    def test_error_hides_key(self, _sleep):
        session = mock.Mock()
        session.post.side_effect = requests.ConnectionError("failed: https://in.jooble.org/api/SECRETKEY")
        r = jooble.collect(session, "SECRETKEY")
        self.assertFalse(r.complete)
        self.assertNotIn("SECRETKEY", r.error)
        self.assertIn("***", r.error)


class TestJobicy(unittest.TestCase):
    def item(self, n, geo, date="2026-10-03T10:00:00+00:00"):
        return {"id": n, "url": f"https://jobicy.com/jobs/{n}-job", "jobTitle": f"Job {n}", "companyName": "Remote Co",
                "jobGeo": geo, "jobType": ["Full-Time"], "jobDescription": "<p>Python and SQL</p>", "pubDate": date}

    def test_keeps_jobs_open_to_india(self):
        session = mock.Mock()
        session.get.side_effect = [
            fake_response({"jobs": [self.item(1, "Anywhere"), self.item(2, "USA"),
                                    self.item(3, "Anywhere", date="2026-07-01T10:00:00+00:00")]}),   # too old
            fake_response({"jobs": [self.item(4, "APAC"), self.item(5, "Hong Kong,  Singapore"),
                                    self.item(1, "Anywhere")]}),                                       # 1 again
        ]
        r = jobicy.collect(session, now=NOW)
        self.assertTrue(r.complete)
        self.assertFalse(r.snapshot)
        self.assertEqual([j.source_job_id for j in r.jobs], ["1", "4"])
        self.assertEqual([c.kwargs["params"]["geo"] for c in session.get.call_args_list], ["anywhere", "apac"])
        job = clean_job(r.jobs[0], now=NOW)
        self.assertEqual((job.area, job.work_mode, job.job_type, job.source), ("Work from home", "remote",
                                                                               "full_time", "jobicy"))
        self.assertEqual(job.apply_url, "https://jobicy.com/jobs/1-job")      # Jobicy's own page (their rule)

    def test_error(self):
        session = mock.Mock()
        session.get.return_value = fake_response({}, status=503)
        r = jobicy.collect(session, now=NOW)
        self.assertFalse(r.complete)
        self.assertIn("503", r.error)


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
        self.assertEqual(kwargs["headers"]["Referer"], "https://kolkata-live-jobs.vercel.app/")   # else 403
        self.assertEqual((kwargs["params"]["locale_code"], kwargs["params"]["location"], kwargs["params"]["offset"],
                          kwargs["params"]["user_ip"]), ("en_IN", "Kolkata", 0, "203.0.113.5"))
        self.assertEqual((r.jobs[0].salary_min, r.jobs[0].salary_period), (300000, "year"))
        self.assertEqual((r.jobs[1].salary_min, r.jobs[1].salary_period), (None, None))
        self.assertEqual(r.jobs[0].posted_at, datetime(2026, 10, 5, 8, 30, tzinfo=timezone.utc))

    @mock.patch.object(careerjet.time, "sleep")
    def test_moves_on_with_offset_up_to_the_limit(self, _sleep):
        # Careerjet sends 20 jobs per answer; we walk offset 0, 20, 40 ... up to its limit of 999
        def answer(url, params=None, **kw):
            start = params["offset"]
            return fake_response({"type": "JOBS", "hits": 5000, "jobs": [
                self.item(start + i, "Mon, 05 Oct 2026 08:30:00 GMT") for i in range(20)]})
        session = mock.Mock()
        session.get.side_effect = answer
        r = careerjet.collect(session, "KEY", now=NOW)
        offsets = [c.kwargs["params"]["offset"] for c in session.get.call_args_list]
        self.assertEqual(offsets[:3], [0, 20, 40])
        self.assertEqual(offsets[-1], 980)                        # next would be 1000: past the API's limit
        self.assertEqual(len(r.jobs), 1000)
        self.assertEqual(session.get.call_args.kwargs["params"]["user_ip"], "127.0.0.1")
        self.assertTrue(r.complete)

    def test_stops_at_the_end_of_the_list(self):
        session = mock.Mock()
        session.get.return_value = fake_response({"type": "JOBS", "hits": 2, "jobs": [
            self.item(1, "Mon, 05 Oct 2026 08:30:00 GMT"), self.item(2, "Mon, 05 Oct 2026 08:30:00 GMT")]})
        r = careerjet.collect(session, "KEY", now=NOW)
        self.assertEqual((session.get.call_count, len(r.jobs), r.complete), (1, 2, True))

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
