"""Offline tests on synthetic AION 2 streams. Run: python -m unittest discover tests"""
import random
import struct
import unittest

from shugotracker import servers as sv
from shugotracker.lz4block import compress_literals, decompress_py
from shugotracker.protocol import (EntityGone, Hit, MapLoaded, OwnerRecord, PlayerSeen, SelfSeen, StreamDecoder,
                                 encode_varint, read_varint)
from shugotracker.reassembly import TcpStream
from shugotracker.shugo import parse_profile, profile_url
from shugotracker.tracker import (ALLY, ENEMY, PRIO_ALLY, PRIO_COMBAT, PRIO_ENEMY, PRIO_UNKNOWN, UNKNOWN,
                               Lookup, Tracker)


def frame(body: bytes) -> bytes:
    return encode_varint(len(body) + 4) + body


def name_field(name: str) -> bytes:
    b = name.encode()
    return bytes([0x01, len(b)]) + b


def self_record(eid, name, server, cls=9, level=45):
    return (b"\x33\x36" + encode_varint(eid) + b"\x00\x00\x00\x00" + name_field(name)
            + struct.pack("<HIBI", server, cls, 0, level) + b"\x00" * 24)


def other_record(eid, name, cls=21, tail=b""):
    return (b"\x45\x36" + encode_varint(eid) + b"\x10\x00\x00\x00" + name_field(name)
            + struct.pack("<I", cls) + tail)


def damage(target, actor, skill=12010000):
    return (b"\x04\x38" + encode_varint(target) + encode_varint(0x05) + encode_varint(0)
            + encode_varint(actor) + struct.pack("<I", skill) + b"\x00" * 20)


def ownership(ent, owner, server, name):
    nb = name.encode()
    return (b"\x04\x8d" + encode_varint(ent) + b"\x01\x02\x03\x04" + encode_varint(owner)
            + struct.pack("<H", server) + bytes([len(nb)]) + nb + b"\x00" * 4)


def death(eid, flag):
    return b"\x42\x36" + encode_varint(eid) + encode_varint(0) + encode_varint(flag)


def gone(eid):
    return b"\x35\x36" + encode_varint(eid) + b"\x01"


def map_load(map_id, count=1):
    return b"\x21\x36" + struct.pack("<II", count, map_id) + b"\x00" * 4


def bundle(inner: bytes) -> bytes:
    return frame(b"\xff\xff" + struct.pack("<I", len(inner)) + compress_literals(inner))


class ProtocolTests(unittest.TestCase):
    def decode(self, stream: bytes, segment=37, shuffle=False):
        events = []
        dec = StreamDecoder(events.append, sv.KNOWN_SERVERS)
        tcp = TcpStream()
        segs = [(1000 + i, stream[i:i + segment]) for i in range(0, len(stream), segment)]
        if shuffle:
            rnd = random.Random(7)
            for k in range(1, len(segs) - 1, 3):  # swap neighbours: out-of-order arrival
                if rnd.random() < .7:
                    segs[k], segs[k + 1] = segs[k + 1], segs[k]
            segs.insert(4, segs[2])  # a retransmit
        for seq, data in segs:
            out, gap = tcp.push(seq, data, 0.0)
            self.assertFalse(gap)
            dec.feed(out)
        return events

    def test_varint(self):
        for v in (0, 1, 127, 128, 300, 13978, 9_999_999):
            self.assertEqual(read_varint(encode_varint(v), 0), (v, len(encode_varint(v))))

    def test_lz4_roundtrip_literals(self):
        data = bytes(range(256)) * 3
        self.assertEqual(decompress_py(compress_literals(data), len(data)), data)

    def test_lz4_match_copy(self):
        # token: 3 literals 'abc', match offset 3 len 4+5 -> 'abcabcabcabc', final 1-literal sequence
        block = bytes([0x35]) + b"abc" + b"\x03\x00" + bytes([0x10]) + b"!"
        self.assertEqual(decompress_py(block, 13), b"abcabcabcabc!")

    def test_full_stream(self):
        stream = b"".join([
            b"\x00\x00",  # padding
            bytes([0x17, 0x03, 0x03, 0x00, 0x05]) + b"TLS!!",  # TLS record to skip
            frame(self_record(501, "Aerin", 1101)),
            frame(other_record(9001, "Morg", tail=b"\x00" * 6)),
            bundle(frame(other_record(9002, "Kesh", cls=17, tail=b"\x07\x00" + struct.pack("<H", 2101)))
                   + frame(damage(501, 9001))),
            frame(damage(9002, 501)),
            frame(b"\x99\x99" + ownership(20500, 777, 1101, "Friendo")),
            frame(other_record(9003, "Tal" + "é" + "a")),
            frame(death(9001, 3)),
            bundle(frame(death(9002, 0)) + frame(gone(9003))),
            frame(map_load(1010)),
        ])
        for shuffle in (False, True):
            ev = self.decode(stream, shuffle=shuffle)
            selfs = [e for e in ev if isinstance(e, SelfSeen)]
            players = {e.name: e for e in ev if isinstance(e, PlayerSeen)}
            hits = [e for e in ev if isinstance(e, Hit)]
            owners = [e for e in ev if isinstance(e, OwnerRecord)]
            self.assertEqual(selfs, [SelfSeen(501, "Aerin", 1101, "Templar", 45)])
            self.assertEqual(players["Morg"].server, None)
            self.assertEqual(players["Morg"].class_name, "Elementalist")
            self.assertEqual(players["Kesh"].server, 2101)
            self.assertEqual(players["Kesh"].server_source, "scan")
            self.assertEqual(players["Kesh"].class_name, "Assassin")
            self.assertIn("Taléa", players)
            self.assertIn(Hit(9001, 501), hits)
            self.assertIn(Hit(501, 9002), hits)
            self.assertEqual(owners, [OwnerRecord(777, "Friendo", 1101)])
            self.assertIn(EntityGone(9001, True), ev)
            self.assertIn(EntityGone(9002, False), ev)
            self.assertIn(EntityGone(9003, False), ev)
            self.assertEqual(ev[-1], MapLoaded(1010))

    def test_garbage_does_not_crash(self):
        rnd = random.Random(1)
        dec = StreamDecoder(lambda e: None, sv.KNOWN_SERVERS)
        for _ in range(200):
            dec.feed(bytes(rnd.randrange(256) for _ in range(rnd.randrange(1, 400))))


class ServerTests(unittest.TestCase):
    def test_paths(self):
        self.assertEqual(sv.shugo_server_path(1101), "global/nae-siel")
        self.assertEqual(sv.shugo_server_path(2501), "global/as-israphel")
        self.assertEqual(sv.shugo_server_path(2311), "global/eu-ludra")
        self.assertEqual(sv.shugo_server_path(1404), "global/la-kaisinel")
        self.assertEqual(sv.mirror_server(1101), 2101)
        self.assertEqual(sv.parse_server("nae-siel"), 1101)
        self.assertEqual(sv.parse_server("EU Ludra"), 2311)
        self.assertEqual(profile_url("Bloody丶Mia", 1101),
                         "https://shugo.gg/character/global/nae-siel/Bloody%E4%B8%B6Mia")


PAGE = """<html><head><meta name="description" content="Luna: AION 2 Level 45 Elyos Templar (2,465 GS) of the legion Power on Siel (Global).">
</head><body><h1>Luna - AION 2 character profile</h1>
<p>Luna is an AION 2 character on Siel (Global, North America - East). Level 45 · Templar · Elyos · Legion: Power ·
Gear score 2,465 · Combat power 113,407.</p></body></html>"""


class ShugoTests(unittest.TestCase):
    def test_parse(self):
        d = parse_profile(PAGE)
        self.assertEqual(d["gear_score"], 2465)
        self.assertEqual(d["combat_power"], 113407)
        self.assertEqual(d["level"], 45)
        self.assertEqual(d["class_name"], "Templar")
        self.assertEqual(d["faction"], sv.ELYOS)
        self.assertEqual(d["legion"], "Power")

    def test_parse_asmodian(self):
        d = parse_profile(PAGE.replace("Elyos", "Asmodians"))
        self.assertEqual(d["faction"], sv.ASMODIAN)

    def test_parse_title_and_leaderboard(self):
        page = ("<p>Level 45 · Ranger · Asmodians · Legion: X · Gear score 2,826 · Title: Treading on White Wings · "
                "Combat power 170,729.</p><h2>Top Combat Power on Israphel</h2><td>Combat power 999,999</td>")
        d = parse_profile(page)
        self.assertEqual((d["gear_score"], d["combat_power"]), (2826, 170729))

    def test_parse_missing(self):
        self.assertIsNone(parse_profile("<html>Character not found</html>"))


class TrackerTests(unittest.TestCase):
    def setUp(self):
        self.reqs = []
        self.t = Tracker(lambda n, p, c, g: self.reqs.append((n, p, c, g)), my_server=None)

    def last(self, name):
        return [r for r in self.reqs if r[0] == name][-1]

    def test_flow(self):
        t = self.t
        t.handle(SelfSeen(501, "Aerin", 1101, "Templar", 45), now=1)
        self.assertEqual(self.reqs[-1], ("Aerin", PRIO_COMBAT, [1101], False))  # own reference CP

        t.handle(PlayerSeen(9001, "Morg", None, None, "Elementalist"), now=2)  # unknown: own server, then enemy
        self.assertEqual(self.last("Morg"), ("Morg", PRIO_UNKNOWN, [1101, 2101], True))
        self.assertEqual(t.side(t.players["Morg"]), UNKNOWN)

        t.handle(PlayerSeen(9002, "Ally", 1101, "record", "Cleric"), now=2)   # same faction from the record
        self.assertEqual(self.last("Ally"), ("Ally", PRIO_ALLY, [1101], False))
        self.assertEqual(t.side(t.players["Ally"]), ALLY)

        t.handle(PlayerSeen(9004, "Rival", 2101, "record", "Ranger"), now=3)
        self.assertEqual(self.last("Rival"), ("Rival", PRIO_ENEMY, [2101], False))

        t.handle(OwnerRecord(777, "FarAway", 2101), now=3)                     # not in view: ignored
        self.assertNotIn("FarAway", t.players)

        t.handle(Hit(9001, 501), now=4)                                       # Morg hits you
        self.assertEqual(self.last("Morg")[:3], ("Morg", PRIO_COMBAT, [2101, 1101]))
        self.assertEqual(t.side(t.players["Morg"]), ENEMY)

        t.apply_lookup("Morg", Lookup(status="ok", server=2101, combat_power=90000, faction=sv.ASMODIAN,
                                      guessed=True), [2101])
        g = t.groups()
        self.assertEqual([p.name for p in g[ENEMY]], ["Morg", "Rival"])
        self.assertEqual([p.name for p in g[ALLY]], ["Ally"])

        t.handle(EntityGone(9004, died=True), now=5)                           # died: stays, marked
        self.assertTrue(t.players["Rival"].dead)
        t.handle(EntityGone(9002, died=False), now=5)                          # left view: removed
        self.assertNotIn("Ally", t.players)

        t.handle(MapLoaded(1010), now=6)                                       # zone change wipes the list
        self.assertEqual(t.players, {})
        self.assertEqual(t.me.name, "Aerin")

    def test_expire_safety_net(self):
        t = self.t
        t.handle(PlayerSeen(5, "Xan", None, None, None), now=1)
        t.expire(now=100)
        self.assertIn("Xan", t.players)
        t.expire(now=1000)
        self.assertNotIn("Xan", t.players)

    def test_my_server_from_config(self):
        t = Tracker(lambda *a: self.reqs.append(a), my_server=2311)
        t.handle(PlayerSeen(5, "Xan", None, None, None), now=1)
        self.assertEqual(self.reqs[-1], ("Xan", PRIO_UNKNOWN, [2311, 1311], True))

    def test_allies_lookup_off(self):
        t = Tracker(lambda *a: self.reqs.append(a), my_server=1101, lookup_allies=False)
        t.handle(PlayerSeen(5, "Pal", 1101, "record", None), now=1)
        self.assertEqual(self.reqs, [])


class ReassemblyTests(unittest.TestCase):
    def test_gap_timeout(self):
        s = TcpStream(gap_timeout_s=1)
        self.assertEqual(s.push(100, b"abc", 0), (b"abc", False))
        self.assertEqual(s.push(110, b"xyz", 0.5), (b"", False))     # hole at 103..109
        out, gap = s.push(113, b"!", 2.0)
        self.assertTrue(gap)
        self.assertEqual(out, b"xyz!")

    def test_wraparound(self):
        s = TcpStream()
        start = (1 << 32) - 2
        self.assertEqual(s.push(start, b"ab", 0)[0], b"ab")
        self.assertEqual(s.push(0, b"cd", 0)[0], b"cd")


if __name__ == "__main__":
    unittest.main()
