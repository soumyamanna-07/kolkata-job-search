"""Run the data pipeline: collect -> Kolkata filter -> clean -> de-duplicate -> save -> close.

Only CURRENT jobs are kept open: posted in the last 30 days (see normalize.MAX_JOB_AGE_DAYS).

Run from the project root:
    python data_pipeline/run_pipeline.py --dry-run     (collect and show results, write nothing)
    python data_pipeline/run_pipeline.py               (full run, writes to the database)

Options:
    --sources lever,greenhouse,ashby,workable,career_page,adzuna,jooble,careerjet   only run these
    --adzuna-mode recent|full           recent = new jobs only (daily), full = all jobs + closing (weekly)
    --trigger schedule|manual           recorded in pipeline_runs (GitHub Actions uses schedule)
"""
import argparse
import sys
import time
import traceback

from pipeline import config, store
from pipeline.collectors import adzuna, ashby, career_page, careerjet, greenhouse, jooble, lever, workable
from pipeline.collectors.base import CollectResult, make_session
from pipeline.db import connect
from pipeline.normalize import clean_job, deduplicate

ALL_SOURCES = ("greenhouse", "lever", "ashby", "workable", "career_page", "adzuna", "jooble", "careerjet")
# company job boards: platform name -> collector
BOARD_COLLECTORS = {"greenhouse": greenhouse, "lever": lever, "ashby": ashby, "workable": workable}
DELAY_BETWEEN_COMPANIES = 0.5   # seconds - be polite to job boards


def log(message: str) -> None:
    print(message, flush=True)


def collect_all(companies: list[dict], sources: set[str], adzuna_mode: str = "recent",
                career_pages: list[dict] = ()) -> list[CollectResult]:
    session = make_session()
    results = []
    for company in companies:
        platform = company["ats_platform"]
        if platform not in sources:
            continue
        module = BOARD_COLLECTORS[platform]
        r = module.collect(session, company["ats_token"], company["name"], company["id"])
        results.append(r)
        log(f"  {r.scope:<40} {len(r.jobs):>5} jobs  {'OK' if r.complete else 'FAILED: ' + (r.error or '')}")
        time.sleep(DELAY_BETWEEN_COMPANIES)
    if "career_page" in sources:
        for company in career_pages:
            r = career_page.collect(session, company["careers_url"], company["name"], company["id"])
            results.append(r)
            log(f"  {r.scope:<40} {len(r.jobs):>5} jobs  {'OK' if r.complete else 'FAILED: ' + (r.error or '')}")
            time.sleep(DELAY_BETWEEN_COMPANIES)
    if "adzuna" in sources:
        r = adzuna.collect(session, config.ADZUNA_APP_ID, config.ADZUNA_APP_KEY, adzuna_mode)
        results.append(r)
        log(f"  {r.scope:<40} {len(r.jobs):>5} jobs  {'OK' if r.complete else 'SKIPPED/FAILED: ' + (r.error or '')}"
            f"  ({r.requests_made} API calls)")
    # aggregators that need a free key: skipped quietly until the key is in .env
    aggregators = (
        ("jooble", config.JOOBLE_API_KEY, lambda: jooble.collect(session, config.JOOBLE_API_KEY)),
        ("careerjet", config.CAREERJET_API_KEY,
         lambda: careerjet.collect(session, config.CAREERJET_API_KEY, config.CAREERJET_USER_IP)),
    )
    for name, key, run in aggregators:
        if name not in sources:
            continue
        if not key:
            log(f"  {name:<40}     -  skipped (no API key in .env yet)")
            continue
        r = run()
        results.append(r)
        log(f"  {r.scope:<40} {len(r.jobs):>5} jobs  {'OK' if r.complete else 'FAILED: ' + (r.error or '')}"
            f"  ({r.requests_made} API calls)")
    return results


def process(results: list[CollectResult]):
    raw_jobs = [job for r in results for job in r.jobs]
    cleaned = [c for c in (clean_job(j) for j in raw_jobs) if c is not None]
    unique = deduplicate(cleaned)
    source_stats = {
        r.scope: {"ok": r.complete, "jobs": len(r.jobs), "requests": r.requests_made,
                  **({"error": r.error} if r.error else {})}
        for r in results
    }
    stats = {"total_collected": len(raw_jobs), "kolkata_count": len(cleaned),
             "unique_count": len(unique), "source_stats": source_stats}
    return unique, stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Kolkata job data pipeline")
    parser.add_argument("--dry-run", action="store_true", help="collect and clean only, write nothing")
    parser.add_argument("--sources", default=",".join(ALL_SOURCES))
    parser.add_argument("--adzuna-mode", choices=adzuna.MODES, default="recent")
    parser.add_argument("--trigger", choices=("manual", "schedule"), default="manual")
    args = parser.parse_args()
    sources = {s.strip() for s in args.sources.split(",") if s.strip()}
    unknown = sources - set(ALL_SOURCES)
    if unknown:
        log(f"Unknown source(s): {', '.join(sorted(unknown))}. Choose from: {', '.join(ALL_SOURCES)}")
        return 2

    with connect() as conn:
        conn.autocommit = True
        companies = store.load_companies(conn)
        pages = store.load_career_pages(conn)
        log(f"Companies with a job board: {len(companies)} | with a careers page to read: {len(pages)}")

        run_id = started_at = None
        if not args.dry_run:
            run_id, started_at = store.start_run(conn, args.trigger)
            log(f"Pipeline run #{run_id} started")

        try:
            log("Collecting:")
            results = collect_all(companies, sources, args.adzuna_mode, pages)
            jobs, stats = process(results)
            log(f"Total collected: {stats['total_collected']} -> Kolkata: {stats['kolkata_count']} "
                f"-> Unique: {stats['unique_count']}")

            if args.dry_run:
                for job in jobs[:5]:
                    salary = f"Rs {job.salary_min:,}-{job.salary_max or 0:,}" if job.salary_min else "Not disclosed"
                    log(f"  - {job.title} | {job.company_name} | {job.area} | {salary} | "
                        f"skills: {', '.join(job.skills[:6]) or '-'}")
                log("Dry run: nothing was written to the database.")
                return 0

            with conn.transaction():
                stats["jobs_new"], stats["jobs_updated"] = store.save_jobs(conn, jobs)
                stats["jobs_closed"], warnings = store.close_missing(conn, results, started_at)
                expired = store.close_expired(conn)          # older than 30 days = not current
                stats["jobs_closed"] += expired
            log(f"Closed because older than {store.MAX_JOB_AGE_DAYS} days: {expired}")
            for w in warnings:
                log(f"WARNING: {w}")

            failed = [r.scope for r in results if not r.complete]
            status = "success" if not failed else ("partial" if len(failed) < len(results) else "failed")
            store.finish_run(conn, run_id, status, stats, "; ".join(warnings) or None)
            log(f"New: {stats['jobs_new']} | Updated: {stats['jobs_updated']} | "
                f"Closed: {stats['jobs_closed']} | Status: {status}")
            return 0 if status != "failed" else 1

        except Exception as error:  # record the failure, then re-raise so CI shows it
            if run_id is not None:
                store.finish_run(conn, run_id, "failed", {},
                                 f"{type(error).__name__}: {error}\n{traceback.format_exc()}")
            raise


if __name__ == "__main__":
    sys.exit(main())
