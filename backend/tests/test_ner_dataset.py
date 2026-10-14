"""Tests for building the skill NER dataset (made-up job texts, fake LLM, no internet)."""
import json
import os
import tempfile
import unittest
import uuid
from pathlib import Path

from app import llm
from research import ner_dataset as nd

TEST_DB = os.getenv("TEST_DATABASE_URL")
JOB = {"id": "j1", "title": "Data Analyst",
       "text": "We need SQL and Python. Experience with MS-Excel, Power BI and SQL Server. Team player."}


def fake_chat(reply: str):
    return lambda messages, **kw: reply


class TestHelpers(unittest.TestCase):
    def test_clean(self):
        self.assertEqual(nd.clean("<p>Hello&nbsp;<b>World</b></p><ul><li>SQL</li><li>Java</li></ul>"),
                         "Hello World\nSQL\nJava")
        self.assertEqual(nd.clean(None), "")

    def test_spans(self):
        text = "Java, JavaScript and java"
        self.assertEqual(nd.spans(text, "Java"), [[0, 4]])                 # exact case, whole word only
        self.assertEqual(nd.spans(text, "JAVA"), [[0, 4], [21, 25]])        # no exact match: any case
        self.assertEqual(nd.spans("C++ and C#", "C++"), [[0, 3]])
        self.assertEqual(nd.spans(text, "  "), [])

    def test_parse_reply(self):
        self.assertEqual(nd.parse_reply('Here: {"skills": [{"text": " ReactJS ", "skill": "React"}, {"text": ""}]}'),
                         [{"text": "ReactJS", "skill": "react"}])
        with self.assertRaises(ValueError):
            nd.parse_reply("sorry")


class TestLabel(unittest.TestCase):
    def test_label_one(self):
        reply = json.dumps({"skills": [{"text": "SQL", "skill": "sql"}, {"text": "Python", "skill": "python"},
                                       {"text": "MS-Excel", "skill": "excel"}, {"text": "SQL Server", "skill": "sql server"},
                                       {"text": "Tableau", "skill": "tableau"}]})
        r = nd.label_one(JOB, fake_chat(reply))
        self.assertEqual([e["text"] for e in r["entities"]], ["SQL", "Python", "MS-Excel", "SQL Server"])
        for e in r["entities"]:
            self.assertEqual(JOB["text"][e["start"]:e["end"]], e["text"])
        self.assertEqual(r["not_in_text"], ["Tableau"])                     # invented: dropped
        # "SQL" inside "SQL Server" is not kept twice: the longer span wins
        self.assertEqual(sum(1 for e in r["entities"] if e["skill"] == "sql"), 1)

    def test_label_all_resumes_and_skips_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs, silver = Path(tmp) / "jobs.jsonl", Path(tmp) / "silver.jsonl"
            jobs.write_text("".join(json.dumps({**JOB, "id": f"j{i}"}) + "\n" for i in range(3)))
            calls = []

            def flaky(messages, **kw):
                calls.append(1)
                if len(calls) == 2:
                    raise llm.LLMError("busy")
                return '{"skills": [{"text": "Python", "skill": "python"}]}'

            nd.label_all(flaky, pause=0, log=lambda s: None, jobs_file=jobs, silver_file=silver)
            self.assertEqual([r["id"] for r in nd.read_jsonl(silver)], ["j0", "j2"])
            nd.label_all(flaky, pause=0, log=lambda s: None, jobs_file=jobs, silver_file=silver)
            self.assertEqual(sorted(r["id"] for r in nd.read_jsonl(silver)), ["j0", "j1", "j2"])
            self.assertEqual(len(calls), 4)                                  # done jobs are not asked again

    def test_stops_when_everything_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs, silver = Path(tmp) / "jobs.jsonl", Path(tmp) / "silver.jsonl"
            jobs.write_text("".join(json.dumps({**JOB, "id": f"j{i}"}) + "\n" for i in range(8)))

            def down(messages, **kw):
                raise llm.LLMError("no key")

            self.assertEqual(nd.label_all(down, pause=0, log=lambda s: None, jobs_file=jobs, silver_file=silver), 1)


@unittest.skipUnless(TEST_DB, "set TEST_DATABASE_URL to run database tests")
class TestSample(unittest.TestCase):
    def test_sample_only_allowed_sources(self):
        import psycopg
        db = psycopg.connect(TEST_DB, autocommit=True)
        tag = uuid.uuid4().hex[:8]
        long_text = "<p>" + "Build APIs with Python and SQL. " * 20 + "</p>"
        try:
            for source, text in (("greenhouse", long_text), ("adzuna", long_text), ("lever", "too short"),
                                 ("career_page", long_text)):
                db.execute("""insert into public.jobs (job_key, source, company_name, title, description, apply_url)
                              values (%s, %s, 'Acme', 'Developer', %s, 'https://example.com/j')""",
                           (f"{tag}-{source}", source, text))
            jobs = [j for j in nd.sample_jobs(db, 100) if j["title"] == "Developer"]
            self.assertEqual(len(jobs), 2)                                    # adzuna and the short one left out
            self.assertTrue(all("<p>" not in j["text"] for j in jobs))
            self.assertEqual(nd.sample_jobs(db, 100), nd.sample_jobs(db, 100))  # same seed, same sample
        finally:
            db.execute("delete from public.jobs where job_key like %s", (f"{tag}-%",))
            db.close()


if __name__ == "__main__":
    unittest.main()
