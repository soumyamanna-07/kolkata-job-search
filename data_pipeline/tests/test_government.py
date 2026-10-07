"""Tests for the government recruitment-notice reader (sample pages, no internet)."""
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest import mock

import requests

from pipeline.collectors import government
from pipeline.normalize import clean_job

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
TODAY = date(2026, 10, 7)
PAGE_URL = "https://www.example.gov.in/recruitment/"

# a table like ISI Kolkata: title | issue date | last date | link
TABLE_PAGE = """
<table>
 <tr><th>Title</th><th>Issue date</th><th>Last date</th><th></th></tr>
 <tr><td>Recruitment of one (01) Project-Linked Research Associate-I</td><td>25 September 2026</td>
     <td>20 October 2026</td><td><a href="jobs_view.php?id=77">View</a></td></tr>
 <tr><td>Walk-in interview for the post of Data Entry Operator</td><td>30.09.2026</td><td>14.10.2026</td>
     <td><a href="/files/deo.pdf">Download</a></td></tr>
 <tr><td>Recruitment of Junior Assistant</td><td>01.06.2026</td><td>30.06.2026</td>
     <td><a href="/files/old.pdf">Download</a></td></tr>
 <tr><td>Result of the recruitment test for Junior Assistant</td><td>01.10.2026</td>
     <td><a href="/files/result.pdf">Download</a></td></tr>
 <tr><td>Recruitment of Assistant Professor - Bangalore Centre</td><td>15/09/2026</td><td>22/10/2026</td>
     <td><a href="/files/blr.pdf">Download</a></td></tr>
 <tr><td>Recruitment of Technical Assistant (date not given)</td><td><a href="/files/nodate.pdf">PDF</a></td></tr>
</table>"""

# a list like many state boards: "date - title (link)"
LIST_PAGE = """
<ul>
 <li>02.10.2026 <a href="https://hrb.example.in/notice_1.pdf">Advertisement for recruitment of Staff Nurse, WBHS</a> <img src="new.gif"></li>
 <li>10.02.2020 <a href="https://hrb.example.in/notice_old.pdf">Advertisement for the post of Driver</a></li>
 <li><a href="/about">About us</a></li>
</ul>"""


def response(text, status=200):
    resp = mock.Mock()
    resp.status_code, resp.text = status, text
    resp.raise_for_status.side_effect = requests.HTTPError(f"{status} Error") if status >= 400 else None
    return resp


def session_for(page, robots="", status=200):
    session = mock.Mock()
    session.get.side_effect = lambda url, **kw: response(robots) if url.endswith("/robots.txt") else response(page, status)
    return session


class TestDates(unittest.TestCase):
    def test_formats(self):
        self.assertEqual(government.dates_in("31.10.2026, 1/11/2026, 05-12-2026"),
                         [date(2026, 10, 31), date(2026, 11, 1), date(2026, 12, 5)])
        self.assertEqual(government.dates_in("from 3rd Oct 2026 to October 20, 2026"),
                         [date(2026, 10, 3), date(2026, 10, 20)])
        self.assertEqual(government.dates_in("31.02.2026 and 2026"), [])           # not a real date


class TestNotices(unittest.TestCase):
    def test_table_page(self):
        found = government.notices(TABLE_PAGE, PAGE_URL, TODAY)
        titles = [n["title"] for n in found]
        self.assertEqual(titles, ["Recruitment of one (01) Project-Linked Research Associate-I",
                                  "Walk-in interview for the post of Data Entry Operator",
                                  "Recruitment of Assistant Professor - Bangalore Centre"])
        self.assertEqual(found[0]["url"], "https://www.example.gov.in/recruitment/jobs_view.php?id=77")
        self.assertEqual(found[1]["url"], "https://www.example.gov.in/files/deo.pdf")
        self.assertEqual((found[0]["issued"], found[0]["last_date"]), (date(2026, 9, 25), date(2026, 10, 20)))

    def test_list_page(self):
        found = government.notices(LIST_PAGE, PAGE_URL, TODAY)
        self.assertEqual([(n["title"], n["issued"], n["last_date"]) for n in found],
                         [("Advertisement for recruitment of Staff Nurse, WBHS", date(2026, 10, 2), None)])

    def test_single_date_too_old(self):
        page = '<ul><li>01.08.2026 <a href="/a.pdf">Advertisement for the post of Clerk</a></li></ul>'
        self.assertEqual(government.notices(page, PAGE_URL, TODAY), [])


class TestSession(unittest.TestCase):
    def test_old_servers_allowed_but_certificates_checked(self):
        session = government.make_session()
        adapter = session.get_adapter("https://psc.wb.gov.in/")
        self.assertIsInstance(adapter, government.OldServerTLS)
        context = adapter._context()
        self.assertTrue(context.options & getattr(government.ssl, "OP_LEGACY_SERVER_CONNECT", 0x4))
        self.assertEqual(context.verify_mode, government.ssl.CERT_REQUIRED)   # still checks the certificate
        self.assertTrue(context.check_hostname)                               # ... and the website name
        self.assertIn("KolkataLiveJobSearch", session.headers["User-Agent"])

    def test_not_jobs(self):
        page = ('<ul><li>02.10.2026 <a href="/a.pdf">Advertisement for admission to M.Sc. 2026</a></li>'
                '<li>03.10.2026 <a href="/b.pdf">Result of recruitment for the posts of Clerk</a></li></ul>')
        self.assertEqual(government.notices(page, PAGE_URL, TODAY), [])


class TestCollect(unittest.TestCase):
    def test_collect_and_clean(self):
        r = government.collect(session_for(TABLE_PAGE), PAGE_URL, "Example Institute", "co-1", "Kolkata", now=NOW)
        self.assertTrue(r.complete)
        self.assertTrue(r.snapshot)                       # a notice that disappears is closed next run
        self.assertEqual((r.source, r.company_id, len(r.jobs)), ("government", "co-1", 3))
        jobs = [clean_job(j, now=NOW) for j in r.jobs]
        kept = [j for j in jobs if j]
        self.assertEqual(len(kept), 2)                    # "Bangalore Centre" is not a Kolkata job
        job = kept[0]
        self.assertEqual((job.source, job.area, job.company_name, job.job_type),
                         ("government", "Kolkata", "Example Institute", "contract"))
        self.assertIn("Last date / walk-in date: 20 Oct 2026", job.description)
        self.assertEqual(job.posted_at.date(), date(2026, 9, 25))

    def test_robots_says_no(self):
        robots = "User-agent: *\nDisallow: /recruitment/"
        r = government.collect(session_for(TABLE_PAGE, robots), PAGE_URL, "X", None, now=NOW)
        self.assertFalse(r.complete)
        self.assertIn("robots.txt", r.error)
        self.assertEqual(r.jobs, [])

    def test_page_down(self):
        r = government.collect(session_for("", status=503), PAGE_URL, "X", None, now=NOW)
        self.assertFalse(r.complete)
        self.assertIn("503", r.error)

    def test_old_issue_date_with_future_deadline_has_no_posted_date(self):
        page = ('<table><tr><td>Recruitment of Scientist B</td><td>01.07.2026</td><td>31.10.2026</td>'
                '<td><a href="/sci.pdf">Download</a></td></tr></table>')
        r = government.collect(session_for(page), PAGE_URL, "X", None, now=NOW)
        self.assertIsNone(r.jobs[0].posted_at)            # else the 60-day rule would hide a still-open notice
        self.assertIsNotNone(clean_job(r.jobs[0], now=NOW))


if __name__ == "__main__":
    unittest.main()
