"""Tests for the extra-class suggestions, on a MADE-UP syllabus and made-up jobs."""
import unittest
from datetime import datetime, timedelta, timezone

from app import curriculum_gap as cg, extra_classes as ec
from app.skills import SKILLS
from app.subject_skills import map_subjects

NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)


def rows():
    """200 open computing jobs:
    60 ask for docker AND kubernetes (asked together), 20 more for docker only,
    40 for react + javascript, 30 for python only (taught), 50 for java only (taught)."""
    out = []
    out += [["docker", "kubernetes", "python"]] * 60
    out += [["docker"]] * 20
    out += [["react", "javascript"]] * 40
    out += [["python"]] * 30
    out += [["java"]] * 50
    return [(skills, True, NOW - timedelta(days=1), 0) for skills in out]


SUBJECTS = [
    {"name": "Python Programming", "semester": 3, "kind": "theory"},
    {"name": "Object Oriented Programming using Java", "semester": 4, "kind": "theory"},
]


class TestCatalog(unittest.TestCase):
    def test_every_computing_skill_has_one_track(self):
        for skill in cg.COMPUTING:
            self.assertIn(skill, ec.TRACK_OF, skill)
        for _, (_, skills, prereqs, resources) in ec.TRACKS.items():
            for s in skills + prereqs:
                self.assertIn(s, SKILLS)
            for _, url in resources:
                self.assertTrue(url.startswith("https://"))
        all_skills = [s for _, skills, _, _ in ec.TRACKS.values() for s in skills]
        self.assertEqual(len(all_skills), len(set(all_skills)))            # no skill in two tracks


class TestPairs(unittest.TestCase):
    def test_apriori_pairs(self):
        jobs = [frozenset(r[0]) for r in rows()]
        pairs = ec.frequent_pairs(jobs, {"docker", "kubernetes", "react", "javascript"})
        found = {(p["a"], p["b"]): p for p in pairs}
        dk = found[("docker", "kubernetes")]
        self.assertEqual(dk["jobs"], 60)
        self.assertEqual(dk["confidence_ba"], 1.0)                        # every kubernetes job wants docker
        self.assertEqual(dk["confidence_ab"], 0.75)                       # 60 of 80 docker jobs want kubernetes
        self.assertAlmostEqual(dk["lift"], 2.5)                           # 60*200 / (80*60)
        self.assertNotIn(("docker", "react"), found)                      # never together
        self.assertEqual(pairs[0]["a"], "javascript")                      # react+javascript: lift 5.0, highest

    def test_rare_pairs_left_out(self):
        jobs = [frozenset({"a1", "b1"})] * 2 + [frozenset({"x"})] * 98
        self.assertEqual(ec.frequent_pairs(jobs, {"a1", "b1"}), [])        # only 2 jobs: below the minimum
        self.assertEqual(ec.frequent_pairs([], {"a1"}), [])


class TestClasses(unittest.TestCase):
    def setUp(self):
        self.market = cg.build_market(rows(), "computing", now=NOW)
        self.report = cg.build_report(SUBJECTS, map_subjects(SUBJECTS, use_ai=False), self.market)

    def test_gap_skills(self):
        self.assertEqual(ec.gap_skills(self.report)[0]["skill"], "docker")
        names = {g["skill"] for g in ec.gap_skills(self.report)}
        self.assertEqual(names, {"docker", "kubernetes", "react", "javascript"})    # python, java are taught

    def test_classes(self):
        out = ec.suggest_classes(self.report, self.market)
        classes = out["classes"]
        self.assertEqual([c["track"] for c in classes], ["cloud_devops", "web_frontend"])
        cloud, web = classes
        self.assertEqual([s["skill"] for s in cloud["skills"]], ["docker", "kubernetes"])   # teaching order
        self.assertEqual((cloud["hours"], cloud["jobs"], cloud["new_jobs"]), (20, 80, 80))
        self.assertEqual(cloud["share"], 40.0)
        self.assertEqual(cloud["together"][0]["b"], "kubernetes")
        self.assertEqual(cloud["prerequisites"], [{"skill": "linux", "in_syllabus": False}])
        self.assertTrue(cloud["resources"])
        self.assertEqual([s["skill"] for s in web["skills"]], ["javascript", "react"])
        self.assertEqual((web["hours"], web["new_jobs"], web["reach_after"]), (36, 40, 60.0))
        self.assertEqual(out["reach"], {"jobs": 120, "share": 60.0, "possible_share": 60.0, "hours": 56})
        self.assertIn("2-week", cloud["format"])

    def test_prerequisite_taught_in_syllabus(self):
        subjects = SUBJECTS + [{"name": "Unix and Shell Programming", "semester": 4, "kind": "theory"}]
        mapped = map_subjects(subjects, use_ai=False)
        report = cg.build_report(subjects, mapped, self.market)        # linux: no jobs here, not in the report
        cloud = ec.suggest_classes(report, self.market, mapped)["classes"][0]
        self.assertEqual(cloud["prerequisites"], [{"skill": "linux", "in_syllabus": True}])

    def test_nothing_missing(self):
        subjects = SUBJECTS + [{"name": "Cloud Computing and Docker, Kubernetes", "semester": 5, "kind": "theory"},
                               {"name": "Web Technology using React", "semester": 5, "kind": "theory"}]
        report = cg.build_report(subjects, map_subjects(subjects, use_ai=False), self.market)
        out = ec.suggest_classes(report, self.market)
        self.assertEqual((out["classes"], out["gap_skills"]), ([], []))

    def test_formats(self):
        self.assertIn("Weekend", ec._format(10))
        self.assertIn("2-week", ec._format(20))
        self.assertIn("4-6 week", ec._format(48))


if __name__ == "__main__":
    unittest.main()
