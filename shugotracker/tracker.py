"""Keeps every player in render range, sorts them into enemies/allies, and decides what to look up."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

from . import servers as sv
from .protocol import EntityGone, Event, Hit, MapLoaded, OwnerRecord, PlayerSeen, SelfSeen

# Lookup priorities (lower = sooner)
PRIO_COMBAT, PRIO_ENEMY, PRIO_UNKNOWN, PRIO_ALLY = 0, 1, 2, 3

ENEMY, ALLY, UNKNOWN = "enemy", "ally", "unknown"


@dataclass
class Lookup:
    status: str = "none"          # none | queued | ok | notfound | error
    server: int | None = None     # server the profile was found on
    guessed: bool = False         # server was inferred, not read from the stream
    gear_score: int | None = None
    combat_power: int | None = None
    level: int | None = None
    class_name: str | None = None
    faction: int | None = None    # sv.ELYOS / sv.ASMODIAN
    legion: str | None = None
    url: str | None = None
    error: str | None = None


@dataclass
class Player:
    name: str
    entity_ids: set[int] = field(default_factory=set)
    server: int | None = None
    server_source: str | None = None   # record | owner | scan
    class_name: str | None = None
    first_seen: float = 0.0
    last_seen: float = 0.0
    last_combat: float = 0.0           # last hit between this player and you
    hits_on_you: int = 0
    dead: bool = False
    lookup: Lookup = field(default_factory=Lookup)
    tried_servers: set[int] = field(default_factory=set)

    @property
    def faction(self) -> int | None:
        if self.lookup.faction:
            return self.lookup.faction
        if self.server and self.server_source in ("record", "owner"):
            return sv.race_of(self.server)
        return None


@dataclass
class Me:
    entity_ids: set[int] = field(default_factory=set)
    name: str | None = None
    server: int | None = None
    lookup: Lookup = field(default_factory=Lookup)
    faction_guess: int | None = None   # used until your own record arrives (see NearbyService)

    @property
    def faction(self) -> int | None:
        return sv.race_of(self.server) if self.server else self.faction_guess


class Tracker:
    def __init__(self, request_lookup: Callable[[str, int, list[int], bool], None],
                 my_server: int | None = None, lookup_allies: bool = True,
                 forget_after_s: float = 900.0, extra_enemy_servers: list[int] | None = None,
                 log: Callable[[str], None] | None = None):
        """
        request_lookup(name, priority, candidate_servers, guessed) asks the Shugo worker
        to try those servers in order.
        """
        self.request_lookup = request_lookup
        self.me = Me(server=my_server)
        self.players: dict[str, Player] = {}
        self.by_id: dict[int, str] = {}
        self.lookup_allies = lookup_allies
        self.forget_after_s = forget_after_s
        self.extra_enemy_servers = extra_enemy_servers or []
        self.log = log or (lambda s: None)
        self.on_retry: Callable[[str], None] | None = None
        self.map_id: int | None = None
        self.version = 0  # bumps whenever something visible changes

    # ───── events ─────
    def handle(self, ev: Event, now: float | None = None) -> None:
        now = now or time.time()
        if isinstance(ev, SelfSeen):
            self._on_self(ev)
        elif isinstance(ev, PlayerSeen):
            if self.me.name and ev.name == self.me.name:
                self.me.entity_ids.add(ev.entity_id)
                return
            p = self._player(ev.name, now)
            self._bind(p, ev.entity_id)
            p.dead = False
            if ev.class_name:
                p.class_name = ev.class_name
            if ev.server and (p.server is None or (p.server_source == "scan" and ev.server_source == "record")):
                p.server, p.server_source = ev.server, ev.server_source
            self._consider(p)
        elif isinstance(ev, OwnerRecord):
            if self.me.name and ev.name == self.me.name:
                self.me.entity_ids.add(ev.entity_id)
                if not self.me.server:
                    self._set_my_server(ev.server)
                return
            # Kill credit can name someone far away; only refresh players already in view.
            p = self.players.get(ev.name)
            if p is None:
                return
            p.last_seen = now
            if p.server_source != "record":
                p.server, p.server_source = ev.server, "owner"
            self._consider(p)
        elif isinstance(ev, Hit):
            self._on_hit(ev, now)
        elif isinstance(ev, EntityGone):
            self._on_gone(ev)
        elif isinstance(ev, MapLoaded):
            if ev.map_id != self.map_id:
                self.log(f"map {ev.map_id}: list cleared")
            self.map_id = ev.map_id
            self.clear()  # the server re-sends everyone in view after a load
        self.version += 1

    def _on_self(self, ev: SelfSeen) -> None:
        if ev.name != self.me.name:
            self.log(f"you are {ev.name}" + (f" on {sv.label(ev.server)}" if ev.server else ""))
        self.me.name = ev.name
        self.me.entity_ids.add(ev.entity_id)
        self.players.pop(ev.name, None)
        if ev.server:
            self._set_my_server(ev.server)

    def _set_my_server(self, server: int) -> None:
        changed = server != self.me.server
        self.me.server = server
        if changed and self.me.name:
            self.request_lookup(self.me.name, PRIO_COMBAT, [server], False)
            for p in self.players.values():
                self._consider(p)

    def _on_hit(self, ev: Hit, now: float) -> None:
        actor = self.by_id.get(ev.actor_id)
        target = self.by_id.get(ev.target_id)
        mine = self.me.entity_ids
        if actor and ev.target_id in mine:
            p = self.players[actor]
            p.last_combat = p.last_seen = now
            p.hits_on_you += 1
            self._consider(p, combat=True)
        elif target and ev.actor_id in mine:
            p = self.players[target]
            p.last_combat = p.last_seen = now
            self._consider(p, combat=True)
        else:
            for nm in (actor, target):
                if nm:
                    self.players[nm].last_seen = now

    def _on_gone(self, ev: EntityGone) -> None:
        name = self.by_id.get(ev.entity_id)
        if not name or name not in self.players:
            return
        p = self.players[name]
        if ev.died:
            p.dead = True
            return
        p.entity_ids.discard(ev.entity_id)
        del self.by_id[ev.entity_id]
        if not p.entity_ids:
            del self.players[name]

    # ───── helpers ─────
    def _player(self, name: str, now: float) -> Player:
        p = self.players.get(name)
        if p is None:
            p = self.players[name] = Player(name=name, first_seen=now)
        p.last_seen = now
        return p

    def _bind(self, p: Player, eid: int) -> None:
        old = self.by_id.get(eid)
        if old and old != p.name and old in self.players:
            self.players[old].entity_ids.discard(eid)
        self.by_id[eid] = p.name
        p.entity_ids.add(eid)

    def side(self, p: Player) -> str:
        mine = self.me.faction
        theirs = p.faction
        if mine and theirs:
            return ENEMY if theirs != mine else ALLY
        if p.last_combat:
            return ENEMY
        return UNKNOWN

    def _consider(self, p: Player, combat: bool = False) -> None:
        """Queue a Shugo lookup for this player if one is due."""
        if p.lookup.status in ("queued", "ok"):
            if combat and p.lookup.status == "queued":
                self.request_lookup(p.name, PRIO_COMBAT, self._candidates(p), self._guessed(p))
            return
        s = self.side(p)
        if s == ALLY and not self.lookup_allies:
            return
        cands = [c for c in self._candidates(p) if c not in p.tried_servers]
        if not cands:
            return
        prio = {ENEMY: PRIO_COMBAT if p.last_combat else PRIO_ENEMY,
                UNKNOWN: PRIO_UNKNOWN, ALLY: PRIO_ALLY}[s]
        p.lookup.status = "queued"
        self.request_lookup(p.name, prio, cands, self._guessed(p))

    def _guessed(self, p: Player) -> bool:
        return p.server_source not in ("record", "owner")

    def _candidates(self, p: Player) -> list[int]:
        if p.server and p.server_source in ("record", "owner"):
            return [p.server]
        out: list[int] = []
        if p.server:  # heuristic scan
            out.append(p.server)
        mine = self.me.server
        mirror = sv.mirror_server(mine) if mine else None
        if p.last_combat:
            # Someone fighting you is almost certainly on the enemy side: try theirs first.
            out += [s for s in (mirror,) if s] + self.extra_enemy_servers + ([mine] if mine else [])
        else:
            out += ([mine] if mine else []) + [s for s in (mirror,) if s] + self.extra_enemy_servers
        seen: set[int] = set()
        return [s for s in out if not (s in seen or seen.add(s))][:4]

    # ───── lookup results ─────
    def apply_lookup(self, name: str, result: Lookup, tried: list[int]) -> None:
        if self.me.name == name:
            self.me.lookup = result
            self.version += 1
            return
        p = self.players.get(name)
        if not p:
            return
        p.tried_servers.update(tried)
        p.lookup = result
        if result.status == "ok" and result.server and p.server_source not in ("record", "owner"):
            p.server = result.server
        if result.class_name and not p.class_name:
            p.class_name = result.class_name
        self.version += 1

    def retry(self, name: str) -> None:
        p = self.players.get(name)
        if p:
            if self.on_retry:
                self.on_retry(name)
            p.lookup = Lookup()
            p.tried_servers.clear()
            self._consider(p, combat=bool(p.last_combat))

    # ───── housekeeping / views ─────
    def expire(self, now: float | None = None) -> None:
        """Safety net for players whose 'left view' record was missed."""
        if self.forget_after_s <= 0:
            return
        now = now or time.time()
        dead = [n for n, p in self.players.items() if now - p.last_seen > self.forget_after_s]
        for n in dead:
            for eid in self.players[n].entity_ids:
                if self.by_id.get(eid) == n:
                    del self.by_id[eid]
            del self.players[n]
        if dead:
            self.version += 1

    def clear(self) -> None:
        self.players.clear()
        self.by_id.clear()
        self.version += 1

    def groups(self) -> dict[str, list[Player]]:
        out: dict[str, list[Player]] = {ENEMY: [], ALLY: [], UNKNOWN: []}
        for p in self.players.values():
            out[self.side(p)].append(p)
        for lst in out.values():
            lst.sort(key=lambda p: (p.dead, -p.last_combat, -(p.lookup.combat_power or 0), p.name.lower()))
        return out
