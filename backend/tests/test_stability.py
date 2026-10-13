"""Tests for the gap report stability study (Stage 1.10), on made-up job posts."""
import random
import unittest
from datetime import datetime, timedelta, timezone

from app import subject_skills as ss
from research import stability as st

NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)


def fake_jobs(n: int = 300, seed: int = 1) -> list[tuple]:
    """Python is in most posts, SQL in many, Docker in some, Rust in very few."""
    rng = random.Random(seed)
    rows = []
    for i in range(n):
        skills = [s for s, p in (("python", 0.6), ("sql", 0.4), ("docker", 0.25), ("rust", 0.02)) if rng.random() < p]
        rows.append((skills or ["java"], True, NOW - timedelta(days=rng.randint(0, 80)), 0))
    return rows


class TestHelpers(unittest.TestCase):
    def test_spearman(self):
        self.assertAlmostEqual(st.spearman([1, 2, 3, 4], [10, 20, 30, 40]), 1.0)
        self.assertAlmostEqual(st.spearman([1, 2, 3, 4], [4, 3, 2, 1]), -1.0)
        self.assertAlmostEqual(st.spearman([1, 1, 2, 3], [1, 1, 2, 3]), 1.0)          # ties
        self.assertNotEqual(st.spearman([1, 2], [1, 2]), st.spearman([1, 2], [1, 2]))  # too few: NaN

    def test_jaccard_and_interval(self):
        self.assertEqual(st.jaccard({"a", "b"}, {"b", "c"}), 1 / 3)
        self.assertEqual(st.jaccard(set(), set()), 1.0)
        self.assertEqual(st.interval(list(range(100))), (2, 96))


class TestRun(unittest.TestCase):
    def test_strong_signal_is_stable(self):
        subjects = [{"name": "Database Management Systems", "kind": "theory", "semester": 3}]
        mapped = ss.map_subjects(subjects, use_ai=False)
        r = st.run(fake_jobs(), subjects, mapped, rounds=60, now=NOW)
        learn = dict(r["learn_now"])
        self.assertIn("python", learn)                          # not taught, asked in most posts
        self.assertNotIn("sql", learn)                          # taught by DBMS
        self.assertGreaterEqual(learn["python"], 0.95)          # a strong signal stays every time
        self.assertGreater(r["spearman_mean"], 0.8)
        low, high = r["coverage_ci"]
        self.assertLessEqual(low, r["coverage"])
        self.assertGreaterEqual(high, r["coverage"])
        text = st.report(r, "test")
        self.assertIn("Learn now", text)
        self.assertIn("| python |", text)

    def test_same_seed_same_result(self):
        subjects = [{"name": "Python Programming", "kind": "theory", "semester": 1}]
        mapped = ss.map_subjects(subjects, use_ai=False)
        a = st.run(fake_jobs(), subjects, mapped, rounds=20, now=NOW)
        b = st.run(fake_jobs(), subjects, mapped, rounds=20, now=NOW)
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
