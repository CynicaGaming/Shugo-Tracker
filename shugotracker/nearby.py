"""
Nearby players: passive capture of the game's own traffic (Windows raw sockets) -> decoder -> tracker -> NCSOFT lookups.

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
from .protocol import EntityActive, EntityGone, Hit, MapLoaded, Opcodes, RosterSeen, SelfSeen, StreamDecoder
from .tracker import ALLY, ENEMY, UNKNOWN, Lookup, Player, Tracker

RECORD_MAGIC = b"SHUGOCAP1\n"
RUNNING_LOG_MAX = 512 * 1024 * 1024         # a day's traffic file stops growing past this (a normal day is far less)
RUNNING_LOG_DAYS = 7                         # days of traffic files kept

# states the UI shows
OFF, STARTING, NO_ADMIN, NO_LIBS, WAITING, CAPTURING, ERROR = (
    "off", "starting", "no_admin", "no_libs", "waiting", "capturing", "error")

WIRE_CLASS = {"Elementalist": "Spiritmaster"}   # the wire table predates the Global class names
LOOKUP_WORKERS = 4      # parallel NCSOFT searches (the shared rate limit still caps requests per second)
RETRY_FAILED_S = 300    # someone NCSOFT couldn't find is tried again after this long
PVP_WINDOW_S = 15       # PvP Log: hits this recent count toward a death (the last player's hit is the kill)
RECENT_MAX = 250        # players kept on the Recent list by default (Settings: 50 … 1000 or Unlimited = 0)


def is_admin() -> bool:
    """Raw-socket capture needs Shugo Tracker to run as administrator (Windows only)."""
    if os.name != "nt":
        return False
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001
        return False


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
        import collections
        self._recent: "collections.OrderedDict[str, tuple]" = collections.OrderedDict()
        self._last_players: dict[str, Player] = {}
        self._recent_players: dict[str, Player] = {}
        self._recent_ids: dict[int, str] = {}         # entity id -> name, for players on Recent
        self.recent_max = int(cfg.get("recent_max", RECENT_MAX) or 0)
        # players moved to Recent while possibly still around (Clear Nearby, gone quiet): any record about them
        # puts them back on Nearby. Not those who left view or were left behind by a map change.
        self._parked: dict[int, str] = {}
        # PvP Log: recent hits on each entity, to tell who landed the killing blow
        self._hits: dict[int, list[tuple[float, int]]] = {}
        self._died_at: dict[int, float] = {}
        self.on_pvp: Callable[..., None] = lambda kind, foe, with_, by=None: None
        self._map_loads_seen = False
        self._loaded_since_self = False               # a map load came in since your last own record
        self._self_eid: int | None = None             # your id in the last record of your own
        self._last_roster: tuple = ()
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
        self._record_size = 0
        self._record_writes = 0
        self._record_day = ""
        self.record_path: str | None = None
        self._last_expire = 0.0
        self._v = 0

    def version(self) -> tuple:
        """Changes whenever anything the UI shows changes (cheap to poll)."""
        return (self.tracker.version, self._v, self.state)

    # ───── lifecycle ─────
    def start(self) -> None:
        if self.state not in (OFF, ERROR, NO_ADMIN, NO_LIBS):
            return
        self._stop.clear()
        if not is_admin():
            self._set_state(NO_ADMIN, "needs administrator")
            return
        try:
            from .capture import GameCapture
        except Exception as e:  # noqa: BLE001  (psutil missing: running from a bare source checkout)
            self._set_state(NO_LIBS, f"capture libraries missing: {e}")
            return
        self._set_state(STARTING, "starting capture")
        self.start_lookups()
        self.start_running_log()
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
        self.stop_running_log()
        with self._lock:
            self.tracker.clear()
            self._decoders.clear()
            self._parked.clear()
        self._set_state(OFF, "")

    def start_demo(self, feed: Callable[["NearbyService"], None]) -> None:
        """--demo: no capture; `feed` pushes made-up traffic through the real decoder."""
        self.start_lookups()
        self._set_state(CAPTURING, "demo")
        feed(self)

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
                self._parked.clear()
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
                                                           opcodes=self.opcodes, watch=self._watching)
            if gap:
                dec.reset()
            dec.feed(data)

    def _watching(self, eid: int) -> bool:     # decoder callback (lock held)
        return eid in self._parked or eid in self.tracker.by_id

    def _on_event(self, ev) -> None:          # called with self._lock held
        if isinstance(ev, EntityActive):
            name = self.tracker.by_id.get(ev.entity_id)
            if name in self.tracker.players:
                self.tracker.players[name].last_seen = time.time()     # still here: don't let them expire
            else:
                name = self._parked.pop(ev.entity_id, None)
                if name and name in self._recent and name not in self.tracker.players:
                    self._restore(name, ev.entity_id)
            return
        if isinstance(ev, MapLoaded):
            self._map_loads_seen = True
            self._loaded_since_self = True
            self._hits.clear()
            if ev.map_id != self.tracker.map_id:
                self._parked.clear()                # a new area: those ids mean other things now
        elif isinstance(ev, SelfSeen) and self._new_area(ev) and self.tracker.players:
            self.log(f"nearby: new area (your id changed to {ev.entity_id}): {len(self.tracker.players)} players to Recent")
            self._to_recent(list(self.tracker.players.values()))
            self.tracker.clear()
        elif isinstance(ev, RosterSeen):
            names = tuple(sorted(n for n, _s in ev.players))
            if names != self._last_roster:
                self._last_roster = names
                self.log("nearby: match scoreboard: " + ", ".join(f"{n}@{s}" for n, s in ev.players))
        elif isinstance(ev, EntityGone) and ev.died and ev.in_combat:
            self._pvp_death(ev.entity_id)
        elif isinstance(ev, Hit):
            self._note_hit(ev)
            # someone on the Recent list is fighting right next to you: they never left
            for eid in (ev.actor_id, ev.target_id):
                name = self._recent_ids.get(eid)
                if name and eid not in self.tracker.by_id and name in self._recent:
                    self._restore(name, eid)
        before_names = set(self.tracker.players)
        before = len(before_names)
        was = (self.tracker.me.name, self.tracker.me.server)
        self.tracker.handle(ev)
        left = before_names - set(self.tracker.players)
        if left:
            self._to_recent([self._last_players[n] for n in left if n in self._last_players])
        now_me = (self.tracker.me.name, self.tracker.me.server)
        if now_me != was and all(now_me):
            self.on_me(*now_me)
        self.stats["events"] += 1
        if len(self.tracker.players) > before:
            self.stats["players_seen"] += len(self.tracker.players) - before
        for n in set(self.tracker.players) - before_names:
            self._recent_players.pop(n, None)           # back in range (they stay on Recent as history)
        self._last_players.update(self.tracker.players)

    # ───── PvP Log ─────
    def _note_hit(self, ev: Hit) -> None:      # lock held
        now = time.time()
        lst = self._hits.setdefault(ev.target_id, [])
        lst.append((now, ev.actor_id))
        if len(lst) > 64:
            del lst[:-64]
        if len(self._hits) > 4096:              # (monsters come and go: drop the stale ones)
            for k in [k for k, v in self._hits.items() if now - v[-1][0] > PVP_WINDOW_S]:
                del self._hits[k]

    def _pvp_death(self, eid: int) -> None:    # lock held
        """Someone died just now. You: the last player who hit you killed you. A player you hit: your kill if
        your hit was the last player's hit on them, an assist otherwise."""
        now = time.time()
        hits = [(t, a) for t, a in self._hits.pop(eid, []) if now - t <= PVP_WINDOW_S]
        if now - self._died_at.get(eid, 0) < PVP_WINDOW_S:
            return                                       # the same death reported twice
        self._died_at[eid] = now
        mine = self.tracker.me.entity_ids
        by_id = self.tracker.by_id
        players = [(t, a) for t, a in hits if a in mine or by_id.get(a) in self.tracker.players]
        if not players:
            return                                       # a monster (or a fall) — not PvP
        name_of = lambda a: self.tracker.me.name if a in mine else by_id.get(a)   # noqa: E731
        if eid in mine:
            foes = [a for _t, a in players if a not in mine]
            if not foes:
                return
            killer = self.tracker.players[by_id[foes[-1]]]
            others = sorted({name_of(a) for a in foes[:-1]} - {killer.name})
            self.log(f"pvp: {killer.name} killed you" + (f" (with {', '.join(others)})" if others else ""))
            self.on_pvp("death", self._character(killer), others)
            return
        victim = by_id.get(eid)
        if victim not in self.tracker.players or not any(a in mine for _t, a in players):
            return                                       # not someone you fought
        last = players[-1][1]
        kind = "kill" if last in mine else "assist"
        others = sorted({name_of(a) for _t, a in players if a not in mine})
        self.log(f"pvp: {'you killed' if kind == 'kill' else 'you helped kill'} {victim}"
                 + (f" (with {', '.join(others)})" if others else ""))
        self.on_pvp(kind, self._character(self.tracker.players[victim]), others,
                    by=None if kind == "kill" else name_of(last))

    def _new_area(self, ev: SelfSeen) -> bool:
        """Your own record arriving means a new area when map-load records aren't coming through at all, or
        when it carries a new id for you: entering an instance (Shugo, a rift) can come with no map load, but
        your character always gets a new id there. A respawn (same id, or after a same-map load) isn't."""
        if not self._map_loads_seen:
            return True
        last, self._self_eid = self._self_eid, ev.entity_id
        respawn, self._loaded_since_self = self._loaded_since_self, False   # (a new map already cleared the list)
        return last is not None and ev.entity_id != last and not respawn

    def _to_recent(self, players: list[Player], park: bool = False) -> None:
        now = time.time()
        for p in players:
            if park:
                for eid in p.entity_ids:
                    self._parked[eid] = p.name
            side = self.tracker.side(p)
            self._recent[p.name] = (side, self._character(p), now, bool(p.last_combat))
            self._recent.move_to_end(p.name)
            self._recent_players[p.name] = p
            for eid in p.entity_ids:
                self._recent_ids[eid] = p.name
            self._last_players.pop(p.name, None)
        self._trim_recent()
        self._v += 1

    def _trim_recent(self) -> None:
        while self.recent_max and len(self._recent) > self.recent_max:
            name, _ = self._recent.popitem(last=False)
            self._recent_players.pop(name, None)

    def set_recent_max(self, n: int) -> None:
        """Settings: how many players Recent keeps (0 = no limit)."""
        with self._lock:
            self.recent_max = int(n or 0)
            self._trim_recent()
            self._v += 1

    def clear_nearby(self) -> None:
        """Everyone on the list -> Recent. Anyone still around comes back on their next sign of life (moving,
        casting, fighting); those who left stay on Recent."""
        with self._lock:
            players = list(self.tracker.players.values())
            if players:
                self._to_recent(players, park=True)
                self.tracker.clear()

    def clear_recent(self) -> None:
        with self._lock:
            self._recent.clear()
            self._recent_players.clear()
            self._recent_ids.clear()
            self._parked.clear()
            self._v += 1

    def _restore(self, name: str, eid: int) -> None:
        """Put a player from Recent back on the list (lock held)."""
        old = self._recent_players.pop(name, None)       # (they stay on Recent as history)
        if old is None:
            return
        old.entity_ids = {eid}
        old.last_seen = time.time()
        self.tracker.players[name] = old
        self.tracker.by_id[eid] = name
        self._last_players[name] = old
        self.tracker.version += 1
        self._v += 1

    def recent(self) -> list[tuple[str, Character, float, bool]]:
        """[(side, character, left_at, fought_you)] newest first: everyone you've been near (up to the Recent
        limit), including those who are back on Nearby right now (left_at is when they last left)."""
        with self._lock:
            out = []
            for name, (side, c, left_at, fought) in reversed(self._recent.items()):
                c = self._chars.get(name, c)            # identified after they left
                out.append((side, c, left_at, fought))
            return out

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
                pc_id, race = p.pc_id, p.race
                seen_servers = {c.server_id for c in self._chars.values()}
                my_faction = self.tracker.me.faction
                # someone in a fight with you is almost certainly on the other side (an invader, a gank)
                prefer = (3 - my_faction) if (p.last_combat and my_faction in (1, 2)) else my_faction
            err, cands = None, []
            try:
                # narrowest first: exact class id + faction from the spawn record, then class, then name only
                if pc_id or race:
                    cands = self._find(name, region, pc_ids=[pc_id] if pc_id else None, race=race)
                if not cands and cls:
                    cands = self._find(name, region, [cls])
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
                before = set(self.tracker.players)
                self.tracker.expire(now)
                gone = before - set(self.tracker.players)
                if gone:
                    self._to_recent([self._last_players[n] for n in gone if n in self._last_players], park=True)
            me = self.tracker.me
            if not me.server:
                # Until the game names you: the side most players around you are on is almost always yours.
                races = [p.faction for p in self.tracker.players.values() if p.faction in (1, 2)]
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
        if ph is None or ph.server_id != server or (p.race and ph.race != p.race):
            ph = Character(char_id="", name=p.name, race=p.race or (sv.race_of(server) if server else 0),
                           pc_id=p.pc_id or (ids[0] if ids else 0), level=0, server_id=server,
                           server_name=sv.name_of(server) if server else "",
                           region=sv.REGION_PREFIX.get(sv.region_of(server), "") if server else "")
            ph.status = "pending"
            self._placeholders[p.name] = ph
        if p.name in self._failed:
            ph.status = "unresolved"
        return ph

    def set_me(self, name: str, server: int) -> None:
        """You picked your character (right-click → Set Profile, or Switch Profile): sides follow it at once."""
        with self._lock:
            self.tracker.me.name = name
            if server:
                self.tracker.me.server = server
            self.tracker.players.pop(name, None)
            self.tracker.version += 1
            self._v += 1

    def me(self) -> tuple[str | None, int | None]:
        with self._lock:
            return self.tracker.me.name, self.tracker.me.server

    # ───── running log of the game's traffic ─────
    # While Nearby runs, the traffic it reads is always saved to logs\diagnostics\nearby_<day>.bin: every start
    # that day adds to the same file (each start begins with a marker), a new file starts at midnight, and only
    # the last RUNNING_LOG_DAYS days are kept. A day's file stops growing at RUNNING_LOG_MAX.
    def start_running_log(self) -> str | None:
        if not self.data_dir:
            return None
        from .logfiles import daily_log_path, today
        self.stop_running_log()
        try:
            folder = os.path.join(self.data_dir, "diagnostics")
            path = daily_log_path(folder, "nearby", "bin", RUNNING_LOG_DAYS)
            f = open(path, "ab")
            f.write(RECORD_MAGIC)                     # a session marker (the first one makes it a capture file)
            size = f.tell()
        except OSError as e:
            self.log(f"nearby: running log unavailable: {e}")
            return None
        self._record_file, self._record_size, self._record_day, self.record_path = f, size, today(), path
        return path

    def stop_running_log(self) -> None:
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
        self._record_writes += 1
        key = "|".join(str(x) for x in flow).encode()
        head = struct.pack("<dBH", time.time(), 1 if gap else 0, len(key)) + key + struct.pack("<I", len(data))
        try:
            f.write(head)
            f.write(data)
        except (OSError, ValueError):
            self.stop_running_log()
            return
        self._record_size += len(head) + len(data)
        if self._record_size > RUNNING_LOG_MAX:
            self.log("nearby: today's log is full; no more traffic saved until tomorrow")
            self.stop_running_log()
        elif self._record_writes % 500 == 0:
            from .logfiles import today
            if today() != self._record_day:            # midnight: on to the next day's file
                self.start_running_log()


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
    """Feed a Nearby log (logs\\diagnostics\\nearby_*.bin) back through on_bytes. A day's file holds several
    sessions, each starting with RECORD_MAGIC; a record cut off by a crash is skipped to the next session.
    Returns chunks read."""
    with open(path, "rb") as f:
        blob = f.read()
    if not blob.startswith(RECORD_MAGIC):
        raise ValueError("not a Shugo Tracker capture")
    n = 0
    for chunk in blob.split(RECORD_MAGIC)[1:]:
        o = 0
        while o + 11 <= len(chunk):
            _ts, gap, klen = struct.unpack_from("<dBH", chunk, o)
            o += 11
            if klen > 200 or o + klen + 4 > len(chunk):
                break                                  # cut off (or not a record): on to the next session
            key = tuple(chunk[o:o + klen].decode(errors="replace").split("|"))
            o += klen
            (dlen,) = struct.unpack_from("<I", chunk, o)
            o += 4
            if o + dlen > len(chunk):
                break
            on_bytes(key, chunk[o:o + dlen], bool(gap))
            o += dlen
            n += 1
    return n
