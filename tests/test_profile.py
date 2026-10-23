"""Profile parsing, fetching, and favorites."""
import json
import os
import tempfile
import threading
import unittest

from shugotracker import aion2api as a
from shugotracker.favorites import Favorites
from shugotracker.profile import EQUIPMENT_URL, parse_profile

HERE = os.path.dirname(__file__)
with open(os.path.join(HERE, "fixtures", "profile_sample.json"), encoding="utf-8") as f:
    SAMPLE = json.load(f)


def char(**kw):
    d = dict(char_id="TEST-ID=", name="Testchar", race=1, pc_id=10, level=45, server_id=1101,
             server_name="Siel", region="nae")
    d.update(kw)
    return a.Character(**d)


class ParseProfileTests(unittest.TestCase):
    def setUp(self):
        self.p = parse_profile(SAMPLE["info"], SAMPLE["equipment"])

    def test_header(self):
        p = self.p
        self.assertEqual((p.name, p.class_name, p.level, p.race), ("Testchar", "Templar", 45, 1))
        self.assertEqual((p.combat_power, p.gear_score, p.legion), (119296, 2529, "Power"))
        self.assertIsNone(p.title)  # empty string in the API

    def test_gear(self):
        g = self.p.gear
        self.assertEqual(g["MainHand"].name, "Spiritforged Longsword")
        self.assertEqual((g["MainHand"].enchant, g["MainHand"].grade), (15, "Unique"))
        self.assertEqual(g["Bracelet2"].slot_label, "Bracelet")
        self.assertIn("Arcana1", g)
        self.assertNotIn("Helmet", g)  # missing slots stay missing

    def test_cosmetics(self):
        p = self.p
        self.assertEqual([s.name for s in p.skins], ["Frozen Time (Longsword)", "Dawn Frost (Cloak)"])
        self.assertEqual((p.wing.name, p.wing_skin.name), ("Forest Spirit Wings", "Ultimate Daeva Wings"))
        self.assertEqual((p.pet.name, p.pet.level), ("Crasaur", 3))

    def test_skills_sorted_equipped_first(self):
        act = self.p.skills_in("Active")
        self.assertEqual([s.name for s in act], ["Vicious Strike", "Defiance"])
        dp = self.p.skills_in("Dp")
        self.assertEqual([s.name for s in dp], ["Battlefield Banner", "Nezekan's Shield"])
        self.assertFalse(dp[1].acquired)

    def test_stats_boards_titles(self):
        p = self.p
        self.assertEqual([s.type for s in p.primary_stats], ["STR", "INT"])
        self.assertEqual([s.type for s in p.deity_stats], ["Justice"])
        self.assertEqual(p.deity_stats[0].effects, ["Defense increase +6.9%", "Perfect Chance +6.9%"])
        self.assertEqual([(b.name, b.percent) for b in p.boards], [("Nezekan", 69), ("Azphel", 13)])
        self.assertEqual((p.titles_owned, p.titles_total), (207, 297))
        self.assertEqual(p.titles[0].effects, ["Critical Attack +45", "Critical Damage Boost +3%", "Critical Attack +3"])

    def test_without_equipment(self):
        p = parse_profile(SAMPLE["info"], None)
        self.assertEqual((p.gear, p.skills, p.skins), ({}, [], []))
        self.assertEqual(p.combat_power, 119296)


class FakeResp:
    def __init__(self, data, status=200):
        self._data, self.status_code, self.headers = data, status, {}

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, eq_status=200):
        self.headers, self.calls, self.eq_status = {}, [], eq_status

    def get(self, url, params=None, timeout=None):
        self.calls.append(url)
        if url == a.INFO_URL:
            return FakeResp(SAMPLE["info"])
        if url == EQUIPMENT_URL:
            return FakeResp(SAMPLE["equipment"], self.eq_status)
        raise AssertionError(url)


class FetchProfileTests(unittest.TestCase):
    def fetch(self, api, c):
        out, done = {}, threading.Event()

        def cb(ch, prof, err):
            out.update(prof=prof, err=err)
            done.set()
        api.fetch_profile(c, cb)
        self.assertTrue(done.wait(5))
        return out["prof"], out["err"]

    def test_fetch_and_cache(self):
        sess = FakeSession()
        api = a.Api(session=sess, rate=1000)
        self.addCleanup(api.close)
        c = char()
        prof, err = self.fetch(api, c)
        self.assertIsNone(err)
        self.assertEqual(prof.gear["MainHand"].enchant, 15)
        self.assertEqual((c.status, c.combat_power, c.gear_score), ("ok", 119296, 2529))  # card refreshed too
        self.assertEqual(sorted(sess.calls), sorted([a.INFO_URL, EQUIPMENT_URL]))
        self.fetch(api, c)
        self.assertEqual(len(sess.calls), 2)  # second open is served from the cache
        api.forget(c)
        self.fetch(api, c)
        self.assertEqual(len(sess.calls), 4)

    def test_equipment_failure_still_shows_profile(self):
        api = a.Api(session=FakeSession(eq_status=403), rate=1000)
        self.addCleanup(api.close)
        prof, err = self.fetch(api, char())
        self.assertIsNone(err)
        self.assertEqual(prof.combat_power, 119296)
        self.assertIsNotNone(prof.equipment_error)


class FavoritesTests(unittest.TestCase):
    def test_toggle_and_persist(self):
        path = os.path.join(tempfile.mkdtemp(), "favorites.json")
        fav = Favorites(path)
        c = char(portrait="https://x/p.png")
        self.assertTrue(fav.toggle(c))
        self.assertIn(c.key, fav)
        again = Favorites(path)
        self.assertEqual(len(again), 1)
        restored = again.characters()[0]
        self.assertEqual((restored.key, restored.name, restored.portrait, restored.status),
                         (c.key, "Testchar", "https://x/p.png", "none"))
        self.assertFalse(again.toggle(restored))
        self.assertEqual(len(Favorites(path)), 0)

    def test_corrupt_file_is_ignored(self):
        path = os.path.join(tempfile.mkdtemp(), "favorites.json")
        with open(path, "w") as f:
            f.write("{not json")
        self.assertEqual(len(Favorites(path)), 0)


if __name__ == "__main__":
    unittest.main()
