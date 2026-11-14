"""Config and app-folder helpers used by the core, plus the command-line tools (--search-cli, --bench, --replay-bin).

The app itself is the Electron window in desktop/, which starts shugotracker.core."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

from . import servers as sv
from ._version import __version__

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
                got_prof.append(prof)
                fin.set()
        got_prof: list = []
        api.fetch_profile(top[0], on_prof)
        fin.wait(30)
        # every worn item's details, as opening the profile now loads them
        from .profile import GEAR_ACCESSORIES, GEAR_ARCANA, GEAR_MAIN
        items = [it for s in GEAR_MAIN + GEAR_ACCESSORIES + GEAR_ARCANA
                 if got_prof and (it := got_prof[0].gear.get(s)) is not None and it.slot_pos and it.item_id]
        left_items, all_in = [len(items)], _t.Event()

        def on_item(_det):
            with lock:
                left_items[0] -= 1
                if left_items[0] <= 0:
                    all_in.set()
        t3 = time.perf_counter()
        for it in items:
            api.fetch_item_detail(top[0], it, on_item)
        if items:
            all_in.wait(60)
        t_items = time.perf_counter() - t3
        api.close()
        print(f"{label}: first results {first[0] or 0:.2f}s, all regions {t_search:.2f}s | "
              f"10 cards' GS/CP {t_cards:.2f}s | profile first paint {times.get('first', -1):.2f}s, "
              f"complete {times.get('full', -1):.2f}s | {len(items)} items' details {t_items:.2f}s")

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
    ap = argparse.ArgumentParser(description="Shugo Tracker command-line tools (the app is the Electron window)")
    ap.add_argument("--config", default=os.path.join(DATA, "config.json"))
    ap.add_argument("--search-cli", metavar="NAME", help="search from the command line and print results")
    ap.add_argument("--bench", metavar="NAME", help="time cold vs cached search/profile loading and exit")
    ap.add_argument("--replay-bin", metavar="FILE", help="decode a Nearby troubleshooting recording and print it")
    ap.add_argument("--version", action="version", version=f"Shugo Tracker {__version__}")
    args = ap.parse_args(argv)
    if args.replay_bin:
        return _replay_bin(args.replay_bin)
    if args.search_cli:
        return _search_cli(args.search_cli)
    if args.bench:
        return _bench(args.bench)
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
