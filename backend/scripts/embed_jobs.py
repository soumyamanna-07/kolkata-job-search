"""Give every OPEN job an AI embedding (only new jobs or jobs whose text changed).

Run from the backend/ folder:
    python -m scripts.embed_jobs --dry-run     # only count what needs doing
    python -m scripts.embed_jobs               # do it
Run it again after each pipeline run; already-embedded jobs are skipped.
"""
import argparse
import sys
import time
from typing import Callable, Optional

import psycopg

from app import config
from app.embeddings import Embedder, get_embedder, job_text, text_hash, to_pgvector


def find_jobs_to_embed(conn: psycopg.Connection, limit: Optional[int] = None) -> tuple[int, list[tuple]]:
    """Return (number of open jobs, [(job_id, text, hash), ...] that need a new embedding)."""
    rows = conn.execute(
        "select id, title, skills, description, embedding_hash from public.jobs "
        "where status = 'open' order by first_seen_at desc").fetchall()
    todo = []
    for job_id, title, skills, description, old_hash in rows:
        text = job_text(title, skills or [], description)
        new_hash = text_hash(text)
        if new_hash != old_hash:
            todo.append((job_id, text, new_hash))
    return len(rows), todo[:limit] if limit else todo


def embed_jobs(conn: psycopg.Connection, embedder: Embedder, todo: list[tuple], batch_size: int = 64,
               log: Callable[[str], None] = print) -> int:
    done = 0
    started = time.monotonic()
    for start in range(0, len(todo), batch_size):
        batch = todo[start:start + batch_size]
        vectors = embedder.embed([text for _, text, _ in batch])
        with conn.transaction(), conn.cursor() as cur:
            cur.executemany(
                "update public.jobs set embedding = %s::extensions.vector, embedding_hash = %s where id = %s",
                [(to_pgvector(vec), new_hash, job_id) for (job_id, _, new_hash), vec in zip(batch, vectors)])
        done += len(batch)
        log(f"  embedded {done}/{len(todo)}  ({time.monotonic() - started:.0f}s)")
    return done


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Create AI embeddings for open jobs.")
    parser.add_argument("--dry-run", action="store_true", help="only count, change nothing")
    parser.add_argument("--limit", type=int, default=None, help="embed at most this many jobs")
    parser.add_argument("--batch-size", type=int, default=64)
    args = parser.parse_args(argv)

    if not config.DATABASE_URL:
        print("DATABASE_URL is not set in .env", file=sys.stderr)
        return 1
    with psycopg.connect(config.DATABASE_URL, autocommit=True) as conn:
        total, todo = find_jobs_to_embed(conn, args.limit)
        print(f"open jobs: {total}   need embedding: {len(todo)}")
        if args.dry_run or not todo:
            return 0
        print("loading model (first time downloads ~90 MB)...")
        done = embed_jobs(conn, get_embedder(), todo, args.batch_size)
        missing = conn.execute(
            "select count(*) from public.jobs where status = 'open' and embedding is null").fetchone()[0]
        print(f"done: {done} jobs embedded. open jobs still without embedding: {missing}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
