"""
Self-updater for ShugoTracker.exe, fed by the GitHub Releases of the project repo.

Flow: check the latest release in the background → if it is newer, download the
exe and its .sha256 next to the running exe and verify it → the overlay offers
"restart to update"; if the user just quits instead, the swap happens on exit so
the next launch is the new version.

The swap relies on Windows letting a running .exe be *renamed* (not deleted):
running exe → ShugoTracker.exe.old, downloaded file → ShugoTracker.exe.
The .old file is removed on the next start.
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
import threading
import time
from typing import Callable

import requests

from ._version import __version__

DEFAULT_REPO = "CynicaGaming/shugo-tracker"
EXE_ASSET = "ShugoTracker.exe"
SHA_ASSET = "ShugoTracker.exe.sha256"
CHECK_EVERY_S = 6 * 3600
FROZEN = bool(getattr(sys, "frozen", False))


def parse_version(v: str) -> tuple[int, int, int] | None:
    m = re.match(r"^v?(\d+)\.(\d+)(?:\.(\d+))?$", v.strip())
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)


def is_newer(remote: str, local: str) -> bool:
    r, l = parse_version(remote), parse_version(local)
    if r is None:
        return False
    if l is None:  # dev build
        return False
    return r > l


class Updater:
    def __init__(self, repo: str = DEFAULT_REPO, enabled: bool = True,
                 log: Callable[[str], None] | None = None, on_change: Callable[[], None] | None = None):
        self.repo = repo
        self.enabled = enabled
        self.log = log or (lambda s: None)
        self.on_change = on_change or (lambda: None)
        self.current = __version__
        self.latest: str | None = None
        self.state = "idle"          # idle | checking | downloading | ready | error | uptodate | dev
        self.error: str | None = None
        self.release_url: str | None = None
        self._staged: str | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": f"Shugo-Tracker/{self.current}",
                                      "Accept": "application/vnd.github+json"})

    # ───── lifecycle ─────
    def start(self) -> None:
        self._cleanup_old()
        if not self.enabled:
            return
        threading.Thread(target=self._loop, name="updater", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        self._stop.wait(5)  # let the app settle first
        while not self._stop.is_set():
            try:
                self.check_and_download()
            except Exception as e:  # never let the updater take the app down
                self._set("error", f"{e.__class__.__name__}: {e}")
            self._stop.wait(CHECK_EVERY_S)

    def _set(self, state: str, error: str | None = None) -> None:
        self.state, self.error = state, error
        if error:
            self.log(f"update: {error}")
        self.on_change()

    # ───── check / download ─────
    def check_and_download(self) -> None:
        if self.state in ("downloading", "ready"):
            return
        self._set("checking")
        r = self._session.get(f"https://api.github.com/repos/{self.repo}/releases/latest", timeout=15)
        if r.status_code == 404:
            self._set("uptodate")  # no release published yet
            return
        r.raise_for_status()
        rel = r.json()
        tag = rel.get("tag_name", "")
        self.latest = tag.lstrip("v")
        self.release_url = rel.get("html_url")
        if not is_newer(tag, self.current):
            self._set("dev" if parse_version(self.current) is None else "uptodate")
            return
        self.log(f"update: v{self.latest} available (running v{self.current})")
        if not FROZEN:
            self._set("ready_source")  # running from source: just tell the user
            return
        assets = {a["name"]: a["browser_download_url"] for a in rel.get("assets", [])}
        if EXE_ASSET not in assets or SHA_ASSET not in assets:
            self._set("error", f"release {tag} is missing {EXE_ASSET} or {SHA_ASSET}")
            return
        self._set("downloading")
        expected = self._session.get(assets[SHA_ASSET], timeout=15).text.split()[0].strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", expected):
            self._set("error", "bad checksum file")
            return
        target = sys.executable + ".new"
        h = hashlib.sha256()
        with self._session.get(assets[EXE_ASSET], stream=True, timeout=60) as dl:
            dl.raise_for_status()
            with open(target, "wb") as f:
                for chunk in dl.iter_content(1 << 16):
                    f.write(chunk)
                    h.update(chunk)
        if h.hexdigest() != expected:
            os.remove(target)
            self._set("error", "downloaded update failed its checksum; discarded")
            return
        self._staged = target
        self._set("ready")

    # ───── install ─────
    def apply(self, restart: bool, argv: list[str] | None = None) -> bool:
        """Swap the staged exe in. With restart=True the new version is launched (caller then exits)."""
        with self._lock:
            staged = self._staged
            if not (FROZEN and staged and os.path.exists(staged)):
                return False
            exe = sys.executable
            old = exe + ".old"
            try:
                if os.path.exists(old):
                    os.remove(old)
                os.replace(exe, old)          # allowed while running
                try:
                    os.replace(staged, exe)
                except OSError:
                    os.replace(old, exe)      # roll back
                    raise
            except OSError as e:
                self._set("error", f"could not install update: {e}")
                return False
            self._staged = None
            self.state = "installed"
            self.log(f"update: installed v{self.latest}")
            if restart:
                self.relaunch(argv)
            return True

    @staticmethod
    def relaunch(argv: list[str] | None = None) -> None:
        exe = sys.executable
        flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        subprocess.Popen([exe, *(argv or [])], cwd=os.path.dirname(exe), close_fds=True, creationflags=flags)

    def _cleanup_old(self) -> None:
        if not FROZEN:
            return
        for suffix in (".old", ".new"):
            path = sys.executable + suffix
            for _ in range(10):  # the previous process may take a moment to exit
                try:
                    if os.path.exists(path):
                        os.remove(path)
                    break
                except OSError:
                    time.sleep(0.5)

    # ───── for the overlay ─────
    def banner(self) -> str | None:
        if self.state == "ready":
            return f"⬆ v{self.latest} ready — click to restart & update"
        if self.state == "downloading":
            return f"⬇ downloading v{self.latest}…"
        if self.state == "ready_source":
            return f"⬆ v{self.latest} released — git pull to update"
        return None
