"""Tests for linking college subjects to job skills, on MADE-UP subjects (no real syllabus)."""
import unittest

from app import embeddings, subject_skills as ss
from app.skills import SKILLS


class KeywordEmbedder:
    """A tiny fake model: texts that mention 'dashboard' or 'tableau' point the same way;
    every other text gets its own direction, so it matches nothing."""

    def __init__(self):
        self.dims = {}
        self.calls = 0

    def _vector(self, text):
        vec = [0.0] * embeddings.DIMENSIONS
        low = text.lower()
        if "dashboard" in low or "tableau" in low:
            vec[0] = 1.0
        else:
            vec[self.dims.setdefault(low, len(self.dims) + 1)] = 1.0
        return vec

    def embed(self, texts):
        self.calls += 1
        return [self._vector(t) for t in texts]


def links(result):
    return {l.skill: (l.weight, l.source) for l in result.links}


class TestNames(unittest.TestCase):
    def test_clean_name(self):
        self.assertEqual(ss.clean_name("Mathematics -IA*"), "Mathematics - IA")
        self.assertEqual(ss.clean_name("Physics-I (Gr-A)"), "Physics-I")
        self.assertEqual(ss.clean_name("Chemistry-I Laboratory (Gr- B)#"), "Chemistry-I Laboratory")
        self.assertEqual(ss.clean_name("Engineering Graphics & Design(Gr-A"), "Engineering Graphics & Design")

    def test_base_name(self):
        self.assertEqual(ss.base_name("Physics-I Laboratory (Gr-A)"), "physics")
        self.assertEqual(ss.base_name("Mathematics -IIA#"), "mathematics")
        self.assertEqual(ss.base_name("Database Management Systems Lab"), "database management systems")
        self.assertEqual(ss.base_name("Workshop / Manufacturing Practices"), "manufacturing practices")


class TestTable(unittest.TestCase):
    def test_every_table_skill_is_a_job_skill(self):
        for pattern, pairs in ss.CURRICULUM:
            for skill, weight in pairs:
                self.assertIn(skill, SKILLS, pattern)
                self.assertTrue(0 < weight <= 1)

    def test_named_and_table(self):
        out = ss.map_subjects([
            {"name": "Database Management Systems"},
            {"name": "Database Management Systems Lab", "topics": "Practice of SQL queries"},
            {"name": "Python Programming"},
            {"name": "Programming for Problem Solving*"},
            {"name": "Principles of Management"},
        ], use_ai=False)
        dbms = links(out[0])
        self.assertEqual(dbms["sql"], (0.9, "curriculum"))
        self.assertNotIn("project management", dbms)            # "Database MANAGEMENT" is not management
        self.assertEqual(links(out[1])["sql"], (1.0, "named"))   # written in the topics: strongest
        self.assertEqual(links(out[2])["python"], (1.0, "named"))
        self.assertEqual(out[3].name, "Programming for Problem Solving")
        self.assertEqual(links(out[3]), {"c": (0.9, "curriculum")})
        self.assertIn("project management", links(out[4]))
        self.assertEqual(out[0].links[0].skill, "sql")           # strongest link first

    def test_elective_choices_are_kept_apart(self):
        out = ss.map_subjects([{"name": "Cloud Computing / Computer Vision / Graph Theory",
                                "options": ["Cloud Computing", "Computer Vision", "Graph Theory"],
                                "is_elective": True}], use_ai=False)
        r = out[0]
        self.assertEqual(r.skills, [])                           # no skill is learnt by EVERY student
        self.assertIn("aws", r.option_skills["Cloud Computing"])
        self.assertEqual(r.option_skills["Computer Vision"], ["computer vision", "python"])
        self.assertNotIn("Graph Theory", r.option_skills)
        cv = [l for l in r.links if l.skill == "computer vision"][0]
        self.assertEqual((cv.weight, cv.source, cv.option), (1.0, "named", "Computer Vision"))

    def test_unknown_subject_without_ai(self):
        out = ss.map_subjects([{"name": "Physics-I (Gr-A)"}, {"name": "Data Communication"}], use_ai=False)
        self.assertEqual(out[0].links, [])
        self.assertEqual(out[1].links, [])                       # "communication" skill means soft skills


class TestAI(unittest.TestCase):
    def setUp(self):
        self.fake = KeywordEmbedder()
        embeddings.set_embedder(self.fake)
        ss.clear_cache()

    def tearDown(self):
        embeddings.set_embedder(None)
        ss.clear_cache()

    def test_ai_only_for_unknown_subjects(self):
        out = ss.map_subjects([
            {"name": "Database Management Systems"},
            {"name": "Business Reporting", "topics": "building dashboards for managers"},
            {"name": "Physics-I"},
        ])
        self.assertIsNone(out[0].vector)                         # the table knew it: no AI
        self.assertEqual(links(out[1]), {"tableau": (ss.AI_MAX_WEIGHT, "ai")})
        self.assertIsNotNone(out[1].vector)
        self.assertEqual(out[2].links, [])                       # nothing close enough
        self.assertEqual(self.fake.calls, 2)                     # one batch for subjects, one for skills

    def test_ai_for_one_elective_choice(self):
        out = ss.map_subjects([{"name": "Python Programming / Reporting Dashboards",
                                "options": ["Python Programming", "Reporting Dashboards"]}])
        self.assertEqual(out[0].option_skills, {"Python Programming": ["python"],
                                                "Reporting Dashboards": ["tableau"]})
        self.assertIsNone(out[0].vector)

    def test_skill_vectors_made_once(self):
        ss.map_subjects([{"name": "Physics-I"}])
        ss.map_subjects([{"name": "Chemistry-I"}])
        self.assertEqual(self.fake.calls, 3)

    def test_no_ai_call_when_all_known(self):
        ss.map_subjects([{"name": "Python Programming"}])
        self.assertEqual(self.fake.calls, 0)


if __name__ == "__main__":
    unittest.main()
