"""Stage 1.10: make the held-out test set from a syllabus in the database (e.g. one the fetcher read).

Writes research/heldout_subjects.json with every subject name (each elective choice on its own line)
and "skills": null. You fill in the skills BY HAND, without looking at what the website maps them to,
then run the evaluation ONCE:
    python -m research.eval_mapping --gold research/heldout_subjects.json
No more changes to the mapper after that run: this number is the fair accuracy for the report.

Only subject names are exported (no file text). Use a PUBLIC syllabus (e.g. MAKAUT's), not a student's.

Run from the backend/ folder:
    python -m research.export_heldout <syllabus id>
"""
import argparse
import json
import sys
from pathlib import Path
from typing import Optional

import psycopg

from app import config
from app.subject_skills import clean_name

OUT_FILE = Path(__file__).resolve().parent / "heldout_subjects.json"
SKIP_KINDS = ("project", "other")          # projects, internships, seminars: no subject content to label


def subject_names(conn: psycopg.Connection, syllabus_id: str) -> tuple[dict, list[str]]:
    meta = conn.execute("""select c.name, s.department, s.source, s.source_url from public.syllabi s
                           join public.colleges c on c.id = s.college_id where s.id = %s""", (syllabus_id,)).fetchone()
    if meta is None:
        raise SystemExit(f"No syllabus with id {syllabus_id}")
    rows = conn.execute("""select name, options from public.syllabus_subjects
                           where syllabus_id = %s and kind <> all(%s) order by position""",
                        (syllabus_id, list(SKIP_KINDS))).fetchall()
    names: list[str] = []
    for name, options in rows:
        choices = [o for o in (options or []) if o and o.strip()]
        for n in (choices if len(choices) > 1 else [name]):
            n = clean_name(n)
            if len(n) >= 3 and n.lower() not in {x.lower() for x in names}:
                names.append(n)
    info = {"college": meta[0], "department": meta[1], "source": meta[2], "source_url": meta[3]}
    return info, names


def main(argv: Optional[list[str]] = None, out_file: Path = OUT_FILE, db_url: Optional[str] = None) -> int:
    parser = argparse.ArgumentParser(description="Export subject names of a syllabus as an unlabelled test set.")
    parser.add_argument("syllabus_id")
    parser.add_argument("--force", action="store_true", help="overwrite an existing file (your labels are lost)")
    args = parser.parse_args(argv)
    if out_file.exists() and not args.force:
        print(f"{out_file} already exists; use --force to overwrite it (your labels would be lost)", file=sys.stderr)
        return 1
    db_url = db_url or config.DATABASE_URL
    if not db_url:
        print("DATABASE_URL is not set in .env", file=sys.stderr)
        return 1
    with psycopg.connect(db_url) as conn:
        info, names = subject_names(conn, args.syllabus_id)
    data = {
        "_comment": "Held-out test set for Stage 1.10. Fill in 'skills' for every subject by hand (names from "
                    "shared/skills.json; [] = teaches no listed job skill) WITHOUT looking at the website's mapping. "
                    "Then evaluate once; do not change the mapper after that.",
        "labelled_by": "project author (not labelled yet)",
        "from": f"{info['department']} syllabus ({info['source']}{', ' + info['source_url'] if info['source_url'] else ''})",
        "subjects": [{"name": n, "skills": None} for n in names],
    }
    out_file.write_text(json.dumps(data, indent=1, ensure_ascii=True) + "\n", encoding="ascii")
    print(f"Saved {len(names)} subjects to {out_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
