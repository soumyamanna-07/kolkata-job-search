"""Extra-class suggestions (Stage 1.5): which short add-on classes a college should arrange
(like an "FSB class"), built from the gaps in the curriculum gap report (app.curriculum_gap).

1. Gap skills = skills the market clearly asks for that the syllabus does not teach properly.
2. Association-rule mining (Apriori) on the live jobs: which gap skills are asked for TOGETHER
   (support, confidence, lift). Skills that go together are taught together.
3. Each gap skill belongs to one track (Cloud & DevOps, Web front end, ...). A class is the
   track's gap skills, most-asked first (at most 5 per class).
4. Greedy weighted set cover picks the classes: each time, the class that reaches the most
   NEW jobs per teaching hour, until 5 classes or no class adds 1% of jobs.
   "Reaches a job" = the job asks for at least one skill the class teaches.
Each class gets hours, a format, prerequisites (taught in the syllabus or not) and free resources.
"""
from collections.abc import Sequence
from itertools import combinations
from typing import Optional

from .curriculum_gap import COVERED, LEARN_NOW_MIN_SHARE, Market
from .subject_skills import SubjectSkills

MAX_CLASSES = 5
MAX_SKILLS_PER_CLASS = 5
MIN_NEW_SHARE = 0.01             # a class must reach at least 1% more of the jobs to be suggested
MIN_SUPPORT_JOBS = 3             # a skill pair must appear in at least this many jobs ...
MIN_SUPPORT_SHARE = 0.01         # ... and in at least 1% of the jobs
DEFAULT_HOURS = 8

# track: (class title, skills in teaching order, prerequisites, free resources)
TRACKS: dict[str, tuple[str, list[str], list[str], list[tuple[str, str]]]] = {
    "cloud_devops": ("Cloud and DevOps",
                     ["linux", "bash", "git", "docker", "ci/cd", "devops", "kubernetes", "jenkins", "terraform",
                      "aws", "azure", "gcp"],
                     ["linux"],
                     [("Docker docs: Get started", "https://docs.docker.com/get-started/"),
                      ("Kubernetes basics tutorial", "https://kubernetes.io/docs/tutorials/kubernetes-basics/"),
                      ("Microsoft Learn: Azure fundamentals", "https://learn.microsoft.com/en-us/training/azure/"),
                      ("AWS Skill Builder (free courses)", "https://skillbuilder.aws/"),
                      ("Google Cloud Skills Boost", "https://www.cloudskillsboost.google/"),
                      ("Pro Git book", "https://git-scm.com/book/en/v2")]),
    "web_frontend": ("Web development (front end)",
                     ["html", "css", "javascript", "typescript", "react", "next.js", "angular", "vue",
                      "tailwind css", "bootstrap"],
                     ["html"],
                     [("MDN Learn web development", "https://developer.mozilla.org/en-US/docs/Learn"),
                      ("React docs: Learn", "https://react.dev/learn"),
                      ("freeCodeCamp", "https://www.freecodecamp.org/learn"),
                      ("TypeScript handbook", "https://www.typescriptlang.org/docs/handbook/intro.html")]),
    "backend": ("Back end and APIs",
                ["rest api", "node.js", "express", "django", "flask", "fastapi", "spring boot", "spring", ".net",
                 "php", "laravel", "graphql", "microservices"],
                ["sql"],
                [("FastAPI tutorial", "https://fastapi.tiangolo.com/tutorial/"),
                 ("Spring guides", "https://spring.io/guides"),
                 ("Microsoft Learn: .NET", "https://learn.microsoft.com/en-us/training/dotnet/"),
                 ("Node.js learn", "https://nodejs.org/en/learn")]),
    "databases": ("Databases and SQL",
                  ["sql", "mysql", "postgresql", "oracle", "sql server", "mongodb", "redis", "elasticsearch"],
                  [],
                  [("PostgreSQL tutorial (official docs)", "https://www.postgresql.org/docs/current/tutorial.html"),
                   ("SQLBolt interactive lessons", "https://sqlbolt.com/"),
                   ("MongoDB University", "https://learn.mongodb.com/")]),
    "genai": ("Generative AI and LLM apps",
              ["llm", "generative ai", "rag", "langchain", "hugging face"],
              ["python", "machine learning"],
              [("Hugging Face LLM course", "https://huggingface.co/learn/llm-course"),
               ("DeepLearning.AI short courses", "https://www.deeplearning.ai/short-courses/"),
               ("Google: Introduction to generative AI", "https://www.cloudskillsboost.google/course_templates/536")]),
    "ml_engineering": ("Machine learning engineering",
                       ["machine learning", "scikit-learn", "deep learning", "pytorch", "tensorflow", "nlp",
                        "computer vision", "mlops"],
                       ["python", "statistics"],
                       [("scikit-learn user guide", "https://scikit-learn.org/stable/user_guide.html"),
                        ("PyTorch tutorials", "https://pytorch.org/tutorials/"),
                        ("NPTEL (free IIT courses)", "https://nptel.ac.in/")]),
    "data_analytics": ("Data analytics and BI",
                       ["data analysis", "pandas", "numpy", "statistics", "data visualization", "power bi", "tableau"],
                       ["python"],
                       [("Kaggle Learn: Pandas, Data Visualization", "https://www.kaggle.com/learn"),
                        ("Microsoft Learn: Power BI", "https://learn.microsoft.com/en-us/training/powerplatform/power-bi"),
                        ("Tableau free training videos", "https://www.tableau.com/learn/training")]),
    "data_engineering": ("Data engineering",
                         ["etl", "spark", "airflow", "kafka", "hadoop", "snowflake", "dbt"],
                         ["sql", "python"],
                         [("Apache Spark quick start", "https://spark.apache.org/docs/latest/quick-start.html"),
                          ("Airflow tutorial", "https://airflow.apache.org/docs/apache-airflow/stable/tutorial/index.html"),
                          ("dbt Learn (free courses)", "https://learn.getdbt.com/")]),
    "testing": ("Software testing",
                ["manual testing", "automation testing", "selenium"],
                [],
                [("Selenium docs", "https://www.selenium.dev/documentation/"),
                 ("ISTQB foundation syllabus (free PDF)", "https://www.istqb.org/")]),
    "mobile": ("Mobile app development",
               ["android", "kotlin", "flutter", "dart", "react native", "ios", "swift"],
               [],
               [("Android Basics with Compose", "https://developer.android.com/courses"),
                ("Flutter docs: Get started", "https://docs.flutter.dev/get-started")]),
    "programming": ("Programming language",
                    ["python", "java", "c", "c++", "c#", "go", "rust", "scala", "r", "matlab", "ruby", "wordpress"],
                    [],
                    [("Python tutorial (official)", "https://docs.python.org/3/tutorial/"),
                     ("Dev.java: Learn Java", "https://dev.java/learn/"),
                     ("NPTEL (free IIT courses)", "https://nptel.ac.in/")]),
}
TRACK_OF = {skill: track for track, (_, skills, _, _) in TRACKS.items() for skill in skills}

# rough teaching hours for a working introduction (default DEFAULT_HOURS)
HOURS = {
    "javascript": 20, "react": 16, "typescript": 8, "java": 30, "python": 24, "c++": 24, "c#": 24, ".net": 20,
    "sql": 16, "aws": 12, "azure": 12, "gcp": 10, "kubernetes": 12, "docker": 8, "devops": 8, "ci/cd": 6,
    "git": 4, "linux": 10, "llm": 10, "generative ai": 6, "rag": 8, "spring boot": 16, "django": 14,
    "node.js": 12, "rest api": 6, "machine learning": 24, "deep learning": 20, "power bi": 10, "tableau": 10,
    "spark": 12, "selenium": 10, "android": 24, "flutter": 20, "html": 6, "css": 8,
}


def hours(skill: str) -> int:
    return HOURS.get(skill, DEFAULT_HOURS)


# ---------------------------------------------------------------- association rules (Apriori)
def frequent_pairs(transactions: Sequence[frozenset[str]], items: set[str]) -> list[dict]:
    """Apriori, level 2: skill pairs (from `items`) asked for together in enough jobs.
    support = share of all jobs with both; confidence(a->b) = P(b | a); lift = P(a and b) / (P(a) P(b))."""
    n = len(transactions)
    if not n:
        return []
    baskets = [t & items for t in transactions]
    single: dict[str, int] = {}
    for b in baskets:
        for s in b:
            single[s] = single.get(s, 0) + 1
    min_count = max(MIN_SUPPORT_JOBS, MIN_SUPPORT_SHARE * n)
    frequent = {s for s, c in single.items() if c >= min_count}            # Apriori: a frequent pair needs
    pairs: dict[tuple[str, str], int] = {}                                 # both of its skills to be frequent
    for b in baskets:
        for a, c in combinations(sorted(b & frequent), 2):
            pairs[(a, c)] = pairs.get((a, c), 0) + 1
    out = []
    for (a, b), both in pairs.items():
        if both < min_count:
            continue
        lift = both * n / (single[a] * single[b])
        out.append({"a": a, "b": b, "jobs": both, "support": round(both / n, 4),
                    "confidence_ab": round(both / single[a], 3), "confidence_ba": round(both / single[b], 3),
                    "lift": round(lift, 2)})
    return sorted(out, key=lambda p: (-p["lift"], -p["jobs"], p["a"], p["b"]))


# ---------------------------------------------------------------- the classes
def gap_skills(report: dict) -> list[dict]:
    """Skills the market clearly asks for that the syllabus does not teach properly (most-asked first)."""
    return [x for x in report["skills"]
            if x["coverage_now"] < COVERED and x["ci"][0] >= 100 * LEARN_NOW_MIN_SHARE]


def _format(total_hours: int) -> str:
    if total_hours <= 12:
        return "Weekend workshop (2 days)"
    if total_hours <= 30:
        return f"2-week evening class (about {round(total_hours / 10) * 5 or 5} sessions of 2 hours)"
    return f"4-6 week add-on course (about {total_hours} hours, 2-3 sessions a week)"


def syllabus_skills(mapped: Sequence[SubjectSkills]) -> set[str]:
    """Every skill some core (non-elective) subject of the syllabus teaches."""
    return {skill for result in mapped for skill in result.skills}


def suggest_classes(report: dict, market: Market, mapped: Sequence[SubjectSkills] = ()) -> dict:
    """Extra classes for the gaps in `report`, chosen with the live jobs in `market`.
    `mapped` (the linked subjects) tells which prerequisites the syllabus already teaches."""
    gaps = gap_skills(report)
    gap_by_name = {g["skill"]: g for g in gaps}
    taught_now = syllabus_skills(mapped) | {x["skill"] for x in report["skills"] if x["coverage_now"] >= COVERED}
    pairs = frequent_pairs(market.job_skills, set(gap_by_name))

    candidates = []
    for track, (title, order, prereqs, resources) in TRACKS.items():
        skills = [s for s in sorted(gap_by_name, key=lambda s: (-gap_by_name[s]["jobs"], s))
                  if TRACK_OF.get(s) == track][:MAX_SKILLS_PER_CLASS]
        if not skills:
            continue
        skills.sort(key=order.index)                                     # teach in a sensible order
        if track == "programming":                                       # one language per class
            for s in skills:
                candidates.append((track, f"{title}: {s.upper() if s in ('c', 'c++', 'c#', 'r') else s.capitalize()}",
                                   [s], prereqs, resources))
        else:
            candidates.append((track, title, skills, prereqs, resources))

    jobs = market.job_skills
    reached: set[int] = set()
    chosen = []
    while candidates and len(chosen) < MAX_CLASSES:
        best, best_rate, best_new = None, 0.0, set()
        for cand in candidates:
            skills = set(cand[2])
            new = {i for i, js in enumerate(jobs) if i not in reached and js & skills}
            rate = len(new) / sum(hours(s) for s in skills)
            if rate > best_rate:
                best, best_rate, best_new = cand, rate, new
        if best is None or not jobs or len(best_new) < MIN_NEW_SHARE * len(jobs):
            break
        candidates.remove(best)
        reached |= best_new
        track, title, skills, prereqs, resources = best
        total = sum(hours(s) for s in skills)
        all_jobs = sum(1 for js in jobs if js & set(skills))
        together = [p for p in pairs if p["a"] in skills and p["b"] in skills][:3]
        chosen.append({
            "track": track, "title": title,
            "skills": [{"skill": s, "jobs": gap_by_name[s]["jobs"], "share": gap_by_name[s]["share"],
                        "status": gap_by_name[s]["status"], "trend": gap_by_name[s]["trend"], "hours": hours(s)}
                       for s in skills],
            "hours": total, "format": _format(total),
            "jobs": all_jobs, "share": round(100 * all_jobs / len(jobs), 1),
            "new_jobs": len(best_new), "reach_after": round(100 * len(reached) / len(jobs), 1),
            "jobs_per_hour": round(best_rate, 2),
            "together": together,
            "prerequisites": [{"skill": p, "in_syllabus": p in taught_now} for p in prereqs],
            "resources": [{"title": t, "url": u} for t, u in resources],
        })

    covered_by_gaps = sum(1 for js in jobs if js & set(gap_by_name))
    return {
        "gap_skills": [g["skill"] for g in gaps],
        "classes": chosen,
        "reach": {"jobs": len(reached), "share": round(100 * len(reached) / len(jobs), 1) if jobs else 0.0,
                  "possible_share": round(100 * covered_by_gaps / len(jobs), 1) if jobs else 0.0,
                  "hours": sum(c["hours"] for c in chosen)},
        "asked_together": pairs[:10],
    }


def track_of(skill: str) -> Optional[str]:
    return TRACK_OF.get(skill)
