"""
Decoder for the server -> client side of the AION 2 game stream.

Only what Shugo Tracker needs is decoded: player identities (names, servers, classes),
damage records (to spot who is fighting you) and ownership/kill records (which also
carry a player's server). The wire layout was worked out by the community DPS-meter
projects (A2Tools-DPS-Meter, AIon2-Dps-Meter, aion2-dps-meter, Aion2DPSMeter - all GPL-3.0);
this is an independent Python implementation of that published knowledge.

Wire shape of the stream:
    00 ...                                  padding, skipped
    17 03 03 <u16 len> ...                  a TLS record, skipped
    <varint len> <body>                     a packet; len = body length + 4
    <varint len> FF FF <u32 size> <lz4>     a compressed bundle of further packets
Every body starts with a 2-byte opcode. Game patches shift opcodes, so they are
configurable (see Opcodes / config.json).
"""
from __future__ import annotations

import struct
import unicodedata
from dataclasses import dataclass, field
from typing import Callable, Iterator

from .lz4block import decompress as lz4_decompress

MAX_ENTITY_ID = 9_999_999
MAX_PACKET = 65_535
MAX_FRAGMENT_WAIT = 16_384
MAX_DECOMPRESSED = 1_000_000


# ───────────────────────── events ─────────────────────────

@dataclass(frozen=True)
class SelfSeen:
    entity_id: int
    name: str
    server: int | None
    class_name: str | None
    level: int | None


@dataclass(frozen=True)
class PlayerSeen:
    entity_id: int
    name: str
    server: int | None
    server_source: str | None  # "record" (trusted layout) or "scan" (heuristic)
    class_name: str | None
    race: int | None = None     # 1 Elyos / 2 Asmodian, straight from the spawn record (Oct 2026 layout)
    pc_id: int | None = None    # exact class id (same numbers as NCSOFT's pcId)


@dataclass(frozen=True)
class OwnerRecord:
    """A kill/ownership record naming a player with their server."""
    entity_id: int
    name: str
    server: int


@dataclass(frozen=True)
class Hit:
    actor_id: int
    target_id: int


@dataclass(frozen=True)
class EntityGone:
    """An entity died (died=True) or left view (died=False)."""
    entity_id: int
    died: bool


@dataclass(frozen=True)
class MapLoaded:
    """You loaded a map (zone change or teleport): everything in view will be re-sent."""
    map_id: int


Event = SelfSeen | PlayerSeen | OwnerRecord | Hit | EntityGone | MapLoaded


# ───────────────────────── opcodes ─────────────────────────

@dataclass
class Opcodes:
    damage: list[str] = field(default_factory=lambda: ["04 38"])
    self_record: list[str] = field(default_factory=lambda: ["33 36"])
    player_spawn: list[str] = field(default_factory=lambda: ["44 36", "45 36"])
    ownership: list[str] = field(default_factory=lambda: ["04 8D"])
    death: list[str] = field(default_factory=lambda: ["42 36"])          # id, varint, flag (1/3 = dead)
    object_gone: list[str] = field(default_factory=lambda: ["35 36"])    # id, reason: left view
    map_load: list[str] = field(default_factory=lambda: ["21 36"])       # u32 load count, u32 map id

    def compiled(self) -> "CompiledOpcodes":
        def parse(codes: list[str]) -> tuple[bytes, ...]:
            return tuple(bytes(int(h, 16) for h in c.split()) for c in codes if c.strip())
        return CompiledOpcodes(parse(self.damage), parse(self.self_record),
                               parse(self.player_spawn), parse(self.ownership),
                               parse(self.death), parse(self.object_gone), parse(self.map_load))


@dataclass(frozen=True)
class CompiledOpcodes:
    damage: tuple[bytes, ...]
    self_record: tuple[bytes, ...]
    player_spawn: tuple[bytes, ...]
    ownership: tuple[bytes, ...]
    death: tuple[bytes, ...]
    object_gone: tuple[bytes, ...]
    map_load: tuple[bytes, ...]


def _at(data: bytes, i: int, codes: tuple[bytes, ...]) -> bool:
    return any(data.startswith(c, i) for c in codes)


# ───────────────────────── primitives ─────────────────────────

def read_varint(b: bytes, off: int) -> tuple[int, int]:
    """LEB128 varint at off -> (value, byte_length); (-1, -1) when invalid/truncated."""
    value = shift = 0
    i = off
    n = len(b)
    while True:
        if i < 0 or i >= n:
            return -1, -1
        c = b[i]
        i += 1
        value |= (c & 0x7F) << shift
        if not c & 0x80:
            return value, i - off
        shift += 7
        if shift >= 32:
            return -1, -1


def encode_varint(value: int) -> bytes:
    out = bytearray()
    while True:
        b = value & 0x7F
        value >>= 7
        if value:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def frame_size(value: int, vlen: int) -> int | None:
    size = value - 4 + vlen
    return size if size >= vlen and size > 0 else None


def u16(b: bytes, o: int) -> int:
    return b[o] | (b[o + 1] << 8)


def u32(b: bytes, o: int) -> int:
    return struct.unpack_from("<I", b, o)[0]


CLASS_RANGES = [
    (5, 8, "Gladiator"), (9, 12, "Templar"), (13, 16, "Ranger"), (17, 20, "Assassin"),
    (21, 24, "Elementalist"), (25, 28, "Sorcerer"), (29, 32, "Cleric"), (33, 36, "Chanter"),
    (45, 48, "Brawler"),
]


def class_from_wire(v: int) -> str | None:
    for lo, hi, name in CLASS_RANGES:
        if lo <= v <= hi:
            return name
    return None


def decode_name(field_bytes: bytes) -> str | None:
    """A character name: 1-12 letters/digits in any script, at least one letter."""
    try:
        s = field_bytes.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return None
    if not 1 <= len(s) <= 12:
        return None
    if not all(ch.isalnum() for ch in s):
        return None
    if not any(unicodedata.category(ch).startswith("L") for ch in s):
        return None
    return s


def is_placeholder_name(field_bytes: bytes) -> bool:
    return len(field_bytes) >= 5 and field_bytes[:1] == b"$" and field_bytes[1:].isalnum()


def tls_record_size(b: bytes, o: int) -> int | None:
    if len(b) - o < 5 or not (0x14 <= b[o] <= 0x17) or b[o + 1] != 0x03 or not (0x01 <= b[o + 2] <= 0x04):
        return None
    ln = (b[o + 3] << 8) | b[o + 4]
    return 5 + ln if 0 < ln <= 16_384 + 256 else None


# ───────────────────────── framing ─────────────────────────

@dataclass(frozen=True)
class Frame:
    start: int
    end: int
    payload_start: int  # relative to start
    bundle: bool


def walk(buf: bytes) -> tuple[list[Frame], int]:
    """Split a TCP stream buffer into frames; returns (frames, bytes consumed)."""
    frames: list[Frame] = []
    o = 0
    n = len(buf)
    while o < n:
        if buf[o] == 0:
            o += 1
            continue
        tls = tls_record_size(buf, o)
        if tls is not None:
            if o + tls > n:
                break
            o += tls
            continue
        value, vlen = read_varint(buf, o)
        if vlen <= 0 or value <= 0:
            if o + 5 > n:
                break
            o += 1
            continue
        total = frame_size(value, vlen)
        if total is None or total > MAX_PACKET:
            o += 1
            continue
        if o + total > n:
            if total > MAX_FRAGMENT_WAIT:
                o += 1
                continue
            break  # wait for more bytes
        is_bundle = vlen + 1 < total and buf[o + vlen] == 0xFF and buf[o + vlen + 1] == 0xFF
        frames.append(Frame(o, o + total, vlen, is_bundle))
        o += total
    return frames, o


def walk_inner(buf: bytes) -> list[Frame]:
    frames: list[Frame] = []
    o = 0
    n = len(buf)
    while o < n:
        if buf[o] == 0:
            o += 1
            continue
        value, vlen = read_varint(buf, o)
        if vlen <= 0 or value <= 0:
            break
        total = frame_size(value, vlen)
        if total is None:
            o += 1
            continue
        if o + total > n:
            break
        nested = total > vlen + 1 and buf[o + vlen] == 0xFF and buf[o + vlen + 1] == 0xFF
        frames.append(Frame(o, o + total, vlen, nested))
        o += total
    return frames


def decompress_bundle(payload: bytes) -> bytes | None:
    """payload starts at FF FF: FF FF, u32 LE size, lz4 block."""
    if len(payload) < 7:
        return None
    size = u32(payload, 2)
    if size <= 0 or size > MAX_DECOMPRESSED:
        return None
    try:
        out = lz4_decompress(payload[6:], size)
    except Exception:
        return None
    return out if len(out) == size else None


# ───────────────────────── decoder ─────────────────────────

class StreamDecoder:
    """
    Feed reassembled server->client bytes with feed(); decoded events go to `emit`.
    `known_servers` is the set of valid server ids used to sanity-check heuristics.
    """

    def __init__(self, emit: Callable[[Event], None], known_servers: set[int],
                 opcodes: Opcodes | None = None, debug: Callable[[str], None] | None = None):
        self.emit = emit
        self.known_servers = known_servers
        self.op = (opcodes or Opcodes()).compiled()
        self.debug = debug
        self._buf = b""
        # Identity records are often repeated in several places; dedupe recent ones.
        self._recent: dict[tuple, None] = {}

    # ---- stream entry ----
    def feed(self, data: bytes) -> None:
        if not data:
            return
        buf = self._buf + data
        frames, consumed = walk(buf)
        for f in frames:
            body = buf[f.start:f.end]
            if f.bundle:
                self._bundle(body[f.payload_start:])
            else:
                self._packet(body, f.payload_start)
        rest = buf[consumed:]
        # Never let a broken stream grow without bound.
        self._buf = rest if len(rest) <= 4 * MAX_PACKET else b""

    def reset(self) -> None:
        self._buf = b""

    # ---- containers ----
    def _bundle(self, payload: bytes, depth: int = 0) -> None:
        data = decompress_bundle(payload)
        if data is None or depth > 4:
            return
        for f in walk_inner(data):
            inner = data[f.start:f.end]
            if f.bundle:
                self._bundle(inner[f.payload_start:], depth + 1)
            else:
                self._parse_damage(inner, f.payload_start)
                self._parse_lifecycle(inner, f.payload_start)
        self._scan_identities(data)
        self._scan_ownership(data)

    def _packet(self, packet: bytes, body_off: int) -> None:
        self._parse_damage(packet, body_off)
        self._parse_lifecycle(packet, body_off)
        self._scan_identities(packet)
        self._scan_ownership(packet)
        self._scan_embedded_bundles(packet)

    def _scan_embedded_bundles(self, packet: bytes) -> None:
        """Bundles carried inside a larger packet: <varint len> FF FF ... somewhere mid-packet."""
        i = 1
        n = len(packet)
        while i + 8 < n:
            j = packet.find(b"\xff\xff", i)
            if j < 0 or j + 8 >= n:
                return
            done = False
            for vl in (3, 2, 1):
                at = j - vl
                if at < 0:
                    continue
                value, vlen = read_varint(packet, at)
                if vlen != vl:
                    continue
                size = frame_size(value, vlen)
                if size is None or at + size > n:
                    continue
                data = decompress_bundle(packet[j:at + size])
                if data is None:
                    continue
                self._scan_identities(data)
                self._scan_ownership(data)
                i = at + size
                done = True
                break
            if not done:
                i = j + 1

    # ---- entity lifecycle: death / left view / map load (records at the start of a packet body) ----
    def _parse_lifecycle(self, packet: bytes, body_off: int) -> None:
        o = body_off
        n = len(packet)
        if o + 3 > n:
            return
        if _at(packet, o, self.op.death):
            eid, ln = read_varint(packet, o + 2)
            if ln <= 0 or not 1 <= eid <= MAX_ENTITY_ID:
                return
            p = o + 2 + ln
            _, ln2 = read_varint(packet, p)
            if ln2 <= 0:
                return
            flag, ln3 = read_varint(packet, p + ln2)
            if ln3 <= 0:
                return
            # 3 = died in combat, 1 = came into view already dead; other values = removed from view.
            self.emit(EntityGone(eid, died=flag in (1, 3)))
        elif _at(packet, o, self.op.object_gone):
            eid, ln = read_varint(packet, o + 2)
            if ln > 0 and 1 <= eid <= MAX_ENTITY_ID:
                self.emit(EntityGone(eid, died=False))
        elif _at(packet, o, self.op.map_load):
            if o + 10 <= n:
                map_id = u32(packet, o + 6)
                if 0 < map_id <= 9_999_999:
                    self.emit(MapLoaded(map_id))

    # ---- damage: 04 38 <target> <switch> <varint> <actor> <skill u32> ... ----
    def _parse_damage(self, packet: bytes, body_off: int) -> None:
        o = body_off
        if o + 2 >= len(packet) or not _at(packet, o, self.op.damage):
            return
        o += 2
        target, ln = read_varint(packet, o)
        if ln <= 0 or not 1 <= target <= MAX_ENTITY_ID:
            return
        o += ln
        switch, ln = read_varint(packet, o)
        if ln <= 0 or not 4 <= (switch & 0x0F) <= 7:
            return
        o += ln
        _, ln = read_varint(packet, o)
        if ln <= 0:
            return
        o += ln
        actor, ln = read_varint(packet, o)
        if ln <= 0 or not 1 <= actor <= MAX_ENTITY_ID or actor == target:
            return
        self.emit(Hit(actor, target))

    # ---- identities: 33 36 (self) / 44 36, 45 36 (others) ----
    # <op> <id varint> <mask1 u32> <mask2 u8> [mask2 & 1] <len u8><utf8 name> [server u16, class u32, u8, level u32]
    def _scan_identities(self, data: bytes) -> None:
        n = len(data)
        i = 0
        while i + 9 < n:
            j = data.find(b"\x36", i + 1)
            if j < 0:
                return
            i = j - 1
            is_self = _at(data, i, self.op.self_record)
            if not is_self and not _at(data, i, self.op.player_spawn):
                i = j
                continue
            end = self._parse_identity(data, i + 2, is_self)
            i = end if end else j

    def _parse_identity(self, b: bytes, o: int, is_self: bool) -> int | None:
        eid, ln = read_varint(b, o)
        if ln <= 0 or not 1 <= eid <= MAX_ENTITY_ID:
            return None
        o += ln + 4  # mask1
        if o + 2 > len(b) or not b[o] & 0x01:
            return None
        nlen = b[o + 1]
        o += 2
        if not 1 <= nlen <= 48 or o + nlen > len(b):
            return None
        field_bytes = b[o:o + nlen]
        o += nlen
        if is_self and is_placeholder_name(field_bytes):
            return o
        name = decode_name(field_bytes)
        if name is None:
            return None

        server: int | None = None
        source: str | None = None
        cls: str | None = None
        level: int | None = None
        if o + 6 <= len(b):
            s = u16(b, o)
            c = class_from_wire(u32(b, o + 2))
            if 1000 <= s < 3000 and c:
                server, source, cls = s, "record", c
                if o + 11 <= len(b):
                    lv = u32(b, o + 7)
                    if 1 <= lv <= 99:
                        level = lv
            elif o + 4 <= len(b):
                cls = class_from_wire(u32(b, o))
        # Oct 2026 spawn layout: <u32 class id> <u8 race> ... (no server id). Checked against NCSOFT's own data.
        race = pc_id = None
        if o + 5 <= len(b) and class_from_wire(u32(b, o)):
            pc_id = u32(b, o)
            if b[o + 4] in (1, 2):
                race = b[o + 4]
        if not is_self and server is None:
            server = self._scan_server(b, o)
            source = "scan" if server else None

        key = (is_self, eid, name, server, cls, race)
        if key not in self._recent:
            self._recent[key] = None
            if len(self._recent) > 4096:
                self._recent.pop(next(iter(self._recent)))
            if is_self:
                self.emit(SelfSeen(eid, name, server, cls, level))
            else:
                self.emit(PlayerSeen(eid, name, server, source, cls, race, pc_id))
        return o

    def _scan_server(self, b: bytes, start: int, window: int = 48) -> int | None:
        """Heuristic: first u16 after the name that is a known server id."""
        end = min(len(b) - 1, start + window)
        for k in range(start, end):
            cand = u16(b, k)
            if cand in self.known_servers:
                return cand
        return None

    # ---- ownership: 04 8D <id varint> <4 bytes> <owner varint> <server u16> <len><name> ----
    def _scan_ownership(self, data: bytes) -> None:
        for code in self.op.ownership:
            search = 0
            n = len(data)
            while search + 1 < n:
                idx = data.find(code, search)
                if idx < 0:
                    break
                search = idx + len(code)
                ent, ln = read_varint(data, search)
                if ln <= 0 or not 100 <= ent <= MAX_ENTITY_ID:
                    continue
                after_fixed = search + ln + 4
                if after_fixed >= n or data[after_fixed] == 0:
                    continue
                scan_end = min(n - 2, after_fixed + 128)
                for s in range(after_fixed + 1, scan_end):
                    server = u16(data, s)
                    if server not in self.known_servers:
                        continue
                    owner = _varint_ending_at(data, s, after_fixed, 100, 99_999)
                    if owner is None or owner == ent:
                        continue
                    nl = data[s + 2] if s + 2 < n else 0
                    name_end = s + 3 + nl
                    if not 1 <= nl <= 48 or name_end > n:
                        continue
                    name = decode_name(data[s + 3:name_end])
                    if name:
                        self.emit(OwnerRecord(owner, name, server))
                        search = name_end
                        break


def _varint_ending_at(data: bytes, end: int, min_start: int, lo: int, hi: int) -> int | None:
    fallback = None
    for ln in (1, 2, 3):
        start = end - ln
        if start < 0:
            break
        if start < min_start:
            continue
        v, vl = read_varint(data, start)
        if vl != ln or not lo <= v <= hi:
            continue
        continued = start > 0 and data[start - 1] & 0x80
        if not continued:
            return v
        if fallback is None:
            fallback = v
    return fallback


def iter_hex(data: bytes, width: int = 16) -> Iterator[str]:
    for i in range(0, len(data), width):
        chunk = data[i:i + width]
        yield f"{i:06x}  " + " ".join(f"{x:02x}" for x in chunk)
