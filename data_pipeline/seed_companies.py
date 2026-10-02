"""Add or update Kolkata companies from data_pipeline/companies.csv.

Run from the project root:  python data_pipeline/seed_companies.py

CSV columns: name, website, careers_url, ats_platform, ats_token, notes
  ats_platform: greenhouse | lever | ashby | smartrecruiters | workable |
                zoho_recruit | freshteam | keka | darwinbox | other
  ats_token:    the company's code on that platform (see docs in README)
Running it again is safe: existing companies are updated, not duplicated.
"""
import csv
from pathlib import Path

from pipeline.db import connect
from pipeline.normalize import normalize_company

CSV_PATH = Path(__file__).resolve().parent / "companies.csv"
PLATFORMS = {"greenhouse", "lever", "ashby", "smartrecruiters", "workable",
             "zoho_recruit", "freshteam", "keka", "darwinbox", "other"}

UPSERT_SQL = """
insert into public.companies (name, normalized_name, website, careers_url, ats_platform, ats_token, notes)
values (%s, %s, %s, %s, %s, %s, %s)
on conflict (normalized_name) do update set
    name = excluded.name, website = excluded.website, careers_url = excluded.careers_url,
    ats_platform = excluded.ats_platform, ats_token = excluded.ats_token,
    notes = excluded.notes, is_active = true
returning (xmax = 0) as inserted
"""


def main() -> None:
    with open(CSV_PATH, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        print(f"No companies in {CSV_PATH.name} yet - add rows below the header line.")
        return

    added = updated = skipped = 0
    with connect() as conn:
        for line_no, row in enumerate(rows, start=2):
            name = (row.get("name") or "").strip()
            platform = (row.get("ats_platform") or "other").strip().lower()
            token = (row.get("ats_token") or "").strip() or None
            if not name or platform not in PLATFORMS:
                print(f"  line {line_no}: skipped (missing name or unknown platform '{platform}')")
                skipped += 1
                continue
            inserted = conn.execute(UPSERT_SQL, (
                name, normalize_company(name),
                (row.get("website") or "").strip() or None,
                (row.get("careers_url") or "").strip() or None,
                platform, token, (row.get("notes") or "").strip() or None,
            )).fetchone()[0]
            added += inserted
            updated += not inserted
    print(f"Companies added: {added} | updated: {updated} | skipped: {skipped}")


if __name__ == "__main__":
    main()
