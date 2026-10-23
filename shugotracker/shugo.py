"""Rate-limited, cached character lookups on Shugo.GG (gear score + combat power)."""
from __future__ import annotations

import html
import itertools
import json
import os
import queue
import re
import threading
import time
from typing import Callable
from urllib.parse import quote

import requests

from . import servers as sv
from .tracker import Lookup

BASE = "https://shugo.gg/character"
USER_AGENT = "Shugo-Tracker/1.0 (personal in-game overlay; low-rate cached lookups)"

_RE_GS = re.compile(r"Gear score\s*([\d,.]+)", re.I)
_RE_SUMMARY = re.compile(r"Gear score\s*([\d,.]+)\s*·\s*(?:[^·]{0,80}·\s*){0,3}?Combat power\s*([\d,.]+)", re.I)
_RE_GS_META =re.compile(r"\(([\d,.]+)\s*GS\)")
_RE_CP = re.compile(r"Combat power\s*([\d,.]+)", re.I)
_RE_LINE = re.compile(r"Level\s*(\d+)\s*·\s*([A-Za-z]+)\s*·\s*(Elyos|Asmodians?)", re.I)
_RE_LEGION = re.compile(r"Legion:\s*([^·<\n]+)")


def profile_url(name: str, server: int, kr_tw_region: str = "kr") -> str | None:
    path = sv.shugo_server_path(server, kr_tw_region)
    return f"{BASE}/{path}/{quote(name, safe='')}" if path else None


def _num(s: str | None) -> int | None:
    if not s:
        return None
    digits = re.sub(r"[^\d]", "", s)
    return int(digits) if digits else None


def parse_profile(page: str) -> dict | None:
    """Pull gear score / combat power / level / class / faction out of a profile page."""
    text = html.unescape(re.sub(r"<[^>]+>", " ", page))
    text = re.sub(r"\s+", " ", text)
    # Prefer the profile's own summary line ("Gear score 2,826 · Title: … · Combat power 170,729"),
    # since the page also lists other characters on the server's leaderboard.
    if m := _RE_SUMMARY.search(text):
        gs, cp = _num(m.group(1)), _num(m.group(2))
    else:
        cp = _num(m.group(1)) if (m := _RE_CP.search(text)) else None
        gs = _num(m.group(1)) if (m := _RE_GS.search(text)) else None
    if gs is None:
        gs = _num(m.group(1)) if (m := _RE_GS_META.search(page)) else None
    if cp is None and gs is None:
        return None
    out = {"gear_score": gs, "combat_power": cp}
    if m := _RE_LINE.search(text):
        out["level"] = int(m.group(1))
        out["class_name"] = m.group(2).capitalize()
        out["faction"] = sv.ELYOS if m.group(3).lower().startswith("ely") else sv.ASMODIAN
    if m := _RE_LEGION.search(text):
        out["legion"] = m.group(1).strip()
    return out


class ShugoClient:
    def __init__(self, on_result: Callable[[str, Lookup, list[int]], None],
                 min_interval_s: float = 2.0, cache_path: str | None = None,
                 ttl_found_s: float = 1800, ttl_missing_s: float = 900,
                 kr_tw_region: str = "kr", log: Callable[[str], None] | None = None):
        self.on_result = on_result
        self.min_interval_s = max(1.0, min_interval_s)
        self.cache_path = cache_path
        self.ttl_found_s = ttl_found_s
        self.ttl_missing_s = ttl_missing_s
        self.kr_tw_region = kr_tw_region
        self.log = log or (lambda s: None)
        self._q: queue.PriorityQueue = queue.PriorityQueue()
        self._seq = itertools.count()
        self._best_prio: dict[str, int] = {}
        self._lock = threading.Lock()
        self._last_request = 0.0
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": USER_AGENT, "Accept": "text/html"})
        self._cache: dict[str, dict] = self._load_cache()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="shugo", daemon=True)

    # ───── public ─────
    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._q.put((-1, -1, None, [], False))
        self._save_cache()

    def request(self, name: str, priority: int, candidates: list[int], guessed: bool) -> None:
        with self._lock:
            best = self._best_prio.get(name)
            if best is not None and best <= priority:
                return
            self._best_prio[name] = priority
        self._q.put((priority, next(self._seq), name, list(candidates), guessed))

    def forget(self, name: str) -> None:
        """Drop cached results for a character so the next lookup hits the site."""
        tail = "/" + quote(name, safe="")
        for k in [k for k in self._cache if k.endswith(tail)]:
            self._cache.pop(k, None)
        with self._lock:
            self._best_prio.pop(name, None)

    def pending(self) -> int:
        return self._q.qsize()

    # ───── worker ─────
    def _run(self) -> None:
        saves = 0
        while not self._stop.is_set():
            prio, _, name, candidates, guessed = self._q.get()
            if name is None:
                break
            with self._lock:
                if self._best_prio.get(name) != prio:
                    continue  # superseded by a higher-priority request already handled
                self._best_prio.pop(name, None)
            result = Lookup(status="notfound", guessed=guessed)
            tried: list[int] = []
            for server in candidates:
                tried.append(server)
                r = self._lookup_one(name, server)
                if r.status == "ok":
                    r.guessed = guessed
                    result = r
                    break
                if r.status == "error":
                    result = r
            self.on_result(name, result, tried)
            saves += 1
            if saves % 10 == 0:
                self._save_cache()

    def _lookup_one(self, name: str, server: int) -> Lookup:
        url = profile_url(name, server, self.kr_tw_region)
        if not url:
            return Lookup(status="notfound")
        cached = self._cache.get(url)
        if cached:
            ttl = self.ttl_found_s if cached["status"] == "ok" else self.ttl_missing_s
            if time.time() - cached["ts"] < ttl:
                return self._to_lookup(cached, server, url)
        data = self._fetch(url)
        if data["status"] != "error":
            data["ts"] = time.time()
            self._cache[url] = data
        return self._to_lookup(data, server, url)

    def _fetch(self, url: str) -> dict:
        for attempt in range(3):
            wait = self._last_request + self.min_interval_s - time.time()
            if wait > 0:
                time.sleep(wait)
            self._last_request = time.time()
            try:
                resp = self._session.get(url, timeout=10)
            except requests.RequestException as e:
                self.log(f"shugo: {e.__class__.__name__}")
                return {"status": "error", "error": str(e)[:120]}
            if resp.status_code == 429 or resp.status_code >= 500:
                delay = float(resp.headers.get("Retry-After", 0) or 0) or (10 * (attempt + 1))
                self.log(f"shugo: HTTP {resp.status_code}, backing off {delay:.0f}s")
                time.sleep(min(delay, 120))
                continue
            if resp.status_code == 404:
                return {"status": "notfound"}
            if resp.status_code != 200:
                return {"status": "error", "error": f"HTTP {resp.status_code}"}
            parsed = parse_profile(resp.text)
            if not parsed:
                return {"status": "notfound"}
            return {"status": "ok", **parsed}
        return {"status": "error", "error": "rate limited"}

    @staticmethod
    def _to_lookup(d: dict, server: int, url: str) -> Lookup:
        if d["status"] != "ok":
            return Lookup(status=d["status"], error=d.get("error"))
        return Lookup(status="ok", server=server, url=url,
                      gear_score=d.get("gear_score"), combat_power=d.get("combat_power"),
                      level=d.get("level"), class_name=d.get("class_name"),
                      faction=d.get("faction"), legion=d.get("legion"))

    # ───── cache ─────
    def _load_cache(self) -> dict:
        if not self.cache_path or not os.path.exists(self.cache_path):
            return {}
        try:
            with open(self.cache_path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _save_cache(self) -> None:
        if not self.cache_path:
            return
        now = time.time()
        keep = {k: v for k, v in self._cache.items() if now - v.get("ts", 0) < 86_400}
        try:
            tmp = self.cache_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(keep, f, ensure_ascii=False)
            os.replace(tmp, self.cache_path)
        except OSError:
            pass
