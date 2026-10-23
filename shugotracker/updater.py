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

DEFAULT_REPO = "CynicaGaming/Shugo-Tracker"
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
    """
    States: idle → checking → uptodate | available | dev | error
            available → downloading → ready → (installed on restart or exit)
    The UI drives it with check_async() / download_async(); a quiet check also runs at start-up
    (and every few hours) so the button can already say an update is available.
    """

    def __init__(self, repo: str = DEFAULT_REPO, enabled: bool = True,
                 log: Callable[[str], None] | None = None, on_change: Callable[[], None] | None = None):
        self.repo = repo
        self.enabled = enabled            # automatic background checks
        self.log = log or (lambda s: None)
        self.on_change = on_change or (lambda: None)
        self.current = __version__
        self.latest: str | None = None
        self.state = "idle"
        self.error: str | None = None
        self.release_url: str | None = None
        self.progress: float | None = None   # 0..1 while downloading, if the size is known
        self.checked_at = 0.0
        self._assets: dict[str, str] = {}
        self._staged: str | None = None
        self._lock = threading.Lock()
        self._busy = threading.Lock()
        self._stop = threading.Event()
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": f"Shugo-Tracker/{self.current}",
                                      "Accept": "application/vnd.github+json"})

    # ───── lifecycle ─────
    def start(self) -> None:
        self._cleanup_old()
        if self.enabled:
            threading.Thread(target=self._loop, name="updater", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        self._stop.wait(5)  # let the app settle first
        while not self._stop.is_set():
            if self.state in ("idle", "uptodate", "dev", "error"):
                self._guarded(self.check)
            self._stop.wait(CHECK_EVERY_S)

    def _guarded(self, fn) -> None:
        if not self._busy.acquire(blocking=False):
            return  # a check or download is already running
        try:
            fn()
        except Exception as e:  # never let the updater take the app down
            self._set("error", f"{e.__class__.__name__}: {e}")
        finally:
            self._busy.release()

    def _set(self, state: str, error: str | None = None) -> None:
        self.state, self.error = state, error
        if error:
            self.log(f"update: {error}")
        self.on_change()

    # ───── user actions (non-blocking) ─────
    def check_async(self) -> None:
        threading.Thread(target=self._guarded, args=(self.check,), name="update-check", daemon=True).start()

    def download_async(self) -> None:
        threading.Thread(target=self._guarded, args=(self.download,), name="update-download", daemon=True).start()

    @property
    def can_install(self) -> bool:
        """Only the packaged exe can replace itself; source runs and dev builds open the release page instead."""
        return FROZEN

    # ───── check / download ─────
    def check(self) -> None:
        if self.state in ("downloading", "ready"):
            return
        self._set("checking")
        r = self._session.get(f"https://api.github.com/repos/{self.repo}/releases/latest", timeout=15)
        self.checked_at = time.time()
        if r.status_code == 404:
            self._set("uptodate")  # no release published yet
            return
        r.raise_for_status()
        rel = r.json()
        tag = rel.get("tag_name", "")
        self.latest = tag.lstrip("v")
        self.release_url = rel.get("html_url")
        self._assets = {a["name"]: a["browser_download_url"] for a in rel.get("assets", [])}
        if parse_version(self.current) is None:
            self._set("dev")       # local/dev build: never replaced automatically
            return
        if not is_newer(tag, self.current):
            self._set("uptodate")
            return
        self.log(f"update: v{self.latest} available (running v{self.current})")
        self._set("available")

    def download(self) -> None:
        if self.state != "available":
            return
        if EXE_ASSET not in self._assets or SHA_ASSET not in self._assets:
            self._set("error", f"release v{self.latest} is missing {EXE_ASSET} or {SHA_ASSET}")
            return
        self.progress = 0.0
        self._set("downloading")
        expected = self._session.get(self._assets[SHA_ASSET], timeout=15).text.split()[0].strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", expected):
            self._set("error", "bad checksum file")
            return
        target = sys.executable + ".new"
        h = hashlib.sha256()
        done = 0
        with self._session.get(self._assets[EXE_ASSET], stream=True, timeout=60) as dl:
            dl.raise_for_status()
            total = int(dl.headers.get("Content-Length") or 0)
            with open(target, "wb") as f:
                for chunk in dl.iter_content(1 << 16):
                    f.write(chunk)
                    h.update(chunk)
                    done += len(chunk)
                    if total:
                        new = done / total
                        if new - (self.progress or 0) >= 0.02:
                            self.progress = new
                            self.on_change()
        if h.hexdigest() != expected:
            os.remove(target)
            self._set("error", "downloaded update failed its checksum; discarded")
            return
        self._staged = target
        self.progress = 1.0
        self._set("ready")

    def check_and_download(self) -> None:
        """Check, and download if newer (kept for older call sites)."""
        self.check()
        if self.state == "available" and self.can_install:
            self.download()

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

    # ───── for the UI ─────
    def button(self) -> tuple[str, str]:
        """(label, style) for the update button; style is one of plain | accent | busy | ok | error."""
        st = self.state
        if st == "checking":
            return "Checking…", "busy"
        if st == "available":
            return (f"⬇ Download v{self.latest}" if self.can_install else f"⬇ Get v{self.latest}"), "accent"
        if st == "downloading":
            pct = f" {int((self.progress or 0) * 100)}%" if self.progress else ""
            return f"Downloading…{pct}", "busy"
        if st == "ready":
            return "⟳ Restart to update", "ok"
        if st == "error":
            return "Update failed · retry", "error"
        recent = time.time() - self.checked_at < 5
        if st == "uptodate" and recent:
            return "✓ Up to date", "ok"
        if st == "dev" and recent:
            return "✓ Dev build", "ok"
        return "Check for updates", "plain"

    def click(self, open_url: Callable[[str], None]) -> str | None:
        """Handle a button press. Returns "restart" when the caller should install and relaunch."""
        st = self.state
        if st == "available":
            if self.can_install:
                self.download_async()
            elif self.release_url:
                open_url(self.release_url)
            return None
        if st == "ready":
            return "restart"
        if st in ("checking", "downloading"):
            return None
        self.check_async()
        return None

    # legacy overlay banner
    def banner(self) -> str | None:
        if self.state == "ready":
            return f"⬆ v{self.latest} ready — click to restart & update"
        if self.state == "downloading":
            return f"⬇ downloading v{self.latest}…"
        if self.state == "ready_source":
            return f"⬆ v{self.latest} released — git pull to update"
        return None
