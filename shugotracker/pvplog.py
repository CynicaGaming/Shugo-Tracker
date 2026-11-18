"""The PvP Log: who you killed and who killed you, kept in data\\pvp_log.jsonl (one fight per line, oldest first).

Each record: {"t": epoch seconds, "kind": "kill" | "assist" | "death", "me": your character's name,
"foe": the other player's card (name, server, class, level, key…), "with": other players who took part, "by": on an assist, who landed the killing blow}.
"""
from __future__ import annotations

import json
import os
import threading
import time

KINDS = ("kill", "assist", "death")
_CARD = ("char_id", "name", "race", "pc_id", "level", "server_id", "server_name", "region", "portrait", "legion",
         "class_name", "key")


def foe_id(card: dict) -> str:
    """One opponent across records: name and server (their card key isn't always known yet)."""
    return f"{card.get('server_id') or 0}|{card.get('name') or ''}"


class PvpLog:
    def __init__(self, path: str | None, log=None):
        self.path = path                       # None: in memory only (demo)
        self.log = log or (lambda s: None)
        self.records: list[dict] = []
        self._lock = threading.Lock()
        self.version = 0
        self._load()

    def _load(self) -> None:
        if not self.path or not os.path.exists(self.path):
            return
        try:
            with open(self.path, encoding="utf-8") as f:
                for line in f:
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue                 # a line cut off by a crash: skip it
                    if isinstance(r, dict) and r.get("kind") in KINDS and isinstance(r.get("foe"), dict):
                        self.records.append(r)
        except OSError as e:
            self.log(f"pvp log: couldn't read {self.path}: {e}")

    def add(self, kind: str, me: str, foe: dict, with_: list[str] | None = None, t: float | None = None,
            by: str | None = None) -> dict:
        """by: on an assist, who landed the killing blow."""
        r = {"t": round(t if t is not None else time.time(), 1), "kind": kind, "me": me or "",
             "foe": {k: foe.get(k) for k in _CARD if foe.get(k) not in (None, "")}, "with": list(with_ or [])}
        if by:
            r["by"] = by
        with self._lock:
            self.records.append(r)
            self.version += 1
            if self.path:
                try:
                    with open(self.path, "a", encoding="utf-8") as f:
                        f.write(json.dumps(r, ensure_ascii=False) + "\n")
                except OSError as e:
                    self.log(f"pvp log: couldn't save: {e}")
        return r

    def _mine(self, me: str | None, since: float, until: float = 0) -> list[dict]:
        return [r for r in self.records if r["t"] >= since and (not until or r["t"] < until)
                and (not me or not r.get("me") or r["me"] == me)]

    def summary(self, me: str | None = None, since: float = 0, until: float = 0) -> dict:
        """Everyone you fought between `since` and `until` (0: no end), newest fight first, with kills / assists /
        deaths."""
        with self._lock:
            rows: dict[str, dict] = {}
            totals = {k: 0 for k in KINDS}
            for r in self._mine(me, since, until):
                fid = foe_id(r["foe"])
                row = rows.get(fid)
                if row is None:
                    row = rows[fid] = {"id": fid, "foe": r["foe"], "kill": 0, "assist": 0, "death": 0, "last": 0}
                row[r["kind"]] += 1
                totals[r["kind"]] += 1
                if r["t"] >= row["last"]:
                    row["last"], row["foe"] = r["t"], {**row["foe"], **r["foe"]}   # newest card wins
            out = sorted(rows.values(), key=lambda x: -x["last"])
            return {"foes": out, "totals": totals}

    def detail(self, fid: str, me: str | None = None, since: float = 0, until: float = 0) -> dict:
        """One opponent: every fight between `since` and `until`, newest first."""
        with self._lock:
            fights = [r for r in self._mine(me, since, until) if foe_id(r["foe"]) == fid]
            every = [r for r in self.records if foe_id(r["foe"]) == fid]
        totals = {k: sum(1 for r in fights if r["kind"] == k) for k in KINDS}
        card = {}
        for r in every:                          # their newest card, whatever the filter
            card.update(r["foe"])
        return {"id": fid, "foe": card, "totals": totals, "fights": sorted(fights, key=lambda r: -r["t"])}

    def feed(self, me: str | None = None, limit: int = 50, today_since: float = 0) -> dict:
        """The PVP pop-out: your latest fights (newest first, with each opponent's id) and today's totals."""
        with self._lock:
            mine = self._mine(me, 0)
            latest = sorted(mine, key=lambda r: -r["t"])[:limit]
            today = {k: sum(1 for r in mine if r["t"] >= today_since and r["kind"] == k) for k in KINDS}
        return {"fights": [{**r, "id": foe_id(r["foe"])} for r in latest], "today": today}
