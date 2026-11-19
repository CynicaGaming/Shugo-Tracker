"""Cut a Nearby recording (logs\\diagnostics\\nearby_*.bin) down to a test fixture.

Keeps only a time window, and only the game records Shugo Tracker reads: identities, damage, kills, deaths,
map loads, scoreboards and duels. Everything else (chat, movement, inventory…) is dropped, and compressed
bundles are unpacked into plain records, so the fixture is small and holds nothing but what the decoder uses.
Each kept record is written with its original time and connection, so replaying it behaves like the real thing.

    python -m tools.distill_recording IN.bin OUT.bin 2026-11-17T06:35:50 2026-11-17T06:47:00
"""
from __future__ import annotations

import struct
import sys
import time

from shugotracker import protocol as P
from shugotracker import servers as sv
from shugotracker.nearby import RECORD_MAGIC

KEEP = [bytes.fromhex(x) for x in ("0438", "3336", "4436", "4536", "048d", "4236", "3536", "2136", "0360", "0b94")]
MARKERS = (b"\x33\x36", b"\x44\x36", b"\x45\x36", b"\x04\x8d")   # identity / kill records found mid-packet


def read(path: str):
    """(time, gap, connection key, bytes) for every record, in order."""
    blob = open(path, "rb").read()
    for chunk in blob.split(RECORD_MAGIC)[1:]:
        o = 0
        while o + 11 <= len(chunk):
            ts, gap, klen = struct.unpack_from("<dBH", chunk, o)
            o += 11
            if klen > 200 or o + klen + 4 > len(chunk):
                break
            key = chunk[o:o + klen]
            o += klen
            (dl,) = struct.unpack_from("<I", chunk, o)
            o += 4
            if o + dl > len(chunk):
                break
            yield ts, gap, key, chunk[o:o + dl]
            o += dl


class _Collector(P.StreamDecoder):
    """A decoder that hands over every plain record it meets (bundles unpacked) instead of decoding them."""

    def __init__(self):
        super().__init__(emit=lambda e: None, known_servers=sv.KNOWN_SERVERS)
        self.out: list[bytes] = []

    def _packet(self, packet, body_off):
        self.out.append(bytes(packet))
        self._scan_embedded_bundles(packet)

    def _bundle(self, payload, depth=0):
        data = P.decompress_bundle(payload)
        if data is None or depth > 4:
            return
        for f in P.walk_inner(data):
            inner = data[f.start:f.end]
            if f.bundle:
                self._bundle(inner[f.payload_start:], depth + 1)
            else:
                self.out.append(bytes(inner))

    def _scan_self(self, buf):
        # your own record can straddle two records of the stream: keep it as a record of its own
        for code in self.op.self_record:
            i = buf.find(code)
            while i >= 0:
                if self._parse_identity(buf, i + len(code), True):
                    body = bytes(buf[i:i + 96])               # (the raw bytes, as the parser read them)
                    self.out.append(P.encode_varint(len(body) + 4) + body)
                i = buf.find(code, i + 1)


def wanted(rec: bytes) -> bool:
    _v, vlen = P.read_varint(rec, 0)
    if vlen <= 0:
        return False
    head = rec[vlen:vlen + 2]
    return head in KEEP or any(m in rec for m in MARKERS)


def distill(src: str, dst: str, start: float, end: float) -> tuple[int, int]:
    collectors: dict[bytes, _Collector] = {}
    kept = total = 0
    with open(dst, "wb") as out:
        out.write(RECORD_MAGIC)
        for ts, gap, key, data in read(src):
            c = collectors.setdefault(key, _Collector())
            if gap:
                c.reset()
            c.out.clear()
            c.feed(data)
            if not start <= ts <= end:
                continue
            for rec in c.out:
                total += 1
                if wanted(rec):
                    kept += 1
                    out.write(struct.pack("<dBH", ts, 0, len(key)) + key + struct.pack("<I", len(rec)) + rec)
    return kept, total


def _when(s: str) -> float:
    return time.mktime(time.strptime(s, "%Y-%m-%dT%H:%M:%S"))


if __name__ == "__main__":
    src, dst, a, b = sys.argv[1:5]
    k, t = distill(src, dst, _when(a), _when(b))
    print(f"kept {k} of {t} records -> {dst}")
