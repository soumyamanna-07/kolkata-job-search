"""Skill detection, using the SAME vocabulary as the data pipeline (shared/skills.json),
so skills found in a CV line up exactly with skills tagged on jobs."""
import json
import re
from pathlib import Path

SKILLS_FILE = Path(__file__).resolve().parents[2] / "shared" / "skills.json"
SKILLS: dict[str, list[str]] = json.loads(SKILLS_FILE.read_text(encoding="utf-8"))["skills"]


def _compile() -> list[tuple[str, re.Pattern]]:
    patterns = []
    for skill, aliases in SKILLS.items():
        parts = sorted({re.escape(a.lower()) for a in aliases}, key=len, reverse=True)
        patterns.append((skill, re.compile(rf"(?<![a-z0-9])(?:{'|'.join(parts)})(?![a-z0-9+#])")))
    return patterns


_PATTERNS = _compile()


def extract_skills(text: str) -> list[str]:
    """Canonical skill names found in the text, sorted."""
    lower = (text or "").lower()
    return sorted(skill for skill, pattern in _PATTERNS if pattern.search(lower))


def known_skill(name: str) -> bool:
    return name.lower() in SKILLS
