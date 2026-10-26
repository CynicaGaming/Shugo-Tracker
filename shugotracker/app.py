"""Entry point: wires capture -> decoder -> tracker -> Shugo lookups -> overlay."""
from __future__ import annotations

import argparse
import json
import os
import queue
import sys
import threading
import time

from . import servers as sv
from .protocol import Opcodes, StreamDecoder
from .shugo import ShugoClient
from .tracker import Tracker
from .updater import Updater, __version__

FROZEN = getattr(sys, "frozen", False)
# Next to ShugoTracker.exe when built, else the project folder.
HERE = os.path.dirname(sys.executable) if FROZEN else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _data_dir() -> str:
    """
    Where settings, favorites and caches live. The packaged app uses %APPDATA%\\ShugoTracker so they survive
    updates, moving the exe, or running a freshly downloaded copy from somewhere else.
    """
    if FROZEN and os.name == "nt" and os.environ.get("APPDATA"):
        return os.path.join(os.environ["APPDATA"], "ShugoTracker")
    return HERE


DATA = _data_dir()
USER_FILES = ("config.json", "favorites.json", "character_cache.json")   # (the last is imported into cache/shugo.db)


def migrate_user_files(old_dir: str, new_dir: str) -> list[str]:
    """Bring files that older versions kept next to the exe into the data folder. Returns what moved."""
    import shutil
    moved = []
    if os.path.normcase(os.path.abspath(old_dir)) == os.path.normcase(os.path.abspath(new_dir)):
        return moved
    os.makedirs(new_dir, exist_ok=True)
    for name in USER_FILES:
        src, dst = os.path.join(old_dir, name), os.path.join(new_dir, name)
        if not os.path.isfile(src):
            continue
        try:
            if name == "favorites.json" and os.path.exists(dst):
                from .favorites import Favorites
                merged = Favorites(dst)
                if merged.merge_from(src):
                    merged.save()
            elif not os.path.exists(dst):
                shutil.copy2(src, dst)
            else:
                continue
            os.replace(src, src + ".moved")      # leave a trace, never read again
            moved.append(name)
        except OSError:
            pass
    return moved
DEFAULT_CONFIG = {
    "my_server": "",
    "lookup_allies": True,
    "lookup_interval_s": 2.0,
    "forget_after_s": 900,
    "collapsed_sections": [],
    "max_height": 520,
    "extra_enemy_servers": [],
    "kr_tw_region": "kr",
    "interfaces": [],
    "position": [40, 200],
    "auto_update": True,
    "update_repo": "CynicaGaming/Shugo-Tracker",
    "regions": [],
    "factions": [],
    "always_on_top": True,
    "window_pos": [80, 80],
    "opcodes": {},
}


def load_config(path: str) -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            cfg.update(json.load(f))
    return cfg


def save_config(path: str, cfg: dict) -> None:
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except OSError:
        pass


class App:
    def __init__(self, cfg: dict, debug: bool = False):
        self.cfg = cfg
        self.debug = debug
        self.events: queue.Queue = queue.Queue()
        self.log_lines: list[str] = []
        self._log_file = None
        try:
            self._log_file = open(os.path.join(DATA, "shugo-tracker.log"), "w", encoding="utf-8")
        except OSError:
            pass
        self.capture = None
        self._decoders: dict = {}
        self._dec_lock = threading.Lock()

        my_server = sv.parse_server(cfg.get("my_server"))
        if cfg.get("my_server") and not my_server:
            self.log(f"config: unknown my_server {cfg['my_server']!r}")
        extra = [s for s in (sv.parse_server(x) for x in cfg.get("extra_enemy_servers", [])) if s]
        self.opcodes = Opcodes(**{k: v for k, v in cfg.get("opcodes", {}).items()
                                  if k in Opcodes.__dataclass_fields__})

        self.shugo = ShugoClient(
            on_result=lambda n, r, t: self.events.put(("lookup", n, r, t)),
            min_interval_s=float(cfg.get("lookup_interval_s", 2.0)),
            cache_path=os.path.join(HERE, "shugo_cache.json"),
            kr_tw_region=cfg.get("kr_tw_region", "kr"),
            log=self.log)
        self.tracker = Tracker(
            request_lookup=self.shugo.request,
            my_server=my_server,
            lookup_allies=bool(cfg.get("lookup_allies", True)),
            forget_after_s=float(cfg.get("forget_after_s", 900)),
            extra_enemy_servers=extra,
            log=self.log)
        self.tracker.on_retry = self.shugo.forget
        self.updater = Updater(repo=cfg.get("update_repo") or "CynicaGaming/shugo-tracker",
                               enabled=bool(cfg.get("auto_update", True)), log=self.log)
        self.log(f"Shugo Tracker v{__version__}")

    # ───── logging ─────
    def log(self, msg: str) -> None:
        line = time.strftime("%H:%M:%S ") + msg
        self.log_lines = (self.log_lines + [line])[-50:]
        if sys.stdout is not None:  # no console in the windowed .exe
            print(line, flush=True)
        if self._log_file:
            try:
                self._log_file.write(line + "\n")
                self._log_file.flush()
            except (OSError, ValueError):
                pass

    # ───── capture side (runs on the capture thread) ─────
    def on_bytes(self, flow, data: bytes, gap: bool) -> None:
        with self._dec_lock:
            dec = self._decoders.get(flow)
            if dec is None:
                dec = self._decoders[flow] = StreamDecoder(
                    emit=lambda ev: self.events.put(("ev", ev)),
                    known_servers=sv.KNOWN_SERVERS, opcodes=self.opcodes,
                    debug=self.log if self.debug else None)
            if gap:
                dec.reset()
            dec.feed(data)

    # ───── main thread ─────
    def tick(self) -> None:
        deadline = time.time() + 0.05
        while time.time() < deadline:
            try:
                item = self.events.get_nowait()
            except queue.Empty:
                break
            if item[0] == "ev":
                ev = item[1]
                if self.debug:
                    self.log(repr(ev))
                self.tracker.handle(ev)
            elif item[0] == "lookup":
                _, name, result, tried = item
                self.tracker.apply_lookup(name, result, tried)
        now = time.time()
        if now - getattr(self, "_last_expire", 0) > 5:
            self._last_expire = now
            self.tracker.expire(now)

    def status(self) -> str:
        bits = [f"v{__version__}"]
        if self.capture is not None:
            bits.append(self.capture.status)
        q = self.shugo.pending()
        if q:
            bits.append(f"{q} lookups queued")
        return " · ".join(bits)

    def start_live(self) -> None:
        from .capture import GameCapture
        self.capture = GameCapture(self.on_bytes, ifaces=self.cfg.get("interfaces") or None, log=self.log)
        self.capture.start()

    def stop(self) -> None:
        self.updater.stop()
        if self.capture:
            self.capture.stop()
        self.shugo.stop()


def print_table(app: App) -> None:
    g = app.tracker.groups()
    print(f"\n── you: {app.tracker.me.name or '?'} {sv.label(app.tracker.me.server)} ──")
    for key, title in (("enemy", "ENEMIES"), ("ally", "ALLIES"), ("unknown", "UNIDENTIFIED")):
        print(f" {title} ({len(g[key])})")
        for p in g[key]:
            lk = p.lookup
            print(f"   {('x ' if p.dead else '') + p.name:16} {lk.class_name or p.class_name or '':12} "
                  f"GS {lk.gear_score or '-':>6}  CP {lk.combat_power or '-':>8}  "
                  f"{sv.label(lk.server or p.server)}  [{lk.status}{' guessed' if lk.guessed else ''}]")


def _wire_demo(app: App) -> None:
    """Fake events and fake Shugo answers, to check the overlay without the game."""
    import random
    from .protocol import EntityGone, Hit, PlayerSeen, SelfSeen
    from .tracker import Lookup

    rnd = random.Random()
    classes = ["Gladiator", "Templar", "Ranger", "Assassin", "Elementalist", "Sorcerer", "Cleric", "Chanter"]
    syll = ["ka", "ri", "mor", "vel", "dra", "nyx", "sa", "lo", "thi", "gr", "ae", "zu", "kel", "en"]

    def fake_lookup(name, prio, cands, guessed):
        def answer():
            time.sleep(rnd.uniform(0.2, 1.2))
            srv = rnd.choice(cands)
            r = Lookup(status="ok", server=srv, guessed=guessed, gear_score=rnd.randint(1100, 2900),
                       combat_power=rnd.randint(45_000, 170_000), level=45,
                       class_name=rnd.choice(classes), faction=sv.race_of(srv),
                       url=f"https://shugo.gg/character/{sv.shugo_server_path(srv)}/{name}")
            if name == "Aerin":
                r.combat_power = 100_000
            app.events.put(("lookup", name, r, cands))
        threading.Thread(target=answer, daemon=True).start()

    app.shugo.request = fake_lookup  # type: ignore[method-assign]
    app.tracker.request_lookup = fake_lookup

    def feed():
        app.events.put(("ev", SelfSeen(501, "Aerin", 1101, "Templar", 45)))
        in_view: list[int] = []
        next_id = 9000
        while True:
            time.sleep(rnd.uniform(0.3, 1.2))
            roll = rnd.random()
            if roll < 0.55 or len(in_view) < 6:
                name = "".join(rnd.choice(syll) for _ in range(rnd.randint(2, 3))).capitalize()
                kind = rnd.random()
                server, src = (2101, "record") if kind < 0.35 else (1101, "record") if kind < 0.8 else (None, None)
                app.events.put(("ev", PlayerSeen(next_id, name, server, src, rnd.choice(classes))))
                in_view.append(next_id)
                next_id += 1
            elif roll < 0.75 and in_view:
                gone = in_view.pop(rnd.randrange(len(in_view)))
                app.events.put(("ev", EntityGone(gone, died=rnd.random() < 0.2)))
            elif in_view:
                app.events.put(("ev", Hit(rnd.choice(in_view), 501)))

    threading.Thread(target=feed, daemon=True).start()


def _run_search(cfg: dict, config_path: str, demo: bool = False, query: str | None = None,
                screenshot: str | None = None, after_update: bool = False, selftest: str | None = None) -> int:
    from .aion2api import Api
    from .search_ui import SearchWindow
    from .updater import Updater

    from .desktop import SingleInstance, Tray, folder_size, tray_supported
    from .settings import migrate
    from .settings_ui import SettingsServices

    instance = None
    if not (demo or screenshot):
        instance = SingleInstance()
        acquired = instance.acquire()
        if not acquired and after_update:
            # Started by the updater: the old version may still be finishing its shutdown.
            for _ in range(40):
                time.sleep(0.25)
                if instance.acquire():
                    acquired = True
                    break
        if not acquired:
            # Already running (maybe hidden): bring that copy forward instead of opening a second one.
            if instance.notify_running():
                return 0
            instance = None

    migrate(cfg)
    log = _file_logger()
    log(f"Shugo Tracker v{__version__}" + (" (demo data)" if demo else ""))
    if not demo and not screenshot:
        try:                                    # "Start with Windows" is gone: undo it for anyone who had it on
            from . import desktop
            if desktop.autostart_supported() and desktop.get_autostart():
                desktop.set_autostart(False)
                log("startup: removed the Start with Windows entry")
        except Exception:  # noqa: BLE001
            pass
    session = None
    if demo:
        from .demo import DemoSession
        session = DemoSession()
    cache_dir = None if (demo or screenshot) else os.path.join(DATA, "cache")
    api = Api(db_path=os.path.join(cache_dir, "shugo.db") if cache_dir else None, session=session, log=log,
              migrate_from=(None, None) if demo else (os.path.join(DATA, "character_cache.json"),
                                                      os.path.join(cache_dir, "profiles") if cache_dir else None))
    updater = Updater(repo=cfg.get("update_repo") or "CynicaGaming/Shugo-Tracker",
                      enabled=bool(cfg.get("auto_update", True)) and not demo and not screenshot, log=log)
    updater.start()

    extras: dict = {}
    restart = {"pending": False}

    def on_close():
        """Everything shuts down here (✕, tray Quit, or Restart after an update)."""
        for k in ("hotkey", "tray"):
            if extras.get(k):
                extras[k].stop()
        if instance:
            instance.release()          # free the single-instance port before the new copy starts
        nearby.stop()
        updater.stop()
        api.close()
        if not screenshot:
            save_config(config_path, cfg)
        if restart["pending"]:
            args = [a for a in sys.argv[1:] if a != "--after-update"] + ["--after-update"]
            log(f"update: restarting into v{updater.latest}")
            updater.relaunch(args)
        elif updater.state == "ready":
            updater.apply(restart=False)  # next launch runs the new version

    def on_update() -> bool:
        """Restart clicked: install now; on_close launches the new version once this copy has let go."""
        if not updater.apply(restart=False):
            return False
        restart["pending"] = True
        return True

    from .nearby import NearbyService
    nearby_find = None
    if demo:
        from .demo import find_nearby
        nearby_find = find_nearby(session)
    nearby = NearbyService(api, cfg, log=log, data_dir=DATA, find=nearby_find)

    from .favorites import Favorites
    favorites = Favorites(None if (demo or screenshot) else os.path.join(DATA, "favorites.json"), log=log)
    log(f"data folder: {DATA}  ·  {len(favorites)} favorites")
    if screenshot:
        cfg = {**cfg, "window_pos": [40, 40], "window_size": [600, 720], "regions": [],
               "factions": [], "classes": [], "level_min": None, "level_max": None, "nearby_enabled": False}
    win = SearchWindow(api, cfg, on_close=on_close, favorites=favorites, updater=updater,
                       on_update=on_update,
                       version=__version__, initial_query=query, screenshot=screenshot, cache_dir=cache_dir)
    post = win.inbox.put
    if not screenshot:
        win.save_cfg = lambda: save_config(config_path, cfg)

    def cache_size() -> int:
        return folder_size(cache_dir) if cache_dir and os.path.isdir(cache_dir) else 0

    def clear_cache() -> int:
        before = cache_size()
        api.clear_caches()                       # the database empties itself; the image files go here
        images = os.path.join(cache_dir, "images") if cache_dir else None
        if images and os.path.isdir(images):
            for root, _dirs, files in os.walk(images):
                for f in files:
                    try:
                        os.remove(os.path.join(root, f))
                    except OSError:
                        pass
        return max(0, before - cache_size())

    win.settings_services = SettingsServices(clear_cache=clear_cache, cache_size=cache_size, data_dir=DATA)
    if instance:
        instance.on_show = lambda: post(("show",))
    if not screenshot:
        # The tray icon only exists while the window is tucked away by ✕ with "Close to tray" on.
        tray = Tray(on_toggle=lambda: post(("show",)), on_quit=lambda: post(("quit",)))
        extras["tray"] = tray
        win.tray_ok = tray_supported()
        win.tray_icon = (tray.start, tray.stop)
    def set_nearby_enabled(on: bool):
        cfg["nearby_enabled"] = bool(on)
        if on:
            if demo:
                from .demo import feed_nearby
                nearby.start_demo(feed_nearby)
            else:
                nearby.start()
        else:
            nearby.stop()
        if not screenshot:
            save_config(config_path, cfg)
        win._refresh_nearby(force=True)

    def remember_region(region: str):
        cfg["nearby_region"] = region
        if not screenshot:
            save_config(config_path, cfg)
    nearby.on_region = remember_region

    def remember_me(name: str, server: int):
        cfg["nearby_me"] = [name, server]
        if not screenshot:
            save_config(config_path, cfg)
    nearby.on_me = remember_me
    if demo:
        from .demo import feed_teleport
        win.demo_teleport = lambda: feed_teleport(nearby)
    win.nearby = nearby
    win.set_nearby_enabled = set_nearby_enabled
    if cfg.get("nearby_enabled"):
        set_nearby_enabled(True)

    if selftest:
        def check():
            if len(favorites):
                result = f"loaded {len(favorites)}"
            elif win._view:
                win.toggle_favorite(win._view[0])
                result = "added" if os.path.exists(os.path.join(DATA, "favorites.json")) else \
                    f"add failed: {favorites.last_error}"
            else:
                result = "no search results"
            with open(selftest, "w", encoding="utf-8") as f:
                f.write(f"{result} | {DATA}")
            win.root.after(500, win.close)
        win.root.after(9000, check)
    win.run()
    return 0


def _search_cli(name: str) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    import threading as _t
    from .aion2api import SUB_REGIONS, Api, rank
    api = Api(workers=4)
    found, done = [], _t.Event()
    left = [len(SUB_REGIONS)]
    lock = _t.Lock()

    def on_done(region, chars, total, err):
        with lock:
            print(f"{region}: {total} matches" + (f" (error: {err})" if err else ""))
            found.extend(chars)
            left[0] -= 1
            if left[0] == 0:
                done.set()

    api.search(name, SUB_REGIONS, size=10, on_done=on_done)
    done.wait(30)
    top = rank(found, name)[:10]
    for c in top:
        api.want(c, lambda ch: None)
    deadline = time.time() + 30
    while any(c.status == "loading" for c in top) and time.time() < deadline:
        time.sleep(0.1)
    for c in top:
        print(f"  {c.name:14} {c.class_name:12} Lv{c.level:<3} {c.server_name:12} {c.region:4} {c.faction:9} "
              f"GS {c.gear_score or '-':>5}  CP {c.combat_power or '-':>8}  [{c.status}]")
    api.close()
    return 0 if found else 1


def _bench(name: str) -> int:
    """Time a search, card numbers and a profile open, cold and then warm (cached), against the live API."""
    import tempfile
    import threading as _t
    from .aion2api import SUB_REGIONS, Api, rank

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    tmp = tempfile.mkdtemp()

    def run(label: str) -> None:
        t0 = time.perf_counter()
        api = Api(db_path=os.path.join(tmp, "shugo.db"),
                  log=lambda m: print(f"  [{time.perf_counter() - t0:5.2f}s] {m}"))
        first, done, found, lock, left = [None], _t.Event(), [], _t.Lock(), [len(SUB_REGIONS)]

        def on_done(region, chars, total, err):
            with lock:
                if first[0] is None and chars:
                    first[0] = time.perf_counter() - t0
                found.extend(chars)
                left[0] -= 1
                if not left[0]:
                    done.set()
        api.search(name, SUB_REGIONS, on_done=on_done)
        done.wait(30)
        t_search = time.perf_counter() - t0
        top = rank(found, name)[:10]
        t1 = time.perf_counter()
        print(f"  {label}: {sum(c.status == 'ok' for c in top)}/10 cards cached before asking")
        for c in top:
            api.want(c, lambda ch: None)
        while any(c.status == "loading" for c in top) and time.perf_counter() - t1 < 30:
            time.sleep(0.01)
        t_cards = time.perf_counter() - t1
        print(f"  cards: {[c.status for c in top]}")
        times, fin = {}, _t.Event()
        t2 = time.perf_counter()

        def on_prof(ch, prof, err):
            if prof is None:
                fin.set()
                return
            times.setdefault("first", time.perf_counter() - t2)
            if not prof.equipment_pending:
                times.setdefault("full", time.perf_counter() - t2)
                fin.set()
        api.fetch_profile(top[0], on_prof)
        fin.wait(30)
        api.close()
        print(f"{label}: first results {first[0] or 0:.2f}s, all regions {t_search:.2f}s | "
              f"10 cards' GS/CP {t_cards:.2f}s | profile first paint {times.get('first', -1):.2f}s, "
              f"complete {times.get('full', -1):.2f}s")

    run("cold (nothing cached)")
    run("warm (new app start, cached)")

    # where does search time go? per region, and by page size
    import requests as _rq
    from .aion2api import SEARCH_URL, USER_AGENT
    sess = _rq.Session()
    sess.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
    for size in (10, 30, 50):
        parts = []
        for r in SUB_REGIONS:
            t = time.perf_counter()
            sess.get(SEARCH_URL, params={"keyword": name, "page": 1, "size": size, "localeInfo": "en-US",
                                         "region": r, "serverId": ""}, timeout=20)
            parts.append(f"{r} {time.perf_counter() - t:.2f}s")
        print(f"search size {size}: " + ", ".join(parts))
    return 0


def _file_logger():
    try:
        f = open(os.path.join(DATA, "shugo-tracker.log"), "w", encoding="utf-8")
    except OSError:
        f = None

    def log(msg: str) -> None:
        line = time.strftime("%H:%M:%S ") + msg
        if sys.stdout is not None:
            print(line, flush=True)
        if f:
            try:
                f.write(line + "\n")
                f.flush()
            except (OSError, ValueError):
                pass
    return log


def _selftest_relaunch(path: str, child: bool) -> int:
    """
    Release-build check of the updater's Restart: the exe starts a new copy of itself exactly like the updater
    does and exits at once; the new copy must still be able to start Tk after the old one is gone.
    """
    from .updater import Updater
    if child:
        time.sleep(3)                       # the parent (and its unpacked runtime folder) is gone by now
        import tkinter
        root = tkinter.Tk()
        root.withdraw()
        root.update()
        root.destroy()
        with open(path, "w", encoding="utf-8") as f:
            f.write("OK")
        return 0
    Updater.relaunch(["--selftest-relaunch", path, "--selftest-child"])
    return 0


def _replay_bin(path: str) -> int:
    """Print every event the decoder finds in a Nearby recording, then the resulting player list."""
    from collections import Counter
    from .nearby import replay_recording
    from .protocol import Opcodes, StreamDecoder
    from .tracker import Tracker
    tracker = Tracker(request_lookup=lambda *a: None)
    kinds: Counter = Counter()
    decoders: dict = {}

    def emit(ev):
        kinds[type(ev).__name__] += 1
        print(repr(ev))
        tracker.handle(ev)

    def on_bytes(flow, data, gap):
        dec = decoders.get(flow)
        if dec is None:
            dec = decoders[flow] = StreamDecoder(emit=emit, known_servers=sv.KNOWN_SERVERS, opcodes=Opcodes())
        if gap:
            dec.reset()
        dec.feed(data)
    n = replay_recording(path, on_bytes)
    print(f"\n{n} chunks, {len(decoders)} connection(s); events: {dict(kinds)}")
    print(f"you: {tracker.me.name} on {tracker.me.server}")
    for side, players in tracker.groups().items():
        print(f"{side}: " + ", ".join(f"{p.name}@{p.server}" for p in players))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Shugo Tracker: AION 2 character search with gear score & combat power")
    ap.add_argument("--config", default=os.path.join(DATA, "config.json"))
    ap.add_argument("--nearby", action="store_true",
                    help="EXPERIMENTAL: in-game overlay of nearby players (needs Npcap + administrator)")
    ap.add_argument("--search-cli", metavar="NAME", help="search from the command line and print results")
    ap.add_argument("--query", metavar="NAME", help="start the search window with this search")
    ap.add_argument("--bench", metavar="NAME", help="time cold vs cached search/profile loading and exit")
    ap.add_argument("--screenshot", metavar="PNG", help="save screenshots of the search window, then exit")
    ap.add_argument("--replay", metavar="PCAP", help="decode a Wireshark capture instead of live traffic")
    ap.add_argument("--port", type=int, action="append", help="with --replay: game server port(s), e.g. 13328")
    ap.add_argument("--console", action="store_true", help="print a table instead of showing the overlay")
    ap.add_argument("--no-lookup", action="store_true", help="never contact Shugo.GG")
    ap.add_argument("--debug", action="store_true", help="log every decoded event")
    ap.add_argument("--demo", action="store_true", help="show the overlay with made-up players (no game, no network)")
    ap.add_argument("--version", action="version", version=f"Shugo Tracker {__version__}")
    ap.add_argument("--after-update", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--selftest-relaunch", metavar="FILE", help=argparse.SUPPRESS)
    ap.add_argument("--selftest-child", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--selftest-favorites", metavar="FILE", help=argparse.SUPPRESS)
    ap.add_argument("--replay-bin", metavar="FILE", help="decode a Nearby troubleshooting recording and print it")
    args = ap.parse_args(argv)
    if args.replay_bin:
        return _replay_bin(args.replay_bin)
    if args.selftest_relaunch:
        return _selftest_relaunch(args.selftest_relaunch, child=args.selftest_child)

    if DATA != HERE and args.config == os.path.join(DATA, "config.json"):
        try:
            migrate_user_files(HERE, DATA)
        except OSError:
            pass
    cfg = load_config(args.config)
    if not os.path.exists(args.config):
        save_config(args.config, cfg)  # first run: write the defaults so they can be edited

    if args.search_cli:
        return _search_cli(args.search_cli)
    if args.bench:
        return _bench(args.bench)
    nearby = args.nearby or args.replay or args.console
    if nearby and FROZEN:
        try:
            import scapy  # noqa: F401
        except ImportError:
            print("The experimental --nearby mode isn't part of the packaged app; run it from source.")
            return 2
    if not nearby:
        code = _run_search(cfg, args.config, demo=args.demo, query=args.query or (
                           "Luna" if args.selftest_favorites else None), screenshot=args.screenshot,
                           after_update=args.after_update, selftest=args.selftest_favorites)
        if FROZEN:
            os._exit(code)              # don't let a leftover background thread keep the process alive
        return code

    app = App(cfg, debug=args.debug)
    if args.demo:
        _wire_demo(app)
    elif args.no_lookup:
        app.shugo.request = lambda *a, **k: None  # type: ignore[method-assign]
        app.tracker.request_lookup = app.shugo.request
    else:
        app.shugo.start()

    if args.replay:
        from .capture import replay_pcap
        n = replay_pcap(args.replay, app.on_bytes, set(args.port) if args.port else None)
        app.log(f"replayed {n} packets")
        deadline = time.time() + (0 if args.no_lookup else 30)
        while True:
            app.tick()
            if app.events.empty() and (args.no_lookup or app.shugo.pending() == 0 or time.time() > deadline):
                break
            time.sleep(0.1)
        time.sleep(0 if args.no_lookup else 2.5)
        app.tick()
        print_table(app)
        app.stop()
        return 0

    if not args.demo:
        app.start_live()
    if args.console:
        try:
            while True:
                for _ in range(30):
                    app.tick()
                    time.sleep(0.1)
                print_table(app)
        except KeyboardInterrupt:
            pass
        app.stop()
        return 0

    from .overlay import Overlay

    app.updater.start()

    def on_close():
        app.stop()
        save_config(args.config, cfg)
        if app.updater.state == "ready":
            app.updater.apply(restart=False)  # next launch runs the new version

    def on_update() -> bool:
        save_config(args.config, cfg)
        if not app.updater.apply(restart=False):
            return False
        app.stop()
        app.updater.relaunch(sys.argv[1:])
        return True

    Overlay(app.tracker, cfg, on_tick=app.tick, status=app.status, on_close=on_close,
            update_banner=app.updater.banner, on_update=on_update).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
