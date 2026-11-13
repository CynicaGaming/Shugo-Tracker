"""Profile parsing, fetching, and favorites."""
import json
import os
import tempfile
import threading
import time
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
        api = a.Api(session=sess or FakeSession(), rate=1000,
                    db_path=os.path.join(profile_dir, "shugo.db") if profile_dir else None)
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

    def test_move_keeps_order_on_disk(self):
        path = os.path.join(tempfile.mkdtemp(), "favorites.json")
        fav = Favorites(path)
        cs = [char(char_id=f"c{i}", name=f"N{i}") for i in range(4)]
        for c in cs:
            fav.toggle(c)
        fav.move(cs[3].key, 0)
        fav.move(cs[0].key, 3)
        self.assertEqual([c.name for c in Favorites(path).characters()], ["N3", "N1", "N2", "N0"])

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


class StatBonusTests(unittest.TestCase):
    def test_per_point(self):
        from shugotracker.profile import STAT_BONUSES
        self.assertEqual(STAT_BONUSES["INT"], [("Status Effect Chance", "+")])
        self.assertEqual(STAT_BONUSES["Illusion"], [("Cooldown", "-"), ("Endurance Penetration", "+")])
        self.assertEqual(len(STAT_BONUSES), 16)

    def test_bonus_table_matches_live_text(self):
        # the API's own lines for a stat with points: label and sign must match our table
        from shugotracker.profile import STAT_BONUSES
        live = ["Defense increase +6.9%", "Perfect Chance +6.9%"]          # Justice, 69 points
        self.assertEqual([f"{label} {sign}" for label, sign in STAT_BONUSES["Justice"]],
                         [e[:e.rindex(" ") + 2] for e in live])          # "Defense increase +"


class ReuseCardInfoTests(unittest.TestCase):
    def test_profile_after_card_skips_second_info_call(self):
        sess = FakeSession()
        api = a.Api(session=sess, rate=1000)
        self.addCleanup(api.close)
        c = char()
        done = threading.Event()
        api.want(c, lambda ch: done.set())
        self.assertTrue(done.wait(5))
        got, fin = [], threading.Event()
        api.fetch_profile(c, lambda ch, p, e: (got.append(p), p and not p.equipment_pending and fin.set()))
        self.assertTrue(fin.wait(5))
        self.assertEqual(sess.calls.count(a.INFO_URL), 1)      # the card's info was reused
        self.assertEqual(sess.calls.count(EQUIPMENT_URL), 1)


class EmptyItemTests(unittest.TestCase):
    def test_placeholder_wing_appearance_is_dropped(self):
        import copy
        from shugotracker.profile import parse_profile
        data = json.load(open(os.path.join(os.path.dirname(__file__), "fixtures", "profile_sample.json"), encoding="utf-8"))
        eq = copy.deepcopy(data["equipment"])
        eq["petwing"]["wingSkin"] = {"id": 0, "name": "", "grade": "", "icon": "", "enchantLevel": 0}
        p = parse_profile(data["info"], eq)
        self.assertIsNone(p.wing_skin)
        self.assertIsNotNone(p.wing)



class ItemDetailTests(unittest.TestCase):
    def test_gear_and_arcana(self):
        from shugotracker.profile import GEAR_ARCANA, parse_item_detail
        self.assertEqual(len(GEAR_ARCANA), 10)                       # Arcana1..Arcana10 (slots 41-50)
        sword = parse_item_detail({
            "level": 86, "categoryName": "Longsword", "maxEnchantLevel": 15, "maxExceedEnchantLevel": 5,
            "magicStoneSlotCount": 4, "godStoneSlotCount": 1,
            "mainStats": [{"name": "Attack", "minValue": "354", "value": "442", "extra": "146"},
                          {"name": "Block", "value": "200", "extra": "0"},
                          {"name": "Attack", "value": "24", "exceed": True}], "soulBindRate": "98.8",
            "subStats": [{"name": "Might", "value": "30"}],
            "magicStoneStat": [{"name": "MP", "value": "+15", "grade": "Common", "slotPos": 2},
                               {"name": "HP", "value": "+60", "grade": "Rare", "slotPos": 0}]})
        self.assertEqual(sword.main_stats, [("Attack", "442", "146"), ("Block", "200", "")])
        self.assertEqual([m[0] for m in sword.mana_stones], ["HP", "MP"])          # in slot order
        self.assertEqual((sword.main_min, sword.exceed_stats, sword.soul_bind), ({"Attack": "354"}, [("Attack", "24")], "98.8"))
        self.assertEqual((sword.mana_slots, sword.theo_slots, sword.theostones), (4, 1, []))
        card = parse_item_detail({"subSkills": [{"name": "Judgment", "level": 2}],
                                  "set": {"name": "Primal Vigor", "equippedCount": 4, "items": [{}] * 5,
                                          "bonuses": [{"degree": 2, "descriptions": ["+60 PvE Attack"]}]},
                                  "godStoneStat": [{"name": "Frost", "desc": "Chance to freeze"}]})
        self.assertEqual(card.linked_skills, [("Judgment", 2, "")])
        self.assertEqual((card.set_name, card.set_equipped, card.set_size), ("Primal Vigor", 4, 5))
        self.assertEqual(card.theostones, ["Chance to freeze"])


class ItemCacheTests(unittest.TestCase):
    """Worn items' details are saved with the profile: a profile opened again (even after a restart) asks for
    none of them, stale ones are shown at once then refreshed, and Refresh asks for everything again."""

    class Sess:
        def __init__(self):
            self.headers, self.calls = {}, []

        def get(self, url, params=None, timeout=None):
            from shugotracker.profile import ITEM_URL
            self.calls.append((url, (params or {}).get("slotPos")))
            if url == ITEM_URL:
                return FakeResp({"level": 80 + int(params["slotPos"]), "categoryName": "Longsword"})
            raise AssertionError(url)

    def api(self, folder, sess):
        api = a.Api(session=sess, rate=1000, db_path=os.path.join(folder, "shugo.db"))
        self.addCleanup(api.close)
        return api

    def get(self, api, c, item):
        got, done = [], threading.Event()
        api.fetch_item_detail(c, item, lambda det: (got.append(det), done.set()))
        self.assertTrue(done.wait(5))
        return got[0]

    def item(self, slot=1, enchant=10):
        from shugotracker.profile import Item
        return Item(slot="MainHand", name="Sword", grade="Epic", enchant=enchant, item_id=1234, slot_pos=slot)

    def test_saved_across_restarts(self):
        folder, c = tempfile.mkdtemp(), char()
        s1 = self.Sess()
        api1 = self.api(folder, s1)
        self.assertEqual(self.get(api1, c, self.item()).item_level, 81)
        api1.store.put_profile(c.key, {}, {})            # items are kept as long as their profile
        api1.close()
        s2 = self.Sess()
        api2 = self.api(folder, s2)
        got = []
        api2.fetch_item_detail(c, self.item(), got.append)
        self.assertEqual([d.item_level for d in got], [81])    # answered at once, from disk
        self.assertEqual(s2.calls, [])

    def test_new_enchant_is_a_new_item(self):
        c, s = char(), self.Sess()
        api = self.api(tempfile.mkdtemp(), s)
        self.get(api, c, self.item(enchant=10))
        self.get(api, c, self.item(enchant=11))
        self.assertEqual(len(s.calls), 2)

    def test_stale_shown_then_refreshed(self):
        c, s = char(), self.Sess()
        api = self.api(tempfile.mkdtemp(), s)
        self.get(api, c, self.item())
        key = (c.key, 1, 1234, 10)
        api._item_details[key] = (time.time() - a.ITEM_FRESH_S - 1, api._item_details[key][1])
        got = []
        api.fetch_item_detail(c, self.item(), got.append)
        self.assertEqual(len(got), 1)                          # the old answer, at once
        deadline = time.time() + 5
        while len(s.calls) < 2 and time.time() < deadline:
            time.sleep(0.01)
        self.assertEqual(len(s.calls), 2)                      # …and one quiet refresh

    def test_refresh_forgets_items(self):
        folder, c, s = tempfile.mkdtemp(), char(), self.Sess()
        api = self.api(folder, s)
        self.get(api, c, self.item())
        api.forget(c)
        self.get(api, c, self.item())
        self.assertEqual(len(s.calls), 2)
        self.assertEqual(len(api.store.items_of(c.key)), 1)


def board_raw(opened=(1, 2)):
    """A small board shaped like the real response: Start in the middle, two nodes beside it, empty cells."""
    nodes = [{"boardId": 21, "nodeId": 1, "row": 2, "col": 2, "type": "Start", "grade": "None", "name": "Nezekan - Start",
              "open": 0, "effectList": [{"desc": ""}], "icon": ""},
             {"boardId": 21, "nodeId": 2, "row": 2, "col": 3, "type": "Stat", "grade": "Common", "name": "Critical Hit",
              "open": int(2 in opened), "effectList": [{"desc": "Critical Hit +5"}], "icon": ""},
             {"boardId": 21, "nodeId": 3, "row": 1, "col": 2, "type": "SkillLevel", "grade": "Legend",
              "name": "Skill Level Up - Annihilate", "open": int(1 in opened), "effectList": [{"desc": "Annihilate +1"}],
              "icon": ""},
             {"boardId": 21, "nodeId": 4, "row": 1, "col": 1, "type": "None", "grade": "None", "name": "", "open": 0,
              "effectList": [], "icon": ""}]
    return {"nodeList": nodes, "openStatEffectList": [{"desc": "Critical Hit +5"}],
            "openSkillEffectList": [{"desc": "Annihilate +1"}]}


class BoardTests(unittest.TestCase):
    def test_parse(self):
        from shugotracker.profile import parse_board, parse_profile
        d = parse_board(board_raw())
        self.assertEqual([n.kind for n in d.nodes], ["Start", "Stat", "SkillLevel"])     # empty cells dropped
        self.assertEqual(d.opened, 2)
        self.assertEqual(d.nodes[1].effects, ["Critical Hit +5"])
        self.assertEqual(d.nodes[0].effects, [])
        self.assertEqual((d.stat_effects, d.skill_effects), (["Critical Hit +5"], ["Annihilate +1"]))
        p = parse_profile({"daevanion": {"boardList": [{"id": 21, "name": "Nezekan", "openNodeCount": 2,
                                                         "totalNodeCount": 88}]}}, None)
        self.assertEqual(p.boards[0].board_id, 21)

    class Sess:
        def __init__(self, opened=(1, 2)):
            self.headers, self.calls, self.opened = {}, [], opened

        def get(self, url, params=None, timeout=None):
            self.calls.append(params.get("boardId"))
            return FakeResp(board_raw(self.opened))

    def api(self, folder, sess):
        api = a.Api(session=sess, rate=1000, db_path=os.path.join(folder, "shugo.db"))
        self.addCleanup(api.close)
        return api

    def get(self, api, opened):
        got, done = [], threading.Event()
        api.fetch_board(char(), 21, opened, lambda raw: (got.append(raw), done.set()))
        self.assertTrue(done.wait(5))
        return got[0]

    def test_saved_and_reused_until_a_node_opens(self):
        folder = tempfile.mkdtemp()
        s1 = self.Sess()
        api1 = self.api(folder, s1)
        self.get(api1, 2)
        api1.store.put_profile(char().key, {}, {})        # boards are kept as long as their profile
        api1.close()
        s2 = self.Sess(opened=(1, 2, 3))
        api2 = self.api(folder, s2)
        self.get(api2, 2)
        self.assertEqual(s2.calls, [])                    # same opened count: from disk, no request
        self.get(api2, 3)
        self.assertEqual(s2.calls, [21])                  # the profile says a node opened: ask again

    def test_refresh_forgets_boards(self):
        folder, s = tempfile.mkdtemp(), self.Sess()
        api = self.api(folder, s)
        self.get(api, 2)
        api.forget(char())
        self.get(api, 2)
        self.assertEqual(s.calls, [21, 21])
