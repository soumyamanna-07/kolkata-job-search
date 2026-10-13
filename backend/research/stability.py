"""Stage 1.10 (research): how stable is the gap report when the job data changes a little?

The report is built from a sample of job posts. If a slightly different sample (the same market,
other posts) would give a very different "learn now" list, the advice is noise. This script answers
that with a bootstrap: it resamples the job posts with replacement many times, rebuilds the report
each time (same syllabus, same mapping), and measures how much the results move:

  coverage            : the syllabus' job coverage %, with a 95% interval
  learn now           : for each skill in the real "learn now" list, how often it stays in the list,
                        and the average overlap (Jaccard) between the real list and the resampled ones
  gap ranking         : Spearman rank correlation between the real gap scores and the resampled ones
  trends              : for each skill marked rising / falling, how often the resample agrees

Syllabus used: the generic test-set curriculum (research/gold_subjects.json) by default, or a saved
syllabus with --syllabus <id> (use a public one). Jobs: the live jobs in the database (read only).

Run from the backend/ folder:
    python -m research.stability                 # 200 resamples
    python -m research.stability --rounds 500 --no-ai
"""
import argparse
import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional, Sequence

import psycopg

from app import config, curriculum_gap as cg, subject_skills as ss

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
ROUNDS = 200
SEED = 11
TOP_N = 5                       # the first few "learn now" skills are what students act on

# the same jobs the website's report uses (curriculum_gap.load_market)
JOBS_SQL = """select skills, status = 'open', coalesce(posted_at, first_seen_at), experience_min
              from public.jobs
              where source <> 'adzuna'
                and (status = 'open' or coalesce(posted_at, first_seen_at) >= now() - make_interval(days => %s))"""


def spearman(a: Sequence[float], b: Sequence[float]) -> float:
    """Spearman rank correlation (average ranks for ties)."""
    def ranks(xs):
        order = sorted(range(len(xs)), key=lambda i: xs[i])
        out = [0.0] * len(xs)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
                j += 1
            for k in range(i, j + 1):
                out[order[k]] = (i + j) / 2
            i = j + 1
        return out
    if len(a) < 3:
        return float("nan")
    ra, rb = ranks(a), ranks(b)
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    va, vb = sum((x - ma) ** 2 for x in ra), sum((y - mb) ** 2 for y in rb)
    return cov / (va * vb) ** 0.5 if va and vb else float("nan")


def jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a | b else 1.0


def interval(values: list[float]) -> tuple[float, float]:
    v = sorted(values)
    return v[int(0.025 * len(v))], v[max(0, int(0.975 * len(v)) - 1)]


def run(rows: list[tuple], subjects: list[dict], mapped, field: str = "computing", rounds: int = ROUNDS,
        seed: int = SEED, now: Optional[datetime] = None) -> dict:
    now = now or datetime.now(timezone.utc)
    base = cg.build_report(subjects, mapped, cg.build_market(rows, field, now))
    base_gap = {x["skill"]: x["gap_score"] for x in base["skills"]}
    base_learn = [x["skill"] for x in base["learn_now"]]
    base_top = set(base_learn[:TOP_N])
    base_trend = {x["skill"]: x["trend"] for x in base["skills"] if x["trend"] in ("rising", "falling")}

    rng = random.Random(seed)
    coverage, overlap, top_overlap, rho = [], [], [], []
    stays = {s: 0 for s in base_learn}
    trend_same = {s: 0 for s in base_trend}
    for _ in range(rounds):
        sample = [rng.choice(rows) for _ in rows]
        rep = cg.build_report(subjects, mapped, cg.build_market(sample, field, now))
        coverage.append(rep["summary"]["coverage"])
        learn = [x["skill"] for x in rep["learn_now"]]
        overlap.append(jaccard(set(base_learn), set(learn)))
        top_overlap.append(jaccard(base_top, set(learn[:TOP_N])))
        for s in base_learn:
            stays[s] += s in learn
        gap = {x["skill"]: x["gap_score"] for x in rep["skills"]}
        both = [s for s in base_gap if s in gap]
        r = spearman([base_gap[s] for s in both], [gap[s] for s in both])
        if r == r:                                             # not NaN
            rho.append(r)
        trends = {x["skill"]: x["trend"] for x in rep["skills"]}
        for s, t in base_trend.items():
            trend_same[s] += trends.get(s) == t
    return {
        "jobs": base["market"]["jobs"], "rounds": rounds, "seed": seed,
        "coverage": base["summary"]["coverage"], "coverage_ci": interval(coverage),
        "learn_now": [(s, stays[s] / rounds) for s in base_learn],
        "learn_now_jaccard": sum(overlap) / rounds, "top_jaccard": sum(top_overlap) / rounds,
        "spearman_mean": sum(rho) / len(rho) if rho else float("nan"),
        "spearman_low": interval(rho)[0] if rho else float("nan"),
        "trends": [(s, t, trend_same[s] / rounds) for s, t in base_trend.items()],
    }


def report(r: dict, what: str) -> str:
    lines = [
        "# Gap report: stability under resampling of job posts",
        "",
        f"Syllabus: {what}. Jobs: {r['jobs']} open computing jobs; {r['rounds']} bootstrap resamples "
        f"(seed {r['seed']}).",
        "",
        "| Measure | Result |",
        "|---|---|",
        f"| Job coverage of the syllabus | {r['coverage']:.1f}% (95% interval {r['coverage_ci'][0]:.1f}-"
        f"{r['coverage_ci'][1]:.1f}%) |",
        f"| \"Learn now\" list overlap with the real list (Jaccard, mean) | {r['learn_now_jaccard']:.2f} |",
        f"| Top {TOP_N} \"learn now\" overlap (Jaccard, mean) | {r['top_jaccard']:.2f} |",
        f"| Gap ranking agreement (Spearman rho, mean; 2.5th percentile) | {r['spearman_mean']:.2f}; "
        f"{r['spearman_low']:.2f} |",
        "",
        "## How often each \"learn now\" skill stays in the list",
        "",
        "| Rank | Skill | Kept in resamples |",
        "|---|---|---|",
    ]
    lines += [f"| {i} | {s} | {100 * p:.0f}% |" for i, (s, p) in enumerate(r["learn_now"], 1)]
    if r["trends"]:
        lines += ["", "## Trend labels", "", "| Skill | Trend | Same label in resamples |", "|---|---|---|"]
        lines += [f"| {s} | {t} | {100 * p:.0f}% |" for s, t, p in r["trends"]]
    else:
        lines += ["", "No skill has a significant rising / falling trend in the real data."]
    return "\n".join(lines) + "\n"


def gold_curriculum() -> list[dict]:
    data = json.loads((HERE / "gold_subjects.json").read_text(encoding="utf-8"))
    return [{"name": s["name"], "topics": s.get("topics", ""), "semester": None,
             "kind": "lab" if " lab" in s["name"].lower() else "theory"} for s in data["subjects"]]


def saved_syllabus(conn: psycopg.Connection, syllabus_id: str) -> list[dict]:
    rows = conn.execute("""select name, semester, kind, options, coalesce(topics, '') from public.syllabus_subjects
                           where syllabus_id = %s order by position""", (syllabus_id,)).fetchall()
    if not rows:
        raise SystemExit(f"No subjects for syllabus {syllabus_id}")
    return [{"name": n, "semester": sem, "kind": k, "options": list(o or []), "topics": t} for n, sem, k, o, t in rows]


def main(argv: Optional[list[str]] = None, out_dir: Path = RESULTS, log: Callable[[str], None] = print) -> int:
    parser = argparse.ArgumentParser(description="Bootstrap stability of the curriculum gap report.")
    parser.add_argument("--rounds", type=int, default=ROUNDS)
    parser.add_argument("--syllabus", help="id of a saved (public) syllabus; default: the generic test curriculum")
    parser.add_argument("--no-ai", action="store_true", help="map subjects without the AI layer")
    args = parser.parse_args(argv)
    if not config.DATABASE_URL:
        log("DATABASE_URL is not set in .env")
        return 1
    with psycopg.connect(config.DATABASE_URL) as conn:
        rows = conn.execute(JOBS_SQL, (cg.OLDER_DAYS,)).fetchall()
        subjects = saved_syllabus(conn, args.syllabus) if args.syllabus else gold_curriculum()
    mapped = ss.map_subjects(subjects, use_ai=not args.no_ai)
    result = run(rows, subjects, mapped, rounds=args.rounds)
    what = f"saved syllabus {args.syllabus}" if args.syllabus else f"generic test curriculum ({len(subjects)} subjects)"
    text = report(result, what)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "stability.md").write_text(text, encoding="utf-8")
    log(text)
    log(f"Saved {out_dir / 'stability.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
