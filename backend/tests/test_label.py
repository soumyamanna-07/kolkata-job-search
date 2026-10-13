"""Tests for the terminal labelling helper (Stage 1.10)."""
import json
import tempfile
import unittest
from pathlib import Path

from research import label


def fake_file(tmp: str) -> Path:
    path = Path(tmp) / "set.json"
    path.write_text(json.dumps({"labelled_by": "project author (not labelled yet)", "subjects": [
        {"name": "Physics-I", "skills": None}, {"name": "Database Management Systems", "skills": None},
        {"name": "Python Programming", "skills": None}]}))
    return path


class TestLabel(unittest.TestCase):
    def test_parse(self):
        known = {"sql", "python", "machine learning"}
        self.assertEqual(label.parse(" SQL ,  Machine   Learning,sql", known), (["sql", "machine learning"], []))
        self.assertEqual(label.parse("", known), ([], []))
        self.assertEqual(label.parse("sql, mongo", known), (["sql"], ["mongo"]))

    def test_full_run_with_back_search_and_typo(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = fake_file(tmp)
            answers = iter(["", "? sq", "sqll", "sql", "b", "sql, mysql", "python"])
            said = []
            label.run(path, ask=lambda _: next(answers), say=said.append)
            data = json.loads(path.read_text())
        self.assertEqual([s["skills"] for s in data["subjects"]], [[], ["sql", "mysql"], ["python"]])
        self.assertEqual(data["labelled_by"], label.DONE_LABEL)
        self.assertTrue(any("sql" in line and "mysql" in line for line in said))     # search result
        self.assertTrue(any("Not a skill name: sqll" in line for line in said))

    def test_stop_and_carry_on(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = fake_file(tmp)
            first = iter(["", "q"])
            label.run(path, ask=lambda _: next(first), say=lambda _: None)
            data = json.loads(path.read_text())
            self.assertEqual([s["skills"] for s in data["subjects"]], [[], None, None])
            self.assertIn("not labelled yet", data["labelled_by"])
            asked = []
            answers = iter(["sql", "python"])
            label.run(path, ask=lambda q: (asked.append(q), next(answers))[1], say=lambda _: None)
            self.assertTrue(asked[0].startswith("[1/2] Database"))                   # starts where it stopped


if __name__ == "__main__":
    unittest.main()
