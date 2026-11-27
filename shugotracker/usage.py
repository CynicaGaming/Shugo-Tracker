"""Anonymous usage statistics (Settings → Share Usage Statistics; on unless you turn it off).

About twice a day the app sends one small message to the Shugo Tracker stats server:
  - a random id this install made up for itself (not tied to you, your PC or your characters),
  - the app version, Windows or Android and its version, and the display language,
  - how many times a few things were used since the last message (searches, profiles opened, favorites added…),
  - whether Nearby is on, and how many favorites and own characters are saved.
Never sent: character names (yours or anyone's), what you searched for, your server, or anything from the game.
The server keeps no IP addresses. Turning it off stops it at once and drops anything not yet sent.
"""
from __future__ import annotations

import json
import locale
import platform
import sys
import threading
import time
import uuid

from ._version import __version__

ENDPOINT = "https://shugo-stats.REPLACE.workers.dev/v1/ping"
EVENTS = ("search", "profile", "favorite", "nearby_on", "popout", "pvp", "update")
FIRST_AFTER_S = 20           # the first message, shortly after start
EVERY_S = 12 * 3600          # then twice a day while the app is open
RETRY_S = 30 * 60


def _windows_os() -> str:
    try:
        build = sys.getwindowsversion().build
        return f"Windows {'11' if build >= 22000 else platform.release()}"
    except AttributeError:
        return platform.system() or "Unknown"


class Usage:
    def __init__(self, cfg: dict, save, snapshot, log=None, platform_name: str = "windows", os_name: str | None = None,
                 lang: str | None = None, post=None, enabled_build: bool | None = None):
        """cfg: the app's settings (usage_stats, usage_id, usage_pending live there). save(): writes them.
        snapshot(): {"nearby": bool, "favorites": int, "my_chars": int} at send time."""
        self.cfg, self.save, self.snapshot = cfg, save, snapshot
        self.log = log or (lambda m: None)
        self.platform = platform_name
        self.os = os_name or _windows_os()
        sys_lang = (locale.getlocale()[0] or "").replace("_", "-")
        self.lang = lang or (sys_lang if sys_lang not in ("", "C", "POSIX") else None)
        self.post = post or self._post
        # development builds (0.0.0-dev) and demo mode never send anything
        self.live = (not __version__.startswith("0.0.0")) if enabled_build is None else enabled_build
        self.counts: dict[str, int] = {k: int(v) for k, v in (cfg.get("usage_pending") or {}).items() if k in EVENTS}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def on(self) -> bool:
        return self.cfg.get("usage_stats", True) is not False

    def count(self, name: str, n: int = 1) -> None:
        if name in EVENTS and self.on:
            with self._lock:
                self.counts[name] = self.counts.get(name, 0) + n

    def changed(self) -> None:
        """Settings → Share Usage Statistics was switched: off forgets what wasn't sent."""
        if not self.on:
            with self._lock:
                self.counts.clear()
            self.cfg.pop("usage_pending", None)

    def start(self) -> None:
        if not self.live or self._thread:
            return
        self._thread = threading.Thread(target=self._loop, name="usage", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Quitting: keep unsent counts for next time (sent with the next message)."""
        self._stop.set()
        with self._lock:
            if self.on and any(self.counts.values()):
                self.cfg["usage_pending"] = dict(self.counts)
            else:
                self.cfg.pop("usage_pending", None)

    def _loop(self) -> None:
        wait = FIRST_AFTER_S
        while not self._stop.wait(wait):
            wait = EVERY_S if self.send() else RETRY_S

    def payload(self) -> dict:
        if not self.cfg.get("usage_id"):
            self.cfg["usage_id"] = str(uuid.uuid4())
            self.save()
        try:
            s = self.snapshot()
        except Exception:  # noqa: BLE001
            s = {}
        with self._lock:
            e = {k: v for k, v in self.counts.items() if v}
        return {"id": self.cfg["usage_id"], "v": __version__, "p": self.platform, "os": self.os, "l": self.lang,
                "e": e, "s": s}

    def send(self) -> bool:
        if not self.on or not self.live:
            return True
        body = self.payload()
        try:
            ok = self.post(json.dumps(body, separators=(",", ":")))
        except Exception as e:  # noqa: BLE001
            self.log(f"usage: couldn't send: {e.__class__.__name__}")
            return False
        if ok:
            with self._lock:                          # what was sent is done; anything counted meanwhile stays
                for k, v in body["e"].items():
                    self.counts[k] = max(0, self.counts.get(k, 0) - v)
            if self.cfg.pop("usage_pending", None) is not None:
                self.save()
        return ok

    @staticmethod
    def _post(data: str) -> bool:
        import requests
        r = requests.post(ENDPOINT, data=data, timeout=15,
                          headers={"Content-Type": "application/json", "User-Agent": f"ShugoTracker/{__version__}"})
        return r.status_code in (200, 204)


def throttle(fn, every_s: float):
    """For counting things that can fire in bursts: at most once per `every_s` per key."""
    last: dict = {}

    def wrapped(key):
        now = time.monotonic()
        if now - last.get(key, -1e9) >= every_s:
            last[key] = now
            fn(key)
    return wrapped
