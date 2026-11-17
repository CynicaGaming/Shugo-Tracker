"""PvP Log: telling kills, assists and deaths apart from the game's hit and death records, and the log file."""
import os
import struct
import tempfile
import unittest

from shugotracker import nearby as nb
from shugotracker.protocol import encode_varint
from shugotracker.pvplog import PvpLog, foe_id
from tests.test_scout import damage, frame, other_record, self_record


def death(eid, skill=12010000):
    """The game's kill record: 04 8D <id> <killing skill> <12 zero bytes> 01 02."""
    return b"\x04\x8d" + encode_varint(eid) + struct.pack("<I", skill) + b"\x00" * 12 + b"\x01\x02"


class DetectTests(unittest.TestCase):
    def setUp(self):
        self.got = []
        self.svc = nb.NearbyService(object(), find=lambda *a, **k: [], cfg={"nearby_region": "nae"})
        self.svc.on_pvp = lambda kind, foe, with_, by=None: self.got.append((kind, foe.name, with_) + ((by,) if by else ()))
        self.feed(self_record(100, "Mine", 1101), other_record(200, "Foe"), other_record(300, "Pal"))

    def feed(self, *bodies):
        self.svc.on_bytes(("a", 1, "b", 2), b"".join(frame(b) for b in bodies), False)

    def test_your_last_hit_is_a_kill(self):
        self.feed(damage(200, 300), damage(200, 100), death(200))
        self.assertEqual(self.got, [("kill", "Foe", ["Pal"])])

    def test_someone_elses_last_hit_is_an_assist(self):
        self.feed(damage(200, 100), damage(200, 300), death(200))
        self.assertEqual(self.got, [("assist", "Foe", ["Pal"], "Pal")])

    def test_the_last_player_to_hit_you_killed_you(self):
        self.feed(damage(100, 300), damage(100, 200), damage(100, 9999), death(100))   # 9999: a monster
        self.assertEqual(self.got, [("death", "Foe", ["Pal"])])

    def test_not_pvp(self):
        self.feed(damage(100, 9999), death(100))           # a monster killed you
        self.feed(damage(300, 200), death(300))            # a fight you weren't in
        self.feed(damage(200, 100, skill=5), b"\x04\x8d" + encode_varint(200) + b"\x01\x02\x03\x04"
                  + encode_varint(300) + struct.pack("<H", 1101) + b"\x03Pal" + b"\x00" * 8)   # loot, not a death
        self.assertEqual(self.got, [])

    def test_the_killing_skill_names_the_killer(self):
        # Pal hit last, but with another skill: the killing blow was yours
        self.feed(damage(200, 100, skill=777), damage(200, 300, skill=5), death(200, skill=777))
        self.assertEqual(self.got, [("kill", "Foe", ["Pal"])])

    def test_one_death_counts_once(self):
        self.feed(damage(200, 100), death(200), death(200))
        self.assertEqual(len(self.got), 1)


class LogTests(unittest.TestCase):
    def test_saved_summed_and_filtered(self):
        path = os.path.join(tempfile.mkdtemp(), "pvp_log.jsonl")
        log = PvpLog(path)
        foe = {"name": "Foe", "server_id": 2101, "class_name": "Gladiator"}
        log.add("kill", "Mine", foe, t=1000)
        log.add("death", "Mine", foe, t=2000)
        log.add("kill", "Alt", foe, t=3000)                 # another of your characters
        log.add("assist", "Mine", {"name": "Other", "server_id": 2102}, t=4000, with_=["Pal"])
        with open(path, "a", encoding="utf-8") as f:
            f.write('{"t": 5000, "kind": "ki')               # cut off by a crash
        again = PvpLog(path)
        self.assertEqual(len(again.records), 4)
        s = again.summary("Mine")
        self.assertEqual([r["foe"]["name"] for r in s["foes"]], ["Other", "Foe"])
        self.assertEqual(s["totals"], {"kill": 1, "assist": 1, "death": 1})
        self.assertEqual(again.summary("Mine", since=1500)["totals"]["kill"], 0)
        d = again.detail(foe_id(foe), "Mine")
        self.assertEqual([r["kind"] for r in d["fights"]], ["death", "kill"])
        self.assertEqual(again.detail(foe_id(foe))["totals"]["kill"], 2)


if __name__ == "__main__":
    unittest.main()
