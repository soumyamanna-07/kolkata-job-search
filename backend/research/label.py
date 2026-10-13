"""Stage 1.10: label the held-out test set one subject at a time, in the terminal.

Shows each subject that has no label yet and asks which job skills it really teaches. It never shows
what the website maps the subject to, so your labels stay independent. Every answer is saved at once,
so you can stop with q and carry on later.

    python -m research.label                      # research/heldout_subjects.json
Answers:  sql, python   -> those skills (names from shared/skills.json)
          Enter         -> teaches no listed job skill
          ?  word       -> list skill names containing the word (e.g. "? data")
          b             -> go back one subject       q -> stop (saved)
"""
import argparse
import json
import sys
from pathlib import Path
from typing import Callable, Optional

from app.subject_skills import SKILLS

DEFAULT_FILE = Path(__file__).resolve().parent / "heldout_subjects.json"
DONE_LABEL = "project author (checked)"


def parse(answer: str, known: set) -> tuple[Optional[list[str]], list[str]]:
    """(skills, unknown names). Matching ignores upper / lower case."""
    lower = {k.lower(): k for k in known}
    skills, unknown = [], []
    for part in answer.split(","):
        name = " ".join(part.split()).lower()
        if not name:
            continue
        if name in lower:
            if lower[name] not in skills:
                skills.append(lower[name])
        else:
            unknown.append(part.strip())
    return skills, unknown


def save(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=1, ensure_ascii=True) + "\n", encoding="ascii")


def run(path: Path, ask: Callable[[str], str] = input, say: Callable[[str], None] = print) -> int:
    data = json.loads(path.read_text(encoding="utf-8"))
    subjects, known = data["subjects"], set(SKILLS)
    order = [i for i, s in enumerate(subjects) if s.get("skills") is None]
    say(f"{len(order)} of {len(subjects)} subjects still to label. Enter = no job skill, ? word = search, "
        "b = back, q = stop.")
    pos = 0
    while pos < len(order):
        i = order[pos]
        answer = ask(f"[{pos + 1}/{len(order)}] {subjects[i]['name']}: ").strip()
        if answer.lower() == "q":
            break
        if answer.lower() == "b":
            if pos:
                pos -= 1
                subjects[order[pos]]["skills"] = None
                save(path, data)
            continue
        if answer.startswith("?"):
            word = answer[1:].strip().lower()
            say(", ".join(sorted(k for k in known if word in k)) or "no skill name contains that")
            continue
        skills, unknown = parse(answer, known)
        if unknown:
            say(f"Not a skill name: {', '.join(unknown)}. Use ? word to search.")
            continue
        subjects[i]["skills"] = skills
        save(path, data)
        pos += 1
    left = sum(1 for s in subjects if s.get("skills") is None)
    if left == 0:
        data["labelled_by"] = DONE_LABEL
        save(path, data)
        say("All subjects labelled. Now run: python -m research.eval_mapping --gold research/heldout_subjects.json")
    else:
        say(f"Saved. {left} subjects left; run python -m research.label again to carry on.")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Label a test set subject by subject.")
    parser.add_argument("file", nargs="?", type=Path, default=DEFAULT_FILE)
    args = parser.parse_args(argv)
    return run(args.file)


if __name__ == "__main__":
    sys.exit(main())
