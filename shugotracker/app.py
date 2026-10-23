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
    "window_size": [560, 760],
    "overlay": True,
    "hotkey": "ctrl+shift+s",
    "window_pos": [80, 80],
    "detail_workers": 4,
    "requests_per_second": 6.0,
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
            self._log_file = open(os.path.join(HERE, "shugo-tracker.log"), "w", encoding="utf-8")
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
                screenshot: str | None = None) -> int:
    from .aion2api import Api
    from .search_ui import SearchWindow
    from .updater import Updater

    from .desktop import GlobalHotkey, SingleInstance, Tray, folder_size
    from .settings import migrate
    from .settings_ui import SettingsServices

    instance = None
    if not (demo or screenshot):
        instance = SingleInstance()
        if not instance.acquire():
            # Already running (maybe hidden): bring that copy forward instead of opening a second one.
            if instance.notify_running():
                return 0
            instance = None

    migrate(cfg)
    log = _file_logger()
    log(f"Shugo Tracker v{__version__}" + (" (demo data)" if demo else ""))
    session = None
    if demo:
        from .demo import DemoSession
        session = DemoSession()
    cache_dir = None if (demo or screenshot) else os.path.join(HERE, "cache")
    api = Api(cache_path=None if demo else os.path.join(HERE, "character_cache.json"), session=session,
              profile_dir=os.path.join(cache_dir, "profiles") if cache_dir else None,
              workers=int(cfg.get("detail_workers", 4)), rate=float(cfg.get("requests_per_second", 6.0)), log=log)
    updater = Updater(repo=cfg.get("update_repo") or "CynicaGaming/Shugo-Tracker",
                      enabled=bool(cfg.get("auto_update", True)) and not demo and not screenshot, log=log)
    updater.start()

    extras: dict = {}

    def on_close():
        for k in ("hotkey", "tray"):
            if extras.get(k):
                extras[k].stop()
        if instance:
            instance.release()
        updater.stop()
        api.close()
        if not screenshot:
            save_config(config_path, cfg)
        if updater.state == "ready":
            updater.apply(restart=False)  # next launch runs the new version

    def on_update() -> bool:
        save_config(config_path, cfg)
        if not updater.apply(restart=False):
            return False
        updater.stop()
        api.close()
        updater.relaunch(sys.argv[1:])
        return True

    from .favorites import Favorites
    favorites = Favorites(None if (demo or screenshot) else os.path.join(HERE, "favorites.json"))
    if screenshot:
        cfg = {**cfg, "window_pos": [40, 40], "window_size": [600, 720], "regions": [], "factions": [],
               "opacity_focused": 1.0, "opacity_unfocused": 1.0, "pill_pos": [560, 60]}
    win = SearchWindow(api, cfg, on_close=on_close, favorites=favorites, updater=updater,
                       on_update=on_update,
                       version=__version__, initial_query=query, screenshot=screenshot, cache_dir=cache_dir)
    post = win.inbox.put
    if not screenshot:
        win.save_cfg = lambda: save_config(config_path, cfg)

    def change_hotkey(text: str):
        old = extras.pop("hotkey", None)
        if old:
            old.stop()
        hk = GlobalHotkey(text, lambda: post(("toggle",)))
        if screenshot or hk.start():
            if not screenshot:
                extras["hotkey"] = hk
            win.hotkey_text = text
            win.set_hotkey_ok(True)
            return True, None
        if old:                      # keep the previous shortcut working
            again = GlobalHotkey(old.text, lambda: post(("toggle",)))
            if again.start():
                extras["hotkey"] = again
        return False, hk.error or "not available"

    def cache_size() -> int:
        size = folder_size(cache_dir) if cache_dir and os.path.isdir(cache_dir) else 0
        cp = api.cache_path
        return size + (os.path.getsize(cp) if cp and os.path.exists(cp) else 0)

    def clear_cache() -> int:
        before = cache_size()
        api.clear_caches()
        if cache_dir and os.path.isdir(cache_dir):
            for root, _dirs, files in os.walk(cache_dir):
                for f in files:
                    try:
                        os.remove(os.path.join(root, f))
                    except OSError:
                        pass
        return max(0, before - cache_size())

    win.settings_services = SettingsServices(change_hotkey=change_hotkey, clear_cache=clear_cache,
                                             cache_size=cache_size, data_dir=HERE, set_request_rate=api.set_rate)
    if instance:
        instance.on_show = lambda: post(("show",))
    if not screenshot:
        hk = GlobalHotkey(cfg.get("hotkey", "ctrl+shift+s"), lambda: post(("toggle",)))
        if hk.start():
            extras["hotkey"] = hk
            win.set_hotkey_ok(True)
        elif hk.error and hk.error != "unsupported":
            log(f"hotkey {cfg.get('hotkey')!r}: {hk.error}")
        tray = Tray(on_toggle=lambda: post(("toggle",)), on_quit=lambda: post(("quit",)))
        if tray.start():
            extras["tray"] = tray
    else:
        win.set_hotkey_ok(True)   # show the key label in screenshots
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
        api = Api(cache_path=os.path.join(tmp, "details.json"), profile_dir=os.path.join(tmp, "profiles"))
        t0 = time.perf_counter()
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
        for c in top:
            api.want(c, lambda ch: None)
        while any(c.status == "loading" for c in top) and time.perf_counter() - t1 < 30:
            time.sleep(0.01)
        t_cards = time.perf_counter() - t1
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
    return 0


def _file_logger():
    try:
        f = open(os.path.join(HERE, "shugo-tracker.log"), "w", encoding="utf-8")
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Shugo Tracker: AION 2 character search with gear score & combat power")
    ap.add_argument("--config", default=os.path.join(HERE, "config.json"))
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
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    if not os.path.exists(args.config):
        save_config(args.config, cfg)  # first run: write the defaults so they can be edited

    if args.search_cli:
        return _search_cli(args.search_cli)
    if args.bench:
        return _bench(args.bench)
    nearby = args.nearby or args.replay or args.console
    if not nearby:
        return _run_search(cfg, args.config, demo=args.demo, query=args.query, screenshot=args.screenshot)

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
