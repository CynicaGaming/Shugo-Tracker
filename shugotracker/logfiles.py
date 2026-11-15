"""Log files named by when they started (shugo-core_2026-11-14_22-51-03.log), keeping only the newest few."""
from __future__ import annotations

import glob
import os
import re
import time

STAMP = "%Y-%m-%d_%H-%M-%S"          # local time; sorts by name in the order they were written
MAX_AGE_DAYS = 14                    # and nothing older than this is kept, however few there are


def line_time() -> str:
    """The start of every log line: 2026-11-14 22:51:03.412"""
    t = time.time()
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t)) + f".{int(t % 1 * 1000):03d}"


def new_log_path(folder: str, prefix: str, ext: str, keep: int) -> str:
    """A fresh path for `prefix_<time>.<ext>` in `folder`. Older ones beyond the newest `keep - 1` are deleted,
    so with the new one there are at most `keep`, and so is any older than MAX_AGE_DAYS."""
    os.makedirs(folder, exist_ok=True)
    old = sorted(glob.glob(os.path.join(glob.escape(folder), f"{prefix}_*.{ext}")), key=_order)
    stamp = time.strftime(STAMP)
    same = [p for p in old if _order(p)[0] == stamp]        # started this same second (a quick rollover)
    n = max([_order(p)[1] for p in same], default=0) + 1
    path = os.path.join(folder, f"{prefix}_{stamp}" + (f"-{n}" if n > 1 else "") + f".{ext}")
    cutoff = time.time() - MAX_AGE_DAYS * 86400
    stale = old[:max(0, len(old) - (keep - 1))] + [p for p in old if _mtime(p) < cutoff]
    for p in dict.fromkeys(stale):
        try:
            os.remove(p)
        except OSError:
            pass                      # still open somewhere: next time
    return path


def _order(path: str) -> tuple:
    """Oldest first: by the start time in the name, then by the -2, -3… of files started in the same second."""
    m = re.search(r"_(\d{4}-\d\d-\d\d_\d\d-\d\d-\d\d)(?:-(\d+))?\.[^.]+$", path)
    return (m.group(1), int(m.group(2) or 1)) if m else ("", 0)


def _mtime(path: str) -> float:
    try:
        return os.path.getmtime(path)
    except OSError:
        return float("inf")
