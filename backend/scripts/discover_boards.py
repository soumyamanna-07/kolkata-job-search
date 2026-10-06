"""Find companies whose Greenhouse / Lever / Ashby / Workable job boards list Kolkata jobs right now.

Tries each candidate board code on both platforms, keeps only boards that answer AND
have at least one job in Kolkata / Salt Lake / New Town / Howrah, and adds them to
data_pipeline/companies.csv (rows already there are not added twice).

Run from the backend/ folder:
    python -m scripts.discover_boards --dry-run    # only show what it finds
    python -m scripts.discover_boards              # also add them to companies.csv
Then load them:  cd .. ; python data_pipeline/seed_companies.py
"""
import argparse
import csv
import sys
import time
from pathlib import Path
from typing import Callable, Optional

from app import companies

CSV_PATH = Path(__file__).resolve().parents[2] / "data_pipeline" / "companies.csv"
CSV_COLUMNS = ["name", "website", "careers_url", "ats_platform", "ats_token", "notes"]
DELAY_SECONDS = 0.4                   # be polite to the job boards

# (company name, board code) - India-hiring companies that are known or likely to use
# one of these platforms. The script checks each one; wrong guesses are simply skipped.
CANDIDATES = [
    ("PhonePe", "phonepe"), ("Postman", "postman"), ("BrowserStack", "browserstack"), ("Groww", "groww"),
    ("Razorpay", "razorpay"), ("Dream Sports", "dreamsports"), ("InMobi", "inmobi"), ("Zeta", "zeta"),
    ("Druva", "druva"), ("Hasura", "hasura"), ("Atlan", "atlan"), ("Sprinklr", "sprinklr"),
    ("Innovaccer", "innovaccer"), ("Chargebee", "chargebee"), ("Whatfix", "whatfix"), ("CRED", "cred"),
    ("Meesho", "meesho"), ("Urban Company", "urbancompany"), ("upGrad", "upgrad"), ("Unacademy", "unacademy"),
    ("Vedantu", "vedantu"), ("Physics Wallah", "physicswallah"), ("Lenskart", "lenskart"),
    ("PharmEasy", "pharmeasy"), ("Practo", "practo"), ("Rapido", "rapido"), ("CARS24", "cars24"),
    ("Spinny", "spinny"), ("Jupiter", "jupiter"), ("Slice", "slice"), ("Navi", "navi"), ("ShareChat", "sharechat"),
    ("Delhivery", "delhivery"), ("Rebel Foods", "rebelfoods"), ("Zepto", "zepto"), ("Licious", "licious"),
    ("BharatPe", "bharatpe"), ("OYO", "oyo"), ("Paytm", "paytm"), ("Games24x7", "games24x7"),
    ("Simplilearn", "simplilearn"), ("Khatabook", "khatabook"), ("Nykaa", "nykaa"), ("Udaan", "udaan"),
    ("OfBusiness", "ofbusiness"), ("MoEngage", "moengage"), ("CleverTap", "clevertap"), ("Gupshup", "gupshup"),
    ("Haptik", "haptik"), ("Yellow.ai", "yellowai"), ("Uniphore", "uniphore"), ("Mindtickle", "mindtickle"),
    ("Darwinbox", "darwinbox"), ("LeadSquared", "leadsquared"), ("Exotel", "exotel"), ("Kissflow", "kissflow"),
    ("Capillary Technologies", "capillarytech"), ("Purplle", "purplle"), ("Honasa Consumer", "honasa"),
    ("Cult.fit", "curefit"), ("HealthifyMe", "healthifyme"), ("Classplus", "classplus"), ("Ixigo", "ixigo"),
    ("Turing", "turing"), ("Toptal", "toptal"), ("Grant Thornton Bharat", "grantthorntonbharat"),
    ("Swiggy", "swiggy"), ("Zomato", "zomato"), ("Ola", "ola"), ("Acko", "acko"), ("Zetwerk", "zetwerk"),
    ("Pine Labs", "pinelabs"), ("Freshworks", "freshworks"), ("Juspay", "juspay"), ("Fyle", "fyle"),
]


def existing_tokens(path: Path = CSV_PATH) -> set[tuple[str, str]]:
    if not path.exists():
        return set()
    with open(path, newline="", encoding="utf-8-sig") as f:
        return {((r.get("ats_platform") or "").strip(), (r.get("ats_token") or "").strip().lower())
                for r in csv.DictReader(f)}


def discover(client, candidates=CANDIDATES, delay: float = DELAY_SECONDS,
             log: Callable[[str], None] = print) -> list[dict]:
    """Boards that answer and list at least one Kolkata job."""
    found = []
    for name, token in candidates:
        for platform in companies.COLLECTED_PLATFORMS:
            result = companies.check_board(client, platform, token)
            if delay:
                time.sleep(delay)
            if result.ok:
                log(f"  {name:<24} {platform:<10} {result.jobs:>4} jobs, Kolkata: {result.kolkata_jobs}")
                if result.kolkata_jobs:
                    found.append({"name": name, "ats_platform": platform, "ats_token": token,
                                  "kolkata_jobs": result.kolkata_jobs, "examples": result.sample_titles[:3]})
    return found


def add_to_csv(found: list[dict], path: Path = CSV_PATH) -> int:
    have = existing_tokens(path)
    new = [f for f in found if (f["ats_platform"], f["ats_token"].lower()) not in have]
    if not new:
        return 0
    write_header = not path.exists() or path.stat().st_size == 0
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        if write_header:
            writer.writeheader()
        for row in new:
            writer.writerow({"name": row["name"], "website": "", "careers_url": "", "ats_platform": row["ats_platform"],
                             "ats_token": row["ats_token"],
                             "notes": f"found by discover_boards: {row['kolkata_jobs']} Kolkata jobs"})
    return len(new)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Find company job boards that list Kolkata jobs.")
    parser.add_argument("--dry-run", action="store_true", help="only show, do not change companies.csv")
    args = parser.parse_args(argv)
    print(f"Checking {len(CANDIDATES)} companies on {', '.join(companies.COLLECTED_PLATFORMS)} "
          "(boards that exist are listed)...")
    with companies.make_client() as client:
        found = discover(client)
    print(f"\nBoards with Kolkata jobs: {len(found)}")
    for f in found:
        print(f"  {f['name']} ({f['ats_platform']}:{f['ats_token']}) - {f['kolkata_jobs']} Kolkata jobs, "
              f"e.g. {'; '.join(f['examples'])}")
    if args.dry_run:
        print("Dry run: companies.csv not changed.")
    else:
        print(f"Added to {CSV_PATH.name}: {add_to_csv(found)} new companies")
    return 0


if __name__ == "__main__":
    sys.exit(main())
