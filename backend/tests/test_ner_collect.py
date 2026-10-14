"""Tests for collecting India job texts from public job boards (boards are faked, no internet)."""
import json
import unittest

import httpx

from research import ner_collect as nc

LONG = "We build payment systems with Java, Spring Boot and PostgreSQL on AWS. " * 6


def boards_client(seen: list) -> httpx.Client:
    pages = {
        "https://boards-api.greenhouse.io/v1/boards/acme/jobs?content=true": {"jobs": [
            {"id": 1, "title": "Backend Engineer", "location": {"name": "Bengaluru, India"},
             "content": "&lt;p&gt;" + LONG + "&lt;/p&gt;"},
            {"id": 2, "title": "Sales Lead", "location": {"name": "New York, United States"}, "content": LONG},
            {"id": 3, "title": "Intern", "location": {"name": "Pune"}, "content": "short"}]},
        "https://api.lever.co/v0/postings/beta?mode=json": [
            {"id": "L1", "text": "Data Analyst", "categories": {"location": "Kolkata"},
             "descriptionPlain": LONG, "lists": [{"text": "You know", "content": "<li>SQL</li><li>Power BI</li>"}]},
            {"id": "L2", "text": "Designer", "categories": {"location": "Salt Lake City, UT"}, "descriptionPlain": LONG}],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        seen.append(url)
        if url in pages:
            return httpx.Response(200, json=pages[url])
        return httpx.Response(404)
    return httpx.Client(transport=httpx.MockTransport(handler))


class TestCollect(unittest.TestCase):
    def test_in_india(self):
        self.assertTrue(nc.in_india(["Remote - India"]))
        self.assertTrue(nc.in_india(["Gurugram, Haryana"]))
        self.assertFalse(nc.in_india(["Salt Lake City, UT"]))
        self.assertFalse(nc.in_india(["London"]))
        self.assertFalse(nc.in_india([]))

    def test_collect(self):
        seen, have = [], {"lever:beta:L9"}
        new = nc.collect(boards_client(seen), boards=[("Acme", "greenhouse", "acme")],
                         guesses=[("Beta", "beta"), ("Acme again", "acme")], limit=10, have=have, delay=0,
                         log=lambda s: None)
        self.assertEqual([j["id"] for j in new], ["greenhouse:acme:1", "lever:beta:L1"])
        self.assertNotIn("&lt;", new[0]["text"])                          # escaped HTML cleaned
        self.assertIn("Power BI", new[1]["text"])                          # Lever lists included
        self.assertEqual(new[1]["city"], "Kolkata")
        # a guessed company stops at the first platform that answers; known boards are not guessed again
        self.assertEqual(sum(1 for u in seen if "/beta" in u), 2)          # greenhouse (404), then lever
        self.assertEqual(sum(1 for u in seen if "/acme" in u), 1)

    def test_limit_and_no_duplicates(self):
        have = {"greenhouse:acme:1"}
        new = nc.collect(boards_client([]), boards=[("Acme", "greenhouse", "acme")], guesses=[("Beta", "beta")],
                         limit=1, have=have, delay=0, log=lambda s: None)
        self.assertEqual([j["id"] for j in new], ["lever:beta:L1"])         # job 1 was saved before
        self.assertEqual(len(json.dumps(new)) > 0, True)


if __name__ == "__main__":
    unittest.main()
