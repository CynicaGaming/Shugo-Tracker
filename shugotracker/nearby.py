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
LOOKUP_WORKERS = 4      # parallel NCSOFT searches (the shared rate limit still caps requests per second)
RETRY_FAILED_S = 300    # someone NCSOFT couldn't find is tried again after this long


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
                 find: Callable[..., list[Character]] | None = None):
        cfg = cfg or {}
        self.api = api
        self._find = find or api.find_by_name
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
        self._failed: dict[str, tuple] = {}           # name -> (reason, when)
        self._background: set[str] = set()
        self._inflight: set[str] = set()
        self._my_region: str | None = cfg.get("nearby_region") or None
        self.on_region: Callable[[str], None] = lambda r: None   # remember it (set by the app)
        self.on_me: Callable[[str, int], None] = lambda n, s: None  # remember your character (set by the app)
        self._region_lock = threading.Lock()
        self._workers: list[threading.Thread] = []
        me = cfg.get("nearby_me")
        if isinstance(me, (list, tuple)) and len(me) == 2 and me[0]:
            # your character from last time, until the game names you (login / map load)
            self.tracker.me.name = str(me[0])
            self.tracker.me.server = sv.parse_server(me[1]) or self.tracker.me.server
        self._stop = threading.Event()
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
        self._workers = [w for w in self._workers if w.is_alive()]
        while len(self._workers) < LOOKUP_WORKERS:
            w = threading.Thread(target=self._lookup_loop, name=f"nearby-lookups-{len(self._workers)}", daemon=True)
            w.start()
            self._workers.append(w)

    def stop(self) -> None:
        self._stop.set()
        for _ in self._workers:
            self._lookups.put((-1, 0, None, None))
        self._workers = []
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
                self._background.clear()
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
        was = (self.tracker.me.name, self.tracker.me.server)
        self.tracker.handle(ev)
        now_me = (self.tracker.me.name, self.tracker.me.server)
        if now_me != was and all(now_me):
            self.on_me(*now_me)
        self.stats["events"] += 1
        if len(self.tracker.players) > before:
            self.stats["players_seen"] += len(self.tracker.players) - before

    # ───── lookups ─────
    # Players are listed straight from the game's records; NCSOFT is only asked about cards on screen (want()),
    # with one search per player for the exact name across your region. NCSOFT's answer gives the real server
    # and faction; the server read from the game is only used to choose between namesakes.
    def _request(self, name: str, prio: int, servers: list[int], guessed: bool) -> None:
        """Tracker callback (lock held): every player is identified in the background; cards on screen
        jump the queue (see want())."""
        if name == self.tracker.me.name or name in self._chars or name in self._background:
            return
        self._background.add(name)
        self._lookups.put((2 + prio, next(self._seq), name, None))

    def want(self, name: str) -> None:
        """The UI shows this player's card: identify them next (newest requests first)."""
        with self._lock:
            failed = self._failed.get(name)
            if name in self._chars or name in self._pending or (failed and time.time() - failed[1] < RETRY_FAILED_S):
                return
            self._failed.pop(name, None)
            self._pending.add(name)
        self._lookups.put((0, -next(self._seq), name, None))

    def _region(self, fallback_name: str | None = None) -> str | None:
        """Your region (nearby players share it). Found once by looking a name up in every region at the same
        time: your own name, or while the game hasn't named you yet, a nearby player's. Remembered."""
        if self._my_region:
            return self._my_region
        with self._region_lock:
            if self._my_region:
                return self._my_region
            name, server = self.me()
            probe = name or fallback_name
            if not probe:
                return None
            from concurrent.futures import ThreadPoolExecutor
            regions = ("nae", "naw", "eu", "la", "as")
            try:
                with ThreadPoolExecutor(len(regions)) as pool:
                    found = dict(zip(regions, pool.map(lambda r: self._find(probe, r), regions)))
            except Exception as e:  # noqa: BLE001
                self.log(f"nearby: finding your region failed: {e}")
                return None
            hits = [r for r, cs in found.items() if cs]
            hint = sv.REGION_PREFIX.get(sv.region_of(server)) if (server and name) else None
            if len(hits) == 1:
                region = hits[0]
            elif hint in hits:
                region = hint
            elif name and hits:
                region = hits[0]
            else:
                return None                  # a name in several regions says nothing: try with someone else
            self._my_region = region
            self.log(f"nearby: region {region} (from {'your name' if name else 'a nearby player'})")
            if name:
                mine = [c for c in found[region] if not server or c.server_id == server] or found[region]
                with self._lock:
                    self._chars[name] = mine[0]
                    self.tracker.me.server = mine[0].server_id      # NCSOFT's word over the decoded value
                    self._v += 1
                self.on_me(name, mine[0].server_id)
            self.on_region(region)
            return region

    def _lookup_loop(self) -> None:
        while not self._stop.is_set():
            _prio, _seq, name, _job = self._lookups.get()
            if name is None:
                return
            region = self._region(fallback_name=name)
            if region is None:                       # don't know where you are yet: try again shortly
                self._lookups.put((_prio, _seq, name, _job))
                self._stop.wait(0.5)
                continue
            with self._lock:
                p = self.tracker.players.get(name)
                busy = name in self._inflight
                failed = self._failed.get(name)
                if p is None or name in self._chars or busy or (failed and time.time() - failed[1] < RETRY_FAILED_S):
                    if not busy:
                        self._pending.discard(name)
                    continue
                self._inflight.add(name)
                hint = p.server if p.server_source in ("record", "owner") else None
                cls = WIRE_CLASS.get(p.class_name or "", p.class_name or "")
                seen_servers = {c.server_id for c in self._chars.values()}
                my_faction = self.tracker.me.faction
                # someone in a fight with you is almost certainly on the other side (an invader, a gank)
                prefer = (3 - my_faction) if (p.last_combat and my_faction in (1, 2)) else my_faction
            err, cands = None, []
            try:
                if cls:
                    cands = self._find(name, region, [cls])     # the class the game reported narrows namesakes
                if not cands:
                    cands = self._find(name, region)
            except Exception as e:  # noqa: BLE001
                err = f"{e.__class__.__name__}: {e}"
            pick = choose(cands, hint, seen_servers, prefer, fighting=bool(p.last_combat))
            with self._lock:
                self._inflight.discard(name)
                self._pending.discard(name)
                if pick:
                    self._chars[name] = pick
                    res = Lookup(status="ok", server=pick.server_id, level=pick.level,
                                 class_name=pick.class_name, faction=pick.race or None)
                else:
                    # a network error is retried within seconds; "not on NCSOFT" after RETRY_FAILED_S
                    self._failed[name] = ("error", time.time() - RETRY_FAILED_S + 15) if err else \
                        ("notfound", time.time())
                    res = Lookup(status="error" if err else "notfound", error=err)
                self.tracker.apply_lookup(name, res, [])
                self._v += 1

    # ───── for the UI ─────
    def snapshot(self) -> list[tuple[str, Character, Player]]:
        """[(side, character, player)] sorted enemies first, then allies, then unknown."""
        now = time.time()
        with self._lock:
            if now - self._last_expire > 5:
                self._last_expire = now
                self.tracker.expire(now)
            me = self.tracker.me
            if not me.server:
                # Until the game names you: the side most players around you are on is almost always yours.
                races = [c.race for c in self._chars.values() if c.race in (1, 2) and c.name != me.name]
                top = max((1, 2), key=races.count) if races else None
                me.faction_guess = top if races and races.count(top) >= max(4, 0.7 * len(races)) else None
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
        # the decoder's heuristic server guesses aren't shown: only servers from trusted records
        server = p.server if p.server and p.server_source in ("record", "owner") else 0
        cls = WIRE_CLASS.get(p.class_name or "", p.class_name or "")
        ids = class_pc_ids([cls]) if cls else []
        if ph is None or ph.server_id != server:
            ph = Character(char_id="", name=p.name, race=sv.race_of(server) if server else 0,
                           pc_id=ids[0] if ids else 0, level=0, server_id=server,
                           server_name=sv.name_of(server) if server else "",
                           region=sv.REGION_PREFIX.get(sv.region_of(server), "") if server else "")
            ph.status = "pending"
            self._placeholders[p.name] = ph
        if p.name in self._failed:
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


def choose(cands: list[Character], hint: int | None, seen_servers: set[int], my_faction: int | None,
           fighting: bool = False) -> Character | None:
    """Which of the characters with this exact name is the one standing near you. `my_faction` is the faction
    to prefer (the enemy's when they're fighting you); invaders come from other servers, so for them the
    'seen around you' check is skipped."""
    if not cands:
        return None
    if hint:
        exact = [c for c in cands if c.server_id == hint]
        if exact:
            return exact[0]
    real = [c for c in cands if c.level > 1] or cands        # level-1 namesakes are mostly reserved names
    if len(real) == 1:
        return real[0]
    checks = [lambda c: my_faction is not None and c.race == my_faction]
    if not fighting:
        checks.insert(0, lambda c: c.server_id in seen_servers)   # servers already seen around you
    for narrow in checks:
        subset = [c for c in real if narrow(c)]
        if len(subset) == 1:
            return subset[0]
        if subset:
            real = subset
    return max(real, key=lambda c: c.level)


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
