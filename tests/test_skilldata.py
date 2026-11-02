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
                                        "cd": ["", "8s", "8s"], "mp": ["", "", "10"]},
                           "name:Chanter:Survival Willpower": {"name": "Survival Willpower", "url": "u",
                                                               "text": ["Increases resist"]}}}
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

    def test_by_name(self):
        self.assertEqual(skilldata.describe(18990000, 5, "Survival Willpower", "Chanter").text, "Increases resist")
        self.assertIsNone(skilldata.describe(18990000, 5, "Survival Willpower", "Cleric"))

    def test_scaling_numbers(self):
        texts = ["Move Speed by 10.5% and a 15% chance to restore 127 (+100% Attack)-140 HP. Cooldown: 1s",
                 "Move Speed by 12.5% and a 15% chance to restore 155 (+100% Attack)-171 HP. Cooldown: 1s"]
        t = texts[1]
        got = [t[a:b] for a, b in skilldata.scaling_spans(texts, 1)]
        self.assertEqual(got, ["12.5%", "155", "171"])              # 15%, +100% and 1s don't change

    def test_ranges_and_mismatch(self):
        texts = ["restore 170–187 HP", "restore 190–210 HP"]
        self.assertEqual([texts[0][a:b] for a, b in skilldata.scaling_spans(texts, 0)], ["170–187"])
        odd = ["deals 5 damage", "deals 6 damage, 2 hits"]          # levels don't line up: highlight them all
        self.assertEqual([odd[1][a:b] for a, b in skilldata.scaling_spans(odd, 1)], ["6", "2"])

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


class WrapTest(unittest.TestCase):
    def test_wrapped_lines(self):
        try:
            from shugotracker.profile_ui import wrapped_lines
        except ImportError:                     # no Tk here
            self.skipTest("tkinter not available")
        m = len                                  # 1 px per character
        self.assertEqual(wrapped_lines("aaa bbb ccc", m, 7), 2)        # "aaa bbb" / "ccc"
        self.assertEqual(wrapped_lines("one\n\nthree", m, 50), 3)      # blank line counts
        self.assertEqual(wrapped_lines("", m, 10), 1)
