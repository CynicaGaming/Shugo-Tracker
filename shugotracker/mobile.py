"""The Android app's core: the same Core as the desktop app, driven from the app's WebView instead of a pipe.

Kotlin (android/app/.../MainActivity.kt) calls start(root, js) once, then send(line) for every request the page
makes. Answers and events go back through js.post(line), one JSON object per call. Nearby isn't part of the
phone app (there's no game traffic to read on a phone), so it's never started.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from ._version import __version__
from .core import Core
from .logfiles import DailyText

_core: Core | None = None
_pool: ThreadPoolExecutor | None = None
_post = None
_updater = None


def start(root: str, js) -> None:
    """root: the app's private folder (data, cache, logs). js: has post(str) that hands a message to the page."""
    global _core, _pool, _post, _updater
    if _core is not None:                                    # the page reloaded: same core, new page
        _post = js.post
        if _updater:
            _updater.js = js
        return
    os.makedirs(root, exist_ok=True)
    lock = threading.Lock()

    def write(obj: dict) -> None:
        line = json.dumps(obj, ensure_ascii=True, separators=(",", ":"))
        with lock:
            _post(line)
    daily = DailyText(os.path.join(root, "logs"), "shugo-core")
    log_lock = threading.Lock()

    def log(m: str) -> None:
        with log_lock:
            daily.write(m)
    _post = js.post
    log(f"──── Shugo Tracker core v{__version__} started (Android)")
    _core = Core(root, write, log=log, client=_android_client())
    _core.cfg["nearby_enabled"] = False                      # (no game on a phone)
    _pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="rpc")
    _core._write = write
    _updater = Updater(root, write, js)
    _updater.start(15 * 60)                                  # at start, every 15 minutes, and when Settings opens


def _android_client() -> dict:
    """What the usage statistics say about this phone: Android and its version, and the display language."""
    try:
        from java import jclass
        release = jclass("android.os.Build$VERSION").RELEASE
        lang = jclass("java.util.Locale").getDefault().toLanguageTag()
        return {"platform_name": "android", "os_name": f"Android {release}", "lang": str(lang)}
    except Exception:  # noqa: BLE001  (not on a phone: tests)
        return {"platform_name": "android", "os_name": "Android"}


def send(line: str) -> None:
    """One request from the page (a JSON line, like the desktop app's pipe)."""
    try:
        msg = json.loads(line)
    except ValueError:
        return
    if _core is None:
        return
    if msg.get("method") == "app.update":                    # Settings → Updates (the desktop app's win.update)
        _pool.submit(_updater.handle, msg, _core._write)
    elif msg.get("method") == "config.set":
        _core.handle(msg, _core._write)                       # at once and in order
    else:
        _pool.submit(_core.handle, msg, _core._write)


# ── updates: the desktop app's updater (desktop/updater.js), for the APK ──────────────────────────────────────
REPO = "CynicaGaming/Shugo-Tracker"
APK_ASSET = re.compile(r"^Shugo-Tracker-\d+\.\d+\.\d+-Android\.apk$")   # (up to 2.7.1: ShugoTracker.apk)
LEGACY_APK = "ShugoTracker.apk"


def _apk(rel: dict) -> dict | None:
    assets = rel.get("assets") or []
    return next((a for a in assets if APK_ASSET.match(a.get("name") or "")), None) or \
        next((a for a in assets if a.get("name") == LEGACY_APK), None)


def _parse(v):
    m = re.match(r"^v?(\d+)\.(\d+)(?:\.(\d+))?$", str(v or "").strip())
    return (int(m[1]), int(m[2]), int(m[3] or 0)) if m else None


def newer(a, b) -> bool:
    x, y = _parse(a), _parse(b)
    return bool(x and y and x > y)


def bullets(body: str) -> list[str]:
    """The release's "what's new" bullets: its "- " lines, plain text."""
    out = []
    for line in str(body or "").splitlines():
        line = line.strip()
        if not re.match(r"^[-*] ", line) or re.search(r"Full Changelog|by @\S+ in ", line, re.I):
            continue
        line = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", line[2:])
        line = re.sub(r"\*\*|__|`", "", line).strip()
        if line:
            out.append(line)
    return out[:12]


class Updater:
    """Check GitHub for a newer release, download its APK (Download), then hand it to Android to install
    (Restart). Android asks you to confirm the install; the app restarts on the new version."""

    def __init__(self, root: str, write, js):
        self.write, self.js = write, js
        self.dir = os.path.join(root, "updates")
        self.apk = os.path.join(self.dir, "update.apk")
        self.dev = __version__.startswith("0.0.0")
        self.state = {"state": "idle", "current": __version__, "latest": None, "progress": 0, "error": None,
                      "notes": [], "checkedAt": None}
        self.release = None
        self.timer = None
        self.lock = threading.Lock()
        try:
            os.remove(self.apk)                              # (installed, or given up on)
        except OSError:
            pass

    def set(self, **patch) -> None:
        self.state = {**self.state, **patch}
        self.write({"event": "update", "data": self.state})

    def start(self, every_s) -> None:
        if self.dev:
            self.set(state="dev")
            return
        threading.Thread(target=self.check, daemon=True).start()
        self.every(every_s)

    def every(self, every_s) -> None:
        if self.timer:
            self.timer.cancel()
        if self.dev or not every_s or every_s <= 0:
            return

        def tick():
            if self.state["state"] in ("idle", "uptodate", "error"):
                self.check()
            self.every(every_s)
        self.timer = threading.Timer(every_s, tick)
        self.timer.daemon = True
        self.timer.start()

    def handle(self, msg: dict, reply) -> None:
        a = (msg.get("params") or {}).get("action")
        try:
            if a == "check":
                self.check()
            elif a == "freshen":
                if not self.dev and self.state["state"] not in ("checking", "downloading", "ready") and \
                        (not self.state["checkedAt"] or time.time() * 1000 - self.state["checkedAt"] > 60000):
                    self.check()
            elif isinstance(a, (int, float)) and not isinstance(a, bool):
                self.every(a)
            elif a == "download":
                self.download()
            elif a == "restart":
                if self.state["state"] == "ready" and os.path.exists(self.apk):
                    self.js.install(self.apk)
            reply({"id": msg.get("id"), "result": self.state})
        except Exception as e:  # noqa: BLE001
            reply({"id": msg.get("id"), "error": str(e)})

    def check(self) -> None:
        if self.dev or self.state["state"] == "downloading":
            return
        import requests
        was = self.state["state"]
        self.set(state="ready" if was == "ready" else "checking", error=None)
        try:
            r = requests.get(f"https://api.github.com/repos/{REPO}/releases/latest",
                             headers={"User-Agent": "ShugoTracker"}, timeout=20)
            if r.status_code != 200:
                raise RuntimeError(f"GitHub {r.status_code}")
            rel = r.json()
            self.release = rel
            latest = str(rel.get("tag_name") or "").lstrip("v")
            ready = self.state["state"] == "ready" and latest == self.state["latest"]
            # (a release's APK is attached a few minutes after the release itself: until then, nothing to get)
            has_apk = _apk(rel) is not None
            self.set(latest=latest, notes=bullets(rel.get("body")), checkedAt=int(time.time() * 1000),
                     state="ready" if ready else "available" if newer(latest, __version__) and has_apk else "uptodate")
        except Exception as e:  # noqa: BLE001
            self.set(state="error", error=str(e))

    def download(self) -> None:
        if not self.release or self.state["state"] not in ("available", "error"):
            return
        import requests
        assets = {a.get("name"): a for a in self.release.get("assets") or []}
        apk = _apk(self.release)
        sha = assets.get(apk["name"] + ".sha256") if apk else None
        if not apk:
            self.set(state="error", error="no APK in the release")
            return
        self.set(state="downloading", progress=0)
        try:
            want = None
            if sha:
                want = requests.get(sha["browser_download_url"], timeout=30).text.split()[0].lower()
            os.makedirs(self.dir, exist_ok=True)
            part = self.apk + ".part"
            h = hashlib.sha256()
            with requests.get(apk["browser_download_url"], stream=True, timeout=60) as r:
                r.raise_for_status()
                total = int(r.headers.get("content-length") or apk.get("size") or 0)
                got, shown = 0, 0.0
                with open(part, "wb") as f:
                    for chunk in r.iter_content(1 << 16):
                        f.write(chunk)
                        h.update(chunk)
                        got += len(chunk)
                        if total and got / total - shown >= 0.02:
                            shown = got / total
                            self.set(progress=shown)
            if want and h.hexdigest() != want:
                os.remove(part)
                raise RuntimeError("checksum mismatch")
            os.replace(part, self.apk)
            self.set(state="ready", progress=1)
        except Exception as e:  # noqa: BLE001
            self.set(state="error", error=str(e))
