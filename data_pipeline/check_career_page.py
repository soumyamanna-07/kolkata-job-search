"""Check one company careers page: does it have Google-Jobs tags, and how many Kolkata jobs?

Run from the project root:
    python data_pipeline/check_career_page.py https://careers.example.com/jobs
If it finds Kolkata jobs, add the company in the Admin Company List (ats_platform "other",
careers_url = this link) or in data_pipeline/companies.csv, and the daily run will read it.
"""
import sys

from pipeline.collectors import career_page
from pipeline.collectors.base import make_session
from pipeline.normalize import clean_job


def main(argv: list[str]) -> int:
    if len(argv) != 1 or not argv[0].startswith(("http://", "https://")):
        print("Usage: python data_pipeline/check_career_page.py https://company.com/careers")
        return 2
    result = career_page.collect(make_session(), argv[0], "(company)", None)
    if not result.complete:
        print(f"Could not read it: {result.error}")
        return 1
    kolkata = [c for c in (clean_job(j) for j in result.jobs) if c]
    print(f"Pages read: {result.requests_made} | jobs with Google-Jobs tags: {len(result.jobs)} | "
          f"current Kolkata jobs: {len(kolkata)}")
    for job in kolkata[:10]:
        print(f"  - {job.title} | {job.company_name} | {job.area} | {job.apply_url}")
    if not result.jobs:
        print("No JobPosting tags found: this site can't be read automatically (yet).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
