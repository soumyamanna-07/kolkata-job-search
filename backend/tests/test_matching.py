"""Tests for the match score and the matching endpoints."""
import os
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest import mock

from app.matching import (CVProfile, experience_score, freshness_score, meaning_score, rank, score_job,
                          skill_gap, skill_score, title_min_years)

TEST_DB = os.getenv("TEST_DATABASE_URL")
NOW = datetime(2026, 10, 2, tzinfo=timezone.utc)
ME = CVProfile(skills=["python", "sql", "machine learning", "pandas"], experience_years=0.5)


def job(title, similarity, skills, exp_min=None, exp_max=None, days=1):
    return {"title": title, "similarity": similarity, "skills": skills, "experience_min": exp_min,
            "experience_max": exp_max, "posted_at": NOW - timedelta(days=days)}


class TestSignals(unittest.TestCase):
    def test_meaning_scaled_0_to_1(self):
        self.assertEqual(meaning_score(0.1), 0.0)
        self.assertEqual(meaning_score(0.9), 1.0)
        self.assertAlmostEqual(meaning_score(0.525), 0.5)

    def test_skills(self):
        self.assertEqual(skill_score(["python", "docker"], {"python"}), (0.25, ["python"], ["docker"]))
        self.assertEqual(skill_score([], {"python"}), (None, [], []))
        # 1 of 1 listed skill is not a sure 100%: the AI meaning fills in
        self.assertAlmostEqual(skill_score(["azure"], {"azure"}, meaning=0.4)[0], 0.6)
        # languages / soft skills are ignored
        self.assertEqual(skill_score(["english", "python", "communication"], {"python"}), (1 / 3, ["python"], []))
        self.assertEqual(skill_score(["english"], {"python"}), (None, [], []))

    def test_seniority_from_title(self):
        self.assertEqual(title_min_years("AI ML Engineering Intern"), 0.0)
        self.assertEqual(title_min_years("Microsoft-Pure AI-Senior Manager"), 8.0)
        self.assertEqual(title_min_years("Azure Data Architect - Manager"), 7.0)
        self.assertEqual(title_min_years("Lead Artificial Intelligence Engineer"), 5.0)
        self.assertEqual(title_min_years("Sr. Data Analyst"), 4.0)
        self.assertEqual(title_min_years("ServiceNow - Moveworks AI - Manger"), 5.0)      # typo in a real title
        self.assertIsNone(title_min_years("Data Analyst"))

    def test_experience(self):
        self.assertEqual(experience_score(0.5, 0, 2), 1.0)          # fresher job
        self.assertEqual(experience_score(5, 2, None), 1.0)
        self.assertEqual(experience_score(10, 0, 1), 0.7)           # far more than needed
        self.assertAlmostEqual(experience_score(0.5, 2, None), 0.5)  # 1.5 years short
        self.assertEqual(experience_score(0, 5, None), 0.0)
        self.assertEqual(experience_score(None, 2, None), 0.7)       # unknown

    def test_freshness(self):
        self.assertEqual(freshness_score(NOW - timedelta(days=2), NOW), 1.0)
        self.assertAlmostEqual(freshness_score(NOW - timedelta(days=30), NOW), 0.3)
        self.assertEqual(freshness_score(None, NOW), 0.5)


class TestRanking(unittest.TestCase):
    def test_good_match_beats_bad_match(self):
        ml = score_job(job("ML Intern", 0.62, ["python", "machine learning", "pandas"], 0, 1), ME, NOW)
        acc = score_job(job("Accountant", 0.15, ["tally", "gst"], 2), ME, NOW)
        self.assertGreater(ml.score, 80)
        self.assertLess(acc.score, 25)
        self.assertIn("You have 3 of 3 listed skills: python, machine learning, pandas", ml.reasons)
        self.assertIn("Open to freshers", ml.reasons)
        self.assertIn("Needs 2 years+, you have 0.5 years", acc.reasons)

    def test_senior_roles_drop_for_a_fresher(self):
        # same meaning, but a "Senior Manager" title with no stated experience must rank far lower
        intern = score_job(job("AI Engineering Intern", 0.70, ["machine learning"]), ME, NOW)
        manager = score_job(job("AI Senior Manager", 0.70, []), ME, NOW)
        self.assertGreater(intern.score - manager.score, 30)
        self.assertIn("Senior role (usually 8 years+), you have 0.5 years", manager.reasons)
        senior_me = CVProfile(skills=ME.skills, experience_years=9)
        self.assertGreater(score_job(job("AI Senior Manager", 0.70, []), senior_me, NOW).score, manager.score)

    def test_rank_order_limit_and_skill_gap(self):
        jobs = [job("Data Analyst", 0.50, ["sql", "excel", "power bi"]),
                job("ML Engineer", 0.60, ["python", "docker", "aws"], 3),
                job("ML Intern", 0.62, ["python", "machine learning"]),
                job("Driver", 0.05, [])]
        ranked = rank(jobs, ME, limit=3, now=NOW)
        self.assertEqual([j["title"] for j, _ in ranked], ["ML Intern", "Data Analyst", "ML Engineer"])
        scores = [m.score for _, m in ranked]
        self.assertTrue(scores[1] >= 50 > scores[2])
        # ML Engineer is a weak match (score < 50), so its docker/aws are not in the skill gap
        self.assertEqual({s for s, _ in skill_gap(ranked)}, {"excel", "power bi"})


@unittest.skipUnless(TEST_DB, "set TEST_DATABASE_URL to run API tests")
class TestMatchApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        from fastapi.testclient import TestClient

        from app import auth, config, embeddings
        from scripts.embed_jobs import embed_jobs, find_jobs_to_embed
        from tests.test_auth_and_me import SUPABASE_URL, FakeJwks, make_token
        from tests.test_cv_parser import STUDENT_CV, make_pdf
        from tests.test_embeddings import FakeEmbedder

        cls.fake = FakeEmbedder()
        embeddings.set_embedder(cls.fake)
        cls.patches = [mock.patch.object(config, "DATABASE_URL", TEST_DB),
                       mock.patch.object(config, "SUPABASE_URL", SUPABASE_URL),
                       mock.patch.object(auth, "_jwks", lambda: FakeJwks())]
        for p in cls.patches:
            p.start()
        cls.db = psycopg.connect(TEST_DB, autocommit=True)
        cls.tag = uuid.uuid4().hex[:8]
        for key, title, skills, area, status in [
                ("ml", "ML Intern", ["python", "machine learning", "pandas"], "Salt Lake", "open"),
                ("da", "Data Analyst", ["sql", "excel", "power bi"], "Kolkata", "open"),
                ("acc", "Accountant", ["tally", "gst"], "Kolkata", "open"),
                ("old", "ML Intern old", ["python", "machine learning"], "Kolkata", "closed")]:
            cls.db.execute(
                """insert into public.jobs (job_key, source, company_name, title, description, area, apply_url,
                       skills, status, posted_at) values (%s, 'lever', 'Test Co', %s, %s, %s, 'https://e.com', %s, %s, now())""",
                (f"m-{cls.tag}-{key}", title, f"{title} job. " + " ".join(skills), area, skills, status))
        _, todo = find_jobs_to_embed(cls.db)
        embed_jobs(cls.db, cls.fake, todo, log=lambda _: None)

        cls.user_id = str(uuid.uuid4())
        cls.db.execute("insert into auth.users (id, email) values (%s, 'match@x.com')", (cls.user_id,))
        cls.auth = {"Authorization": f"Bearer {make_token(cls.user_id)}"}
        cls.pdf = make_pdf(STUDENT_CV)

        from app.main import app
        cls.cm = TestClient(app)
        cls.client = cls.cm.__enter__()

    @classmethod
    def tearDownClass(cls):
        from app import embeddings
        cls.cm.__exit__(None, None, None)
        cls.db.execute("delete from public.jobs where job_key like %s", (f"m-{cls.tag}-%",))
        cls.db.execute("delete from auth.users where id = %s", (cls.user_id,))
        cls.db.close()
        for p in cls.patches:
            p.stop()
        embeddings.set_embedder(None)

    def mine(self, items):
        return [j["title"] for j in items if j["company_name"] == "Test Co" and j["apply_url"] == "https://e.com"]

    def test_guest_match(self):
        before = self.db.execute("select count(*) from public.cvs").fetchone()[0]
        r = self.client.post("/api/cv/match", files={"file": ("cv.pdf", self.pdf, "application/pdf")},
                             params={"limit": 50})
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        titles = self.mine(body["items"])
        self.assertEqual(titles[0], "ML Intern")                       # best match first
        self.assertNotIn("ML Intern old", titles)                      # closed jobs never shown
        self.assertEqual(titles[-1], "Accountant")
        top = body["items"][0]
        self.assertEqual(top["matched_skills"], ["python", "machine learning", "pandas"])
        self.assertTrue(0 <= top["match_score"] <= 100)
        self.assertEqual(body["scoring_version"], "v1.1-rules")
        good_missing = {s for j in body["items"] if j["match_score"] >= 50 for s in j["missing_skills"]}
        self.assertEqual({g["skill"] for g in body["skill_gap"]}, good_missing)   # only from real matches
        self.assertEqual(self.db.execute("select count(*) from public.cvs").fetchone()[0], before)  # nothing saved

    def test_filters_and_validation(self):
        files = {"file": ("cv.pdf", self.pdf, "application/pdf")}
        r = self.client.post("/api/cv/match", files=files, params={"area": "Salt Lake", "limit": 50})
        self.assertEqual(self.mine(r.json()["items"]), ["ML Intern"])
        r = self.client.post("/api/cv/match", files=files, params={"area": "Delhi"})
        self.assertEqual(r.status_code, 422)

    def test_my_matches(self):
        self.assertEqual(self.client.get("/api/me/matches").status_code, 401)
        self.client.post("/api/me/consent", headers=self.auth)
        self.db.execute("delete from public.cvs where user_id = %s", (self.user_id,))
        self.assertEqual(self.client.get("/api/me/matches", headers=self.auth).status_code, 404)
        self.client.post("/api/me/cv", files={"file": ("cv.pdf", self.pdf, "application/pdf")}, headers=self.auth)
        r = self.client.get("/api/me/matches", headers=self.auth, params={"limit": 50})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.mine(r.json()["items"])[0], "ML Intern")

        # editing the CV re-embeds it: an accountant profile now ranks the Accountant job first
        edit = {"skills": ["tally", "gst"], "experience_years": 3, "education": "B.Com", "job_titles": ["Accountant"]}
        self.client.put("/api/me/cv", json=edit, headers=self.auth)
        r = self.client.get("/api/me/matches", headers=self.auth, params={"limit": 50})
        self.assertEqual(self.mine(r.json()["items"])[0], "Accountant")

        # a missing embedding (e.g. after a model upgrade) is rebuilt automatically
        self.db.execute("update public.cvs set embedding = null, embedding_hash = null where user_id = %s",
                        (self.user_id,))
        r = self.client.get("/api/me/matches", headers=self.auth, params={"limit": 50})
        self.assertEqual(self.mine(r.json()["items"])[0], "Accountant")
        self.assertTrue(self.db.execute("select embedding is not null from public.cvs where user_id = %s",
                                        (self.user_id,)).fetchone()[0])


if __name__ == "__main__":
    unittest.main()
