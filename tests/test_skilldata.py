import gzip
import json
import os
import tempfile
import unittest
from unittest import mock

from shugotracker import skilldata
from shugotracker.profile import parse_profile


class SkillDataTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        path = os.path.join(self.tmp.name, "skills.json.gz")
        data = {"skills": {"16010000": {"name": "Cold Shock", "class": "Spiritmaster",
                                        "url": "https://metabot.gg/en/aion-2/skills/cold-shock",
                                        "text": ["Deals 54", "Deals 75", "Deals 97"],
                                        "cd": ["", "8s", "8s"], "mp": ["", "", "10"]}}}
        with gzip.open(path, "wt", encoding="utf-8") as f:
            json.dump(data, f)
        self.p1 = mock.patch.object(skilldata, "_path", lambda: path)
        self.p2 = mock.patch.object(skilldata, "_skills", None)
        self.p1.start()
        self.p2.start()

    def tearDown(self):
        self.p2.stop()
        self.p1.stop()
        self.tmp.cleanup()

    def test_level(self):
        t = skilldata.describe(16010000, 2)
        self.assertEqual((t.name, t.text, t.level, t.max_level, t.cooldown), ("Cold Shock", "Deals 75", 2, 3, "8s"))
        self.assertTrue(t.url.endswith("/cold-shock"))

    def test_clamped(self):
        self.assertEqual(skilldata.describe(16010000, 0).level, 1)       # not learned: level 1
        self.assertEqual(skilldata.describe(16010000, 14).text, "Deals 97")   # Daevanion levels past the data
        self.assertEqual(skilldata.describe(16010000, 3).mp, "10")

    def test_unknown(self):
        self.assertIsNone(skilldata.describe(1, 1))
        self.assertIsNone(skilldata.describe(0, 1))

    def test_missing_file(self):
        with mock.patch.object(skilldata, "_path", lambda: "/nope/skills.json.gz"), \
                mock.patch.object(skilldata, "_skills", None):
            self.assertIsNone(skilldata.describe(16010000, 1))

    def test_profile_keeps_skill_id(self):
        eq = {"skill": {"skillList": [{"id": 16010000, "name": "Cold Shock", "category": "Active",
                                       "skillLevel": 14, "equip": 1, "acquired": 1}]}}
        p = parse_profile({"profile": {}}, eq)
        self.assertEqual(p.skills[0].skill_id, 16010000)


if __name__ == "__main__":
    unittest.main()
