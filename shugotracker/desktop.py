"""Small Windows helpers for the core: folder sizes and whether Alt is held (even while the game has focus)."""
from __future__ import annotations

import ctypes
import os
import sys


def folder_size(path: str) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def alt_down() -> bool | None:
    """Whether Alt is held right now, even while another window (the game) has focus.
    None where we can't ask the system (not Windows): the caller falls back to Tk's key events."""
    if sys.platform != "win32":
        return None
    try:
        return bool(ctypes.windll.user32.GetAsyncKeyState(0x12) & 0x8000)   # VK_MENU
    except Exception:  # noqa: BLE001
        return None
