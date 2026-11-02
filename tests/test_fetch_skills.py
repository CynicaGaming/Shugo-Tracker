import gzip
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import fetch_skills as fs  # noqa: E402

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "metabot_skill_cold_shock.html")
URL = "https://metabot.gg/en/aion-2/skills/cold-shock"


class ParseTest(unittest.TestCase):
    def setUp(self):
        with open(FIX, encoding="utf-8") as f:
            self.html = f.read()

    def test_page(self):
        sid, e = fs.parse_skill_page(self.html, URL)
        self.assertEqual(sid, "16010000")                 # the skill's own icon, not the first one on the page
        self.assertEqual((e["name"], e["class"], e["url"]), ("Cold Shock", "Spiritmaster", URL))
        self.assertEqual(len(e["text"]), 4)
        self.assertTrue(e["text"][0].startswith("Deals 54 "))      # sorted by level
        self.assertIn("1,111", e["text"][-1])
        self.assertIn("\n\n10 Stagger", e["text"][-1])
        self.assertEqual(e["cd"][:2], ["", "8s"])

    def test_not_a_skill(self):
        self.assertIsNone(fs.parse_skill_page("<html></html>", URL))

    def test_slugs(self):
        html = '<a href="/en/aion-2/skills/frost">x</a><a href="/en/aion-2/skills/cold-shock">'\
               '<a href="/en/aion-2/skills/frost">'
        self.assertEqual(fs.skill_slugs(html), ["frost", "cold-shock"])

    @staticmethod
    def _read(path):
        with open(path, "rb") as f:
            return f.read()

    def test_write_is_stable(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(fs, "OUT", os.path.join(d, "s.json.gz")):
            fs.write({"2": {"name": "b"}, "1": {"name": "a"}})
            first = self._read(fs.OUT)
            fs.write({"1": {"name": "a"}, "2": {"name": "b"}})
            self.assertEqual(first, self._read(fs.OUT))               # no timestamps: no needless commits
            data = json.loads(gzip.decompress(first))
            self.assertEqual(list(data["skills"]), ["1", "2"])
            self.assertEqual(data["source"], "MetaBot.GG")


if __name__ == "__main__":
    unittest.main()
