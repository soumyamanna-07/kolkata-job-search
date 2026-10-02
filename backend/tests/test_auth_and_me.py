"""Login-token security and logged-in user endpoints, against a TEST database.

Tokens are signed with a throw-away test key, so no real Supabase is needed.
NEVER point TEST_DATABASE_URL at the real database. Skipped unless it is set.
"""
import os
import time
import unittest
import uuid
from unittest import mock

import jwt
from cryptography.hazmat.primitives.asymmetric import ec

TEST_DB = os.getenv("TEST_DATABASE_URL")
SUPABASE_URL = "https://testproject.supabase.co"
GOOD_KEY = ec.generate_private_key(ec.SECP256R1())
OTHER_KEY = ec.generate_private_key(ec.SECP256R1())


def make_token(user_id, key=GOOD_KEY, alg="ES256", **overrides):
    now = int(time.time())
    claims = {"sub": user_id, "email": "test@example.com", "aud": "authenticated",
              "iss": f"{SUPABASE_URL}/auth/v1", "iat": now, "exp": now + 3600, "role": "authenticated"}
    claims.update(overrides)
    return jwt.encode(claims, key, algorithm=alg, headers={"kid": "test-key"})


class FakeJwks:
    """Stands in for Supabase's public key endpoint: always returns GOOD_KEY's public half."""
    def get_signing_key_from_jwt(self, token):
        return mock.Mock(key=GOOD_KEY.public_key())


@unittest.skipUnless(TEST_DB, "set TEST_DATABASE_URL to run API tests")
class TestAuthAndMe(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        from fastapi.testclient import TestClient

        from app import auth, config
        cls.patches = [mock.patch.object(config, "DATABASE_URL", TEST_DB),
                       mock.patch.object(config, "SUPABASE_URL", SUPABASE_URL),
                       mock.patch.object(config, "SUPABASE_JWT_SECRET", ""),
                       mock.patch.object(auth, "_jwks", lambda: FakeJwks())]
        for p in cls.patches:
            p.start()
        cls.db = psycopg.connect(TEST_DB, autocommit=True)
        cls.db.execute("truncate public.jobs, public.job_events cascade")
        cls.db.execute("delete from auth.users")
        cls.user_id = str(uuid.uuid4())
        cls.blocked_id = str(uuid.uuid4())
        cls.db.execute("insert into auth.users (id, email, raw_user_meta_data) values "
                       "(%s, 'a@x.com', '{\"full_name\": \"Asha\"}'), (%s, 'b@x.com', '{}')",
                       (cls.user_id, cls.blocked_id))
        cls.db.execute("update public.profiles set is_blocked = true where id = %s", (cls.blocked_id,))
        cls.job_id = cls.db.execute(
            "insert into public.jobs (job_key, source, company_name, title, area, apply_url, skills) "
            "values ('k1', 'lever', 'ABC', 'Data Analyst', 'Kolkata', 'https://x/1', '{sql}') "
            "returning id::text").fetchone()[0]

        from app.main import app
        cls.cm = TestClient(app)
        cls.client = cls.cm.__enter__()
        cls.auth = {"Authorization": f"Bearer {make_token(cls.user_id)}"}

    @classmethod
    def tearDownClass(cls):
        cls.cm.__exit__(None, None, None)
        cls.db.close()
        for p in cls.patches:
            p.stop()

    def me(self, token):
        return self.client.get("/api/me", headers={"Authorization": f"Bearer {token}"})

    # ---------------- token security
    def test_valid_token(self):
        r = self.client.get("/api/me", headers=self.auth)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual((body["id"], body["role"], body["email"]), (self.user_id, "candidate", "test@example.com"))

    def test_rejected_tokens(self):
        self.assertEqual(self.client.get("/api/me").status_code, 401)                       # no token
        self.assertEqual(self.me("not.a.token").status_code, 401)                            # garbage
        self.assertEqual(self.me(make_token(self.user_id, exp=int(time.time()) - 120)).status_code, 401)  # expired
        self.assertEqual(self.me(make_token(self.user_id, key=OTHER_KEY)).status_code, 401)  # forged
        self.assertEqual(self.me(make_token(self.user_id, iss="https://evil.supabase.co/auth/v1")).status_code, 401)
        self.assertEqual(self.me(make_token(self.user_id, aud="anon")).status_code, 401)     # wrong audience
        hs_token = make_token(self.user_id, key="a-shared-secret-that-is-long-enough-32b", alg="HS256")
        self.assertEqual(self.me(hs_token).status_code, 401)                                 # no HS secret set
        unsigned = jwt.encode({"sub": self.user_id, "aud": "authenticated",
                               "iss": f"{SUPABASE_URL}/auth/v1", "exp": int(time.time()) + 60}, None, algorithm="none")
        self.assertEqual(self.me(unsigned).status_code, 401)                                 # alg=none
        self.assertEqual(self.me(make_token(str(uuid.uuid4()))).status_code, 401)            # unknown user

    def test_blocked_user(self):
        self.assertEqual(self.me(make_token(self.blocked_id)).status_code, 403)

    def test_role_check(self):
        from fastapi import HTTPException

        from app.auth import CurrentUser, require_role
        checker = require_role("admin")
        with self.assertRaises(HTTPException) as e:
            checker(CurrentUser(id="x", email=None, full_name=None, role="candidate", privacy_consent_at=None))
        self.assertEqual(e.exception.status_code, 403)

    # ---------------- profile
    def test_update_name_and_consent(self):
        r = self.client.patch("/api/me", json={"full_name": "  Asha Roy "}, headers=self.auth)
        self.assertEqual(r.json()["full_name"], "Asha Roy")
        self.assertEqual(self.client.patch("/api/me", json={"full_name": ""}, headers=self.auth).status_code, 422)
        first = self.client.post("/api/me/consent", headers=self.auth).json()["privacy_consent_at"]
        again = self.client.post("/api/me/consent", headers=self.auth).json()["privacy_consent_at"]
        self.assertIsNotNone(first)
        self.assertEqual(first, again)                       # first consent time is kept

    # ---------------- saved jobs and activity
    def test_saved_jobs(self):
        url = f"/api/me/saved-jobs/{self.job_id}"
        self.assertEqual(self.client.put(url).status_code, 401)                      # login required
        self.assertEqual(self.client.put(url, headers=self.auth).status_code, 204)
        self.assertEqual(self.client.put(url, headers=self.auth).status_code, 204)   # twice is fine
        saved = self.client.get("/api/me/saved-jobs", headers=self.auth).json()
        self.assertEqual([(j["title"], j["status"]) for j in saved], [("Data Analyst", "open")])
        self.assertEqual(self.client.put(f"/api/me/saved-jobs/{uuid.uuid4()}", headers=self.auth).status_code, 404)
        self.assertEqual(self.client.delete(url, headers=self.auth).status_code, 204)
        self.assertEqual(self.client.get("/api/me/saved-jobs", headers=self.auth).json(), [])

    def test_events_and_applied_history(self):
        event = {"job_id": self.job_id, "event_type": "view"}
        self.assertEqual(self.client.post("/api/events", json=event).status_code, 422)          # guest w/o session
        self.assertEqual(self.client.post("/api/events", json={**event, "session_id": "g1"}).status_code, 204)
        click = {"job_id": self.job_id, "event_type": "click_apply", "source_page": "search", "rank_position": 1}
        self.assertEqual(self.client.post("/api/events", json=click, headers=self.auth).status_code, 204)
        bad = {"job_id": str(uuid.uuid4()), "event_type": "view", "session_id": "g1"}
        self.assertEqual(self.client.post("/api/events", json=bad).status_code, 404)
        applied = self.client.get("/api/me/applied", headers=self.auth).json()
        self.assertEqual([j["title"] for j in applied], ["Data Analyst"])


if __name__ == "__main__":
    unittest.main()
