"""Tests for the syllabus fetcher (college websites are faked; made-up syllabus, no real internet)."""
import os
import unittest
import uuid
from unittest import mock

import httpx

from scripts import fetch_syllabi as fs
from tests.test_syllabus_api import FlatEmbedder, docx
from tests.test_syllabus_parser import SAMPLE

TEST_DB = os.getenv("TEST_DATABASE_URL")
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def fake_site(pages: dict, seen: list = None) -> httpx.Client:
    """pages: url -> (status, content-type, body) or an exception class. Missing robots.txt = 404."""
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if seen is not None:
            seen.append(url)
        target = pages.get(url, (404, "text/plain", b""))
        if isinstance(target, type) and issubclass(target, Exception):
            raise target("fake failure", request=request)
        status, kind, body = target
        headers = {"content-type": kind}
        if 300 <= status < 400:
            headers["location"] = body.decode()
            body = b""
        return httpx.Response(status, headers=headers, content=body)
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)


class TestDownload(unittest.TestCase):
    def test_robots_and_redirects(self):
        robots = (200, "text/plain", b"User-agent: *\nDisallow: /private/\n")
        file = (200, "application/pdf", b"%PDF-1.4 fake")
        client = fake_site({"https://a.edu/robots.txt": robots, "https://a.edu/syl.pdf": file,
                            "https://a.edu/private/syl.pdf": file,
                            "https://a.edu/old.pdf": (301, "", b"/syl.pdf"),
                            "https://a.edu/sneaky.pdf": (302, "", b"/private/syl.pdf"),
                            "https://b.edu/syl.pdf": file})
        r = fs.Robots(client)
        self.assertEqual(fs.download(client, r, "https://a.edu/syl.pdf"), (b"%PDF-1.4 fake", "https://a.edu/syl.pdf"))
        self.assertEqual(fs.download(client, r, "https://a.edu/old.pdf")[1], "https://a.edu/syl.pdf")
        for url in ("https://a.edu/private/syl.pdf", "https://a.edu/sneaky.pdf"):        # redirect checked too
            with self.assertRaises(fs.FetchProblem) as ctx:
                fs.download(client, r, url)
            self.assertEqual(ctx.exception.status, fs.BLOCKED)
        self.assertEqual(fs.download(client, r, "https://b.edu/syl.pdf")[0][:4], b"%PDF")  # no robots.txt = allowed

    def test_problems(self):
        client = fake_site({"https://c.edu/robots.txt": (503, "text/plain", b""),
                            "https://d.edu/page": (200, "text/html; charset=utf-8", b"<html>"),
                            "https://d.edu/gone.pdf": (404, "text/plain", b""),
                            "https://d.edu/loop.pdf": (302, "", b"/loop.pdf"),
                            "https://e.edu/robots.txt": httpx.ConnectError})
        r = fs.Robots(client)
        cases = {"https://c.edu/x.pdf": fs.BLOCKED, "https://e.edu/x.pdf": fs.BLOCKED,   # robots.txt unreachable
                 "https://d.edu/page": fs.ERROR, "https://d.edu/gone.pdf": fs.ERROR, "https://d.edu/loop.pdf": fs.ERROR,
                 "ftp://d.edu/x.pdf": fs.ERROR}
        for url, status in cases.items():
            with self.assertRaises(fs.FetchProblem, msg=url) as ctx:
                fs.download(client, r, url)
            self.assertEqual(ctx.exception.status, status, url)

    def test_size_limit_and_name(self):
        big = (200, "application/pdf", b"x" * 1024)
        client = fake_site({"https://f.edu/big.pdf": big})
        with mock.patch.object(fs.syllabus_parser, "MAX_FILE_BYTES", 100):
            with self.assertRaises(fs.FetchProblem):
                fs.download(client, fs.Robots(client), "https://f.edu/big.pdf")
        self.assertEqual(fs.file_name("https://f.edu/files/CSE%20R22.pdf?v=2"), "CSE R22.pdf")


@unittest.skipUnless(TEST_DB, "set TEST_DATABASE_URL to run database tests")
class TestFetchRun(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg

        from app import embeddings, llm, subject_skills
        cls.patches = [mock.patch.object(llm, "is_configured", lambda: False)]
        for p in cls.patches:
            p.start()
        embeddings.set_embedder(FlatEmbedder())
        subject_skills.clear_cache()
        cls.db = psycopg.connect(TEST_DB, autocommit=True)
        cls.db.execute("delete from public.syllabi")
        cls.db.execute("delete from public.syllabus_sources")
        cls.college = str(cls.db.execute("insert into public.colleges (name, status) values (%s, 'approved') "
                                         "returning id", (f"Fetch Test College {uuid.uuid4().hex[:6]}",)).fetchone()[0])

    @classmethod
    def tearDownClass(cls):
        from app import embeddings
        cls.db.execute("delete from public.colleges where id = %s", (cls.college,))
        cls.db.close()
        embeddings.set_embedder(None)
        for p in cls.patches:
            p.stop()

    def add_source(self, url, **extra):
        return str(self.db.execute(
            """insert into public.syllabus_sources (college_id, url, department, batch, semester, enabled)
               values (%s, %s, %s, %s, %s, %s) returning id""",
            (self.college, url, extra.get("department", "CSE"), extra.get("batch"), extra.get("semester"),
             extra.get("enabled", True))).fetchone()[0])

    def source(self, sid):
        return self.db.execute("select last_status, last_error, last_hash from public.syllabus_sources where id = %s",
                               (sid,)).fetchone()

    def test_run(self):
        file = (200, DOCX, docx(SAMPLE))
        pages = {"https://tc.edu/robots.txt": (200, "text/plain", b"User-agent: *\nDisallow: /exam/\n"),
                 "https://tc.edu/cse.docx": file, "https://tc.edu/copy/cse.docx": file,
                 "https://tc.edu/exam/cse.docx": file, "https://tc.edu/notice": (200, "text/html", b"<html></html>")}
        ok = self.add_source("https://tc.edu/cse.docx", department="CSE (Data Science)", batch="2024-28")
        blocked = self.add_source("https://tc.edu/exam/cse.docx")
        page = self.add_source("https://tc.edu/notice")
        off = self.add_source("https://tc.edu/off.docx", enabled=False)
        seen, waits, lines = [], [], []

        stats = fs.run(self.db, fake_site(pages, seen), allow_ai=False, sleep=waits.append, log=lines.append)
        self.assertEqual((stats.checked, stats.counts), (3, {"new": 1, "unchanged": 0, "blocked": 1, "error": 1}))
        self.assertEqual(waits, [fs.DELAY_SECONDS] * 2)                     # a pause between downloads
        self.assertNotIn("https://tc.edu/off.docx", seen)                  # switched-off links are not read
        self.assertNotIn("https://tc.edu/exam/cse.docx", seen)             # robots.txt says no: never downloaded
        self.assertEqual(seen.count("https://tc.edu/robots.txt"), 1)       # robots.txt read once per website

        row = self.db.execute("""select id::text, source, status, source_url, file_name, department, batch, content_hash,
                                        submitted_by, (select count(*) from public.syllabus_subjects x
                                                       where x.syllabus_id = s.id)
                                 from public.syllabi s where college_id = %s""", (self.college,)).fetchall()
        self.assertEqual(len(row), 1)
        sid, source, status, url, name, dept, batch, digest, by, subjects = row[0]
        self.assertEqual((source, status, url, name, dept, batch, by), ("website", "pending", "https://tc.edu/cse.docx",
                                                                       "cse.docx", "CSE (Data Science)", "2024-28", None))
        self.assertEqual(subjects, 8)
        self.assertEqual(self.source(ok), ("new", None, digest))
        self.assertEqual(self.source(blocked)[0], "blocked")
        self.assertIn("web page", self.source(page)[1])
        self.assertIsNone(self.source(off)[0])

        # Waiting = not used for anyone until the admin approves it
        in_use = self.db.execute("select count(*) from public.syllabi where college_id = %s "
                                 "and status in ('approved', 'unverified')", (self.college,)).fetchone()[0]
        self.assertEqual(in_use, 0)

        # next run: same file -> nothing new; the admin removed it -> the same file under another link stays out
        self.db.execute("update public.syllabi set status = 'rejected' where id = %s", (sid,))
        copy = self.add_source("https://tc.edu/copy/cse.docx")
        stats = fs.run(self.db, fake_site(pages), allow_ai=False, sleep=lambda s: None, log=lines.append)
        self.assertEqual(stats.counts["new"], 0)
        self.assertEqual(self.source(ok)[0], "unchanged")
        self.assertEqual(self.source(copy)[0], "unchanged")
        self.assertIn("status rejected", lines[-1] + " ".join(lines))
        self.assertEqual(self.db.execute("select count(*) from public.syllabi where college_id = %s",
                                         (self.college,)).fetchone()[0], 1)

    def test_unreadable_file(self):
        url = "https://ud.edu/scan.pdf"
        sid = self.add_source(url)
        client = fake_site({url: (200, "application/pdf", b"%PDF-1.4 not really a pdf")})
        stats = fs.run(self.db, client, allow_ai=False, sleep=lambda s: None, log=lambda s: None)
        self.assertGreaterEqual(stats.counts["error"], 1)
        status, error, digest = self.source(sid)
        self.assertEqual((status, digest), ("error", None))                 # tried again next run
        self.assertTrue(error)


if __name__ == "__main__":
    unittest.main()
