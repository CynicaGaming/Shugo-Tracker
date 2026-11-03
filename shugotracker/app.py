"""Entry point: the search window (with Nearby), plus the command-line tools (--search-cli, --bench, …)."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

from . import servers as sv
from .updater import Updater, __version__

FROZEN = getattr(sys, "frozen", False)
# Next to ShugoTracker.exe when built, else the project folder.
HERE = os.path.dirname(sys.executable) if FROZEN else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _writable(folder: str) -> bool:
    try:
        os.makedirs(folder, exist_ok=True)
        probe = os.path.join(folder, ".write-test")
        with open(probe, "w") as f:
            f.write("ok")
        os.remove(probe)
        return True
    except OSError:
        return False


def _app_root() -> str:
    """
    Everything the app keeps lives in its own folder, so the whole folder can be moved or copied anywhere:

        ShugoTracker.exe
        data\\    config.json, favorites.json
        cache\\   shugo.db (card numbers, profiles, Nearby lookups), images\\
        logs\\    shugo-tracker.log, diagnostics\\ (Nearby recordings)

    Only if that folder can't be written to (e.g. Program Files) does it fall back to %APPDATA%\\ShugoTracker.
    """
    if _writable(os.path.join(HERE, "data")):
        return HERE
    return os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "ShugoTracker")


ROOT = _app_root()
DATA = os.path.join(ROOT, "data")
CACHE = os.path.join(ROOT, "cache")
LOGS = os.path.join(ROOT, "logs")
OLD_APPDATA = os.path.join(os.environ["APPDATA"], "ShugoTracker") if os.environ.get("APPDATA") else None
USER_FILES = ("config.json", "favorites.json", "character_cache.json")   # (the last is imported into cache/shugo.db)


def migrate_user_files(old_dir: str, new_dir: str) -> list[str]:
    """Bring settings / favorites an older version kept in old_dir into the data folder. Returns what moved."""
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
    "forget_after_s": 900,
    "auto_update": True,
    "update_repo": "CynicaGaming/Shugo-Tracker",
    "regions": [],
    "factions": [],
    "always_on_top": True,
    "window_pos": [80, 80],
    "opcodes": {},
}


def migrate_to_app_folder(root: str | None = None, old: str | None = None) -> list[str]:
    """
    v1.22 and earlier kept everything in %APPDATA%\\ShugoTracker (and before that, loose next to the exe). Move it
    all into the app's own folders, then remove the old folder. Returns what moved.
    """
    import shutil
    root = root or ROOT
    old = OLD_APPDATA if old is None else old
    data, cache, logs = (os.path.join(root, d) for d in ("data", "cache", "logs"))
    moved = migrate_user_files(root, data)                  # loose files next to the exe (oldest versions)
    if not old or not os.path.isdir(old) or \
            os.path.normcase(os.path.abspath(old)) == os.path.normcase(os.path.abspath(root)):
        return moved
    moved += migrate_user_files(old, data)
    failed = False
    for src, dst in ((os.path.join(old, "cache"), cache),
                     (os.path.join(old, "diagnostics"), os.path.join(logs, "diagnostics"))):
        if not os.path.isdir(src):
            continue
        for dirpath, _dirs, files in os.walk(src):
            target = os.path.join(dst, os.path.relpath(dirpath, src))
            os.makedirs(target, exist_ok=True)
            for f in files:
                if not os.path.exists(os.path.join(target, f)):
                    try:
                        shutil.move(os.path.join(dirpath, f), os.path.join(target, f))
                        moved.append(os.path.relpath(os.path.join(dirpath, f), old))
                    except OSError:
                        failed = True
    failed = failed or any(os.path.isfile(os.path.join(old, n)) for n in ("config.json", "favorites.json"))
    if not failed:
        shutil.rmtree(old, ignore_errors=True)              # what's left: old logs and ".moved" traces
    return moved


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


def _run_search(cfg: dict, config_path: str, demo: bool = False, query: str | None = None, showcase: str | None = None,
                screenshot: str | None = None, after_update: bool = False, selftest: str | None = None) -> int:
    from .aion2api import Api
    from .search_ui import SearchWindow
    from .updater import Updater

    from .desktop import SingleInstance, folder_size
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
        from .demo import DemoSession, ShowcaseSession
        session = ShowcaseSession(*showcase.split("=", 1)) if showcase else DemoSession()
    cache_dir = None if (demo or screenshot) else CACHE
    api = Api(db_path=os.path.join(cache_dir, "shugo.db") if cache_dir else None, session=session, log=log,
              migrate_from=(None, None) if demo else (os.path.join(DATA, "character_cache.json"),
                                                      os.path.join(cache_dir, "profiles") if cache_dir else None))
    updater = Updater(repo=cfg.get("update_repo") or "CynicaGaming/Shugo-Tracker",
                      enabled=bool(cfg.get("auto_update", True)) and not demo and not screenshot, log=log)
    updater.start()

    restart = {"pending": False}

    def on_close():
        """Everything shuts down here (✕, or Restart after an update)."""
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

    from .nearby import NO_ADMIN, NearbyService
    nearby_find = None
    if demo:
        from .demo import find_nearby
        nearby_find = find_nearby(session)
    from .profiles import MyCharacters
    MyCharacters(cfg)                                # Nearby starts as your active character (Set Profile)
    nearby = NearbyService(api, cfg, log=log, data_dir=LOGS, find=nearby_find)

    from .favorites import Favorites
    favorites = Favorites(None if (demo or screenshot) else os.path.join(DATA, "favorites.json"), log=log)
    log(f"app folder: {ROOT}  ·  {len(favorites)} favorites")
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

    win.settings_services = SettingsServices(clear_cache=clear_cache, cache_size=cache_size, data_dir=ROOT)
    if instance:
        instance.on_show = lambda: post(("show",))
    def request_admin():
        """Nearby needs administrator: start an elevated copy (Windows asks) and close this one. Declined, this
        copy stays, and Nearby says why it can't run."""
        from .desktop import relaunch_as_admin
        args = [a for a in sys.argv[1:] if a != "--after-update"] + ["--after-update"]
        if relaunch_as_admin(args):
            log("nearby: restarting as administrator")
            win.close()
        else:
            log("nearby: administrator declined")

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
        if on and not (demo or screenshot) and nearby.state == NO_ADMIN:
            win.root.after(300, request_admin)

    def remember_region(region: str):
        cfg["nearby_region"] = region
        if not screenshot:
            save_config(config_path, cfg)
    nearby.on_region = remember_region

    # Your character is whoever you set (Set Profile); what the game's traffic says never changes it.
    if demo:
        from .demo import feed_teleport
        win.demo_teleport = lambda: feed_teleport(nearby)
    win.nearby = nearby
    win.set_nearby_enabled = set_nearby_enabled
    win.request_admin = request_admin
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
        os.makedirs(LOGS, exist_ok=True)
        f = open(os.path.join(LOGS, "shugo-tracker.log"), "w", encoding="utf-8")
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
    ap.add_argument("--search-cli", metavar="NAME", help="search from the command line and print results")
    ap.add_argument("--query", metavar="NAME", help="start the search window with this search")
    ap.add_argument("--bench", metavar="NAME", help="time cold vs cached search/profile loading and exit")
    ap.add_argument("--showcase", metavar="REAL=ALIAS",
                    help="demo data, plus one real character shown under another name (README screenshots)")
    ap.add_argument("--screenshot", metavar="PNG", help="save screenshots of the search window, then exit")
    ap.add_argument("--demo", action="store_true", help="made-up characters and players (no game, no network)")
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

    if args.config == os.path.join(DATA, "config.json"):
        try:
            os.makedirs(DATA, exist_ok=True)
            migrate_to_app_folder()
        except OSError:
            pass
    cfg = load_config(args.config)
    if not os.path.exists(args.config):
        save_config(args.config, cfg)  # first run: write the defaults so they can be edited

    if args.search_cli:
        return _search_cli(args.search_cli)
    if args.bench:
        return _bench(args.bench)
    code = _run_search(cfg, args.config, demo=args.demo or bool(args.showcase), showcase=args.showcase,
                       query=args.query or ("Luna" if args.selftest_favorites else None), screenshot=args.screenshot,
                       after_update=args.after_update, selftest=args.selftest_favorites)
    if FROZEN:
        os._exit(code)                  # don't let a leftover background thread keep the process alive
    return code


if __name__ == "__main__":
    sys.exit(main())
