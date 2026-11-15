"""Log files, one per day (shugo-core_2026-11-15.log): every start that day adds to the same file, and files older
than a set number of days are deleted. A day's file is easy to find ("it broke on Saturday") and holds the whole
day, restarts included."""
from __future__ import annotations

import glob
import os
import re
import time

TEXT_KEEP_DAYS = 14                  # shugo-core_*.log, shugo-window_*.log
_DAY = re.compile(r"_(\d{4}-\d\d-\d\d)")


def today() -> str:
    return time.strftime("%Y-%m-%d")


def line_time() -> str:
    """The start of every log line: 2026-11-14 22:51:03.412"""
    t = time.time()
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t)) + f".{int(t % 1 * 1000):03d}"


def daily_log_path(folder: str, prefix: str, ext: str, keep_days: int) -> str:
    """Today's `prefix_YYYY-MM-DD.ext` in `folder`. Files of this kind from more than `keep_days` days ago are
    deleted (older per-start names like prefix_2026-11-14_22-51-03.ext count by their date too)."""
    os.makedirs(folder, exist_ok=True)
    cutoff = time.strftime("%Y-%m-%d", time.localtime(time.time() - keep_days * 86400))
    for path in glob.glob(os.path.join(glob.escape(folder), f"{prefix}_*.{ext}")):
        m = _DAY.search(os.path.basename(path)[len(prefix):])
        if m and m.group(1) <= cutoff:
            try:
                os.remove(path)
            except OSError:
                pass                  # still open somewhere: next time
    return os.path.join(folder, f"{prefix}_{today()}.{ext}")


class DailyText:
    """A text log that writes to today's file and moves on to the next day's at midnight."""

    def __init__(self, folder: str, prefix: str, keep_days: int = TEXT_KEEP_DAYS):
        self.folder, self.prefix, self.keep = folder, prefix, keep_days
        self.day, self.f = None, None

    def write(self, msg: str) -> None:
        if self.day != today():
            self._open()
        if self.f:
            try:
                self.f.write(f"{line_time()} {msg}\n")
                self.f.flush()
            except (OSError, ValueError):
                pass

    def _open(self) -> None:
        if self.f:
            self.f.close()
        self.day = today()
        try:
            self.f = open(daily_log_path(self.folder, self.prefix, "log", self.keep), "a", encoding="utf-8")
        except OSError:
            self.f = None
