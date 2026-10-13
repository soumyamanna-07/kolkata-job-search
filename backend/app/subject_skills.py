"""Link college subjects to the job skills employers ask for (Stage 1.3).

Each subject gets a list of skills from the SAME vocabulary jobs are tagged with (shared/skills.json),
so a subject can be compared directly with live Kolkata job demand. Three layers, strongest first:

  1. named      - the skill is written in the subject name or its topics ("Python Programming" -> python)
  2. curriculum - a hand-made table of common B.Tech subjects ("Database Management Systems" -> sql, mysql ...)
  3. ai         - sentence-embedding similarity (all-MiniLM-L6-v2) between the subject and each skill,
                  for subjects the first two layers do not know. Only close matches are kept.

Every link has a weight 0..1 (how strongly the subject teaches that skill) and its source,
so the gap report can show WHY a subject was linked to a skill.
For an elective ("Cloud Computing / Pattern Recognition / ..."), each choice is linked on its own and the
link names its choice in `option`, because a student studies only ONE of them.
"""
import math
import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Optional

from . import embeddings
from .skills import SKILLS, extract_skills

AI_MIN_SIMILARITY = 0.50       # below this, the subject and the skill are not really about the same thing
AI_MAX_SKILLS = 3              # the AI layer adds at most this many skills per subject
AI_MAX_WEIGHT = 0.6            # AI links are never trusted as much as named or table links

# skills that say nothing about a subject's content (languages, generic soft skills)
NOT_FROM_AI = {"english", "bengali", "hindi", "communication", "customer service", "sales"}


@dataclass
class SkillLink:
    skill: str
    weight: float
    source: str            # named / curriculum / ai
    option: Optional[str] = None     # for an elective: the choice that teaches it (None = every student)

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------- cleaning subject names
_FOOTNOTE = re.compile(r"[*#\u2020\u2021]+")
_GROUP = re.compile(r"\(\s*gr(?:oup)?\.?\s*-?\s*[a-z]\s*(?:\)|$)", re.I)    # "(Gr-A)", also cut off "(Gr-A"
_SPACES = re.compile(r"\s+")
_LAB_WORDS = re.compile(r"\b(laboratory|lab|practical|sessional|workshop)\b", re.I)
_PART = re.compile(r"\s*-?\s*\b(?:i{1,3}|iv|v|vi{0,3})[a-d]?\b\s*$", re.I)     # "-I", "IA", "II"


def clean_name(name: str) -> str:
    """Remove footnote marks and group labels: 'Mathematics -IA*' -> 'Mathematics - IA',
    'Physics-I (Gr-A)' -> 'Physics-I'."""
    text = _GROUP.sub(" ", _FOOTNOTE.sub(" ", name or ""))
    text = re.sub(r"\s+-\s*", " - ", text)
    text = re.sub(r"\(\s*\)", " ", text)
    return _SPACES.sub(" ", text).strip(" -,;:/&")


def base_name(name: str) -> str:
    """The subject without 'Laboratory' or the part number, lower case, used to look it up:
    'Physics-I Laboratory (Gr-A)' -> 'physics'."""
    text = _LAB_WORDS.sub(" ", clean_name(name))
    text = _SPACES.sub(" ", text).strip(" -,;:/&")
    for _ in range(2):
        text = _PART.sub("", text).strip(" -,;:/&")
    return text.lower()


# ---------------------------------------------------------------- layer 2: the curriculum table
# (pattern on the base name, [(skill, weight)]). Weight 0.9 = the subject is mainly about the skill,
# 0.6 = the subject teaches a good part of it, 0.4 = it gives the background for it.
CURRICULUM: list[tuple[str, list[tuple[str, float]]]] = [
    (r"programming for problem solving|\bc programming\b|computer programming",
     [("c", 0.9)]),
    (r"object oriented|\boops?\b",
     [("java", 0.6), ("c++", 0.6)]),
    (r"data structures?",
     [("c", 0.4), ("c++", 0.4), ("python", 0.4)]),
    (r"database|dbms|rdbms",
     [("sql", 0.9), ("mysql", 0.6), ("postgresql", 0.4), ("oracle", 0.4)]),
    (r"data ?warehous|data mining",
     [("etl", 0.6), ("sql", 0.6), ("data analysis", 0.6)]),
    (r"web (technolog|development|programming|design)|internet technolog",
     [("html", 0.9), ("css", 0.9), ("javascript", 0.6), ("php", 0.4), ("rest api", 0.4)]),
    (r"software engineering",
     [("agile", 0.6), ("git", 0.4), ("manual testing", 0.4), ("project management", 0.4), ("jira", 0.4)]),
    (r"software testing|quality assurance",
     [("manual testing", 0.9), ("automation testing", 0.6), ("selenium", 0.4)]),
    (r"operating systems?",
     [("linux", 0.6), ("bash", 0.4)]),
    (r"unix|linux|shell programming",
     [("linux", 0.9), ("bash", 0.6)]),
    (r"computer networks?",
     [("linux", 0.4)]),
    (r"cloud computing",
     [("aws", 0.6), ("azure", 0.6), ("gcp", 0.4), ("docker", 0.4), ("kubernetes", 0.4)]),
    (r"devops",
     [("devops", 0.9), ("docker", 0.6), ("ci/cd", 0.6), ("git", 0.6), ("jenkins", 0.4)]),
    (r"big data",
     [("hadoop", 0.9), ("spark", 0.6), ("kafka", 0.4)]),
    (r"artificial intelligence",
     [("machine learning", 0.6), ("python", 0.4)]),
    (r"machine learning|pattern recognition",
     [("machine learning", 0.9), ("python", 0.6), ("scikit-learn", 0.6), ("statistics", 0.4)]),
    (r"deep learning|neural networks?|soft computing",
     [("deep learning", 0.9), ("python", 0.4), ("tensorflow", 0.4), ("pytorch", 0.4)]),
    (r"natural language|\bnlp\b|text mining",
     [("nlp", 0.9), ("python", 0.4)]),
    (r"image processing|computer vision",
     [("computer vision", 0.9), ("python", 0.4)]),
    (r"generative ai|large language",
     [("generative ai", 0.9), ("llm", 0.9)]),
    (r"data (science|analytics)|business analytics",
     [("data analysis", 0.9), ("python", 0.6), ("pandas", 0.6), ("statistics", 0.6), ("data visualization", 0.4)]),
    (r"data visuali[sz]ation",
     [("data visualization", 0.9), ("tableau", 0.4), ("power bi", 0.4)]),
    (r"probability|statistic",
     [("statistics", 0.9), ("data analysis", 0.4)]),
    (r"numerical (methods|analysis)|scientific computing",
     [("matlab", 0.4), ("python", 0.4)]),
    (r"mobile (application|app|computing)|android",
     [("android", 0.6), ("kotlin", 0.4), ("flutter", 0.4)]),
    (r"python",
     [("python", 0.9)]),
    (r"java\b",
     [("java", 0.9)]),
    (r"principles of management|industrial management|engineering management|management for engineers|project management|entrepreneurship",
     [("project management", 0.4)]),
    (r"economics|accountancy|accounting|financial",
     [("financial analysis", 0.4), ("accounting", 0.4)]),
    (r"english|professional communication|communication skills|technical writing|soft skill",
     [("english", 0.6), ("communication", 0.6)]),
    (r"engineering graphics|engineering drawing|computer aided design",
     [("autocad", 0.6)]),
]
_CURRICULUM = [(re.compile(p, re.I), links) for p, links in CURRICULUM]


def _named(text: str) -> list[SkillLink]:
    return [SkillLink(skill, 1.0, "named") for skill in extract_skills(text)]


def _from_table(name: str) -> list[SkillLink]:
    key = base_name(name)
    found: dict[str, float] = {}
    for pattern, links in _CURRICULUM:
        if pattern.search(key):
            for skill, weight in links:
                found[skill] = max(found.get(skill, 0.0), weight)
    return [SkillLink(s, w, "curriculum") for s, w in found.items()]


def _merge(*groups: Sequence[SkillLink]) -> list[SkillLink]:
    """Keep the strongest link for each skill; strongest first."""
    best: dict[str, SkillLink] = {}
    for group in groups:
        for link in group:
            if link.skill not in best or link.weight > best[link.skill].weight:
                best[link.skill] = link
    return sorted(best.values(), key=lambda l: (-l.weight, l.skill))


# ---------------------------------------------------------------- layer 3: AI similarity
def subject_text(name: str, topics: str = "") -> str:
    """The text that is embedded for a subject (also stored as syllabus_subjects.embedding)."""
    text = f"College subject: {clean_name(name)}"
    topics = _SPACES.sub(" ", topics or "").strip()
    if topics:
        text += ". Topics: " + topics[:800]
    return text


def skill_text(skill: str) -> str:
    aliases = [a for a in SKILLS[skill] if a.lower() != skill][:5]
    return f"Job skill: {skill}" + (f" ({', '.join(aliases)})" if aliases else "")


_skill_vectors: Optional[tuple[list[str], list[list[float]]]] = None


def _skill_matrix() -> tuple[list[str], list[list[float]]]:
    """Embeddings of every skill, made once per process (124 short texts)."""
    global _skill_vectors
    if _skill_vectors is None:
        names = [s for s in SKILLS if s not in NOT_FROM_AI]
        _skill_vectors = (names, embeddings.get_embedder().embed([skill_text(s) for s in names]))
    return _skill_vectors


def clear_cache() -> None:
    global _skill_vectors
    _skill_vectors = None


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


def _from_ai(vector: Sequence[float], known: set[str]) -> list[SkillLink]:
    names, vectors = _skill_matrix()
    scored = sorted(((_cosine(vector, v), s) for s, v in zip(names, vectors) if s not in known), reverse=True)
    return [SkillLink(s, round(min(AI_MAX_WEIGHT, sim), 2), "ai")
            for sim, s in scored[:AI_MAX_SKILLS] if sim >= AI_MIN_SIMILARITY]


# ---------------------------------------------------------------- public
@dataclass
class SubjectSkills:
    name: str                       # cleaned name
    links: list[SkillLink]
    vector: Optional[list[float]] = None      # subject embedding, when the AI layer ran (not for electives)

    @property
    def skills(self) -> list[str]:
        """Skills every student of this subject learns (elective choices left out)."""
        return [l.skill for l in self.links if l.option is None]

    @property
    def option_skills(self) -> dict[str, list[str]]:
        """For an elective: {choice: its skills}."""
        out: dict[str, list[str]] = {}
        for l in self.links:
            if l.option is not None:
                out.setdefault(l.option, []).append(l.skill)
        return out


def _units(subject: dict) -> list[tuple[Optional[str], str, str]]:
    """What gets linked on its own: (option, name, topics). A core subject is one unit;
    an elective is one unit per choice (its name is only the choices joined together)."""
    options = [o for o in (subject.get("options") or []) if o and o.strip()]
    if len(options) > 1:
        return [(clean_name(o), o, "") for o in options]
    return [(None, subject.get("name") or "", subject.get("topics") or "")]


def map_subjects(subjects: Sequence[dict], use_ai: bool = True) -> list[SubjectSkills]:
    """subjects: dicts with 'name' and optionally 'topics' and 'options' (elective choices).
    Returns one SubjectSkills per subject, in the same order.
    The AI layer runs (one batch) only for subjects or choices the named and table layers found nothing for."""
    results: list[SubjectSkills] = []
    unknown: list[tuple[int, Optional[str], str]] = []          # (subject index, option, text to embed)
    for index, subject in enumerate(subjects):
        links: list[SkillLink] = []
        for option, name, topics in _units(subject):
            found = _merge(_named(f"{name} {topics}"), _from_table(name))
            if not found:
                unknown.append((index, option, subject_text(name, topics)))
            for link in found:
                link.option = option
            links.extend(found)
        results.append(SubjectSkills(clean_name(subject.get("name") or ""), links))

    if use_ai and unknown:
        vectors = embeddings.get_embedder().embed([text for _, _, text in unknown])
        for (index, option, _), vector in zip(unknown, vectors):
            found = _from_ai(vector, set())
            for link in found:
                link.option = option
            results[index].links.extend(found)
            if option is None:
                results[index].vector = vector
    return results
