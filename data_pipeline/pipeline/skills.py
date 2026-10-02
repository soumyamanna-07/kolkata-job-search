"""Skill vocabulary used to tag jobs.

The list itself lives in shared/skills.json so the backend (CV reader) and the
pipeline (job tagger) always use exactly the same skills.
Each entry: canonical skill name -> list of ways it is written in job posts.
Matching is case-insensitive and on whole words, so "java" does not match
"javascript". Ambiguous words (e.g. "go", "r") are only matched in safe forms.
"""
import json
from pathlib import Path

SKILLS_FILE = Path(__file__).resolve().parents[2] / "shared" / "skills.json"

SKILLS: dict[str, list[str]] = json.loads(SKILLS_FILE.read_text(encoding="utf-8"))["skills"]
