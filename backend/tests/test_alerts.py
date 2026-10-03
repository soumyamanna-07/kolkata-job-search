"""Tests for job alerts: due times, the email, finding new jobs, the sender script and the API."""
import os
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest import mock

from app import alerts, config, mailer

TEST_DB = os.getenv("TEST_DATABASE_URL")
NOW = datetime(2026, 10, 3, 7, 0, tzinfo=timezone.utc)


def job(**over):
    base = {"id": uuid.uuid4(), "title": "Python Developer", "company_name": "ABC Tech", "area": "Salt Lake",
            "salary_min": 400000, "salary_max": 600000, "salary_period": "year", "apply_url": "https://abc.in/apply",
            "source": "adzuna"}
    return {**base, **over}


class TestAlertLogic(unittest.TestCase):
    def test_due_times(self):
        self.assertTrue(alerts.is_due("daily", None, NOW))                              # never sent
        self.assertTrue(alerts.is_due("daily", NOW - timedelta(hours=23), NOW))         # a little early is fine
        self.assertFalse(alerts.is_due("daily", NOW - timedelta(hours=12), NOW))
        self.assertFalse(alerts.is_due("weekly", NOW - timedelta(days=6), NOW))
        self.assertTrue(alerts.is_due("weekly", NOW - timedelta(days=7), NOW))

    def test_since(self):
        self.assertEqual(alerts.since_for("daily", NOW, NOW - timedelta(days=30)), NOW)
        self.assertEqual(alerts.since_for("weekly", None, NOW), NOW - timedelta(days=7))

    def test_salary_text(self):
        self.assertEqual(alerts.salary_text(job()), "\u20b94 L - 6 L a year")
        self.assertEqual(alerts.salary_text(job(salary_min=450000, salary_max=None)), "\u20b94.5 L a year")
        self.assertEqual(alerts.salary_text(job(salary_min=15000, salary_max=20000, salary_period="month")),
                         "\u20b915,000 - 20,000 a month")
        self.assertEqual(alerts.salary_text(job(salary_min=None, salary_max=None)), "")

    def test_email(self):
        with mock.patch.object(config, "ALERTS_SECRET", "test-secret"), \
             mock.patch.object(config, "APP_URL", "https://kjs.in"):
            jobs = [job(title="<script>alert(1)</script> Dev"), job(apply_url="javascript:alert(1)", source="lever")]
            email = alerts.build_email("Asha", "Python <jobs>", jobs, 12, "a1")
            sig = alerts.unsubscribe_sig("a1")
        self.assertEqual(email.subject, '12 new Kolkata jobs for "Python <jobs>"')
        self.assertNotIn("<script>", email.html)                                        # job text is escaped
        self.assertIn("&lt;script&gt;", email.html)
        self.assertNotIn("javascript:", email.html)                                     # bad links replaced
        self.assertIn(f"https://kjs.in/jobs/{jobs[1]['id']}", email.html)
        self.assertIn("Showing the newest 2 of 12", email.text)
        self.assertIn("Jobs by Adzuna", email.text)                                     # Adzuna's terms
        self.assertTrue(email.unsubscribe_url.endswith(f"/api/alerts/a1/unsubscribe?sig={sig}"))

    def test_unsubscribe_signature(self):
        with mock.patch.object(config, "ALERTS_SECRET", "test-secret"):
            sig = alerts.unsubscribe_sig("a1")
            self.assertTrue(alerts.sig_ok("a1", sig))
            self.assertFalse(alerts.sig_ok("a2", sig))                                  # other alert
            self.assertFalse(alerts.sig_ok("a1", "0" * 32))
        with mock.patch.object(config, "ALERTS_SECRET", ""):
            self.assertFalse(alerts.sig_ok("a1", sig))                                  # no secret: never valid

    def test_message_headers(self):
        with mock.patch.object(config, "MAIL_FROM", "alerts@kjs.in"):
            msg = mailer.build_message("a@x.com", "Hi", "text", "<p>html</p>", "https://api/u?sig=1")
        self.assertEqual(msg["To"], "a@x.com")
        self.assertIn("alerts@kjs.in", msg["From"])
        self.assertEqual(msg["List-Unsubscribe"], "<https://api/u?sig=1>")
        self.assertEqual(msg["List-Unsubscribe-Post"], "List-Unsubscribe=One-Click")


class FakeMailer:
    """Collects messages instead of sending them."""
    sent = []
    fail_for = set()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def send(self, msg):
        if msg["To"] in self.fail_for:
            raise OSError("mailbox full")
        FakeMailer.sent.append(msg)


@unittest.skipUnless(TEST_DB, "set TEST_DATABASE_URL to run database tests")
class TestAlertSender(unittest.TestCase):
    """Finding new jobs and sending emails (no web server needed)."""

    @classmethod
    def setUpClass(cls):
        import psycopg

        from app.embeddings import cv_text, job_text, to_pgvector
        from tests.test_embeddings import FakeEmbedder
        cls.db = psycopg.connect(TEST_DB, autocommit=True)
        cls.db.execute("truncate public.jobs cascade")
        cls.tag = uuid.uuid4().hex[:8]
        cls.ids = {name: str(uuid.uuid4()) for name in ("asha", "bikram", "blocked")}
        for name, uid in cls.ids.items():
            cls.db.execute("insert into auth.users (id, email, raw_user_meta_data) values (%s, %s, %s)",
                           (uid, f"{name}-{cls.tag}@test.in", '{"full_name": "%s"}' % name.title()))
        cls.db.execute("update public.profiles set is_blocked = true where id = %s", (cls.ids["blocked"],))
        fake = FakeEmbedder()
        now = datetime.now(timezone.utc)
        jobs = [("new-py", "Python Developer", ["python", "sql"], now - timedelta(hours=2)),
                ("old-py", "Python Engineer", ["python"], now - timedelta(days=3)),
                ("new-sales", "Sales Executive", ["sales"], now - timedelta(hours=1))]
        for key, title, skills, seen in jobs:
            vec = to_pgvector(fake.embed([job_text(title, skills, "Build things in Kolkata")])[0])
            cls.db.execute(
                """insert into public.jobs (job_key, source, company_name, title, area, apply_url, skills,
                                            experience_min, posted_at, first_seen_at, description, embedding)
                   values (%s, 'adzuna', 'ABC', %s, 'Kolkata', 'https://x.in', %s, 0, %s, %s,
                           'Build things in Kolkata', %s::extensions.vector)""",
                (f"{key}-{cls.tag}", title, skills, seen, seen, vec))
        cv_vec = to_pgvector(fake.embed([cv_text(["Python Developer"], ["python", "sql"], None, 0.0)])[0])
        cls.db.execute("""insert into public.cvs (user_id, skills, experience_years, embedding)
                          values (%s, '{python,sql}', 0, %s::extensions.vector)""", (cls.ids["asha"], cv_vec))

    @classmethod
    def tearDownClass(cls):
        cls.db.execute("delete from auth.users where id = any(%s::uuid[])", (list(cls.ids.values()),))
        cls.db.execute("truncate public.jobs cascade")
        cls.db.close()

    def setUp(self):
        self.db.execute("delete from public.job_alerts")
        FakeMailer.sent, FakeMailer.fail_for = [], set()

    def add_alert(self, who, filters, use_cv=False, frequency="daily", last_sent=None):
        from psycopg.types.json import Jsonb
        return self.db.execute(
            """insert into public.job_alerts (user_id, name, filters, use_cv_match, frequency, last_sent_at)
               values (%s, 'My alert', %s, %s, %s, %s) returning id""",
            (self.ids[who], Jsonb(filters), use_cv, frequency, last_sent)).fetchone()[0]

    def run_sender(self, **kw):
        from scripts import send_alerts
        with mock.patch.object(config, "ALERTS_SECRET", "test-secret"), \
             mock.patch.object(config, "MAIL_FROM", "alerts@kjs.in"):
            return send_alerts.run(self.db, FakeMailer, datetime.now(timezone.utc), log=lambda _: None, **kw)

    def test_find_new_jobs(self):
        since = datetime.now(timezone.utc) - timedelta(days=1)
        found, total = alerts.find_new_jobs(self.db, self.ids["asha"], {"skills": ["python"]}, False, since)
        self.assertEqual(([j["title"] for j in found], total), (["Python Developer"], 1))   # 3-day-old job left out
        week = datetime.now(timezone.utc) - timedelta(days=7)
        _, total = alerts.find_new_jobs(self.db, self.ids["asha"], {"q": "python"}, False, week)
        self.assertEqual(total, 2)

    def test_cv_match(self):
        since = datetime.now(timezone.utc) - timedelta(days=1)
        found, total = alerts.find_new_jobs(self.db, self.ids["asha"], {}, True, since)
        self.assertEqual([j["title"] for j in found], ["Python Developer"])              # sales job is no match
        self.assertGreaterEqual(found[0]["match_score"], alerts.CV_MIN_SCORE)
        self.assertEqual(alerts.find_new_jobs(self.db, self.ids["bikram"], {}, True, since), ([], 0))  # no CV

    def test_sender(self):
        self.add_alert("asha", {"skills": ["python"]})
        self.add_alert("bikram", {"q": "nurse"})                                          # nothing new
        self.add_alert("bikram", {"q": "python"}, last_sent=datetime.now(timezone.utc) - timedelta(hours=3))
        self.add_alert("blocked", {"q": "python"})                                        # blocked: skipped
        stats = self.run_sender()
        self.assertEqual((stats.checked, stats.sent, stats.no_new_jobs, stats.not_due), (3, 1, 1, 1))
        self.assertEqual(FakeMailer.sent[0]["To"], f"asha-{self.tag}@test.in")
        self.assertIn("Python Developer", FakeMailer.sent[0].get_body(("plain",)).get_content())
        stats = self.run_sender()                                                         # run again at once
        self.assertEqual((stats.sent, len(FakeMailer.sent)), (0, 1))                      # nothing sent twice

    def test_failed_email_is_retried_next_time(self):
        alert_id = self.add_alert("asha", {"skills": ["python"]})
        FakeMailer.fail_for = {f"asha-{self.tag}@test.in"}
        stats = self.run_sender()
        self.assertEqual((stats.sent, stats.failed), (0, 1))
        last = self.db.execute("select last_sent_at from public.job_alerts where id = %s", (alert_id,)).fetchone()[0]
        self.assertIsNone(last)                                                           # still due
        FakeMailer.fail_for = set()
        self.assertEqual(self.run_sender().sent, 1)

    def test_dry_run_changes_nothing(self):
        self.add_alert("asha", {"skills": ["python"]})
        self.add_alert("bikram", {"q": "nurse"})
        stats = self.run_sender(dry_run=True)
        self.assertEqual((stats.sent, len(FakeMailer.sent)), (1, 0))
        self.assertEqual(self.db.execute("select count(*) from public.job_alerts where last_sent_at is not null")
                         .fetchone()[0], 0)

    def test_email_limit_per_run(self):
        self.add_alert("asha", {"skills": ["python"]})
        self.add_alert("bikram", {"q": "python"})
        stats = self.run_sender(max_emails=1)
        self.assertEqual((stats.sent, stats.left_for_next_run), (1, 1))


@unittest.skipUnless(TEST_DB, "set TEST_DATABASE_URL to run API tests")
class TestAlertApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        from fastapi.testclient import TestClient

        from app import auth
        from tests.test_auth_and_me import SUPABASE_URL, FakeJwks, make_token
        cls.patches = [mock.patch.object(config, "DATABASE_URL", TEST_DB),
                       mock.patch.object(config, "SUPABASE_URL", SUPABASE_URL),
                       mock.patch.object(config, "ALERTS_SECRET", "test-secret"),
                       mock.patch.object(auth, "_jwks", lambda: FakeJwks())]
        for p in cls.patches:
            p.start()
        cls.db = psycopg.connect(TEST_DB, autocommit=True)
        cls.ids = {name: str(uuid.uuid4()) for name in ("u1", "u2")}
        for name, uid in cls.ids.items():
            cls.db.execute("insert into auth.users (id, email) values (%s, %s)", (uid, f"{name}-{uid[:8]}@test.in"))
        cls.auth = {name: {"Authorization": f"Bearer {make_token(uid)}"} for name, uid in cls.ids.items()}
        cls.db.execute("""insert into public.jobs (job_key, source, company_name, title, area, apply_url, skills,
                                                   posted_at)
                          values (%s, 'adzuna', 'ABC', 'Python Developer', 'Salt Lake', 'https://x.in', '{python}',
                                  now())""", (f"alert-api-{cls.ids['u1'][:8]}",))
        from app.main import app
        cls.cm = TestClient(app)
        cls.client = cls.cm.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.cm.__exit__(None, None, None)
        cls.db.execute("delete from public.jobs where job_key = %s", (f"alert-api-{cls.ids['u1'][:8]}",))
        cls.db.execute("delete from auth.users where id = any(%s::uuid[])", (list(cls.ids.values()),))
        cls.db.close()
        for p in cls.patches:
            p.stop()

    def setUp(self):
        self.db.execute("delete from public.job_alerts where user_id = any(%s::uuid[])", (list(self.ids.values()),))

    def create(self, who="u1", **body):
        body = {"name": "Python in Salt Lake", "filters": {"skills": ["Python"], "areas": ["Salt Lake"]}, **body}
        return self.client.post("/api/me/alerts", json=body, headers=self.auth[who])

    def test_create_list_update_delete(self):
        c, h = self.client, self.auth
        self.assertEqual(c.get("/api/me/alerts").status_code, 401)                       # login needed
        r = self.create()
        self.assertEqual(r.status_code, 201, r.text)
        alert = r.json()
        self.assertEqual(alert["filters"]["skills"], ["python"])                          # cleaned up
        self.assertEqual(alert["frequency"], "daily")
        self.assertEqual([a["id"] for a in c.get("/api/me/alerts", headers=h["u1"]).json()], [alert["id"]])
        self.assertEqual(c.get("/api/me/alerts", headers=h["u2"]).json(), [])            # private

        body = {"name": "Weekly python", "filters": {"q": "python"}, "frequency": "weekly", "is_active": False}
        self.assertEqual(c.put(f"/api/me/alerts/{alert['id']}", json=body, headers=h["u2"]).status_code, 404)
        r = c.put(f"/api/me/alerts/{alert['id']}", json=body, headers=h["u1"])
        self.assertEqual((r.json()["frequency"], r.json()["is_active"]), ("weekly", False))
        self.assertEqual(c.delete(f"/api/me/alerts/{alert['id']}", headers=h["u2"]).status_code, 404)
        self.assertEqual(c.delete(f"/api/me/alerts/{alert['id']}", headers=h["u1"]).status_code, 204)

    def test_validation(self):
        self.assertEqual(self.create(filters={}).status_code, 422)                       # nothing to watch
        self.assertEqual(self.create(filters={"skills": ["not-a-skill"]}).status_code, 422)
        self.assertEqual(self.create(filters={"areas": ["Mumbai"]}).status_code, 422)
        self.assertEqual(self.create(frequency="hourly").status_code, 422)
        self.assertEqual(self.create(filters={}, use_cv_match=True).status_code, 422)    # no CV saved yet

    def test_limit(self):
        for _ in range(alerts.MAX_ALERTS_PER_USER):
            self.assertEqual(self.create().status_code, 201)
        self.assertEqual(self.create().status_code, 409)

    def test_preview(self):
        alert_id = self.create().json()["id"]
        p = self.client.get(f"/api/me/alerts/{alert_id}/preview", headers=self.auth["u1"]).json()
        self.assertGreaterEqual(p["total_new"], 1)
        self.assertIn("Python Developer", [j["title"] for j in p["items"]])

    def test_unsubscribe(self):
        alert_id = self.create().json()["id"]
        url = f"/api/alerts/{alert_id}/unsubscribe"
        self.assertEqual(self.client.get(url, params={"sig": "bad"}).status_code, 400)
        sig = alerts.unsubscribe_sig(alert_id)
        page = self.client.get(url, params={"sig": sig})
        self.assertEqual(page.status_code, 200)
        self.assertIn("<form", page.text)
        self.assertTrue(self.client.get("/api/me/alerts", headers=self.auth["u1"]).json()[0]["is_active"])
        self.assertEqual(self.client.post(url, params={"sig": sig}).status_code, 200)    # no login needed
        self.assertFalse(self.client.get("/api/me/alerts", headers=self.auth["u1"]).json()[0]["is_active"])


if __name__ == "__main__":
    unittest.main()
