"""Tests for the CV parser, using small PDF and DOCX files built in memory."""
import io
import unittest
import zipfile
from datetime import date

from app.cv_parser import CVError, extract_text, parse_cv

TODAY = date(2026, 10, 2)

STUDENT_CV = """Soumya Test
test@example.com | +91 90000 00000 | Kolkata

Summary
Final year B.Tech CSE (AI & ML) student who enjoys building data products.

Education
B.Tech in Computer Science, Techno Main Salt Lake    2023 - 2027
Higher Secondary (12th), WBCHSE                        2021 - 2023

Experience
ML Intern, Euphoria GenX                               May 2026 - Aug 2026
Built a fertilizer recommendation model with Python, scikit-learn and Pandas.

Skills
Python, SQL, Machine Learning, FastAPI, Git, Power BI
"""

EXPERIENCED_CV = """Riya Sen

Professional Experience
Senior Data Analyst | ABC Bank | Jan 2022 - Present
Data Analyst | XYZ Retail | Jun 2019 - Mar 2022
Built Tableau dashboards; advanced Excel; SQL Server.

Education
MBA, IIM Calcutta
"""


def make_pdf(text: str, password: str = "") -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4, encrypt=password or None)
    y = 800
    for line in text.splitlines():
        c.drawString(40, y, line)
        y -= 16
    c.save()
    return buf.getvalue()


def make_docx(text: str, extra_xml: bytes = b"") -> bytes:
    paras = "".join(f'<w:p><w:r><w:t xml:space="preserve">{line}</w:t></w:r></w:p>'
                    for line in text.replace("&", "&amp;").splitlines())
    xml = (b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' + extra_xml +
           b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>' +
           paras.encode() + b"</w:body></w:document>")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", xml)
    return buf.getvalue()


class TestStudentCV(unittest.TestCase):
    def check(self, cv):
        for skill in ["python", "sql", "machine learning", "fastapi", "git", "power bi", "scikit-learn", "pandas"]:
            self.assertIn(skill, cv.skills)
        self.assertEqual(cv.education, "B.Tech / B.E.")
        # only the internship counts (May-Aug 2026 = 4 months), NOT college years 2023-2027
        self.assertEqual(cv.experience_years, 0.3)
        self.assertEqual(cv.job_titles, ["ML Intern"])

    def test_pdf(self):
        cv = parse_cv(make_pdf(STUDENT_CV), today=TODAY)
        self.assertEqual(cv.file_type, "application/pdf")
        self.check(cv)

    def test_docx(self):
        self.check(parse_cv(make_docx(STUDENT_CV), today=TODAY))


class TestExperiencedCV(unittest.TestCase):
    def test_overlapping_jobs_counted_once(self):
        cv = parse_cv(make_pdf(EXPERIENCED_CV), today=TODAY)
        # Jun 2019 -> Oct 2026 (present) = 89 months, overlap Jan-Mar 2022 not double counted
        self.assertEqual(cv.experience_years, 7.4)
        self.assertEqual(cv.education, "MBA")
        self.assertEqual(cv.job_titles, ["Senior Data Analyst", "Data Analyst"])
        for skill in ["tableau", "excel", "sql server"]:
            self.assertIn(skill, cv.skills)

    def test_stated_years_when_no_dates(self):
        text = "Summary\nAccountant with 5 years of experience in Tally and GST filing.\n" + "x " * 30
        cv = parse_cv(make_docx(text), today=TODAY)
        self.assertEqual(cv.experience_years, 5.0)
        self.assertIn("tally", cv.skills)

    def test_fresher_without_experience_section(self):
        text = "Education\nBCA, St. Xavier's College Kolkata 2022 - 2025\nSkills\nJava, HTML, CSS\n" + "x " * 30
        cv = parse_cv(make_docx(text), today=TODAY)
        self.assertEqual(cv.experience_years, 0.0)
        self.assertEqual(cv.education, "BCA")


class TestFormats(unittest.TestCase):
    def test_dashes_bullets_and_numeric_dates(self):
        from app.cv_parser import extract_experience, extract_job_titles, split_sections
        text = ("Experience\nData Analyst \u2022 ABC Ltd \u2013 Jan 2024 \u2014 Dec 2024\n"
                "Intern | XYZ | 06/2023 \u2013 08/2023\n")
        sections = split_sections(text)
        self.assertEqual(extract_experience(sections, TODAY), 1.2)      # 12 + 3 months
        self.assertEqual(extract_job_titles(sections), ["Data Analyst", "Intern"])


class TestTitleCleanup(unittest.TestCase):
    def test_location_and_mode_removed(self):
        from app.cv_parser import extract_job_titles, split_sections
        text = ("Experience\n"
                "AI & ML Engineer / Data Analysis Intern Chennai (Hybrid)   Sep 2026 - Present\n"
                "Machine Learning Intern Salt Lake Sector V, Kolkata   May 2026 - Aug 2026\n"
                "Worked with the senior engineer team on data cleaning and model training.\n")
        self.assertEqual(extract_job_titles(split_sections(text)),
                         ["AI & ML Engineer / Data Analysis Intern", "Machine Learning Intern"])

    def test_latex_pdf_dash(self):
        from app.cv_parser import extract_experience, split_sections
        text = ("Experience\n"
                "Ramakrishna Mission Vivekananda Educational and Research Institute Aug. 2026 \x15 Present\n"
                "Euphoria GenX May 2026 \x15 Aug. 2026\n")
        # May 2026 -> Oct 2026 (present), the Aug overlap counted once = 6 months
        self.assertEqual(extract_experience(split_sections(text), TODAY), 0.5)


class TestBadFiles(unittest.TestCase):
    def assert_cv_error(self, data, words):
        with self.assertRaises(CVError) as e:
            extract_text(data)
        self.assertIn(words, str(e.exception))

    def test_rejections(self):
        self.assert_cv_error(b"", "empty")
        self.assert_cv_error(b"\x89PNG\r\n\x1a\n" + b"0" * 100, "PDF or Word")
        self.assert_cv_error(b"%PDF-" + b"0" * (5 * 1024 * 1024), "larger than 5 MB")
        self.assert_cv_error(make_pdf("Hi"), "No text found")                       # e.g. scanned image
        self.assert_cv_error(b"%PDF-1.4 broken file", "could not be read")
        self.assert_cv_error(make_pdf(STUDENT_CV, password="secret"), "password-protected")

    def test_xml_attack_blocked(self):
        evil = b'<!DOCTYPE lolz [<!ENTITY lol "lol">]>'
        self.assert_cv_error(make_docx(STUDENT_CV, extra_xml=evil), "could not be read")

    def test_other_zip_is_not_a_cv(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("hello.txt", "hi")
        self.assert_cv_error(buf.getvalue(), "PDF or Word")


if __name__ == "__main__":
    unittest.main()
