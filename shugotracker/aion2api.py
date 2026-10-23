"""
Client for the public AION 2 (Global) character endpoints that Shugo.GG itself uses:

  search:  https://api-search.plaync.com/aion2global/search/v2/character
           ?keyword=&page=&size=&localeInfo=en-US&region=<nae|naw|eu|la|as>&serverId=
  details: https://aion2.plaync.com/api/character/info?lang=en-US&characterId=&serverId=&region=

Search returns name / server / faction / class id / level / character id (paginated);
details add combat power and item level (gear score). Results link to Shugo.GG profiles.
"""
from __future__ import annotations

import html
import itertools
import json
import os
import queue
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from typing import Callable
from urllib.parse import quote, unquote

import requests

from . import servers as sv
from ._version import __version__

SEARCH_URL = "https://api-search.plaync.com/aion2global/search/v2/character"
INFO_URL = "https://aion2.plaync.com/api/character/info"
PORTRAIT_BASE = "https://profileimg.plaync.com"
SUB_REGIONS = ["nae", "naw", "eu", "la", "as"]
REGION_LABELS = {"nae": "NA East", "naw": "NA West", "eu": "Europe", "la": "Latin America", "as": "Asia"}
USER_AGENT = f"ShugoTracker/{__version__} (+https://github.com/CynicaGaming/Shugo-Tracker)"

CLASS_RANGES = [
    (5, 8, "Gladiator"), (9, 12, "Templar"), (13, 16, "Ranger"), (17, 20, "Assassin"),
    (21, 24, "Spiritmaster"), (25, 28, "Sorcerer"), (29, 32, "Cleric"), (33, 36, "Chanter"),
    (45, 48, "Brawler"),
]


def class_name(pc_id: int) -> str:
    for lo, hi, name in CLASS_RANGES:
        if lo <= pc_id <= hi:
            return name
    return ""


def strip_tags(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", s or ""))


@dataclass
class Character:
    char_id: str            # decoded (no %3D)
    name: str
    race: int               # 1 Elyos, 2 Asmodian
    pc_id: int
    level: int
    server_id: int
    server_name: str
    region: str             # nae / naw / eu / la / as
    portrait: str | None = None
    # details (filled lazily)
    status: str = "none"    # none | loading | ok | error
    combat_power: int | None = None
    gear_score: int | None = None
    title: str | None = None
    error: str | None = None

    @property
    def key(self) -> str:
        return f"{self.server_id}:{self.char_id}"

    @property
    def class_name(self) -> str:
        return class_name(self.pc_id)

    @property
    def faction(self) -> str:
        return {1: "Elyos", 2: "Asmodian"}.get(self.race, "?")

    @property
    def shugo_url(self) -> str:
        return f"https://shugo.gg/character/global/{self.region}-{sv.re_slug(self.server_name)}/{quote(self.name, safe='')}"


def parse_search(data: dict) -> tuple[list[Character], int]:
    out = []
    for it in data.get("list") or []:
        try:
            img = it.get("profileImageUrl") or None
            out.append(Character(
                char_id=unquote(it["characterId"]),
                name=strip_tags(it["name"]),
                race=int(it.get("race") or 0),
                pc_id=int(it.get("pcId") or 0),
                level=int(it.get("level") or 0),
                server_id=int(it["serverId"]),
                server_name=it.get("serverName") or sv.name_of(int(it["serverId"])),
                region=it.get("region") or "",
                portrait=(PORTRAIT_BASE + img) if img and img.startswith("/") else img,
            ))
        except (KeyError, TypeError, ValueError):
            continue
    total = int((data.get("pagination") or {}).get("total") or len(out))
    return out, total


def parse_info(data: dict) -> dict:
    prof = data.get("profile") or {}
    gs = None
    for st in (data.get("stat") or {}).get("statList") or []:
        if st.get("type") == "ItemLevel":
            gs = int(st.get("value") or 0) or None
    return {
        "combat_power": int(prof["combatPower"]) if prof.get("combatPower") is not None else None,
        "gear_score": gs,
        "level": prof.get("characterLevel"),
        "title": prof.get("titleName") or None,
        "portrait": prof.get("profileImage") or None,
    }


def rank(results: list[Character], keyword: str) -> list[Character]:
    k = keyword.casefold()
    def score(c: Character):
        n = c.name.casefold()
        tier = 0 if n == k else 1 if n.startswith(k) else 2
        return (tier, -c.level, len(c.name), c.name.casefold())
    return sorted(results, key=score)


class RateLimiter:
    """Token bucket shared by all workers; halves its rate on HTTP 429/5xx and recovers slowly."""

    def __init__(self, rate: float = 6.0, min_rate: float = 0.5, max_rate: float = 8.0):
        self.rate, self.min_rate, self.max_rate = rate, min_rate, max_rate
        self._next = 0.0
        self._pause_until = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            start = max(now, self._next, self._pause_until)
            self._next = start + 1.0 / self.rate
        delay = start - time.monotonic()
        if delay > 0:
            time.sleep(delay)

    def ok(self) -> None:
        with self._lock:
            self.rate = min(self.max_rate, self.rate + 0.05)

    def throttled(self, retry_after: float | None) -> None:
        with self._lock:
            self.rate = max(self.min_rate, self.rate / 2)
            self._pause_until = time.monotonic() + (retry_after or 5.0)


class Api:
    """Search (parallel over sub-regions) and lazily-fetched character details."""

    def __init__(self, cache_path: str | None = None, workers: int = 4, rate: float = 6.0,
                 cache_ttl_s: float = 1800, log: Callable[[str], None] | None = None,
                 session: requests.Session | None = None):
        self.log = log or (lambda s: None)
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
        self.limiter = RateLimiter(rate=rate)
        self.cache_path = cache_path
        self.cache_ttl_s = cache_ttl_s
        self._cache: dict[str, dict] = self._load_cache()
        self._cache_lock = threading.Lock()
        self._search_pool = ThreadPoolExecutor(max_workers=len(SUB_REGIONS), thread_name_prefix="search")
        # details: newest request first, stale generations dropped
        self._dq: queue.PriorityQueue = queue.PriorityQueue()
        self._seq = itertools.count()
        self._generation = 0
        self._queued: set[str] = set()
        self._qlock = threading.Lock()
        self._stop = threading.Event()
        self._workers = [threading.Thread(target=self._detail_worker, name=f"details-{i}", daemon=True)
                         for i in range(workers)]
        for w in self._workers:
            w.start()

    def close(self) -> None:
        self._stop.set()
        for _ in self._workers:
            self._dq.put((0, 0, None, None))
        self._search_pool.shutdown(wait=False, cancel_futures=True)
        self.save_cache()

    # ───── HTTP ─────
    def _get_json(self, url: str, params: dict, timeout: float = 10) -> dict:
        for attempt in range(3):
            self.limiter.wait()
            r = self.session.get(url, params=params, timeout=timeout)
            if r.status_code == 429 or r.status_code >= 500:
                ra = r.headers.get("Retry-After")
                self.limiter.throttled(float(ra) if ra and ra.replace(".", "").isdigit() else None)
                self.log(f"api: HTTP {r.status_code}, slowing down")
                continue
            r.raise_for_status()
            self.limiter.ok()
            return r.json()
        raise RuntimeError("server busy (rate limited)")

    # ───── search ─────
    def search_region(self, keyword: str, region: str, page: int = 1, size: int = 30) -> tuple[list[Character], int]:
        data = self._get_json(SEARCH_URL, {"keyword": keyword, "page": page, "size": size,
                                           "localeInfo": "en-US", "region": region, "serverId": ""})
        chars, total = parse_search(data)
        for c in chars:
            self._apply_cached(c)
        return chars, total

    def search(self, keyword: str, regions: list[str], page: int = 1, size: int = 30,
               on_done: Callable[[str, list[Character], int, str | None], None] | None = None):
        """Runs one request per region in parallel; on_done(region, chars, total, error) per region."""
        def run(region):
            try:
                chars, total = self.search_region(keyword, region, page, size)
                on_done(region, chars, total, None)
            except Exception as e:  # noqa: BLE001
                on_done(region, [], 0, f"{e.__class__.__name__}: {e}")
        return [self._search_pool.submit(run, r) for r in regions]

    # ───── details ─────
    def new_generation(self) -> None:
        """A new search started: forget queued detail requests from the old one."""
        with self._qlock:
            self._generation += 1
            self._queued.clear()

    def want(self, c: Character, on_done: Callable[[Character], None]) -> None:
        """Ask for c's details (no-op if loaded or already queued). Newest requests are served first."""
        if c.status in ("ok", "loading") or self._apply_cached(c):
            return
        with self._qlock:
            if c.key in self._queued:
                return
            self._queued.add(c.key)
            gen = self._generation
        c.status = "loading"
        self._dq.put((-next(self._seq), gen, c, on_done))

    def _detail_worker(self) -> None:
        while not self._stop.is_set():
            _, gen, c, on_done = self._dq.get()
            if c is None:
                return
            with self._qlock:
                stale = gen != self._generation
                self._queued.discard(c.key)
            if stale:
                c.status = "none"
                continue
            try:
                data = self._get_json(INFO_URL, {"lang": "en-US", "characterId": c.char_id,
                                                 "serverId": c.server_id, "region": c.region})
                info = parse_info(data)
                self._store(c, info)
                self._fill(c, info)
            except Exception as e:  # noqa: BLE001
                c.status, c.error = "error", f"{e.__class__.__name__}"
                self.log(f"api: details for {c.name}@{c.server_name} failed: {e}")
            on_done(c)

    @staticmethod
    def _fill(c: Character, info: dict) -> None:
        c.combat_power = info.get("combat_power")
        c.gear_score = info.get("gear_score")
        c.title = info.get("title")
        if info.get("level"):
            c.level = int(info["level"])
        if info.get("portrait"):
            c.portrait = info["portrait"]
        c.status = "ok"

    def forget(self, c: Character) -> None:
        with self._cache_lock:
            self._cache.pop(c.key, None)

    # ───── cache ─────
    def _apply_cached(self, c: Character) -> bool:
        with self._cache_lock:
            hit = self._cache.get(c.key)
        if hit and time.time() - hit.get("ts", 0) < self.cache_ttl_s:
            self._fill(c, hit)
            return True
        return False

    def _store(self, c: Character, info: dict) -> None:
        with self._cache_lock:
            self._cache[c.key] = {**info, "ts": time.time()}

    def _load_cache(self) -> dict:
        if not self.cache_path or not os.path.exists(self.cache_path):
            return {}
        try:
            with open(self.cache_path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def save_cache(self) -> None:
        if not self.cache_path:
            return
        now = time.time()
        with self._cache_lock:
            keep = {k: v for k, v in self._cache.items() if now - v.get("ts", 0) < self.cache_ttl_s}
        try:
            tmp = self.cache_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(keep, f)
            os.replace(tmp, self.cache_path)
        except OSError:
            pass


def character_from_dict(d: dict) -> Character:
    return Character(**{k: v for k, v in d.items() if k in Character.__dataclass_fields__})


def character_to_dict(c: Character) -> dict:
    return asdict(c)
