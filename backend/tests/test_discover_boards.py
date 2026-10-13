"""Tests for discover_boards: keeps only boards with Kolkata jobs, never adds a company twice."""
import csv
import tempfile
import unittest
from pathlib import Path

from scripts import discover_boards
from tests.test_admin_companies import GH_URL, GREENHOUSE, LV_URL, FakeClient, FakeResponse


class TestDiscoverBoards(unittest.TestCase):
    def test_discover_and_add(self):
        routes = {GH_URL.format("abc"): FakeResponse(200, GREENHOUSE), LV_URL.format("abc"): FakeResponse(404),
                  GH_URL.format("far"): FakeResponse(200, {"jobs": [{"title": "X", "location": {"name": "Pune"}}]}),
                  LV_URL.format("far"): FakeResponse(404),
                  GH_URL.format("none"): FakeResponse(404), LV_URL.format("none"): FakeResponse(404)}
        found = discover_boards.discover(FakeClient(routes), [("ABC", "abc"), ("Far Co", "far"), ("None", "none")],
                                         delay=0, log=lambda _: None)
        self.assertEqual([(f["name"], f["ats_platform"], f["kolkata_jobs"]) for f in found],
                         [("ABC", "greenhouse", 2)])                  # Pune-only board and missing board dropped

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "companies.csv"
            path.write_text("name,website,careers_url,ats_platform,ats_token,notes\n", encoding="utf-8")
            self.assertEqual(discover_boards.add_to_csv(found, path), 1)
            self.assertEqual(discover_boards.add_to_csv(found, path), 0)   # run again: no duplicate
            with open(path, newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual([(r["name"], r["ats_platform"], r["ats_token"]) for r in rows],
                             [("ABC", "greenhouse", "abc")])


if __name__ == "__main__":
    unittest.main()
