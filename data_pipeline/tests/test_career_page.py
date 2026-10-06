"""Tests for the career-page reader (pages are faked, no internet needed)."""
import json
import unittest
from datetime import datetime, timezone
from unittest import mock

from pipeline.collectors import career_page
from pipeline.normalize import clean_job

NOW = datetime.now(timezone.utc).isoformat()


def ld(*objects) -> str:
    return "".join(f'<script type="application/ld+json">{json.dumps(o)}</script>' for o in objects)


POSTING = {"@context": "https://schema.org", "@type": "JobPosting", "title": "Python Developer",
           "datePosted": NOW, "description": "<p>Django and SQL</p>", "employmentType": ["FULL_TIME"],
           "hiringOrganization": {"@type": "Organization", "name": "ABC Tech"},
           "identifier": {"@type": "PropertyValue", "value": "JOB-7"},
           "jobLocation": {"@type": "Place", "address": {"@type": "PostalAddress", "addressLocality": "Salt Lake",
                                                         "addressRegion": "West Bengal", "addressCountry": "IN"}},
           "baseSalary": {"@type": "MonetaryAmount", "currency": "INR",
                          "value": {"@type": "QuantitativeValue", "minValue": 400000, "maxValue": 600000,
                                    "unitText": "YEAR"}},
           "url": "/jobs/7"}


def page(text, status=200):
    resp = mock.Mock(status_code=status, text=text)
    resp.raise_for_status.side_effect = None if status < 400 else career_page.requests.HTTPError(str(status))
    return resp


class FakeSession:
    def __init__(self, pages):
        self.pages, self.asked = pages, []

    def get(self, url, **kwargs):
        self.asked.append(url)
        return self.pages.get(url, page("", 404))


class TestReading(unittest.TestCase):
    def test_reads_posting(self):
        postings = career_page.postings_in(ld({"@graph": [{"@type": "Organization"}, POSTING]}))
        job = career_page.to_raw(postings[0], "https://abc.in/careers", "ABC", "cid")
        self.assertEqual((job.title, job.company_name, job.source_job_id, job.apply_url),
                         ("Python Developer", "ABC Tech", "JOB-7", "https://abc.in/jobs/7"))
        self.assertEqual((job.salary_min, job.salary_max, job.salary_period), (400000, 600000, "year"))
        clean = clean_job(job)
        self.assertEqual((clean.area, clean.job_type), ("Salt Lake", "full_time"))
        self.assertIn("django", clean.skills)

    def test_expired_and_broken(self):
        old = {**POSTING, "validThrough": "2020-01-01"}
        self.assertIsNone(career_page.to_raw(old, "https://abc.in", "ABC", None))       # expired
        self.assertEqual(career_page.postings_in('<script type="application/ld+json">{not json</script>'), [])
        remote = career_page.to_raw({**POSTING, "jobLocationType": "TELECOMMUTE"}, "https://abc.in", "ABC", None)
        self.assertEqual(remote.work_mode_hint, "remote")


class TestCollect(unittest.TestCase):
    def test_list_page_then_job_pages(self):
        session = FakeSession({
            "https://abc.in/robots.txt": page("User-agent: *\nDisallow: /private/"),
            "https://abc.in/careers": page('<a href="/jobs/7">Dev</a> <a href="/private/jobs/9">x</a> '
                                           '<a href="https://other.com/jobs/1">y</a> <a href="/about">z</a>'),
            "https://abc.in/jobs/7": page(ld(POSTING)),
        })
        r = career_page.collect(session, "https://abc.in/careers", "ABC", "cid", delay=0)
        self.assertTrue(r.complete)
        self.assertEqual([j.title for j in r.jobs], ["Python Developer"])
        self.assertNotIn("https://abc.in/private/jobs/9", session.asked)                 # robots.txt obeyed
        self.assertNotIn("https://other.com/jobs/1", session.asked)                      # other websites ignored

    def test_robots_block_whole_site(self):
        session = FakeSession({"https://abc.in/robots.txt": page("User-agent: *\nDisallow: /")})
        r = career_page.collect(session, "https://abc.in/careers", "ABC", "cid", delay=0)
        self.assertFalse(r.complete)
        self.assertIn("robots.txt", r.error)
        self.assertEqual(session.asked, ["https://abc.in/robots.txt"])

    def test_failed_page_is_not_complete(self):
        session = FakeSession({"https://abc.in/careers": page("", 500)})
        r = career_page.collect(session, "https://abc.in/careers", "ABC", "cid", delay=0)
        self.assertFalse(r.complete)                                                       # never close on errors


if __name__ == "__main__":
    unittest.main()
