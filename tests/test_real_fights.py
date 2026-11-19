"""Real fights, replayed: short cuts of the author's own Nearby recordings (tools/distill_recording.py keeps only the
records Shugo Tracker reads). Each must give exactly the PVP Log entries that really happened. When the game
changes and a fight goes missing, a new recording cut the same way shows what moved."""
import os
import struct
import unittest
from unittest import mock

from shugotracker import nearby as nb
from tools.distill_recording import read

HERE = os.path.join(os.path.dirname(__file__), "fixtures")


def replay(name: str, svc_out: list | None = None) -> list[tuple]:
    got, clock = [], [0.0]
    with mock.patch("time.time", lambda: clock[0]):
        svc = nb.NearbyService(object(), find=lambda *a, **k: [], cfg={"nearby_region": "nae", "nearby_me": ["Cynica", 1104]})
        svc.set_me("Cynica", 1104)
        svc.on_pvp = lambda kind, foe, with_, by=None, duel=False: got.append(
            (kind, foe.name) + ((f"by {by}",) if by else ()) + (("duel",) if duel else ()))
        for ts, gap, key, data in read(os.path.join(HERE, name)):
            clock[0] = ts
            svc.on_bytes(tuple(key.decode().split("|")), data, bool(gap))
    if svc_out is not None:
        svc_out.append(svc)
    return got


class RealFights(unittest.TestCase):
    def test_arena(self):
        # Nov 17 morning, arena: the killer isn't named there, the killing skill tells who it was
        self.assertEqual(replay("arena_2026-11-17.bin"), [
            ("death", "Tisander"), ("death", "Tisander"), ("death", "Tisander"),
            ("kill", "Compa"), ("kill", "Compa"), ("kill", "Compa"),
            ("death", "Tisander"), ("kill", "Tisander"), ("kill", "Tisander"), ("death", "Tisander"), ("kill", "Tisander")])

    def test_recent_remembers_the_area(self):
        # the second arena loaded as map 60; the first one (Compa) came without a map load, so it's unknown
        out = []
        replay("arena_2026-11-17.bin", out)
        self.assertEqual(out[0].area_of("Tisander"), 60)
        self.assertIsNone(out[0].area_of("Compa"))

    def test_open_world(self):
        # Nov 17 evening: the kill record names the killer outright
        self.assertEqual(replay("open_world_2026-11-17.bin"), [("assist", "Exodos", "by Jinsoyun"), ("death", "explosion")])

    def test_duel_and_abyss(self):
        # Nov 18: lost a duel to Cito, then Riddle killed you in the Abyss
        self.assertEqual(replay("duel_abyss_2026-11-18.bin"), [("death", "Cito", "duel"), ("death", "Riddle")])

    def test_pve_is_not_pvp(self):
        # Nov 15: hundreds of monster kills around you, none of them PvP
        self.assertEqual(replay("pve_2026-11-15.bin"), [])


if __name__ == "__main__":
    unittest.main()
