"""Tests for exporting a held-out test set from a saved syllabus (made-up syllabus)."""
import json
import os
import tempfile
import unittest
import uuid
from pathlib import Path

from research import export_heldout as ex

TEST_DB = os.getenv("TEST_DATABASE_URL")


@unittest.skipUnless(TEST_DB, "set TEST_DATABASE_URL to run database tests")
class TestExport(unittest.TestCase):
    def test_export(self):
        import psycopg
        db = psycopg.connect(TEST_DB, autocommit=True)
        college = db.execute("insert into public.colleges (name, status) values (%s, 'approved') returning id",
                             (f"Export Test {uuid.uuid4().hex[:6]}",)).fetchone()[0]
        try:
            sid = str(db.execute("""insert into public.syllabi (college_id, department, source, status, source_url)
                                    values (%s, 'IT', 'website', 'pending', 'https://example.edu/it.pdf')
                                    returning id""", (college,)).fetchone()[0])
            rows = [("Compiler Design", "theory", []), ("Compiler Design Lab", "lab", []),
                    ("Professional Elective-I", "theory", ["Cloud Computing", "Graph Theory"]),
                    ("Major Project", "project", []), ("compiler design", "theory", [])]
            for i, (name, kind, options) in enumerate(rows):
                db.execute("""insert into public.syllabus_subjects (syllabus_id, name, kind, options, is_elective, position)
                              values (%s, %s, %s, %s, %s, %s)""", (sid, name, kind, options, bool(options), i))
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / "heldout.json"
                self.assertEqual(ex.main([sid], out_file=out, db_url=TEST_DB), 0)
                data = json.loads(out.read_text())
                self.assertEqual(ex.main([sid], out_file=out, db_url=TEST_DB), 1)      # never overwrites labels
            self.assertEqual([s["name"] for s in data["subjects"]],
                             ["Compiler Design", "Compiler Design Lab", "Cloud Computing", "Graph Theory"])
            self.assertTrue(all(s["skills"] is None for s in data["subjects"]))
            self.assertIn("https://example.edu/it.pdf", data["from"])
        finally:
            db.execute("delete from public.colleges where id = %s", (college,))
            db.close()


if __name__ == "__main__":
    unittest.main()
