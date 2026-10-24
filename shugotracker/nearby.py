"""
Nearby players: passive capture of the game's own traffic (Npcap) -> decoder -> tracker -> NCSOFT lookups.

Opt-in only. Nothing is sent to the game or modified; the only network requests are the normal NCSOFT
character searches used everywhere else in the app (one per player, name + server, under the same rate limit).
"""
from __future__ import annotations

import itertools
import os
import queue
import struct
import threading
import time
from typing import Callable

from . import servers as sv
from .aion2api import Api, Character, class_pc_ids
from .protocol import Opcodes, StreamDecoder
from .tracker import ALLY, ENEMY, UNKNOWN, Lookup, Player, Tracker

NPCAP_URL = "https://npcap.com/#download"
RECORD_MAGIC = b"SHUGOCAP1\n"

# states the UI shows
OFF, STARTING, NO_NPCAP, NO_LIBS, WAITING, CAPTURING, ERROR = (
    "off", "starting", "no_npcap", "no_libs", "waiting", "capturing", "error")

WIRE_CLASS = {"Elementalist": "Spiritmaster"}   # the wire table predates the Global class names
GUESS_DELAY_S = 2.5    # a player's server record usually follows their spawn: wait this long before guessing


def npcap_installed() -> bool:
    if os.name != "nt":
        return False
    root = os.environ.get("SystemRoot", r"C:\Windows")
    return any(os.path.exists(os.path.join(root, d, "Npcap", "wpcap.dll")) for d in ("System32", "SysWOW64"))


class NearbyService:
    """
    Thread-safe. The capture thread feeds the decoder/tracker; a lookup thread resolves players to NCSOFT
    characters. The UI calls snapshot() and gets plain Character objects plus their side.
    """

    def __init__(self, api: Api, cfg: dict | None = None, log: Callable[[str], None] | None = None,
                 on_change: Callable[[], None] | None = None, data_dir: str | None = None,
                 find: Callable[[str, int], Character | None] | None = None):
        cfg = cfg or {}
        self.api = api
        self._find = find or api.find_player
        self.log = log or (lambda s: None)
        self.on_change = on_change or (lambda: None)
        self.data_dir = data_dir
        self.opcodes = Opcodes(**{k: v for k, v in (cfg.get("opcodes") or {}).items()
                                  if k in Opcodes.__dataclass_fields__})
        self._lock = threading.RLock()
        self.tracker = Tracker(request_lookup=self._request, my_server=sv.parse_server(cfg.get("my_server")),
                               lookup_allies=True, forget_after_s=float(cfg.get("forget_after_s", 900)),
                               log=self.log)
        self._decoders: dict = {}
        self._chars: dict[str, Character] = {}        # player name -> resolved character
        self._placeholders: dict[str, Character] = {}
        self._lookups: queue.PriorityQueue = queue.PriorityQueue()
        self._seq = itertools.count()
        self._pending: set[str] = set()
        self._stop = threading.Event()
        self._lookup_thread: threading.Thread | None = None
        self.capture = None
        self.state = OFF
        self.detail = ""
        self.stats = {"bytes": 0, "players_seen": 0, "events": 0}
        self._record_file = None
        self._record_until = 0.0
        self.record_path: str | None = None
        self._last_expire = 0.0
        self._v = 0

    def version(self) -> tuple:
        """Changes whenever anything the UI shows changes (cheap to poll)."""
        return (self.tracker.version, self._v, self.state)

    # ───── lifecycle ─────
    def start(self) -> None:
        if self.state not in (OFF, ERROR, NO_NPCAP, NO_LIBS):
            return
        self._stop.clear()
        if not npcap_installed():
            self._set_state(NO_NPCAP, "Npcap isn't installed")
            return
        try:
            from .capture import GameCapture
        except Exception as e:  # noqa: BLE001  (scapy / psutil missing: running from a bare source checkout)
            self._set_state(NO_LIBS, f"capture libraries missing: {e}")
            return
        self._set_state(STARTING, "starting capture")
        self.start_lookups()
        self.capture = GameCapture(self.on_bytes, log=self._capture_log)
        self.capture.start()

    def start_lookups(self) -> None:
        if self._lookup_thread is None or not self._lookup_thread.is_alive():
            self._lookup_thread = threading.Thread(target=self._lookup_loop, name="nearby-lookups", daemon=True)
            self._lookup_thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._lookups.put((-1, 0, None, None))
        if self.capture is not None:
            self.capture.stop()
            self.capture = None
        self.stop_recording()
        with self._lock:
            self.tracker.clear()
            self._decoders.clear()
        self._set_state(OFF, "")

    def start_demo(self, feed: Callable[["NearbyService"], None]) -> None:
        """--demo: no capture; `feed` pushes made-up traffic through the real decoder."""
        self.start_lookups()
        self._set_state(CAPTURING, "demo")
        feed(self)

    def retry(self) -> None:
        """'Check again' after installing Npcap."""
        if self.state in (NO_NPCAP, NO_LIBS, ERROR):
            self.state = OFF
            self.start()

    def _capture_log(self, msg: str) -> None:
        self.log(f"nearby: {msg}")
        low = msg.lower()
        if low.startswith("capturing"):
            self._set_state(CAPTURING, msg)
        elif low.startswith("waiting"):
            self._set_state(WAITING, "waiting for AION 2")
            with self._lock:
                self.tracker.clear()
        elif "error" in low:
            self._set_state(ERROR, msg)

    def _set_state(self, state: str, detail: str) -> None:
        changed = (state, detail) != (self.state, self.detail)
        self.state, self.detail = state, detail
        if changed:
            self._v += 1
            self.on_change()

    # ───── capture thread ─────
    def on_bytes(self, flow, data: bytes, gap: bool) -> None:
        self.stats["bytes"] += len(data)
        self._maybe_record(flow, data, gap)
        with self._lock:
            dec = self._decoders.get(flow)
            if dec is None:
                dec = self._decoders[flow] = StreamDecoder(emit=self._on_event, known_servers=sv.KNOWN_SERVERS,
                                                           opcodes=self.opcodes)
            if gap:
                dec.reset()
            dec.feed(data)

    def _on_event(self, ev) -> None:          # called with self._lock held
        before = len(self.tracker.players)
        self.tracker.handle(ev)
        name = getattr(ev, "name", None)
        p = self.tracker.players.get(name) if name else None
        if p is not None and p.server and p.server_source in ("record", "owner"):
            c = self._chars.get(name)
            if c is not None and c.server_id != p.server:       # a guess matched a namesake elsewhere
                del self._chars[name]
                self.tracker.retry(name)
        self.stats["events"] += 1
        if len(self.tracker.players) > before:
            self.stats["players_seen"] += len(self.tracker.players) - before

    # ───── lookups ─────
    def _request(self, name: str, prio: int, servers: list[int], guessed: bool) -> None:
        """Tracker callback (lock held): resolve `name` on the first of `servers` that has them."""
        if name in self._chars:
            return
        self._pending.add(name)
        not_before = time.time() + GUESS_DELAY_S if guessed else 0.0
        self._lookups.put((prio, next(self._seq), name, (list(servers), not_before)))

    def _lookup_loop(self) -> None:
        while not self._stop.is_set():
            prio, seq, name, job = self._lookups.get()
            if name is None:
                return
            servers, not_before = job
            with self._lock:
                if name in self._chars or (name not in self.tracker.players and name != self.tracker.me.name):
                    self._pending.discard(name)
                    continue
                p = self.tracker.players.get(name)
                if p is not None and p.server and p.server_source in ("record", "owner"):
                    servers, not_before = [p.server], 0.0        # the real server arrived meanwhile
            if not_before > time.time():
                self._lookups.put((prio, seq, name, (servers, not_before)))
                self._stop.wait(0.2)
                continue
            found, tried, err = None, [], None
            for sid in servers:
                tried.append(sid)
                try:
                    found = self._find(name, sid)
                except Exception as e:  # noqa: BLE001
                    err = f"{e.__class__.__name__}: {e}"
                    break
                if found:
                    break
            with self._lock:
                self._pending.discard(name)
                if found:
                    self._chars[name] = found
                    res = Lookup(status="ok", server=found.server_id, level=found.level,
                                 class_name=found.class_name, faction=found.race or None)
                else:
                    res = Lookup(status="error" if err else "notfound", error=err)
                self.tracker.apply_lookup(name, res, tried)
                self._v += 1

    # ───── for the UI ─────
    def snapshot(self) -> list[tuple[str, Character, Player]]:
        """[(side, character, player)] sorted enemies first, then allies, then unknown."""
        now = time.time()
        with self._lock:
            if now - self._last_expire > 5:
                self._last_expire = now
                self.tracker.expire(now)
            groups = self.tracker.groups()
            out = []
            for side in (ENEMY, ALLY, UNKNOWN):
                for p in groups[side]:
                    out.append((side, self._character(p), p))
            return out

    def _character(self, p: Player) -> Character:
        c = self._chars.get(p.name)
        if c is not None:
            return c
        ph = self._placeholders.get(p.name)
        server = p.server or 0
        cls = WIRE_CLASS.get(p.class_name or "", p.class_name or "")
        ids = class_pc_ids([cls]) if cls else []
        if ph is None or ph.server_id != server:
            ph = Character(char_id="", name=p.name, race=sv.race_of(server) if server else 0,
                           pc_id=ids[0] if ids else 0, level=0, server_id=server,
                           server_name=sv.name_of(server) if server else "",
                           region=sv.REGION_PREFIX.get(sv.region_of(server), "") if server else "")
            ph.status = "pending"
            self._placeholders[p.name] = ph
        if p.lookup.status in ("notfound", "error"):
            ph.status = "unresolved"
        return ph

    def me(self) -> tuple[str | None, int | None]:
        with self._lock:
            return self.tracker.me.name, self.tracker.me.server

    def counts(self) -> dict[str, int]:
        with self._lock:
            g = self.tracker.groups()
            return {k: len(v) for k, v in g.items()}

    def is_nearby(self, c: Character) -> bool:
        with self._lock:
            hit = self._chars.get(c.name)
            return hit is not None and hit.key == c.key

    # ───── troubleshooting recording ─────
    def start_recording(self, seconds: float = 60.0) -> str | None:
        """Save the next `seconds` of decoded-ready game traffic to a file (for fixing the decoder)."""
        if not self.data_dir:
            return None
        folder = os.path.join(self.data_dir, "diagnostics")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, time.strftime("nearby-%Y%m%d-%H%M%S.bin"))
        f = open(path, "wb")
        f.write(RECORD_MAGIC)
        with self._lock:
            self._record_file, self._record_until, self.record_path = f, time.time() + seconds, path
        self.log(f"nearby: recording to {path}")
        return path

    def recording(self) -> float:
        """Seconds of recording left (0 when not recording)."""
        return max(0.0, self._record_until - time.time()) if self._record_file else 0.0

    def stop_recording(self) -> None:
        with self._lock:
            f, self._record_file = self._record_file, None
        if f:
            try:
                f.close()
            except OSError:
                pass

    def _maybe_record(self, flow, data: bytes, gap: bool) -> None:
        f = self._record_file
        if f is None:
            return
        if time.time() > self._record_until:
            self.stop_recording()
            self._v += 1
            return
        key = "|".join(str(x) for x in flow).encode()
        try:
            f.write(struct.pack("<dBH", time.time(), 1 if gap else 0, len(key)) + key + struct.pack("<I", len(data)))
            f.write(data)
        except (OSError, ValueError):
            self.stop_recording()


def replay_recording(path: str, on_bytes: Callable[[tuple, bytes, bool], None]) -> int:
    """Feed a file saved by start_recording() back through on_bytes. Returns chunks read."""
    n = 0
    with open(path, "rb") as f:
        if f.read(len(RECORD_MAGIC)) != RECORD_MAGIC:
            raise ValueError("not a Shugo Tracker capture")
        while True:
            head = f.read(11)
            if len(head) < 11:
                break
            _ts, gap, klen = struct.unpack("<dBH", head)
            key = tuple(f.read(klen).decode().split("|"))
            (dlen,) = struct.unpack("<I", f.read(4))
            on_bytes(key, f.read(dlen), bool(gap))
            n += 1
    return n
