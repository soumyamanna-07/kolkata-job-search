"""Check that the pipeline can reach the database and see our tables.

Run from the project root:  python data_pipeline/check_db.py
"""
from pipeline.db import connect

EXPECTED_TABLES = {
    "profiles", "companies", "jobs", "cvs", "saved_jobs", "job_alerts",
    "job_events", "employer_profiles", "job_submissions", "job_reports",
    "job_link_submissions", "pipeline_runs", "admin_actions", "model_versions",
}


def main() -> None:
    with connect() as conn:
        version = conn.execute("show server_version").fetchone()[0]
        print(f"Connected to PostgreSQL {version}")

        rows = conn.execute(
            "select table_name from information_schema.tables "
            "where table_schema = 'public' and table_type = 'BASE TABLE'"
        ).fetchall()
        found = {r[0] for r in rows}
        missing = EXPECTED_TABLES - found
        print(f"Tables found: {len(found & EXPECTED_TABLES)} / {len(EXPECTED_TABLES)}")
        if missing:
            print("MISSING tables:", ", ".join(sorted(missing)))

        jobs = conn.execute("select count(*) from public.jobs").fetchone()[0]
        print(f"Jobs in database: {jobs}")
        print("Database check OK" if not missing else "Database check FAILED")


if __name__ == "__main__":
    main()