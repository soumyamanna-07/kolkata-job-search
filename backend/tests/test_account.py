"""Tests for "Delete my account": everything personal goes, anonymous activity stays."""
import os
import unittest
import uuid
from unittest import mock

from app import account, config

TEST_DB = os.getenv("TEST_DATABASE_URL")


def add_user(db, role="candidate"):
    uid = str(uuid.uuid4())
    db.execute("insert into auth.users (id, email) values (%s, %s)", (uid, f"del-{uid[:8]}@test.in"))
    if role != "candidate":
        db.execute("update public.profiles set role = %s where id = %s", (role, uid))
    return uid


@unittest.skipUnless(TEST_DB, "set TEST_DATABASE_URL to run database tests")
class TestDeleteAccount(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        cls.db = psycopg.connect(TEST_DB, autocommit=True)
        cls.tag = uuid.uuid4().hex[:8]

    @classmethod
    def tearDownClass(cls):
        cls.db.execute("delete from public.jobs where job_key like %s", (f"del-{cls.tag}%",))
        cls.db.close()

    def add_job(self, key, employer_id=None):
        return self.db.execute(
            """insert into public.jobs (job_key, source, company_name, title, apply_url, employer_id)
               values (%s, %s, 'ABC', 'Data Analyst', 'https://x.in', %s) returning id""",
            (f"del-{self.tag}-{key}", "employer" if employer_id else "adzuna", employer_id)).fetchone()[0]

    def count(self, table, column, uid):
        return self.db.execute(f"select count(*) from public.{table} where {column} = %s", (uid,)).fetchone()[0]

    def test_candidate_data_removed_activity_kept(self):
        uid = add_user(self.db)
        job = self.add_job("c1")
        self.db.execute("insert into public.cvs (user_id, skills) values (%s, '{python}')", (uid,))
        self.db.execute("insert into public.saved_jobs (user_id, job_id) values (%s, %s)", (uid, job))
        self.db.execute("insert into public.job_alerts (user_id, name) values (%s, 'a')", (uid,))
        event = self.db.execute("insert into public.job_events (user_id, job_id, event_type) "
                                "values (%s, %s, 'view') returning id", (uid, job)).fetchone()[0]

        result = account.delete_account(self.db, uid)
        self.assertEqual((result.cvs, result.saved_jobs, result.alerts, result.closed_jobs), (1, 1, 1, 0))
        for table, column in [("profiles", "id"), ("cvs", "user_id"), ("saved_jobs", "user_id"),
                              ("job_alerts", "user_id")]:
            self.assertEqual(self.count(table, column, uid), 0, table)
        self.assertEqual(self.db.execute("select count(*) from auth.users where id = %s", (uid,)).fetchone()[0], 0)
        user_of_event = self.db.execute("select user_id from public.job_events where id = %s", (event,)).fetchone()
        self.assertIsNone(user_of_event[0])                       # click kept, but anonymous now
        self.assertEqual(self.db.execute("select status from public.jobs where id = %s", (job,)).fetchone()[0], "open")

    def test_employer_jobs_closed(self):
        uid = add_user(self.db, "employer")
        open_job = self.add_job("e1", uid)
        result = account.delete_account(self.db, uid)
        self.assertEqual(result.closed_jobs, 1)
        status, employer = self.db.execute("select status, employer_id from public.jobs where id = %s",
                                           (open_job,)).fetchone()
        self.assertEqual((status, employer), ("closed", None))   # no open job left without an owner

    def test_admin_cannot_self_delete(self):
        uid = add_user(self.db, "admin")
        with self.assertRaises(account.CannotDelete):
            account.delete_account(self.db, uid)
        self.assertEqual(self.count("profiles", "id", uid), 1)   # nothing changed
        self.db.execute("delete from auth.users where id = %s", (uid,))

    def test_unknown_account(self):
        with self.assertRaises(LookupError):
            account.delete_account(self.db, str(uuid.uuid4()))


@unittest.skipUnless(TEST_DB, "set TEST_DATABASE_URL to run API tests")
class TestDeleteAccountApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        from fastapi.testclient import TestClient

        from app import auth
        from tests.test_auth_and_me import SUPABASE_URL, FakeJwks, make_token
        cls.make_token = staticmethod(make_token)
        cls.patches = [mock.patch.object(config, "DATABASE_URL", TEST_DB),
                       mock.patch.object(config, "SUPABASE_URL", SUPABASE_URL),
                       mock.patch.object(auth, "_jwks", lambda: FakeJwks())]
        for p in cls.patches:
            p.start()
        cls.db = psycopg.connect(TEST_DB, autocommit=True)
        from app.main import app
        cls.cm = TestClient(app)
        cls.client = cls.cm.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.cm.__exit__(None, None, None)
        cls.db.close()
        for p in cls.patches:
            p.stop()

    def delete(self, uid, confirm="DELETE MY ACCOUNT"):
        return self.client.request("DELETE", "/api/me", json={"confirm": confirm},
                                   headers={"Authorization": f"Bearer {self.make_token(uid)}"})

    def test_delete_flow(self):
        uid = add_user(self.db)
        self.assertEqual(self.delete(uid, confirm="yes").status_code, 422)          # must type the phrase
        self.assertEqual(self.delete(uid).status_code, 204)
        me = self.client.get("/api/me", headers={"Authorization": f"Bearer {self.make_token(uid)}"})
        self.assertEqual(me.status_code, 401)                                        # old login stops working
        self.assertEqual(self.client.request("DELETE", "/api/me", json={"confirm": "DELETE MY ACCOUNT"})
                         .status_code, 401)                                          # login needed

    def test_admin_gets_409(self):
        uid = add_user(self.db, "admin")
        self.assertEqual(self.delete(uid).status_code, 409)
        self.db.execute("delete from auth.users where id = %s", (uid,))


if __name__ == "__main__":
    unittest.main()
