"""Nearby service on synthetic game traffic, with NCSOFT lookups faked."""
import os
import tempfile
import threading
import time
import unittest

from shugotracker import nearby as nb
from shugotracker.aion2api import Character
from tests.test_scout import damage, frame, other_record, ownership, self_record


def char(name, sid):
    return Character(char_id=f"{name}-{sid}", name=name, race=sid // 1000, pc_id=10, level=45, server_id=sid,
                     server_name="Srv", region="nae")


class FakeNcsoft:
    """find_by_name over a small world: {name: [server, ...]} per region."""

    def __init__(self, world):
        self.world, self.calls, self.lock = world, [], threading.Lock()

    def __call__(self, name, region):
        with self.lock:
            self.calls.append((name, region))
        return [char(name, sid) for sid in self.world.get(region, {}).get(name, [])]


def wait_for(cond, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


class NearbyServiceTests(unittest.TestCase):
    def make(self, world, cfg=None):
        find = FakeNcsoft(world)
        svc = nb.NearbyService(object(), cfg=cfg, data_dir=tempfile.mkdtemp(), find=find)
        svc.start_lookups()
        self.addCleanup(svc.stop)
        return svc, find

    def feed(self, svc, *bodies):
        svc.on_bytes(("1.2.3.4", 7777, "10.0.0.2", 5000), b"".join(frame(b) for b in bodies), False)

    def show_all(self, svc):                     # what the UI does for cards on screen
        for _side, c, _p in svc.snapshot():
            if not c.char_id:
                svc.want(c.name)

    def test_listed_at_once_identified_only_when_shown(self):
        svc, find = self.make({"nae": {"Mine": [1101], "Foe": [2101], "Friend": [1101]}})
        self.feed(svc, self_record(100, "Mine", 1101), other_record(200, "Foe"), other_record(300, "Friend"),
                  damage(100, 200))
        self.assertEqual({c.name for _s, c, _p in svc.snapshot()}, {"Foe", "Friend"})   # instantly
        time.sleep(0.2)
        self.assertEqual([n for n, _r in find.calls if n != "Mine"], [])            # nobody looked up yet
        self.show_all(svc)
        self.assertTrue(wait_for(lambda: all(c.char_id for _s, c, _p in svc.snapshot())))
        sides = {c.name: side for side, c, _p in svc.snapshot()}
        self.assertEqual(sides, {"Foe": "enemy", "Friend": "ally"})
        self.assertEqual(svc.snapshot()[0][1].name, "Foe")                            # enemies first

    def test_one_search_per_player_and_server_comes_from_ncsoft(self):
        # the game record says 1101 for Foe (wrong); NCSOFT knows exactly one Foe, on 2101
        svc, find = self.make({"nae": {"Mine": [1101], "Foe": [2101]}})
        self.feed(svc, self_record(100, "Mine", 1101), other_record(200, "Foe"), ownership(5000, 200, 1101, "Foe"))
        self.show_all(svc)
        self.assertTrue(wait_for(lambda: svc.snapshot()[0][1].char_id))
        side, c, _ = svc.snapshot()[0]
        self.assertEqual((side, c.server_id), ("enemy", 2101))
        self.assertEqual([r for n, r in find.calls if n == "Foe"], ["nae"])

    def test_namesakes_use_the_game_server_to_choose(self):
        svc, _ = self.make({"nae": {"Mine": [1101], "Ash": [1101, 2101]}})
        self.feed(svc, self_record(100, "Mine", 1101), other_record(200, "Ash"), ownership(5000, 200, 2101, "Ash"))
        self.show_all(svc)
        self.assertTrue(wait_for(lambda: svc.snapshot()[0][1].char_id))
        self.assertEqual(svc.snapshot()[0][1].server_id, 2101)

    def test_ambiguous_namesake_stops_loading(self):
        svc, _ = self.make({"nae": {"Mine": [1101], "Ash": [1101, 2101]}})
        self.feed(svc, self_record(100, "Mine", 1101), other_record(200, "Ash"))
        self.show_all(svc)
        self.assertTrue(wait_for(lambda: svc.snapshot()[0][1].status == "unresolved"))   # no endless shimmer

    def test_lookups_run_in_parallel(self):
        world = {"nae": {"Mine": [1101], **{f"P{i}": [1101] for i in range(8)}}}
        slow = FakeNcsoft(world)

        def find(name, region):
            time.sleep(0.2)
            return slow(name, region)
        svc = nb.NearbyService(object(), find=find, cfg={"nearby_region": "nae"})
        svc.start_lookups()
        self.addCleanup(svc.stop)
        self.feed(svc, self_record(100, "Mine", 1101), *[other_record(200 + i, f"P{i}") for i in range(8)])
        t0 = time.time()
        self.show_all(svc)
        self.assertTrue(wait_for(lambda: all(c.char_id for _s, c, _p in svc.snapshot()), timeout=5))
        self.assertLess(time.time() - t0, 1.0)            # 8 x 0.2 s one at a time would be 1.6 s

    def test_region_and_sides_without_your_own_record(self):
        # Nearby turned on mid-session: the game hasn't named you, nothing remembered
        world = {"nae": {"A": [1101], "B": [1101], "C": [1102], "D": [1101], "E": [2101]}}
        svc, find = self.make(world)
        self.feed(svc, *[other_record(200 + i, n) for i, n in enumerate("ABCDE")])
        self.show_all(svc)
        self.assertTrue(wait_for(lambda: all(c.char_id for _s, c, _p in svc.snapshot()), timeout=5))
        sides = {c.name: side for side, c, _p in svc.snapshot()}
        self.assertEqual(sides["E"], "enemy")            # most people around you are on your side
        self.assertEqual(sides["A"], "ally")

    def test_your_character_is_remembered(self):
        got = []
        svc, _ = self.make({"nae": {"Mine": [1101]}})
        svc.on_me = lambda n, s: got.append((n, s))
        self.feed(svc, self_record(100, "Mine", 1101))
        self.assertEqual(got, [("Mine", 1101)])
        svc2, _ = self.make({}, cfg={"nearby_me": ["Mine", 1101]})
        self.assertEqual(svc2.me(), ("Mine", 1101))

    def test_heuristic_server_is_not_shown(self):
        svc, _ = self.make({})
        self.feed(svc, self_record(100, "Mine", 1101), other_record(200, "Zed"))
        with svc._lock:
            p = svc.tracker.players["Zed"]
            p.server, p.server_source = 2301, "scan"
        self.assertEqual(svc.snapshot()[0][1].server_name, "")

    def test_region_found_from_your_own_name_and_remembered(self):
        # the game says 1101 (NA East) but you're really in Europe
        svc, find = self.make({"eu": {"Mine": [3101], "Foe": [4101 - 1000]}})
        got = []
        svc.on_region = got.append
        self.feed(svc, self_record(100, "Mine", 1101), other_record(200, "Foe"))
        self.show_all(svc)
        self.assertTrue(wait_for(lambda: got == ["eu"]))
        self.assertEqual(svc.me()[1], 3101)
        svc2, find2 = self.make({"eu": {"Mine": [3101]}}, cfg={"nearby_region": "eu"})
        self.feed(svc2, self_record(100, "Mine", 1101), other_record(200, "Foe"))
        self.show_all(svc2)
        self.assertTrue(wait_for(lambda: find2.calls))
        time.sleep(0.2)
        self.assertNotIn(("Mine", "nae"), find2.calls)              # remembered: no region hunt

    def test_recording_roundtrip(self):
        svc, _ = self.make({})
        path = svc.start_recording(5)
        self.feed(svc, self_record(100, "Mine", 1101), other_record(200, "Foe"))
        svc.stop_recording()
        got = []
        n = nb.replay_recording(path, lambda flow, data, gap: got.append((flow, data, gap)))
        self.assertEqual(n, 1)
        self.assertEqual(got[0][0], ("1.2.3.4", "7777", "10.0.0.2", "5000"))
        self.assertTrue(os.path.getsize(path) > 20)

    def test_start_without_npcap(self):
        if nb.npcap_installed():
            self.skipTest("Npcap is installed here")
        svc = nb.NearbyService(object(), find=lambda n, r: [])
        svc.start()
        self.assertEqual(svc.state, nb.NO_NPCAP)


if __name__ == "__main__":
    unittest.main()
