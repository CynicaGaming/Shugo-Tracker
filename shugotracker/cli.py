"""Command-line tools for development and CI (the app itself is the Electron window, which runs shugotracker.core):

    python -m shugotracker.cli --search-cli Luna      search like the app does and print the results
    python -m shugotracker.cli --bench Luna           time a search, card numbers and a profile, cold and cached
    python -m shugotracker.cli --replay-bin FILE      decode a Nearby log (logs\\diagnostics\\nearby_*.bin)
"""
from __future__ import annotations

import argparse
import os
import sys
import time

from . import servers as sv
from ._version import __version__


def _utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def _search_cli(name: str) -> int:
    _utf8_console()
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

    _utf8_console()
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
    ap.add_argument("--search-cli", metavar="NAME", help="search from the command line and print results")
    ap.add_argument("--bench", metavar="NAME", help="time cold vs cached search/profile loading and exit")
    ap.add_argument("--replay-bin", metavar="FILE", help="decode a Nearby log file and print it")
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
