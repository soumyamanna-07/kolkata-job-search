"""One command to refresh the jobs: collect (pipeline) -> close old ones -> embed new ones.

Run from the backend/ folder:
    python -m scripts.update_jobs                    # daily: new Adzuna jobs only (few API calls)
    python -m scripts.update_jobs --adzuna-mode full # weekly: all Adzuna jobs, closes removed ones
    python -m scripts.update_jobs --embed-only       # skip collecting, just embed what is missing

The embedding step always runs, even if collecting partly failed, so every open job
in the database can be found by "Best for You" and "Ask AI".
"""
import argparse
import subprocess
import sys
from pathlib import Path
from typing import Optional

from scripts import embed_jobs

ROOT_DIR = Path(__file__).resolve().parents[2]
PIPELINE = ROOT_DIR / "data_pipeline" / "run_pipeline.py"


def run_pipeline(adzuna_mode: str, trigger: str) -> int:
    print(f"== 1/2 Collecting jobs (Adzuna mode: {adzuna_mode}) ==", flush=True)
    return subprocess.run([sys.executable, str(PIPELINE), "--adzuna-mode", adzuna_mode, "--trigger", trigger],
                          cwd=ROOT_DIR).returncode


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Collect new Kolkata jobs, then embed them for AI matching.")
    parser.add_argument("--adzuna-mode", choices=("recent", "full"), default="recent")
    parser.add_argument("--trigger", choices=("manual", "schedule"), default="manual")
    parser.add_argument("--embed-only", action="store_true", help="skip collecting")
    args = parser.parse_args(argv)

    pipeline_code = 0
    if not args.embed_only:
        pipeline_code = run_pipeline(args.adzuna_mode, args.trigger)
        if pipeline_code != 0:
            print(f"WARNING: collecting ended with code {pipeline_code}; embedding the jobs we have anyway.",
                  flush=True)

    print("== 2/2 Embedding new or changed jobs ==", flush=True)
    embed_code = embed_jobs.main([])
    return pipeline_code or embed_code


if __name__ == "__main__":
    sys.exit(main())
