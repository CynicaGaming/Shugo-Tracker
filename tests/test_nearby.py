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

    def __call__(self, name, region, classes=None, pc_ids=None, race=None):
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

    def test_listed_at_once_then_identified(self):
        svc, find = self.make({"nae": {"Mine": [1101], "Foe": [2101], "Friend": [1101]}})
        self.feed(svc, self_record(100, "Mine", 1101), other_record(200, "Foe"), other_record(300, "Friend"),
                  damage(100, 200))
        self.assertEqual({c.name for _s, c, _p in svc.snapshot()}, {"Foe", "Friend"})   # instantly
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

    def test_namesakes_without_a_hint_still_resolve(self):
        svc, _ = self.make({"nae": {"Mine": [1101], "Ash": [1101, 2101]}})
        self.feed(svc, self_record(100, "Mine", 1101), other_record(200, "Ash"))
        self.assertTrue(wait_for(lambda: svc.snapshot()[0][1].char_id))
        self.assertEqual(svc.snapshot()[0][1].server_id, 1101)        # your faction wins a tie

    def test_not_on_ncsoft_stops_loading(self):
        svc, _ = self.make({"nae": {"Mine": [1101]}})
        self.feed(svc, self_record(100, "Mine", 1101), other_record(200, "Nobody"))
        self.assertTrue(wait_for(lambda: svc.snapshot()[0][1].status == "unresolved"))   # no endless shimmer

    def test_lookups_run_in_parallel(self):
        world = {"nae": {"Mine": [1101], **{f"P{i}": [1101] for i in range(8)}}}
        slow = FakeNcsoft(world)

        def find(name, region, classes=None, pc_ids=None, race=None):
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


class ChooseTests(unittest.TestCase):
    def c(self, sid, level, race=None):
        x = char("Ivaldi", sid)
        x.level = level
        return x

    def test_real_namesakes_and_reserved_names(self):
        # live data for "Ivaldi" (Sorcerer) in NA East: 12 level-1 reservations and two real characters
        cands = [self.c(s, 1) for s in (1101, 1102, 1103, 1105, 1106, 1107, 1108, 2104, 2105, 2106, 2107, 2108)]
        cands += [self.c(2101, 45), self.c(1104, 45)]
        self.assertIsNone(nb.choose([], None, set(), None))
        self.assertEqual(nb.choose(cands, 1104, set(), None).server_id, 1104)          # trusted game record
        self.assertEqual(nb.choose(cands, None, {1104}, None).server_id, 1104)          # seen around you
        self.assertEqual(nb.choose(cands, None, set(), 2).server_id, 2101)              # your faction
        self.assertEqual(nb.choose([self.c(2103, 4), self.c(1104, 45)], None, set(), None).server_id, 1104)
        # an invader fighting you: the enemy faction wins, even over servers seen around you
        self.assertEqual(nb.choose(cands, None, {1104}, 2, fighting=True).server_id, 2101)

    def test_background_queue_identifies_off_screen_players(self):
        find = FakeNcsoft({"nae": {"Mine": [1101], "Far": [1101]}})
        svc = nb.NearbyService(object(), find=find, cfg={"nearby_region": "nae"})
        svc.start_lookups()
        self.addCleanup(svc.stop)
        svc.on_bytes(("a", 1, "b", 2), frame(self_record(100, "Mine", 1101)) + frame(other_record(200, "Far")), False)
        self.assertTrue(wait_for(lambda: svc.snapshot()[0][1].char_id))                # never asked for by the UI


if __name__ == "__main__":
    unittest.main()


class LiveLayoutTests(unittest.TestCase):
    """Spawn records as AION 2 sent them on 2026-10-24 (bytes from a real capture near invaders)."""
    WOODOO = bytes.fromhex("4536e14001 20a00107 06 576f6f646f6f".replace(" ", "")) + bytes.fromhex(
        "200000000202 00 12f59a3a46253d52c6003eb8461f49a443a7e901b850b850810d00000400040200 31f88801040000 10".replace(" ", ""))
    SHAGRA = bytes.fromhex("4536dd0401 20a40107 06 536861677261".replace(" ", "")) + bytes.fromhex(
        "210000000101 00 d23b393946ce4b1ec6008a99468c15b343b3fe01fe48b35cf70900000400040200 31d48e01040000 10".replace(" ", ""))

    def test_faction_and_class_come_from_the_spawn_record(self):
        from shugotracker import servers as sv
        from shugotracker.protocol import PlayerSeen, StreamDecoder
        got = []
        dec = StreamDecoder(emit=got.append, known_servers=sv.KNOWN_SERVERS)
        dec.feed(frame(self.WOODOO) + frame(self.SHAGRA))
        seen = {e.name: e for e in got if isinstance(e, PlayerSeen)}
        self.assertEqual((seen["Woodoo"].race, seen["Woodoo"].pc_id, seen["Woodoo"].class_name), (2, 32, "Cleric"))
        self.assertEqual((seen["Shagra"].race, seen["Shagra"].pc_id, seen["Shagra"].class_name), (1, 33, "Chanter"))

    def test_invader_is_an_enemy_before_any_lookup(self):
        svc = nb.NearbyService(object(), find=lambda *a, **k: [], cfg={"nearby_me": ["Mine", 1104]})
        svc.on_bytes(("a", 1, "b", 2), frame(self.WOODOO) + frame(self.SHAGRA), False)
        sides = {c.name: side for side, c, _p in svc.snapshot()}
        self.assertEqual(sides, {"Woodoo": "enemy", "Shagra": "ally"})


class CapturePaddingTests(unittest.TestCase):
    def test_ethernet_padding_is_not_payload(self):
        try:
            from scapy.layers.inet import IP, TCP
            from scapy.packet import Padding, Raw
        except ImportError:
            self.skipTest("no scapy here")
        from shugotracker.capture import tcp_payload
        ack = IP(bytes(IP(src="1.1.1.1", dst="2.2.2.2") / TCP(sport=13328, dport=5000, flags="A")) + b"\0" * 6)
        self.assertEqual(tcp_payload(ack[IP], ack[TCP]), b"")
        data = IP(bytes(IP(src="1.1.1.1", dst="2.2.2.2") / TCP(sport=13328, dport=5000) / Raw(b"\x0e\x00\x36")))
        self.assertEqual(tcp_payload(data[IP], data[TCP]), b"\x0e\x00\x36")


class RecentTests(unittest.TestCase):
    def test_new_area_moves_everyone_to_recent(self):
        from tests.test_scout import gone
        svc = nb.NearbyService(object(), find=lambda *a, **k: [], cfg={"nearby_region": "nae"})
        feed = lambda *b: svc.on_bytes(("a", 1, "b", 2), b"".join(frame(x) for x in b), False)  # noqa: E731
        feed(self_record(100, "Mine", 1101), other_record(200, "Foe"), other_record(300, "Pal"), damage(100, 200))
        self.assertEqual(len(svc.snapshot()), 2)
        feed(gone(300))                                            # Pal walks out of view
        self.assertEqual([c.name for _s, c, _p in svc.snapshot()], ["Foe"])
        self.assertEqual([c.name for _s, c, _t, _f in svc.recent()], ["Pal"])
        for dec in svc._decoders.values():
            dec._self_at.clear()                                   # (the next teleport is more than 2 s later)
        feed(self_record(100, "Mine", 1101), other_record(400, "New"))   # teleport: your record is re-sent
        self.assertEqual([c.name for _s, c, _p in svc.snapshot()], ["New"])
        recent = svc.recent()
        self.assertEqual([c.name for _s, c, _t, _f in recent], ["Foe", "Pal"])    # newest first
        self.assertEqual([f for _s, _c, _t, f in recent], [True, False])          # Foe fought you
        feed(other_record(201, "Foe"))                                            # Foe shows up again:
        self.assertIn("Foe", [c.name for _s, c, _p in svc.snapshot()])            # back on Nearby,
        self.assertEqual([c.name for _s, c, _t, _f in svc.recent()], ["Foe", "Pal"])   # and still on Recent


class ArenaTests(unittest.TestCase):
    def make(self):
        svc = nb.NearbyService(object(), find=lambda *a, **k: [], cfg={"nearby_region": "nae"})
        feed = lambda *b: svc.on_bytes(("a", 1, "b", 2), b"".join(frame(x) for x in b), False)  # noqa: E731
        return svc, feed

    def names(self, svc):
        return sorted(c.name for _s, c, _p in svc.snapshot())

    def test_dying_in_the_arena_keeps_everyone(self):
        from tests.test_scout import map_load
        svc, feed = self.make()
        feed(map_load(61), self_record(100, "Mine", 1104), other_record(200, "Foe"), other_record(300, "Pal"))
        self.assertEqual(self.names(svc), ["Foe", "Pal"])
        for dec in svc._decoders.values():
            dec._self_at.clear()
        feed(map_load(61, count=2), self_record(100, "Mine", 1104))       # you died and respawned: same map
        self.assertEqual(self.names(svc), ["Foe", "Pal"])
        self.assertEqual(svc.recent(), [])

    def test_a_different_map_moves_everyone_to_recent(self):
        from tests.test_scout import map_load
        svc, feed = self.make()
        feed(map_load(61), self_record(100, "Mine", 1104), other_record(200, "Foe"))
        feed(map_load(12), other_record(400, "New"))
        self.assertEqual(self.names(svc), ["New"])
        self.assertEqual([c.name for _s, c, _t, _f in svc.recent()], ["Foe"])

    def test_fighting_brings_a_player_back_from_recent(self):
        from tests.test_scout import map_load
        svc, feed = self.make()
        feed(map_load(61), self_record(100, "Mine", 1104), other_record(200, "Foe"))
        feed(map_load(12))                                                 # (wrongly) a new map
        self.assertEqual(self.names(svc), [])
        feed(damage(100, 200))                                             # but Foe hits you
        self.assertEqual(self.names(svc), ["Foe"])
        self.assertEqual([c.name for _s, c, _t, _f in svc.recent()], ["Foe"])     # Recent keeps the history


class SelfRecordTests(unittest.TestCase):
    def test_lookalike_self_record_is_ignored(self):
        from shugotracker import servers as sv
        from shugotracker.protocol import SelfSeen, StreamDecoder, encode_varint
        got = []
        dec = StreamDecoder(emit=got.append, known_servers=sv.KNOWN_SERVERS)
        fake = b"\x33\x36" + encode_varint(500) + b"\x00" * 4 + bytes([0x01, 2]) + b"lw" + b"\x07\x00\x00\x00"
        dec.feed(frame(fake) + frame(self_record(100, "Cynica", 1104, cls=10, level=45)))
        mine = [e for e in got if isinstance(e, SelfSeen)]
        self.assertEqual([(e.name, e.server) for e in mine], [("Cynica", 1104)])


class ManualClearTests(unittest.TestCase):
    def test_clear_nearby_and_recent(self):
        svc = nb.NearbyService(object(), find=lambda *a, **k: [], cfg={"nearby_region": "nae"})
        svc.on_bytes(("a", 1, "b", 2), frame(self_record(100, "Mine", 1101)) + frame(other_record(200, "Foe"))
                     + frame(other_record(300, "Pal")), False)
        svc.clear_nearby()
        self.assertEqual(svc.snapshot(), [])
        self.assertEqual(sorted(c.name for _s, c, _t, _f in svc.recent()), ["Foe", "Pal"])
        svc.on_bytes(("a", 1, "b", 2), frame(damage(100, 200)), False)       # Foe is still here, fighting
        self.assertEqual([c.name for _s, c, _p in svc.snapshot()], ["Foe"])
        svc.clear_recent()
        self.assertEqual(svc.recent(), [])


class ComingBackTests(unittest.TestCase):
    def make(self):
        svc = nb.NearbyService(object(), find=lambda *a, **k: [], cfg={"nearby_region": "nae"})
        feed = lambda *b: svc.on_bytes(("a", 1, "b", 2), b"".join(frame(x) for x in b), False)  # noqa: E731
        return svc, feed

    def names(self, svc):
        return sorted(c.name for _s, c, _p in svc.snapshot())

    def test_same_player_walking_back_into_view_returns(self):
        # v1.25 and earlier: a re-sent spawn record (same entity id) was dropped as a duplicate forever
        from shugotracker import protocol as P
        from tests.test_scout import gone
        old, P.SPAWN_DEDUPE_S = P.SPAWN_DEDUPE_S, 0.0             # (the walk back takes longer than 2 s)
        self.addCleanup(setattr, P, "SPAWN_DEDUPE_S", old)
        svc, feed = self.make()
        feed(self_record(100, "Mine", 1101), other_record(300, "Pal"))
        feed(gone(300))
        self.assertEqual(self.names(svc), [])
        feed(other_record(300, "Pal"))                             # Pal walks back: the game re-sends them
        self.assertEqual(self.names(svc), ["Pal"])
        self.assertEqual([c.name for _s, c, _t, _f in svc.recent()], ["Pal"])

    def test_cleared_players_still_around_come_back(self):
        from shugotracker.protocol import encode_varint
        svc, feed = self.make()
        feed(self_record(100, "Mine", 1101), other_record(200, "Foe"), other_record(300, "Pal"))
        svc.clear_nearby()
        self.assertEqual(self.names(svc), [])
        feed(b"\x1d\x37" + encode_varint(300) + b"\x00" * 12)       # any update about Pal: Pal's still here
        self.assertEqual(self.names(svc), ["Pal"])
        self.assertEqual(sorted(c.name for _s, c, _t, _f in svc.recent()), ["Foe", "Pal"])

    def test_left_behind_players_dont_come_back_on_an_id_match(self):
        from shugotracker.protocol import encode_varint
        from tests.test_scout import map_load
        svc, feed = self.make()
        feed(map_load(61), self_record(100, "Mine", 1101), other_record(300, "Pal"))
        feed(map_load(12))                                         # a new area: 300 is someone else here
        feed(b"\x1d\x37" + encode_varint(300) + b"\x00" * 12)
        self.assertEqual(self.names(svc), [])


class CaptureFilterTests(unittest.TestCase):
    def test_new_servers_on_the_game_port_are_heard_at_once(self):
        try:
            from shugotracker.capture import bpf_for
        except ImportError as e:  # psutil missing here
            self.skipTest(str(e))
        flt = bpf_for({("10.0.0.2", 61217, "193.202.112.5", 13328), ("10.0.0.2", 64951, "64.25.35.157", 443)})
        self.assertIn("src port 13328", flt)                       # any host: Shugo / arena servers included
        self.assertNotIn("src host 193.202.112.5", flt)
        self.assertIn("src host 64.25.35.157 and src port 443 and dst port 64951", flt)   # web ports stay exact
        # a second world server on the same port doesn't change the filter (so no sniffer restart)
        self.assertEqual(flt, bpf_for({("10.0.0.2", 61217, "193.202.112.5", 13328),
                                       ("10.0.0.2", 50961, "193.202.112.39", 13328),
                                       ("10.0.0.2", 64951, "64.25.35.157", 443)}))
