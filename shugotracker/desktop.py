"""Desktop integration for the overlay: global hotkey, tray icon, single instance, window styling (Windows)."""
from __future__ import annotations

import ctypes
import os
import socket
import threading
from typing import Callable

# ───── hotkey parsing ─────
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
_MODS = {"ctrl": MOD_CONTROL, "control": MOD_CONTROL, "shift": MOD_SHIFT, "alt": MOD_ALT, "win": MOD_WIN}
_NAMED_KEYS = {
    **{f"f{i}": 0x6F + i for i in range(1, 25)},
    "space": 0x20, "tab": 0x09, "home": 0x24, "end": 0x23, "insert": 0x2D, "ins": 0x2D, "delete": 0x2E,
    "pageup": 0x21, "pagedown": 0x22, "`": 0xC0, "backquote": 0xC0, "pause": 0x13, "scrolllock": 0x91,
}


def parse_hotkey(text: str) -> tuple[int, int] | None:
    """'ctrl+shift+s' -> (modifiers, virtual key). None if it can't be parsed."""
    if not text:
        return None
    parts = [p.strip().lower() for p in text.replace("-", "+").split("+") if p.strip()]
    mods, key = 0, None
    for p in parts:
        if p in _MODS:
            mods |= _MODS[p]
        elif key is None:
            if len(p) == 1 and p.isalnum():
                key = ord(p.upper())
            elif p in _NAMED_KEYS:
                key = _NAMED_KEYS[p]
            else:
                return None
        else:
            return None
    if key is None:
        return None
    if mods == 0 and not (0x70 <= key <= 0x87 or key in (0x13, 0x91)):
        return None  # a bare letter would steal typing from the game
    return mods, key


def hotkey_label(text: str) -> str:
    """'ctrl+shift+s' -> 'Ctrl+Shift+S'."""
    out = []
    for p in text.replace("-", "+").split("+"):
        p = p.strip()
        if p:
            out.append(p.upper() if len(p) == 1 else p[:1].upper() + p[1:].lower())
    return "+".join(out)


class GlobalHotkey:
    """RegisterHotKey on its own thread; on_press is called from that thread (post to the UI yourself)."""

    WM_HOTKEY = 0x0312

    def __init__(self, text: str, on_press: Callable[[], None]):
        self.text = text
        self.on_press = on_press
        self.ok = False
        self.error: str | None = None
        self._thread_id = None
        self._ready = threading.Event()

    def start(self) -> bool:
        parsed = parse_hotkey(self.text)
        if os.name != "nt" or parsed is None:
            self.error = "unsupported" if os.name != "nt" else f"can't parse hotkey {self.text!r}"
            return False
        threading.Thread(target=self._run, args=parsed, name="hotkey", daemon=True).start()
        self._ready.wait(2)
        return self.ok

    def _run(self, mods: int, vk: int) -> None:
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        self._thread_id = kernel32.GetCurrentThreadId()
        self.ok = bool(user32.RegisterHotKey(None, 1, mods | MOD_NOREPEAT, vk))
        if not self.ok:
            self.error = "already used by another program"
        self._ready.set()
        if not self.ok:
            return
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == self.WM_HOTKEY:
                try:
                    self.on_press()
                except Exception:  # noqa: BLE001
                    pass
        user32.UnregisterHotKey(None, 1)

    def stop(self) -> None:
        if self._thread_id and os.name == "nt":
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, 0x0012, 0, 0)  # WM_QUIT


# ───── single instance ─────
class SingleInstance:
    """
    The first copy listens on a localhost port; a second copy sends it "show" and exits.
    on_show is called (from a background thread) when another launch asks this copy to appear.
    """

    def __init__(self, port: int = 47815):
        self.port = port
        self._sock: socket.socket | None = None
        self.on_show: Callable[[], None] = lambda: None

    def acquire(self) -> bool:
        """True if this is the only running copy."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            if os.name == "nt":
                s.setsockopt(socket.SOL_SOCKET, getattr(socket, "SO_EXCLUSIVEADDRUSE", 0x4), 1)
            s.bind(("127.0.0.1", self.port))
            s.listen(2)
        except OSError:
            return False
        self._sock = s
        threading.Thread(target=self._serve, name="single-instance", daemon=True).start()
        return True

    def _serve(self) -> None:
        while self._sock is not None:
            try:
                conn, _ = self._sock.accept()
            except OSError:
                return
            with conn:
                try:
                    if conn.recv(16).startswith(b"show"):
                        self.on_show()
                except OSError:
                    pass

    def notify_running(self) -> bool:
        """Ask the running copy to show itself. True if one answered."""
        try:
            with socket.create_connection(("127.0.0.1", self.port), timeout=1) as c:
                c.sendall(b"show")
            return True
        except OSError:
            return False

    def release(self) -> None:
        s, self._sock = self._sock, None
        if s:
            try:
                s.close()
            except OSError:
                pass


# ───── tray icon ─────
# Lightning bolt, in 0..1 coordinates of the icon square.
BOLT = [(0.585, 0.08), (0.215, 0.565), (0.465, 0.565), (0.405, 0.92), (0.785, 0.425), (0.535, 0.425), (0.655, 0.08)]
GOLD_TOP, GOLD_BOTTOM, INK = (246, 205, 98), (210, 154, 42), (26, 19, 6)


def _bolt(draw, box, fill, ss):
    x0, y0, x1, y1 = box
    pts = [(x0 + x * (x1 - x0), y0 + y * (y1 - y0)) for x, y in BOLT]
    draw.polygon(pts, fill=fill)
    draw.line(pts + pts[:1], fill=fill, width=max(1, int((x1 - x0) * 0.035)), joint="curve")  # soften the tips


def make_icon_image(size: int = 64):
    """App icon: a gold rounded square with a dark lightning bolt."""
    from PIL import Image, ImageDraw
    ss = 8
    S = size * ss
    grad = Image.new("RGBA", (S, S))
    g = ImageDraw.Draw(grad)
    for y in range(S):
        t = y / (S - 1)
        g.line([(0, y), (S, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(GOLD_TOP, GOLD_BOTTOM)) + (255,))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, S - 1, S - 1), radius=int(S * 0.24), fill=255)
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    im.paste(grad, (0, 0), mask)
    _bolt(ImageDraw.Draw(im), (0, 0, S, S), INK + (255,), ss)
    return im.resize((size, size), Image.LANCZOS)


def make_bubble_image(size: int = 46):
    """Collapsed-window bubble: the app icon as a gold disc with a dark bolt."""
    from PIL import Image, ImageDraw
    ss = 8
    S = size * ss
    grad = Image.new("RGBA", (S, S))
    g = ImageDraw.Draw(grad)
    for y in range(S):
        t = y / (S - 1)
        g.line([(0, y), (S, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(GOLD_TOP, GOLD_BOTTOM)) + (255,))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).ellipse((ss, ss, S - ss, S - ss), fill=255)
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    im.paste(grad, (0, 0), mask)
    d = ImageDraw.Draw(im)
    d.ellipse((ss, ss, S - ss, S - ss), outline=INK + (255,), width=int(S * 0.03))
    pad = S * 0.17
    _bolt(d, (pad, pad, S - pad, S - pad), INK + (255,), ss)
    return im.resize((size, size), Image.LANCZOS)


def save_ico(path: str) -> None:
    make_icon_image(256).save(path, sizes=[(s, s) for s in (16, 20, 24, 32, 40, 48, 64, 128, 256)])


def tray_supported() -> bool:
    try:
        import pystray  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


class Tray:
    """System-tray icon with Show/Hide and Quit (pystray). All callbacks run on pystray's thread."""

    def __init__(self, on_toggle: Callable[[], None], on_quit: Callable[[], None]):
        self.on_toggle = on_toggle
        self.on_quit = on_quit
        self.icon = None

    def start(self) -> bool:
        if self.icon is not None:
            return True
        try:
            import pystray
        except Exception:  # noqa: BLE001
            return False
        try:
            menu = pystray.Menu(
                pystray.MenuItem("Show", lambda icon, item: self.on_toggle(), default=True),
                pystray.MenuItem("Quit", lambda icon, item: self.on_quit()),
            )
            self.icon = pystray.Icon("ShugoTracker", make_icon_image(64), "Shugo Tracker", menu)
            self.icon.run_detached()
            return True
        except Exception:  # noqa: BLE001
            self.icon = None
            return False

    def stop(self) -> None:
        if self.icon is not None:
            try:
                self.icon.stop()
            except Exception:  # noqa: BLE001
                pass
            self.icon = None


# ───── window styling ─────
def round_corners(hwnd: int) -> None:
    """Windows 11 rounded corners for a frameless window (no-op elsewhere)."""
    try:
        val = ctypes.c_int(2)  # DWMWCP_ROUND
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(val), ctypes.sizeof(val))
    except Exception:  # noqa: BLE001
        pass


def window_handle(tk_widget) -> int | None:
    try:
        return ctypes.windll.user32.GetParent(tk_widget.winfo_id())
    except Exception:  # noqa: BLE001
        return None


def foreground_hwnd() -> int | None:
    """The window Windows considers active (the one receiving keyboard input)."""
    try:
        return ctypes.windll.user32.GetForegroundWindow()
    except Exception:  # noqa: BLE001
        return None


def is_same_app_window(fg: int | None, ours: int | None) -> bool:
    """Is the foreground window ours, or one of its popups (menus, tooltips)? Compares top-level owners."""
    if not fg or not ours:
        return False
    if fg == ours:
        return True
    try:
        u = ctypes.windll.user32
        GA_ROOT, GA_ROOTOWNER = 2, 3
        mine = u.GetAncestor(ours, GA_ROOT) or ours
        return mine in (u.GetAncestor(fg, GA_ROOT), u.GetAncestor(fg, GA_ROOTOWNER))
    except Exception:  # noqa: BLE001
        return False


def activate(hwnd: int) -> None:
    """Make our frameless window the active one (a click alone doesn't, for overrideredirect windows)."""
    try:
        ctypes.windll.user32.SetForegroundWindow(hwnd)
    except Exception:  # noqa: BLE001
        pass


# ───── start with Windows ─────
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "ShugoTracker"


def autostart_command(exe: str) -> str:
    return f'"{exe}"'


def autostart_supported() -> bool:
    import sys
    return os.name == "nt" and bool(getattr(sys, "frozen", False))


def get_autostart() -> bool:
    if os.name != "nt":
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, RUN_NAME)
        return True
    except OSError:
        return False


def set_autostart(enabled: bool) -> bool:
    """Add/remove the per-user Run entry for the packaged exe. True on success."""
    import sys
    if not autostart_supported():
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            if enabled:
                winreg.SetValueEx(k, RUN_NAME, 0, winreg.REG_SZ, autostart_command(sys.executable))
            else:
                try:
                    winreg.DeleteValue(k, RUN_NAME)
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        return False


def open_folder(path: str) -> None:
    try:
        if os.name == "nt":
            os.startfile(path)  # noqa: S606
        else:
            import subprocess
            subprocess.Popen(["xdg-open", path])
    except Exception:  # noqa: BLE001
        pass


def folder_size(path: str) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total
