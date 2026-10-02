"""Tests for embeddings. A small fake model is used, so the real model is not needed here."""
import hashlib
import os
import re
import unittest
import uuid

from app.embeddings import DIMENSIONS, _normalize, cv_text, job_text, text_hash, to_pgvector

TEST_DB = os.getenv("TEST_DATABASE_URL")


class FakeEmbedder:
    """Bag-of-words vectors: texts sharing words point the same way. Fast and repeatable."""

    def __init__(self):
        self.calls = 0

    def embed(self, texts):
        self.calls += 1
        out = []
        for text in texts:
            vec = [0.0] * DIMENSIONS
            for word in re.findall(r"[a-z]+", text.lower()):
                vec[int(hashlib.md5(word.encode()).hexdigest(), 16) % DIMENSIONS] += 1.0
            out.append(_normalize(vec))
        return out


class TestTexts(unittest.TestCase):
    def test_job_text_order_and_cleanup(self):
        text = job_text("Python Developer", ["python", "sql"], "<p>Build   APIs</p>\n\nin Kolkata")
        self.assertEqual(text, "Python Developer. Skills: python, sql. Build APIs in Kolkata")
        self.assertEqual(job_text("Driver", [], None), "Driver")
        self.assertLessEqual(len(job_text("T", [], "x" * 5000)), 1300)         # long descriptions cut

    def test_cv_text_has_no_personal_details(self):
        text = cv_text(["ML Intern"], ["python", "sql"], "B.Tech / B.E.", 0.5)
        self.assertEqual(text, "ML Intern. Skills: python, sql. Education: B.Tech / B.E.. 0.5 years of experience")
        self.assertTrue(cv_text([], ["excel"], None, 0.0).endswith("Fresher"))

    def test_hash_changes_with_text(self):
        self.assertEqual(text_hash("a"), text_hash("a"))
        self.assertNotEqual(text_hash("a"), text_hash("b"))

    def test_pgvector_format(self):
        vec = _normalize([1.0] + [0.0] * (DIMENSIONS - 1))
        self.assertTrue(to_pgvector(vec).startswith("[1.000000,0.000000,"))
        with self.assertRaises(ValueError):
            to_pgvector([0.1, 0.2])

    def test_fake_model_similarity(self):
        a, b, c = FakeEmbedder().embed(["python developer", "senior python developer", "accountant tally"])
        dot = lambda x, y: sum(i * j for i, j in zip(x, y))
        self.assertGreater(dot(a, b), dot(a, c))


@unittest.skipUnless(TEST_DB, "set TEST_DATABASE_URL to run database tests")
class TestEmbedJobsScript(unittest.TestCase):
    def setUp(self):
        import psycopg
        self.conn = psycopg.connect(TEST_DB, autocommit=True)
        self.tag = uuid.uuid4().hex[:8]
        self.ids = {}
        for key, title, skills, status in [("py", "Python Developer", ["python", "fastapi"], "open"),
                                           ("acc", "Accountant", ["tally", "gst"], "open"),
                                           ("old", "Python Developer old", ["python"], "closed")]:
            self.ids[key] = self.conn.execute(
                """insert into public.jobs (job_key, source, company_name, title, description, apply_url, skills, status)
                   values (%s, 'lever', 'Test Co', %s, 'Kolkata role', 'https://example.com', %s, %s) returning id""",
                (f"emb-{self.tag}-{key}", title, skills, status)).fetchone()[0]

    def tearDown(self):
        self.conn.execute("delete from public.jobs where job_key like %s", (f"emb-{self.tag}-%",))
        self.conn.close()

    def mine(self, todo):
        return {row[0] for row in todo} & set(self.ids.values())

    def test_embeds_only_new_or_changed_open_jobs(self):
        from scripts.embed_jobs import embed_jobs, find_jobs_to_embed
        _, todo = find_jobs_to_embed(self.conn)
        self.assertEqual(self.mine(todo), {self.ids["py"], self.ids["acc"]})         # closed job skipped
        embed_jobs(self.conn, FakeEmbedder(), todo, batch_size=2, log=lambda _: None)

        _, todo = find_jobs_to_embed(self.conn)
        self.assertEqual(self.mine(todo), set())                                       # nothing left to do

        self.conn.execute("update public.jobs set title = 'Senior Python Developer' where id = %s", (self.ids["py"],))
        _, todo = find_jobs_to_embed(self.conn)
        self.assertEqual(self.mine(todo), {self.ids["py"]})                            # text changed -> again

    def test_nearest_job_by_meaning(self):
        from scripts.embed_jobs import embed_jobs, find_jobs_to_embed
        fake = FakeEmbedder()
        _, todo = find_jobs_to_embed(self.conn)
        embed_jobs(self.conn, fake, todo, log=lambda _: None)
        query = to_pgvector(fake.embed(["python fastapi backend developer"])[0])
        nearest = self.conn.execute(
            """select id from public.jobs where job_key like %s and status = 'open'
               order by embedding operator(extensions.<=>) %s::extensions.vector limit 1""",
            (f"emb-{self.tag}-%", query)).fetchone()[0]
        self.assertEqual(nearest, self.ids["py"])


if __name__ == "__main__":
    unittest.main()
