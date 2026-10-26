"""
One small SQLite file for everything Shugo Tracker caches about characters:

  details   card numbers (CP, GS, legion, level, portrait …) per character        key -> compact JSON
  profiles  full profiles (info + equipment) per character                       key -> zlib-packed JSON
  lookups   name lookups ("who is called X in region R, with class/faction F")  query -> the characters found

Replaces character_cache.json (rewritten whole on every exit) and one JSON file per profile. Lookups are what
make Nearby fast: a player you've met before resolves without asking NCSOFT again.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import zlib

_SCHEMA = """
CREATE TABLE IF NOT EXISTS details (key TEXT PRIMARY KEY, ts REAL NOT NULL, data TEXT NOT NULL) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS profiles (key TEXT PRIMARY KEY, ts REAL NOT NULL, data BLOB NOT NULL) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS lookups (q TEXT PRIMARY KEY, ts REAL NOT NULL, data TEXT NOT NULL) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS profiles_ts ON profiles (ts);
"""
_DUMPS = dict(separators=(",", ":"), ensure_ascii=False)


class Store:
    def __init__(self, path: str | None = None):
        """path None = in memory only (tests, --demo)."""
        self.path = path
        if path:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self._lock = threading.Lock()
        self._db = self._open()

    def _open(self) -> sqlite3.Connection:
        try:
            db = sqlite3.connect(self.path or ":memory:", check_same_thread=False, isolation_level=None)
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=NORMAL")
            db.executescript(_SCHEMA)
            return db
        except sqlite3.DatabaseError:
            if not self.path:
                raise
            # a damaged cache is just a cache: start a new one
            for suffix in ("", "-wal", "-shm"):
                try:
                    os.remove(self.path + suffix)
                except OSError:
                    pass
            db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
            db.executescript(_SCHEMA)
            return db

    def _run(self, sql: str, args=(), many: bool = False):
        with self._lock:
            try:
                return (self._db.executemany if many else self._db.execute)(sql, args).fetchall()
            except sqlite3.Error:
                return []

    # ───── card details ─────
    def all_details(self, newer_than: float) -> dict[str, dict]:
        out = {}
        for key, ts, data in self._run("SELECT key, ts, data FROM details WHERE ts > ?", (newer_than,)):
            try:
                out[key] = {**json.loads(data), "ts": ts}
            except ValueError:
                pass
        return out

    def put_details(self, key: str, info: dict, ts: float | None = None) -> None:
        info = {k: v for k, v in info.items() if k != "ts" and v is not None}
        self._run("INSERT OR REPLACE INTO details VALUES (?, ?, ?)", (key, ts or time.time(), json.dumps(info, **_DUMPS)))

    def drop_details(self, key: str) -> None:
        self._run("DELETE FROM details WHERE key = ?", (key,))

    # ───── profiles ─────
    def get_profile(self, key: str) -> tuple[float, dict, dict | None] | None:
        rows = self._run("SELECT ts, data FROM profiles WHERE key = ?", (key,))
        if not rows:
            return None
        try:
            d = json.loads(zlib.decompress(rows[0][1]))
            return rows[0][0], d["info"], d.get("equipment")
        except (zlib.error, ValueError, KeyError, TypeError):
            return None

    def put_profile(self, key: str, info: dict, eq: dict | None, ts: float | None = None) -> None:
        blob = zlib.compress(json.dumps({"info": info, "equipment": eq}, **_DUMPS).encode(), 6)
        self._run("INSERT OR REPLACE INTO profiles VALUES (?, ?, ?)", (key, ts or time.time(), blob))

    def drop_profile(self, key: str) -> None:
        self._run("DELETE FROM profiles WHERE key = ?", (key,))

    # ───── name lookups ─────
    @staticmethod
    def lookup_key(region: str, name: str, pc_ids=None, race=None) -> str:
        ids = ",".join(str(i) for i in sorted(pc_ids)) if pc_ids else ""
        return f"{region}|{name.casefold()}|{ids}|{race or ''}"

    def get_lookup(self, q: str, max_age: float, empty_max_age: float) -> list[dict] | None:
        rows = self._run("SELECT ts, data FROM lookups WHERE q = ?", (q,))
        if not rows:
            return None
        ts, data = rows[0]
        try:
            found = json.loads(data)
        except ValueError:
            return None
        age = time.time() - ts
        return found if age < (max_age if found else empty_max_age) else None

    def put_lookup(self, q: str, found: list[dict]) -> None:
        self._run("INSERT OR REPLACE INTO lookups VALUES (?, ?, ?)", (q, time.time(), json.dumps(found, **_DUMPS)))

    # ───── housekeeping ─────
    def prune(self, details_keep: float, profiles_keep: float, profiles_max: int, lookups_keep: float) -> None:
        now = time.time()
        self._run("DELETE FROM details WHERE ts < ?", (now - details_keep,))
        self._run("DELETE FROM lookups WHERE ts < ?", (now - lookups_keep,))
        self._run("DELETE FROM profiles WHERE ts < ? OR key NOT IN "
                  "(SELECT key FROM profiles ORDER BY ts DESC LIMIT ?)", (now - profiles_keep, profiles_max))

    def clear(self) -> None:
        for table in ("details", "profiles", "lookups"):
            self._run(f"DELETE FROM {table}")
        self._run("VACUUM")

    def size(self) -> int:
        if not self.path:
            return 0
        return sum(os.path.getsize(self.path + s) for s in ("", "-wal") if os.path.exists(self.path + s))

    def counts(self) -> dict[str, int]:
        return {t: (self._run(f"SELECT COUNT(*) FROM {t}") or [(0,)])[0][0] for t in ("details", "profiles", "lookups")}

    def close(self) -> None:
        with self._lock:
            try:
                self._db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                self._db.close()
            except sqlite3.Error:
                pass

    # ───── moving off the old files ─────
    def migrate(self, details_json: str | None, profile_dir: str | None) -> None:
        """Import character_cache.json once and delete it; old per-profile JSON files are just removed."""
        if details_json and os.path.exists(details_json):
            try:
                with open(details_json, encoding="utf-8") as f:
                    data = json.load(f)
                rows = [(k, float(v.get("ts", 0)), json.dumps({kk: vv for kk, vv in v.items()
                                                                if kk != "ts" and vv is not None}, **_DUMPS))
                        for k, v in (data.items() if isinstance(data, dict) else []) if isinstance(v, dict)]
                self._run("INSERT OR REPLACE INTO details VALUES (?, ?, ?)", rows, many=True)
            except (OSError, ValueError, TypeError):
                pass
            try:
                os.remove(details_json)
            except OSError:
                pass
        if profile_dir and os.path.isdir(profile_dir):
            for f in os.listdir(profile_dir):
                try:
                    os.remove(os.path.join(profile_dir, f))
                except OSError:
                    pass
            try:
                os.rmdir(profile_dir)
            except OSError:
                pass
