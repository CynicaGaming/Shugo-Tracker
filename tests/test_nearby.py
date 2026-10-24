"""Nearby service on synthetic game traffic, with NCSOFT lookups faked."""
import os
import tempfile
import threading
import time
import unittest

from shugotracker import nearby as nb
from shugotracker.aion2api import Character
from shugotracker.tracker import ALLY, ENEMY
from tests.test_scout import damage, frame, other_record, ownership, self_record


class FakeApi:
    def __init__(self):
        self.calls = []
        self.lock = threading.Lock()

    def find_player(self, name, server_id):
        with self.lock:
            self.calls.append((name, server_id))
        if name == "Ghost":
            return None
        return Character(char_id=f"id-{name}", name=name, race=server_id // 1000, pc_id=10, level=45,
                         server_id=server_id, server_name="Srv", region="nae")


def wait_for(cond, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


class NearbyServiceTests(unittest.TestCase):
    def make(self):
        api = FakeApi()
        svc = nb.NearbyService(api, data_dir=tempfile.mkdtemp())
        svc.start_lookups()
        self.addCleanup(svc.stop)
        return svc, api

    def feed(self, svc, *bodies):
        svc.on_bytes(("1.2.3.4", 7777, "10.0.0.2", 5000), b"".join(frame(b) for b in bodies), False)

    def test_enemies_and_allies_are_resolved(self):
        svc, api = self.make()
        v0 = svc.version()
        # me on Siel (Elyos, 1101); an Asmodian attacker named on Israphel (2101) and an Elyos ally on Siel
        self.feed(svc, self_record(100, "Mine", 1101),
                  other_record(200, "Foe"), ownership(5000, 200, 2101, "Foe"),
                  other_record(300, "Friend"), ownership(5001, 300, 1101, "Friend"),
                  damage(100, 200))
        self.assertNotEqual(svc.version(), v0)
        self.assertTrue(wait_for(lambda: all(c.char_id for _, c, _ in svc.snapshot())))
        snap = {c.name: side for side, c, _ in svc.snapshot()}
        self.assertEqual(snap, {"Foe": ENEMY, "Friend": ALLY})
        self.assertEqual(svc.snapshot()[0][1].name, "Foe")          # enemies first
        self.assertIn(("Foe", 2101), api.calls)
        self.assertEqual([sid for n, sid in api.calls if n == "Foe"], [2101])   # server known: one lookup
        self.assertEqual(svc.counts()[ENEMY], 1)

    def test_unknown_player_gets_placeholder_then_unresolved(self):
        svc, api = self.make()
        self.feed(svc, self_record(100, "Mine", 1101), other_record(400, "Ghost"), ownership(5002, 400, 2101, "Ghost"))
        side, c, p = svc.snapshot()[0]
        self.assertEqual((c.name, c.char_id), ("Ghost", ""))      # shown at once, before NCSOFT answers
        self.assertTrue(wait_for(lambda: svc.snapshot()[0][1].status == "unresolved"))

    def test_recording_roundtrip(self):
        svc, _ = self.make()
        path = svc.start_recording(5)
        self.feed(svc, self_record(100, "Mine", 1101), other_record(200, "Foe"))
        svc.stop_recording()
        got = []
        n = nb.replay_recording(path, lambda flow, data, gap: got.append((flow, data, gap)))
        self.assertEqual(n, 1)
        self.assertEqual(got[0][0], ("1.2.3.4", "7777", "10.0.0.2", "5000"))
        self.assertTrue(os.path.getsize(path) > 20)

    def test_start_without_npcap(self):
        svc = nb.NearbyService(FakeApi())
        if nb.npcap_installed():
            self.skipTest("Npcap is installed here")
        svc.start()
        self.assertEqual(svc.state, nb.NO_NPCAP)


if __name__ == "__main__":
    unittest.main()


class GuessTests(unittest.TestCase):
    def test_namesake_on_my_server_is_not_mistaken_for_the_player(self):
        calls = []

        def find(name, sid):
            calls.append((name, sid))
            # "Ash" exists on my server (1101) AND on the enemy server (2101)
            return Character(char_id=f"{name}-{sid}", name=name, race=sid // 1000, pc_id=10, level=45,
                             server_id=sid, server_name="S", region="nae")
        svc = nb.NearbyService(FakeApi(), find=find)
        svc.start_lookups()
        self.addCleanup(svc.stop)
        feed = lambda *b: svc.on_bytes(("a", 1, "b", 2), b"".join(frame(x) for x in b), False)  # noqa: E731
        feed(self_record(100, "Mine", 1101), other_record(200, "Ash"))       # server not known yet
        time.sleep(0.3)
        feed(ownership(5000, 200, 2101, "Ash"))                               # ...and here it is
        self.assertTrue(wait_for(lambda: svc.snapshot()[0][1].char_id != "", timeout=5))
        side, c, _ = svc.snapshot()[0]
        self.assertEqual((side, c.server_id), (ENEMY, 2101))
        self.assertEqual([sid for n, sid in calls if n == "Ash"], [2101])       # never guessed on 1101
