"""Stage 1.10 (research): how well does the subject -> skill mapping work?

Compares the mapper with a hand-labelled test set (research/gold_subjects.json) and reports, for each
way of mapping:
  named    : skill names written in the subject name / topics (layer 1)
  table    : the curriculum table (layer 2)
  rules    : layers 1 + 2 together
  ai only  : the embedding similarity (layer 3) for every subject
  system   : what the website really does (layers 1 + 2, and layer 3 only when they find nothing)
  system, weight >= 0.6 / 0.9 : the same, keeping only the stronger links (shows the precision / recall trade-off)

Measures (over all (subject, skill) pairs, "micro"):
  precision  = of the skills the mapper gave, how many are right
  recall     = of the right skills, how many the mapper found
  F1         = harmonic mean of the two, with a 95% bootstrap interval (subjects resampled 2000 times)
  empty ok   = of the subjects that teach no job skill, how many the mapper (correctly) left empty
Writes research/results/mapping_eval.md (tables for the project report) and mapping_errors.csv
(every wrong or missing skill, for the error analysis).

Run from the backend/ folder (needs the AI model, like the website):
    python -m research.eval_mapping
    python -m research.eval_mapping --no-ai      # layers 1 and 2 only (fast, no model)
    python -m research.eval_mapping --sweep-ai   # also try other AI similarity cut-offs (choose it on THIS set,
                                                 # then check the choice once on a separate, unseen set)
"""
import argparse
import csv
import json
import random
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from app import embeddings, subject_skills as ss

HERE = Path(__file__).resolve().parent
GOLD_FILE = HERE / "gold_subjects.json"
RESULTS = HERE / "results"
BOOTSTRAP = 2000
SEED = 7
SWEEP = (0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60)   # AI similarity cut-offs tried by --sweep-ai
WEIGHT_CUTS = (0.6, 0.9)        # also score the system keeping only the stronger links (precision vs recall)


@dataclass
class Score:
    tp: int = 0
    fp: int = 0
    fn: int = 0
    empty_total: int = 0
    empty_ok: int = 0

    def add(self, predicted: set, gold: set) -> None:
        self.tp += len(predicted & gold)
        self.fp += len(predicted - gold)
        self.fn += len(gold - predicted)
        if not gold:
            self.empty_total += 1
            self.empty_ok += not predicted

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else 0.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p + r else 0.0


def score(pairs: list[tuple[set, set]]) -> Score:
    s = Score()
    for predicted, gold in pairs:
        s.add(predicted, gold)
    return s


def bootstrap_f1(pairs: list[tuple[set, set]], rounds: int = BOOTSTRAP, seed: int = SEED) -> tuple[float, float]:
    """95% interval of F1 when the test subjects are resampled with replacement."""
    rng = random.Random(seed)
    values = sorted(score([rng.choice(pairs) for _ in pairs]).f1 for _ in range(rounds))
    return values[int(0.025 * rounds)], values[int(0.975 * rounds) - 1]


def load_gold(path: Path = GOLD_FILE) -> list[dict]:
    known = set(ss.SKILLS)
    subjects = json.loads(path.read_text(encoding="utf-8"))["subjects"]
    for s in subjects:
        unknown = [k for k in s["skills"] if k not in known]
        if unknown:
            raise SystemExit(f"{s['name']}: not in shared/skills.json: {unknown}")
    return subjects


def methods(subjects: list[dict], use_ai: bool) -> dict[str, list[set]]:
    """Predicted skills for every subject, for each way of mapping."""
    out: dict[str, list[set]] = {
        "named": [{l.skill for l in ss._named(f"{s['name']} {s.get('topics', '')}")} for s in subjects],
        "table": [{l.skill for l in ss._from_table(s["name"])} for s in subjects],
    }
    out["rules"] = [a | b for a, b in zip(out["named"], out["table"])]
    if use_ai:
        vectors = embeddings.get_embedder().embed([ss.subject_text(s["name"], s.get("topics", "")) for s in subjects])
        out["ai only"] = [{l.skill for l in ss._from_ai(v, set())} for v in vectors]
    mapped = ss.map_subjects(subjects, use_ai=use_ai)
    out["system"] = [{l.skill for l in m.links} for m in mapped]
    for cut in WEIGHT_CUTS:                     # only links at least this strong (0.9 = "mainly about")
        out[f"system, weight >= {cut}"] = [{l.skill for l in m.links if l.weight >= cut} for m in mapped]
    return out


def evaluate(subjects: list[dict], predictions: dict[str, list[set]]) -> list[dict]:
    rows = []
    for name, predicted in predictions.items():
        pairs = [(p, set(s["skills"])) for p, s in zip(predicted, subjects)]
        sc = score(pairs)
        low, high = bootstrap_f1(pairs)
        rows.append({"method": name, "precision": sc.precision, "recall": sc.recall, "f1": sc.f1,
                     "f1_low": low, "f1_high": high, "tp": sc.tp, "fp": sc.fp, "fn": sc.fn,
                     "empty_ok": sc.empty_ok, "empty_total": sc.empty_total,
                     "subjects_with_skills": sum(1 for p in predicted if p)})
    return rows


def errors(subjects: list[dict], predicted: list[set]) -> list[dict]:
    out = []
    for s, p in zip(subjects, predicted):
        gold = set(s["skills"])
        out += [{"subject": s["name"], "skill": k, "error": "wrong (false positive)"} for k in sorted(p - gold)]
        out += [{"subject": s["name"], "skill": k, "error": "missed (false negative)"} for k in sorted(gold - p)]
    return out


def report(rows: list[dict], subjects: list[dict], labelled_by: str) -> str:
    gold_pairs = sum(len(s["skills"]) for s in subjects)
    lines = [
        "# Subject-to-skill mapping: evaluation",
        "",
        f"Test set: {len(subjects)} subjects, {gold_pairs} correct (subject, skill) pairs, "
        f"{sum(1 for s in subjects if not s['skills'])} subjects that teach no listed job skill. "
        f"Labelled by: {labelled_by}.",
        "",
        "| Method | Precision | Recall | F1 (95% CI) | Empty subjects left empty |",
        "|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(f"| {r['method']} | {r['precision']:.2f} | {r['recall']:.2f} | "
                     f"{r['f1']:.2f} ({r['f1_low']:.2f}-{r['f1_high']:.2f}) | {r['empty_ok']}/{r['empty_total']} |")
    lines += ["", "Precision/recall/F1 are micro-averaged over (subject, skill) pairs; the interval is a "
                  f"{BOOTSTRAP}-round bootstrap over subjects (seed {SEED})."]
    return "\n".join(lines) + "\n"


def sweep_ai(subjects: list[dict], cuts=SWEEP) -> str:
    """System F1 for each AI similarity cut-off (the AI layer only runs where the rules found nothing)."""
    gold = [set(s["skills"]) for s in subjects]
    saved = ss.AI_MIN_SIMILARITY
    lines = ["", "## AI similarity cut-off (system)", "",
             "| Cut-off | Precision | Recall | F1 | Empty subjects left empty | Skills added by AI |",
             "|---|---|---|---|---|---|"]
    try:
        for cut in cuts:
            ss.AI_MIN_SIMILARITY = cut
            mapped = ss.map_subjects(subjects, use_ai=True)
            predicted = [{l.skill for l in m.links} for m in mapped]
            sc = score(list(zip(predicted, gold)))
            added = sum(1 for m in mapped for l in m.links if l.source == "ai")
            mark = " (now)" if cut == saved else ""
            lines.append(f"| {cut:.2f}{mark} | {sc.precision:.2f} | {sc.recall:.2f} | {sc.f1:.2f} | "
                         f"{sc.empty_ok}/{sc.empty_total} | {added} |")
    finally:
        ss.AI_MIN_SIMILARITY = saved
    return "\n".join(lines) + "\n"


def main(argv: Optional[list[str]] = None, out_dir: Path = RESULTS, log: Callable[[str], None] = print) -> int:
    parser = argparse.ArgumentParser(description="Evaluate the subject -> skill mapping on the labelled test set.")
    parser.add_argument("--no-ai", action="store_true", help="skip the AI layer (no model needed)")
    parser.add_argument("--gold", type=Path, default=GOLD_FILE)
    parser.add_argument("--sweep-ai", action="store_true", help="also try other AI similarity cut-offs")
    args = parser.parse_args(argv)

    data = json.loads(args.gold.read_text(encoding="utf-8"))
    subjects = load_gold(args.gold)
    predictions = methods(subjects, use_ai=not args.no_ai)
    rows = evaluate(subjects, predictions)
    text = report(rows, subjects, data.get("labelled_by", "unknown"))
    if args.sweep_ai and not args.no_ai:
        text += sweep_ai(subjects)

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "mapping_eval.md").write_text(text, encoding="utf-8")
    with open(out_dir / "mapping_errors.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["subject", "skill", "error"])
        writer.writeheader()
        writer.writerows(errors(subjects, predictions["system"]))
    log(text)
    log(f"Saved {out_dir / 'mapping_eval.md'} and {out_dir / 'mapping_errors.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
