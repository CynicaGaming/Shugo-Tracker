"""
Nearby players for the main window: who is in render range, read passively from the game's
network traffic (Npcap), with no web requests of its own.

Packets name a player and their class, but usually not their server. A nearby name is turned into a
full character (for the Nearby tab) only when its card is on screen, with an exact-name search limited
to your own region, preferring your server and its paired enemy server.
"""
from __future__ import annotations

import ctypes
import itertools
import os
import queue
import sys
import threading
import time
from typing import Callable

from . import servers as sv
from .aion2api import SUB_REGIONS, Api, Character
from .protocol import Opcodes, StreamDecoder
from .tracker import ALLY, ENEMY, Player, Tracker

REGION_CODES = {1: "nae", 2: "naw", 3: "eu", 4: "la", 5: "as"}


# ───── environment checks (Windows) ─────
def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001  (not Windows)
        return os.name != "nt" and hasattr(os, "geteuid") and os.geteuid() == 0


def npcap_installed() -> bool:
    if os.name != "nt":
        return True
    root = os.environ.get("SystemRoot", r"C:\Windows")
    return any(os.path.exists(os.path.join(root, d, "wpcap.dll"))
               for d in (r"System32\Npcap", "System32"))


def relaunch_as_admin(extra_args: list[str]) -> bool:
    """Start this app again elevated (UAC prompt). True if the new process was started."""
    try:
        if getattr(sys, "frozen", False):
            exe, args = sys.executable, list(sys.argv[1:])
        else:
            exe, args = sys.executable, ["-m", "shugotracker.app", *sys.argv[1:]]
        args += [a for a in extra_args if a not in args]
        params = " ".join(f'"{a}"' if " " in a else a for a in args)
        rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, os.getcwd(), 1)
        return rc > 32
    except Exception:  # noqa: BLE001
        return False


class NearbyService:
    def __init__(self, api: Api, my_server: int | None = None, forget_after_s: float = 900,
                 interfaces: list[str] | None = None, opcodes: dict | None = None,
                 log: Callable[[str], None] | None = None):
        self.api = api
        self.log = log or (lambda s: None)
        self.interfaces = interfaces or None
        self.tracker = Tracker(request_lookup=lambda *a: None, my_server=my_server, lookup_allies=False,
                               forget_after_s=forget_after_s, log=self.log)
        self.opcodes = Opcodes(**{k: v for k, v in (opcodes or {}).items() if k in Opcodes.__dataclass_fields__})
        self.events: queue.Queue = queue.Queue()
        self.capture = None
        self.running = False
        self._decoders: dict = {}
        self._dec_lock = threading.Lock()
        # name -> placeholder Character shown in the Nearby tab (filled in place once resolved)
        self.cards: dict[str, Character] = {}
        self._resolve_q: queue.PriorityQueue = queue.PriorityQueue()
        self._resolving: set[str] = set()
        self._seq = itertools.count()
        self._resolved_inbox: queue.Queue = queue.Queue()
        self._workers_started = False
        self.version = 0

    # ───── capture ─────
    def start(self) -> None:
        if self.running:
            return
        from .capture import GameCapture
        self.capture = GameCapture(self._on_bytes, ifaces=self.interfaces, log=self.log)
        self.capture.start()
        self.running = True
        self._start_workers()

    def start_feed(self, feeder: Callable[["NearbyService"], None]) -> None:
        """Demo/testing: events come from feeder instead of the network."""
        self.running = True
        self._start_workers()
        threading.Thread(target=feeder, args=(self,), daemon=True, name="nearby-demo").start()

    def stop(self) -> None:
        if self.capture:
            self.capture.stop()
        self.capture = None
        self.running = False

    def status(self) -> str:
        if not self.running:
            return "off"
        return self.capture.status if self.capture else "demo"

    def _on_bytes(self, flow, data: bytes, gap: bool) -> None:
        with self._dec_lock:
            dec = self._decoders.get(flow)
            if dec is None:
                dec = self._decoders[flow] = StreamDecoder(emit=self.events.put, known_servers=sv.KNOWN_SERVERS,
                                                           opcodes=self.opcodes)
            if gap:
                dec.reset()
            dec.feed(data)

    def pump(self, budget_s: float = 0.03) -> bool:
        """Main thread: apply decoded events and finished resolutions. True if anything changed."""
        changed = False
        deadline = time.monotonic() + budget_s
        while time.monotonic() < deadline:
            try:
                ev = self.events.get_nowait()
            except queue.Empty:
                break
            self.tracker.handle(ev)
            changed = True
        while True:
            try:
                name, ch = self._resolved_inbox.get_nowait()
            except queue.Empty:
                break
            self._apply_resolution(name, ch)
            changed = True
        if changed:
            self._sync_cards()
            self.version += 1
        return changed

    # ───── queries ─────
    @property
    def me(self):
        return self.tracker.me

    def count(self) -> int:
        return len(self.tracker.players)

    def side_of(self, name: str) -> str | None:
        p = self.tracker.players.get(name)
        return self.tracker.side(p) if p else None

    def match(self, c: Character) -> Player | None:
        """The nearby player this search result is, if any."""
        p = self.tracker.players.get(c.name)
        if p is None:
            return None
        if p.server:
            return p if p.server == c.server_id else None
        mine = self.tracker.me.server
        if mine:
            return p if sv.region_of(mine) == sv.region_of(c.server_id) else None
        return p

    def nearby_cards(self) -> list[Character]:
        """Placeholder/resolved Characters for everyone in range, enemies first."""
        order = {ENEMY: 0, "unknown": 1, ALLY: 2}
        players = list(self.tracker.players.values())
        players.sort(key=lambda p: (order.get(self.tracker.side(p), 1), p.dead, -p.last_combat,
                                    -(self.cards[p.name].combat_power or 0) if p.name in self.cards else 0,
                                    p.name.lower()))
        return [self.cards[p.name] for p in players if p.name in self.cards]

    def player(self, name: str) -> Player | None:
        return self.tracker.players.get(name)

    # ───── placeholders & resolution ─────
    def _sync_cards(self) -> None:
        live = self.tracker.players
        for name in [n for n in self.cards if n not in live]:
            del self.cards[name]
        for name, p in live.items():
            c = self.cards.get(name)
            if c is None:
                server = p.server if p.server in sv.KNOWN_SERVERS else 0
                c = Character(char_id="", name=name, race=sv.race_of(server) if server else 0, pc_id=0, level=0,
                              server_id=server, server_name=sv.name_of(server) if server else "",
                              region=REGION_CODES.get(sv.region_of(server), "") if server else "",
                              class_hint=p.class_name, status="unresolved")
                self.cards[name] = c
            elif c.status == "unresolved" and p.class_name and not c.class_hint:
                c.class_hint = p.class_name

    def request_resolve(self, c: Character, generation: int = 0) -> None:
        """Called for on-screen cards only. Newest requests first."""
        if c.status != "unresolved" or c.name in self._resolving:
            return
        self._resolving.add(c.name)
        c.status = "resolving"
        self._resolve_q.put((-next(self._seq), c.name))

    def _start_workers(self) -> None:
        if self._workers_started:
            return
        self._workers_started = True
        for i in range(2):
            threading.Thread(target=self._resolve_worker, daemon=True, name=f"resolve-{i}").start()

    def _resolve_worker(self) -> None:
        while True:
            _, name = self._resolve_q.get()
            try:
                ch = self.resolve(name)
            except Exception as e:  # noqa: BLE001
                self.log(f"nearby: resolving {name} failed: {e}")
                ch = None
            self._resolved_inbox.put((name, ch))

    def resolve(self, name: str) -> Character | None:
        """Exact-name search in your region (all regions if unknown); pick the most plausible server."""
        p = self.tracker.players.get(name)
        known = p.server if p and p.server in sv.KNOWN_SERVERS else None
        mine = self.tracker.me.server
        if known:
            regions = [REGION_CODES.get(sv.region_of(known))]
        elif mine:
            regions = [REGION_CODES.get(sv.region_of(mine))]
        else:
            regions = list(SUB_REGIONS)
        exact: list[Character] = []
        for region in [r for r in regions if r]:
            chars, _ = self.api.search_region(name, region, page=1, size=30)
            exact += [c for c in chars if c.name == name]
        if not exact:
            return None
        if known:
            hit = [c for c in exact if c.server_id == known]
            return hit[0] if hit else None
        prefer = [s for s in (mine, sv.mirror_server(mine) if mine else None) if s]
        for s in prefer:
            for c in exact:
                if c.server_id == s:
                    return c
        if len(exact) == 1:
            return exact[0]
        # Several same-name characters in the region and none on your server pair: take the highest level.
        best = max(exact, key=lambda c: c.level)
        best.error = "ambiguous"
        return best

    def _apply_resolution(self, name: str, ch: Character | None) -> None:
        self._resolving.discard(name)
        card = self.cards.get(name)
        if card is None:
            return
        if ch is None:
            card.status = "notfound"
            return
        for f in ("char_id", "race", "pc_id", "level", "server_id", "server_name", "region", "portrait",
                  "combat_power", "gear_score", "title"):
            setattr(card, f, getattr(ch, f))
        card.error = ch.error
        card.status = ch.status if ch.status == "ok" else "none"   # "none" → card asks for details when visible
        p = self.tracker.players.get(name)
        if p is not None:
            p.lookup.faction = ch.race or p.lookup.faction
            if not p.server:
                p.server, p.server_source = ch.server_id, "resolved"
