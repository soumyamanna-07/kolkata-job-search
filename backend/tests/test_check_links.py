"""Tests for the dead-link checker (websites are faked, no real internet needed)."""
import os
import unittest
import uuid
from datetime import datetime, timedelta, timezone

import httpx

from scripts import check_links
from scripts.check_links import DEAD, OK, UNSURE, check_url, classify

TEST_DB = os.getenv("TEST_DATABASE_URL")


def fake_client(routes: dict) -> httpx.Client:
    """routes: url -> status code, or an exception class to raise. HEAD to /no-head gets 405."""
    def handler(request: httpx.Request) -> httpx.Response:
        target = routes[str(request.url)]
        if isinstance(target, type) and issubclass(target, Exception):
            raise target("fake failure", request=request)
        if request.method == "HEAD" and str(request.url).endswith("/no-head"):
            return httpx.Response(405)
        return httpx.Response(target)
    return httpx.Client(transport=httpx.MockTransport(handler))


class TestCheckUrl(unittest.TestCase):
    def test_classify(self):
        self.assertEqual([classify(s) for s in (200, 301, 404, 410, 403, 429, 503)],
                         [OK, OK, DEAD, DEAD, UNSURE, UNSURE, UNSURE])

    def test_check_url(self):
        client = fake_client({"https://a.in/ok": 200, "https://a.in/gone": 404, "https://a.in/no-head": 200,
                              "https://dead-domain.in/x": httpx.ConnectError,
                              "https://slow.in/x": httpx.ReadTimeout, "https://busy.in/x": 503})
        self.assertEqual(check_url(client, "https://a.in/ok"), OK)
        self.assertEqual(check_url(client, "https://a.in/gone"), DEAD)
        self.assertEqual(check_url(client, "https://a.in/no-head"), OK)        # HEAD refused, GET works
        self.assertEqual(check_url(client, "https://dead-domain.in/x"), DEAD)
        self.assertEqual(check_url(client, "https://slow.in/x"), UNSURE)       # never close on a timeout
        self.assertEqual(check_url(client, "https://busy.in/x"), UNSURE)


@unittest.skipUnless(TEST_DB, "set TEST_DATABASE_URL to run database tests")
class TestCheckLinksRun(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        cls.db = psycopg.connect(TEST_DB, autocommit=True)
        cls.tag = uuid.uuid4().hex[:8]
        cls.emp = str(uuid.uuid4())
        cls.db.execute("insert into auth.users (id, email, raw_user_meta_data) values (%s, %s, %s)",
                       (cls.emp, f"links-{cls.tag}@test.in", '{"account_type": "employer"}'))

    @classmethod
    def tearDownClass(cls):
        cls.db.execute("delete from public.jobs where job_key like %s", (f"links-{cls.tag}%",))
        cls.db.execute("delete from auth.users where id = %s", (cls.emp,))
        cls.db.close()

    def setUp(self):
        self.db.execute("delete from public.jobs where job_key like %s", (f"links-{self.tag}%",))

    def add_job(self, key, url, source="employer", fails=0):
        job_id = self.db.execute(
            """insert into public.jobs (job_key, source, company_name, title, apply_url, employer_id, link_fail_count)
               values (%s, %s, 'ABC', 'Analyst', %s, %s, %s) returning id""",
            (f"links-{self.tag}-{key}", source, url, self.emp if source == "employer" else None, fails)).fetchone()[0]
        if source == "employer":
            self.db.execute("""insert into public.job_submissions (employer_id, title, description, apply_url,
                                                                   status, published_job_id)
                               values (%s, 'Analyst', 'd', %s, 'approved', %s)""", (self.emp, url, job_id))
        return job_id

    def job(self, job_id):
        return self.db.execute("select status, link_fail_count, close_reason, link_checked_at is not null "
                               "from public.jobs where id = %s", (job_id,)).fetchone()

    def run_checker(self, routes, now=None, **kw):
        return check_links.run(self.db, fake_client(routes), now or datetime.now(timezone.utc),
                               log=lambda _: None, **kw)

    def test_third_failure_closes_job(self):
        dying = self.add_job("dying", "https://a.in/gone", fails=2)
        fine = self.add_job("fine", "https://a.in/ok", fails=2)
        flaky = self.add_job("flaky", "https://busy.in/x", fails=1)
        adzuna = self.add_job("adz", "https://a.in/gone", source="adzuna")
        stats = self.run_checker({"https://a.in/gone": 404, "https://a.in/ok": 200, "https://busy.in/x": 503})
        self.assertEqual((stats.checked, stats.ok, stats.dead, stats.unsure, stats.closed), (3, 1, 1, 1, 1))
        self.assertEqual(self.job(dying), ("closed", 3, "dead_link", True))
        sub = self.db.execute("select status from public.job_submissions where published_job_id = %s",
                              (dying,)).fetchone()[0]
        self.assertEqual(sub, "closed")                                   # employer sees it closed too
        self.assertEqual(self.job(fine), ("open", 0, None, True))         # a working link resets the count
        self.assertEqual(self.job(flaky), ("open", 1, None, True))        # 503 neither adds nor resets
        self.assertEqual(self.job(adzuna)[3], False)                      # aggregator jobs are not crawled

    def test_first_failure_does_not_close(self):
        job = self.add_job("new", "https://a.in/gone")
        self.run_checker({"https://a.in/gone": 404})
        self.assertEqual(self.job(job)[:2], ("open", 1))

    def test_checked_once_a_day(self):
        job = self.add_job("daily", "https://a.in/gone")
        now = datetime.now(timezone.utc)
        self.run_checker({"https://a.in/gone": 404}, now=now)
        self.assertEqual(self.run_checker({"https://a.in/gone": 404}, now=now + timedelta(hours=2)).checked, 0)
        self.run_checker({"https://a.in/gone": 404}, now=now + timedelta(days=1))
        self.assertEqual(self.job(job)[1], 2)

    def test_dry_run_changes_nothing(self):
        job = self.add_job("dry", "https://a.in/gone", fails=2)
        stats = self.run_checker({"https://a.in/gone": 404}, dry_run=True)
        self.assertEqual(stats.closed, 1)
        self.assertEqual(self.job(job), ("open", 2, None, False))


if __name__ == "__main__":
    unittest.main()
