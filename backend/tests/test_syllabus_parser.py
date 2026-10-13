"""Syllabus reader: semesters, split subject codes, names, labs, projects, electives, topics, AI fallback.

The text below is MADE UP in the messy style of university syllabus PDFs (codes split across lines,
names wrapping, hours on separate lines). No real college syllabus is stored in the tests.
"""
import io
import json
import unittest
import zipfile
from unittest import mock

from app import llm, syllabus_parser as sp

SAMPLE = """
Example Technical University, Kolkata
Syllabus for B. Tech in Computer Science (Data Science)
(Applicable from the academic session 2024-2025)
Curriculum Structure
First Year First Semester
Sl No. Category Subject Code Subject Name L T P Credits
Theory
1 Basic Science
Course
BS-MA101 Calculus and
Linear Algebra 3 1 0 4
2 Engineering
Science Courses
ES-
CS101
Programming in C
3
0
0
3
Total Theory 6 1 0 7
Practical
1 Engineering Science ES-CS191 Programming in C Laboratory 0 0 4 2
Total credit for First Semester 9
Semester IV (Second year)
1 THEORY Professional Core
Course
PCCDS40
1
Database Management
Systems
3 0 0 3
2 Professional
Elective
PECDS 402
(A/B/C)
Cloud Computing /Web
Technologies/
Graph Theory 3 0 0 3
3 Humanities HSMC 403 Project Management and Finance 2 0 0 2
4 PRACTICAL Professional Core PCCDS49 1 Database Lab 0 0 4 2
5th Semester
1 Project PROJDS
L581 Project I 0 0 12 6
TOTAL CREDITS 30

Detailed syllabus
Course Code: PCCDS401   Course Name: Database Management Systems
Module 1: Introduction to databases, data models, the relational model and relational algebra in detail.
Module 2: SQL queries, joins, views, stored procedures and triggers, with many worked examples for practice.
Module 3: Normalisation (1NF to BCNF), functional dependencies, transactions, concurrency control and recovery.
Module 4: Indexing with B+ trees and hashing, query processing and optimisation, NoSQL databases like MongoDB.
"""


def by_code(parsed):
    return {s.code: s for s in parsed.subjects}


class TestRules(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parsed = sp.read_with_rules(SAMPLE)
        cls.subjects = by_code(cls.parsed)

    def test_finds_every_subject_once(self):
        self.assertEqual(list(self.subjects), ["BS-MA101", "ES-CS101", "ES-CS191", "PCCDS401", "PECDS402",
                                               "HSMC403", "PCCDS491", "PROJDSL581"])

    def test_semesters(self):
        self.assertEqual([s.semester for s in self.parsed.subjects], [1, 1, 1, 4, 4, 4, 4, 5])

    def test_names_and_credits_from_split_lines(self):
        s = self.subjects
        self.assertEqual((s["BS-MA101"].name, s["BS-MA101"].credits), ("Calculus and Linear Algebra", 4.0))
        self.assertEqual((s["ES-CS101"].name, s["ES-CS101"].credits), ("Programming in C", 3.0))
        self.assertEqual(s["PCCDS401"].name, "Database Management Systems")

    def test_kinds(self):
        s = self.subjects
        self.assertEqual([s[c].kind for c in ("ES-CS191", "PCCDS491", "PROJDSL581", "HSMC403", "PCCDS401")],
                         ["lab", "lab", "project", "theory", "theory"])   # "Project Management" is a theory subject

    def test_elective_with_choices(self):
        e = self.subjects["PECDS402"]
        self.assertTrue(e.is_elective)
        self.assertEqual(e.options, ["Cloud Computing", "Web Technologies", "Graph Theory"])   # "Theory" kept
        self.assertFalse(self.subjects["PCCDS401"].is_elective)

    def test_topics_from_detailed_part(self):
        topics = self.subjects["PCCDS401"].topics
        self.assertIn("Module 2: SQL queries", topics)
        self.assertEqual(self.subjects["BS-MA101"].topics, "")

    def test_university_department_batch(self):
        p = self.parsed
        self.assertEqual((p.university, p.department, p.batch),
                         ("Example Technical University", "Computer Science (Data Science)", "2024-2025"))


class FakeHttp:
    def __init__(self, content):
        self.content = content

    def post(self, *args, **kwargs):
        return mock.Mock(status_code=200, json=lambda: {"choices": [{"message": {"content": self.content}}]})


class TestAiFallback(unittest.TestCase):
    def tearDown(self):
        llm.set_client(None)

    def test_unusual_layout_goes_to_ai(self):
        reply = json.dumps({"department": "ECE", "batch": "2023-27", "subjects": [
            {"semester": 3, "code": "EC301", "name": "Signals and Systems", "kind": "theory", "credits": 4},
            {"semester": 3, "code": None, "name": "Circuits Lab", "kind": "lab", "credits": 2},
            {"semester": 11, "name": "Elective", "kind": "weird", "is_elective": True, "options": ["VLSI", "IoT"]},
            {"name": ""}]})
        llm.set_client(FakeHttp("Here you go:\n" + reply))
        text = "Semester three subjects: Signals and Systems, Circuits Lab and one elective. " * 3
        with mock.patch.object(llm, "is_configured", return_value=True):
            parsed = sp.read_syllabus(text)
        self.assertEqual(parsed.method, "ai")
        self.assertEqual([s.name for s in parsed.subjects], ["Signals and Systems", "Circuits Lab", "Elective"])
        last = parsed.subjects[2]
        self.assertEqual((last.semester, last.kind, last.options), (None, "theory", ["VLSI", "IoT"]))
        self.assertEqual((parsed.department, parsed.batch), ("ECE", "2023-27"))

    def test_rules_are_enough_no_ai_call(self):
        with mock.patch.object(llm, "chat") as chat, mock.patch.object(llm, "is_configured", return_value=True):
            self.assertEqual(sp.read_syllabus(SAMPLE).method, "rules")
        chat.assert_not_called()

    def test_ai_not_set_up_keeps_rules_result(self):
        with mock.patch.object(llm, "is_configured", return_value=False):
            self.assertEqual(sp.read_syllabus("hello " * 50).subjects, [])


class TestFiles(unittest.TestCase):
    def test_bad_files(self):
        for data, message in ((b"", "empty"), (b"hello world", "PDF or Word"), (b"x" * (11 * 1024 * 1024), "10 MB")):
            with self.assertRaises(sp.SyllabusError) as ctx:
                sp.extract_text(data)
            self.assertIn(message, str(ctx.exception))

    def test_word_file(self):
        body = "".join(f"<w:p><w:r><w:t>{line}</w:t></w:r></w:p>" for line in SAMPLE.splitlines())
        xml = ('<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/'
               f'main"><w:body>{body}</w:body></w:document>').replace("&", "&amp;")
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as z:
            z.writestr("word/document.xml", xml)
        text = sp.extract_text(buffer.getvalue())
        self.assertEqual(len(sp.read_with_rules(text).subjects), 8)


if __name__ == "__main__":
    unittest.main()
