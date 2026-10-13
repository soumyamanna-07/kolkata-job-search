"""Tests for the mapping evaluation (Stage 1.10): the measures and that the script runs."""
import json
import tempfile
import unittest
from pathlib import Path

from research import eval_mapping as em


class TestMeasures(unittest.TestCase):
    def test_score(self):
        s = em.score([({"sql", "mysql"}, {"sql"}), (set(), {"python"}), (set(), set()), ({"linux"}, set())])
        self.assertEqual((s.tp, s.fp, s.fn), (1, 2, 1))
        self.assertAlmostEqual(s.precision, 1 / 3)
        self.assertAlmostEqual(s.recall, 1 / 2)
        self.assertAlmostEqual(s.f1, 0.4)
        self.assertEqual((s.empty_ok, s.empty_total), (1, 2))
        self.assertEqual(em.score([(set(), set())]).f1, 0.0)                 # nothing to find, nothing found

    def test_bootstrap(self):
        perfect = [({"c"}, {"c"})] * 10
        self.assertEqual(em.bootstrap_f1(perfect, rounds=200), (1.0, 1.0))
        mixed = [({"c"}, {"c"}), (set(), {"java"})] * 10
        low, high = em.bootstrap_f1(mixed, rounds=500)
        self.assertLessEqual(low, em.score(mixed).f1)
        self.assertGreaterEqual(high, em.score(mixed).f1)
        self.assertEqual(em.bootstrap_f1(mixed, rounds=500), (low, high))     # same seed, same answer

    def test_gold_file_uses_known_skills(self):
        subjects = em.load_gold()
        self.assertGreaterEqual(len(subjects), 60)
        self.assertEqual(len({s["name"] for s in subjects}), len(subjects))   # no subject twice

    def test_runs_without_ai(self):
        gold = {"labelled_by": "test", "subjects": [
            {"name": "Database Management Systems", "skills": ["sql"]},
            {"name": "Engineering Physics", "skills": []},
            {"name": "Python Programming", "skills": ["python", "pandas"]}]}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gold.json"
            path.write_text(json.dumps(gold))
            lines = []
            self.assertEqual(em.main(["--no-ai", "--gold", str(path)], out_dir=Path(tmp) / "out", log=lines.append), 0)
            text = (Path(tmp) / "out" / "mapping_eval.md").read_text()
            errors = (Path(tmp) / "out" / "mapping_errors.csv").read_text()
        self.assertIn("| system |", text)
        self.assertIn("| rules |", text)
        self.assertIn("| system, weight >= 0.9 |", text)
        self.assertNotIn("ai only", text)
        self.assertIn("Python Programming,pandas,missed (false negative)", errors)


if __name__ == "__main__":
    unittest.main()
