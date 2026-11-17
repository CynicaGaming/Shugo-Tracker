"""
The backend of the Electron app: everything that isn't drawing (NCSOFT client and caches, favorites, your
characters, Nearby capture, skill text), driven by JSON messages.

Electron starts it as a child process and talks over stdin / stdout, one JSON object per line:

    in:   {"id": 7, "method": "search", "params": {...}}
    out:  {"id": 7, "result": ...}            (or {"id": 7, "error": "..."}), possibly later (profile items, boards)
    out:  {"event": "card", "data": {...}}    (pushed: search pages, card numbers, profile stages, Nearby)

`python -m shugotracker.devserver` runs the same Core behind a small web server so the UI can be previewed in a
browser (demo data).
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import traceback
from dataclasses import asdict
from typing import Any, Callable

from . import servers as sv
from ._version import __version__
from .aion2api import SUB_REGIONS, Api, Character, character_from_dict, rank

PAGE_SIZE = 50


def char_json(c: Character) -> dict:
    d = asdict(c)
    d["key"], d["class_name"] = c.key, c.class_name
    return d


def to_json(o):
    """Dataclasses (Profile, ItemDetail, …) as plain JSON."""
    if o is None:
        return None
    try:
        return asdict(o)
    except TypeError:
        return o


class Core:
    def __init__(self, root: str, emit: Callable[[dict], None], demo: bool = False, log=None,
                 showcase: str | None = None):
        """root: the app folder (data, cache, logs live next to the exe). emit: sends one message to the UI."""
        from .config import DEFAULTS, load_config, migrate, migrate_to_app_folder
        from .favorites import Favorites
        from .profiles import MyCharacters

        self.root, self.demo, self._emit = root, demo, emit
        self.data, self.cache, self.logs = (os.path.join(root, d) for d in ("data", "cache", "logs"))
        for d in (self.data, self.cache, self.logs):
            os.makedirs(d, exist_ok=True)
        self.log = log or (lambda m: None)
        if not demo:
            try:
                migrate_to_app_folder(root)              # very old versions kept everything in %APPDATA%
            except OSError:
                pass
        self.config_path = os.path.join(self.data, "config.json")
        self.cfg = migrate(dict(DEFAULTS)) if demo else load_config(self.config_path)
        session = None
        if showcase:                                     # README screenshots: demo data plus one real character
            from .demo import ShowcaseSession
            session = ShowcaseSession(*showcase.split("=", 1))
        elif demo:
            from .demo import DemoSession
            session = DemoSession()
        self.api = Api(db_path=None if demo else os.path.join(self.cache, "shugo.db"), session=session, log=self.log)
        self.my = MyCharacters(self.cfg)
        self.favorites = Favorites(None if demo else os.path.join(self.data, "favorites.json"), log=self.log)
        self.chars: dict[str, Character] = {}           # every character the UI has seen, by key
        self._lock = threading.Lock()
        self._gen = 0
        from .nearby import NearbyService
        find = None
        if demo:
            from .demo import find_nearby
            find = find_nearby(session)
        self.nearby = NearbyService(self.api, self.cfg, log=self.log, data_dir=self.logs, find=find)
        self.nearby.on_region = lambda r: self.set_config("nearby_region", r)
        from .pvplog import PvpLog
        self.pvp = PvpLog(None if demo else os.path.join(self.data, "pvp_log.jsonl"), log=self.log)
        if demo:
            from .demo import seed_pvp
            seed_pvp(self.pvp)
        self.nearby.on_pvp = self._on_pvp
        mine = self.my.active()
        if mine and not demo:                            # your character, before the game says so (mid-match starts)
            self.nearby.set_me(mine["name"], mine.get("server_id") or 0)
        self._nearby_seen = None
        self._stop = threading.Event()
        threading.Thread(target=self._watch_nearby, name="nearby-watch", daemon=True).start()
        try:
            os.remove(os.path.join(self.cache, "nearby_state.json"))   # (2.3.12 saved the list there)
        except OSError:
            pass
        if self.cfg.get("nearby_enabled"):
            self._nearby_on(True)

    # ───── plumbing ─────
    def emit(self, event: str, data: Any) -> None:
        self._emit({"event": event, "data": data})

    def save(self) -> None:
        if not self.demo:
            from .config import save_config
            save_config(self.config_path, self.cfg)

    def set_config(self, key: str, value) -> None:
        self.cfg[key] = value
        self.save()

    def _char(self, key: str) -> Character:
        c = self.chars.get(key)
        if c is None:
            raise KeyError(f"unknown character {key}")
        return c

    def _keep(self, chars) -> list[dict]:
        out = []
        for c in chars:
            old = self.chars.get(c.key)
            if old is not None and old.status == "ok" and c.status != "ok":
                c = old                                   # keep numbers we already have
            self.chars[c.key] = c
            out.append(char_json(c))
        return out

    def handle(self, msg: dict, reply: Callable[[dict], None]) -> None:
        """One request. Replies through `reply`, now or later (from a worker thread)."""
        rid, method, params = msg.get("id"), msg.get("method", ""), msg.get("params") or {}
        fn = getattr(self, "rpc_" + method.replace(".", "_"), None)
        if fn is None:
            reply({"id": rid, "error": f"unknown method {method}"})
            return

        def answer(result=None, error=None):
            reply({"id": rid, "error": error} if error else {"id": rid, "result": result})
        try:
            out = fn(answer=answer, **params) if getattr(fn, "deferred", False) else fn(**params)
            if not getattr(fn, "deferred", False):
                answer(out)
        except Exception as e:  # noqa: BLE001
            self.log(f"core: {method} failed: {e}\n{traceback.format_exc()}")
            answer(error=f"{e.__class__.__name__}: {e}")

    def close(self) -> None:
        self._stop.set()
        self.nearby.stop()
        self.api.close()
        self.save()

    # ───── start-up ─────
    def rpc_init(self) -> dict:
        self._nearby_seen = None             # the window is (re)loaded: send it Nearby's state again
        return {"version": __version__, "demo": self.demo, "config": self.cfg, "regions": SUB_REGIONS,
                "favorites": self._keep(self.favorites.characters()), "my": self._my_state(),
                "nearby": self._nearby_state()}

    def rpc_config_set(self, key: str, value=None) -> bool:
        self.set_config(key, value)
        return True

    # ───── search ─────
    @staticmethod
    def _filters(f: dict | None) -> dict:
        """The UI's filters ({classes, factions, level_min, level_max}) -> what NCSOFT's search applies itself."""
        from .aion2api import search_filters
        f = f or {}
        return search_filters(f.get("classes") or (), f.get("factions") or (), f.get("level_min"), f.get("level_max"))

    def rpc_search(self, keyword: str, filters: dict | None = None, gen: int | None = None) -> int:
        """A new search over every region; pages arrive as "search" events tagged with `gen` (the UI numbers its
        searches itself: cached pages can arrive before this call has even answered)."""
        filters = self._filters(filters)
        with self._lock:
            self._gen = gen if gen is not None else self._gen + 1
            gen = self._gen
        self.api.new_generation()
        for r in SUB_REGIONS:
            self._page(gen, keyword, r, 1, filters or {})
        return gen

    def rpc_search_more(self, gen: int, keyword: str, region: str, page: int, filters: dict | None = None) -> bool:
        self._page(gen, keyword, region, page, self._filters(filters))
        return True

    def _page(self, gen: int, keyword: str, region: str, page: int, filters: dict) -> None:
        def done(reg, chars, total, err):
            if gen != self._gen:
                return
            ranked = rank(chars, keyword)
            self.emit("search", {"gen": gen, "region": reg, "page": page, "total": total, "error": err,
                                 "chars": self._keep(ranked)})
        self.api.search(keyword, [region], page=page, size=PAGE_SIZE, filters=filters, on_done=done)

    def rpc_cards_want(self, keys: list[str], background: bool = False) -> bool:
        """Card numbers (CP, GS, legion) for these characters; each arrives as a "card" event."""
        for k in keys:
            c = self.chars.get(k)
            if c is not None:
                self.api.want(c, lambda ch: self.emit("card", char_json(ch)), background=background)
                if c.status == "ok" and not c.stale:
                    self.emit("card", char_json(c))
        return True

    def rpc_card_refresh(self, key: str) -> bool:
        c = self._char(key)
        c.status = "none"
        self.api.forget(c)
        self.api.want(c, lambda ch: self.emit("card", char_json(ch)))
        return True

    # ───── favorites ─────
    def rpc_favorites_toggle(self, key: str) -> dict:
        on = self.favorites.toggle(self._char(key))
        return {"on": on, "favorites": self._keep(self.favorites.characters())}

    def rpc_favorites_move(self, key: str, index: int) -> list[dict]:
        self.favorites.move(key, index)
        return self._keep(self.favorites.characters())

    # ───── your characters (Set Profile / Switch Profile) ─────
    def _my_state(self) -> dict:
        return {"slots": self.my.slots, "active": self.my.active_slot}

    def _my_changed(self) -> dict:
        a = self.my.active()
        if a:
            self.nearby.set_me(a["name"], a.get("server_id") or 0)
        self.save()
        return self._my_state()

    def rpc_my_set(self, key: str, slot: int) -> dict:
        from .profiles import KEEP
        c = self._char(key)
        self.my.set(slot, {k: getattr(c, k) for k in KEEP})
        return self._my_changed()

    def rpc_my_switch(self, slot: int) -> dict:
        self.my.activate(slot)
        return self._my_changed()

    def rpc_my_delete(self, slot: int) -> dict:
        self.my.delete(slot)
        return self._my_changed()

    def rpc_my_character(self) -> dict | None:
        """Your active character as a Character (registered, so its profile can be opened)."""
        a = self.my.active()
        if not a:
            return None
        c = character_from_dict(a)
        self.chars.setdefault(c.key, c)
        return char_json(self.chars[c.key])

    # ───── profiles ─────
    def rpc_profile_open(self, key: str, force: bool = False) -> bool:
        """The profile arrives as "profile" events: a cached copy, a partial one (gear pending), the full one."""
        c = self._char(key)
        if force:
            self.api.forget(c)

        def done(ch, prof, err):
            self.emit("profile", {"key": ch.key, "profile": to_json(prof), "error": err,
                                  "char": char_json(ch)})
        self.api.fetch_profile(c, done, force=force)
        return True

    def rpc_item_detail(self, key: str, item: dict, answer) -> None:
        from .profile import Item
        c = self._char(key)
        it = Item(slot=item.get("slot", ""), name=item.get("name", ""), grade=item.get("grade", ""),
                  enchant=int(item.get("enchant") or 0), item_id=int(item.get("item_id") or 0),
                  slot_pos=int(item.get("slot_pos") or 0))
        self.api.fetch_item_detail(c, it, lambda det: answer(to_json(det)))
    rpc_item_detail.deferred = True

    def rpc_board(self, key: str, board_id: int, opened: int, answer) -> None:
        from .profile import parse_board
        c = self._char(key)
        self.api.fetch_board(c, board_id, opened, lambda raw: answer(to_json(parse_board(raw)) if raw else None))
    rpc_board.deferred = True

    def rpc_skill(self, skill_id: int, level: int, name: str = "", cls: str = "") -> dict | None:
        from . import skilldata
        t = skilldata.describe(skill_id, level, name, cls)
        return to_json(t)

    def rpc_alt(self) -> bool | None:
        """Whether Alt is held, even while the game has focus (Alt-compare in a profile); None where Windows
        can't be asked (the window then goes by its own key events)."""
        if sys.platform != "win32":
            return None
        import ctypes
        return bool(ctypes.windll.user32.GetAsyncKeyState(0x12) & 0x8000)   # VK_MENU

    # ───── Nearby ─────
    def rpc_nearby_enable(self, on: bool) -> dict:
        self._nearby_on(on)
        return self._nearby_state()

    def _nearby_on(self, on: bool) -> None:
        self.cfg["nearby_enabled"] = bool(on)
        if on:
            if self.demo:
                from .demo import feed_nearby
                self.nearby.start_demo(feed_nearby)
            else:
                self.nearby.start()
        else:
            self.nearby.stop()
        self.save()
        self._nearby_seen = None

    def _nearby_state(self) -> dict:
        nb = self.nearby
        rows = nb.snapshot() if self.cfg.get("nearby_enabled") else []
        recent = nb.recent() if self.cfg.get("nearby_enabled") else []
        for _s, c, *_ in rows + recent:
            self.chars[c.key] = c
        return {"enabled": bool(self.cfg.get("nearby_enabled")), "state": nb.state, "detail": nb.detail,
                "rows": [{"side": s, "char": char_json(c)} for s, c, _p in rows],
                "recent": [{"side": s, "char": char_json(c), "seen": t, "fought": f} for s, c, t, f in recent]}

    def _watch_nearby(self) -> None:
        cleared = time.monotonic()
        while not self._stop.wait(0.3):
            try:
                every = int(self.cfg.get("nearby_autoclear_s") or 0)   # Settings: move everyone to Recent every N s
                if not (every and self.cfg.get("nearby_enabled")):
                    cleared = time.monotonic()
                elif time.monotonic() - cleared >= every:
                    cleared = time.monotonic()
                    self.nearby.clear_nearby()
                v = (self.nearby.version(), bool(self.cfg.get("nearby_enabled")), self.nearby.state)
                if v != self._nearby_seen:
                    self.emit("nearby", self._nearby_state())
                    self._nearby_seen = v                   # (only once sent: a failed send is tried again)
            except Exception as e:  # noqa: BLE001
                self.log(f"core: nearby watch: {e}")

    def rpc_demo_teleport(self) -> bool:
        """Demo only: you load into a new area, so the crowd moves to Recent (README screenshots)."""
        if not self.demo:
            return False
        from .demo import feed_teleport
        feed_teleport(self.nearby)
        return True

    def rpc_nearby_clear(self, which: str = "nearby") -> bool:
        (self.nearby.clear_recent if which == "recent" else self.nearby.clear_nearby)()
        return True

    # ───── PvP Log ─────
    def _on_pvp(self, kind: str, foe: Character, with_: list[str], by: str | None = None) -> None:
        me = self.nearby.tracker.me.name or (self.my.active() or {}).get("name") or ""
        self.chars[foe.key] = foe
        r = self.pvp.add(kind, me, char_json(foe), with_, by=by)
        self.emit("pvp", r)

    def _pvp_me(self) -> str | None:
        """The log follows the character you've picked (all of them when none is)."""
        return (self.my.active() or {}).get("name") or None

    def rpc_pvp_list(self, since: float = 0, until: float = 0) -> dict:
        return self.pvp.summary(self._pvp_me(), since or 0, until or 0)

    def rpc_pvp_detail(self, id: str, since: float = 0, until: float = 0) -> dict:   # noqa: A002
        d = self.pvp.detail(id, self._pvp_me(), since or 0, until or 0)
        f = d["foe"]
        if f.get("char_id") and f.get("server_id") and f.get("key") not in self.chars:   # so View Profile opens it
            from dataclasses import fields
            names = {x.name for x in fields(Character)}
            base = {"race": 0, "pc_id": 0, "level": 0, "server_name": "", "region": ""}
            c = Character(**{**base, **{k: v for k, v in f.items() if k in names}})
            self.chars[c.key] = c
            f["key"] = c.key
        return d

    def rpc_recent_max(self, n: int) -> bool:
        self.set_config("recent_max", int(n))
        self.nearby.set_recent_max(int(n))
        return True

    def rpc_find_mine(self, name: str, server_id: int) -> list[dict]:
        """First-run setup: characters on one server whose names start with `name` (one search request)."""
        sid = int(server_id)
        region = sv.REGION_PREFIX.get(sv.region_of(sid))
        name = (name or "").strip()
        if not region or not name:
            return []
        try:
            chars, _total = self.api.search_region(name, region, 1, 30, {"serverId": sid, "race": sv.race_of(sid)})
        except Exception as e:  # noqa: BLE001
            self.log(f"core: find_mine: {e}")
            raise RuntimeError("Couldn't reach the AION 2 site. Try again in a moment.") from e
        mine = [c for c in chars if c.server_id == sid] or (chars if self.demo else [])
        return self._keep(rank(mine, name))

    def rpc_servers(self) -> dict:
        """Server id -> name (for labels)."""
        return {str(k): v for k, v in sv.SERVER_NAMES.items()}


def serve_stdio(root: str, demo: bool = False, showcase: str | None = None) -> int:
    """Electron's child process: requests on stdin, answers and events on stdout."""
    out_lock = threading.Lock()
    # The pipe to Electron is UTF-8 both ways. Windows would otherwise use its old ANSI code page (cp1252), and
    # one player named in Chinese or Korean made every message about Nearby fail to send ("'charmap' codec
    # can't encode"); output is also kept pure ASCII (\uXXXX escapes), so no encoding can trip it again.
    for stream in (sys.stdin, sys.stdout):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    stdout = sys.stdout

    def write(obj: dict) -> None:
        line = json.dumps(obj, ensure_ascii=True, separators=(",", ":"))
        with out_lock:
            stdout.write(line + "\n")
            stdout.flush()
    from .logfiles import DailyText
    daily = DailyText(os.path.join(root, "logs"), "shugo-core")      # logs\shugo-core_<day>.log, 14 days kept
    log_lock = threading.Lock()

    def log(m: str) -> None:
        with log_lock:
            daily.write(m)
    log(f"──── Shugo Tracker core v{__version__} started" + (" (demo)" if demo else ""))
    core = Core(root, write, demo=demo or bool(showcase), log=log, showcase=showcase)
    # Requests run on a small pool (some wait on the network; most are instant), not a new thread each.
    from concurrent.futures import ThreadPoolExecutor
    pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="rpc")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        if msg.get("method") == "quit":
            break
        if msg.get("method") == "config.set":
            core.handle(msg, write)                        # at once and in order: the last ones arrive with "quit"
            continue
        pool.submit(core.handle, msg, write)
    pool.shutdown(wait=False, cancel_futures=True)
    core.close()
    return 0


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Shugo Tracker core (started by the Electron app)")
    ap.add_argument("--root", required=True, help="the app folder: data, cache and logs live here")
    ap.add_argument("--demo", action="store_true", help="made-up characters and players (no network)")
    ap.add_argument("--showcase", metavar="REAL=ALIAS", help="demo data plus one real character under another name")
    a = ap.parse_args(argv)
    return serve_stdio(a.root, a.demo, a.showcase)


if __name__ == "__main__":
    sys.exit(main())
