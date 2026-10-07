"""Check government recruitment pages: can we read them, and which notices are current?

Run from the data_pipeline/ folder:
    python check_government_pages.py                 (checks every page in CANDIDATES below)
    python check_government_pages.py https://...     (checks only the pages you give)
Nothing is saved. Pages that work and show current notices can then be added to the daily run.
"""
import sys
import time

from pipeline.collectors import government
from pipeline.normalize import clean_job

# (office, recruitment page, area) - official pages of government offices and institutes in / near Kolkata.
# Some addresses are best guesses: a page that does not exist simply shows an error here.
CANDIDATES = [
    ("Indian Statistical Institute, Kolkata", "https://www.isical.ac.in/jobs", "Kolkata"),
    ("Chittaranjan National Cancer Institute (doctors and faculty)",
     "https://cnci.ac.in/doctors-faculties-positions-1", "Kolkata"),
    ("Chittaranjan National Cancer Institute (nursing and technical)",
     "https://cnci.ac.in/nursing-technical-positions-1", "Kolkata"),
    ("Indian Association for the Cultivation of Science (research associates)",
     "https://www.iacs.res.in/splcareerra.php", "Kolkata"),
    ("Indian Association for the Cultivation of Science (administrative and technical)",
     "https://www.iacs.res.in/splcareerstaff.php", "Kolkata"),
    ("IIEST Shibpur", "https://www.iiests.ac.in/IIEST/Notices/Employment", "Howrah"),
    ("West Bengal Health Recruitment Board", "https://hrb.wb.gov.in/", "Kolkata"),
    # these failed before with old-server HTTPS errors; the new session should read them
    ("West Bengal Police Recruitment Board", "https://prb.wb.gov.in/recruitments", "Kolkata"),
    ("West Bengal Public Service Commission", "https://psc.wb.gov.in/", "Kolkata"),
    ("Calcutta High Court", "https://www.calcuttahighcourt.gov.in/Notice-Files/recruitment", "Kolkata"),
    ("Railway Recruitment Board, Kolkata", "https://www.rrbkolkata.gov.in/", "Kolkata"),
    ("Jadavpur University", "https://jadavpuruniversity.in/", "Kolkata"),
    ("Bose Institute", "https://jcbose.ac.in/recruitment", "Salt Lake"),
]


def check(session, office: str, url: str, area: str) -> None:
    result = government.collect(session, url, office, None, area)
    print(f"\n{office}\n  {url}")
    if not result.complete:
        print(f"  could not read it: {result.error}")
        return
    kept = [c for c in (clean_job(j) for j in result.jobs) if c]
    print(f"  current recruitment notices: {len(result.jobs)} | kept after Kolkata check: {len(kept)}")
    for job in kept[:5]:
        last = next((line for line in job.description.splitlines() if line.startswith("Last date")), "no last date")
        print(f"    - {job.title[:90]} | {last}")


def main(argv: list[str]) -> int:
    pages = [(f"(page {i + 1})", url, "Kolkata") for i, url in enumerate(argv)] if argv else CANDIDATES
    session = government.make_session(retries=False)   # no retries here: a dead page fails fast
    for office, url, area in pages:
        check(session, office, url, area)
        time.sleep(1)
    print("\nNothing was saved. Send this output to decide which pages to add.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
