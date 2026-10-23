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
    def fetch(self, api, c, force=False):
        """All deliveries for one open, until the complete profile (or an error) arrives."""
        got, done = [], threading.Event()

        def cb(ch, prof, err):
            got.append((prof, err))
            if err or (prof and not prof.equipment_pending and prof.cached_at is None):
                done.set()
        api.fetch_profile(c, cb, force=force)
        done.wait(5)
        return got

    def final(self, got):
        return got[-1]

    def make(self, sess=None, profile_dir=None):
        api = a.Api(session=sess or FakeSession(), rate=1000, profile_dir=profile_dir)
        self.addCleanup(api.close)
        return api

    def test_fetch_and_cache(self):
        sess = FakeSession()
        api = self.make(sess)
        c = char()
        prof, err = self.final(self.fetch(api, c))
        self.assertIsNone(err)
        self.assertEqual(prof.gear["MainHand"].enchant, 15)
        self.assertEqual((c.status, c.combat_power, c.gear_score), ("ok", 119296, 2529))  # card refreshed too
        self.assertEqual(sorted(sess.calls), sorted([a.INFO_URL, EQUIPMENT_URL]))
        again = []
        api.fetch_profile(c, lambda ch, p, e: again.append(p))
        self.assertEqual(len(sess.calls), 2)              # served from the cache, synchronously
        self.assertEqual(again[0].gear["MainHand"].enchant, 15)
        api.forget(c)
        self.fetch(api, c)
        self.assertEqual(len(sess.calls), 4)

    def test_partial_profile_arrives_before_gear(self):
        gate = threading.Event()

        class SlowGear(FakeSession):
            def get(self, url, params=None, timeout=None):
                if url == EQUIPMENT_URL:
                    gate.wait(5)
                return super().get(url, params, timeout)

        api = self.make(SlowGear())
        got, first = [], threading.Event()
        api.fetch_profile(char(), lambda ch, p, e: (got.append(p), first.set()))
        self.assertTrue(first.wait(5))
        self.assertTrue(got[0].equipment_pending)          # stats / boards / titles can render already
        self.assertEqual(got[0].combat_power, 119296)
        self.assertEqual(got[0].gear, {})
        gate.set()
        for _ in range(100):
            if len(got) > 1:
                break
            threading.Event().wait(0.02)
        self.assertFalse(got[-1].equipment_pending)
        self.assertIn("MainHand", got[-1].gear)

    def test_prefetch_and_click_share_one_fetch(self):
        gate = threading.Event()

        class Slow(FakeSession):
            def get(self, url, params=None, timeout=None):
                gate.wait(5)
                return super().get(url, params, timeout)

        sess = Slow()
        api = self.make(sess)
        c = char()
        api.prefetch_profile(c)                           # pointer rests on the card
        got, done = [], threading.Event()
        api.fetch_profile(c, lambda ch, p, e: (got.append(p), (p and not p.equipment_pending) and done.set()))
        gate.set()
        self.assertTrue(done.wait(5))
        self.assertEqual(len(sess.calls), 2)              # one info + one equipment call in total

    def test_profiles_persist_and_stale_ones_show_then_refresh(self):
        folder = tempfile.mkdtemp()
        sess = FakeSession()
        self.fetch(self.make(sess, folder), char())
        self.assertEqual(len(sess.calls), 2)

        # A new app start: the profile comes from disk instantly...
        sess2 = FakeSession()
        api2 = self.make(sess2, folder)
        got = []
        api2.fetch_profile(char(), lambda ch, p, e: got.append(p))
        self.assertEqual(len(got), 1)
        self.assertIsNotNone(got[0].cached_at)
        self.assertEqual(sess2.calls, [])                 # ...and it was fresh, so no network at all

        # ...and when it's older than the fresh window it is still shown first, then refreshed.
        key = char().key
        ts, info, eq = api2._profiles[key]
        api2._profiles[key] = (ts - a.PROFILE_FRESH_S - 5, info, eq)
        got = self.fetch(api2, char())
        self.assertIsNotNone(got[0][0].cached_at)
        self.assertIsNone(got[-1][0].cached_at)
        self.assertEqual(len(sess2.calls), 2)

    def test_equipment_failure_still_shows_profile(self):
        prof, err = self.final(self.fetch(self.make(FakeSession(eq_status=403)), char()))
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


class LegionTests(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(a.parse_info(SAMPLE["info"])["legion"], "Power")
        no_legion = {"profile": {**SAMPLE["info"]["profile"], "regionName": ""}}
        self.assertIsNone(a.parse_info(no_legion)["legion"])

    def test_card_details_include_legion(self):
        api = a.Api(session=FakeSession(), rate=1000)
        self.addCleanup(api.close)
        c, done = char(), threading.Event()
        api.want(c, lambda ch: done.set())
        self.assertTrue(done.wait(5))
        self.assertEqual(c.legion, "Power")

    def test_old_cache_entries_are_refetched(self):
        sess = FakeSession()
        api = a.Api(session=sess, rate=1000)
        self.addCleanup(api.close)
        c = char()
        api._cache[c.key] = {"combat_power": 1, "gear_score": 2, "ts": 9e18}   # saved before legions existed
        done = threading.Event()
        api.want(c, lambda ch: done.set())
        self.assertTrue(done.wait(5))
        self.assertEqual((c.legion, c.combat_power), ("Power", 119296))
        self.assertIn(a.INFO_URL, sess.calls)
