"""Shugo Tracker main window: character search, favorites, and full character profiles."""
from __future__ import annotations

import hashlib
import io
import os
import queue
import time
import tkinter as tk
import tkinter.font as tkfont
import webbrowser
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

import requests

from .aion2api import (CLASSES, REGION_LABELS, SUB_REGIONS, USER_AGENT, Api, Character, rank,
                       search_filters)
from .favorites import Favorites
from .columns import layout_columns
from .sorting import SORTS, sort_chars

try:  # images are optional
    from PIL import Image, ImageDraw, ImageTk
except ImportError:  # pragma: no cover
    Image = ImageDraw = ImageTk = None

# ───── theme ─────
BG = "#101114"             # graphite ground ("Ledger" look)
SURFACE = "#18191e"        # inputs, segmented controls, cells
SURFACE_2 = "#26282f"      # the selected segment, buttons
HOVER = "#1c1d23"          # a hovered row
BORDER = "#2c2e35"
LINE = "#1f2026"           # table rules
FG = "#e9eaee"
FG_DIM = "#8d919c"
FG_FAINT = "#5f6470"
GOLD_SOFT = "#2a2414"      # gold-tinted fill behind a chosen filter
GOLD_TEXT = "#e8c46a"
ACCENT = "#d9a93a"        # Shugo gold
ACCENT_FG = "#1a1306"
ELYOS = "#6aa8ff"
ASMO = "#b98cff"
RED = "#ff6b6b"
GREEN = "#5fd38a"
LEGION = "#9fd0a8"
SKEL_A = "#1f2127"
SKEL_B = "#282a31"

CARD_H = 40                # one table row
CARD_GAP = 0
PAD = 16
PORTRAIT = 26
PAGE_SIZE = 30
REGION_NAMES = {"nae": "NA - East", "naw": "NA - West", "eu": "Europe", "la": "Latin America", "as": "Asia"}
LOCAL_FILTER_PAGES = 20       # with a level range, look through at most this many pages per region

CLASS_COLORS = {
    "Gladiator": "#e0864a", "Templar": "#d8b44a", "Ranger": "#7fc06a", "Assassin": "#c96ad6",
    "Spiritmaster": "#5fc4c4", "Sorcerer": "#6a8fe0", "Cleric": "#f0e08a", "Chanter": "#8ad49a",
    "Brawler": "#e06a6a",
}
GRADE_COLORS = {
    "Common": "#b8bcc6", "Rare": "#6fd38a", "Legend": "#5aa9ff", "Unique": "#e2b84a",
    "Epic": "#ff8a3d", "Special": "#4fd1c5", "Mythic": "#ff5c8a",
}
FACTIONS = [("1", "Elyos"), ("2", "Asmodian")]


def fmt_int(n: int | None) -> str:
    return "—" if n is None else f"{n:,}"


def ago(seconds: float) -> str:
    s = int(max(0, seconds))
    if s < 60:
        return "just now"
    if s < 3600:
        return f"{s // 60}m ago"
    return f"{s // 3600}h ago"


def elide(font, text: str, max_w: float) -> str:
    """text, cut with "…" so it fits in max_w pixels."""
    if max_w <= 0:
        return ""
    if font.measure(text) <= max_w:
        return text
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if font.measure(text[:mid].rstrip() + "…") <= max_w:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo].rstrip() + "…" if lo else ""


def round_rect(cv: tk.Canvas, x0, y0, x1, y1, r, **kw):
    r = max(0, min(r, (x1 - x0) / 2, (y1 - y0) / 2))
    pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1, x1 - r, y1,
           x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
    return cv.create_polygon(pts, smooth=True, **kw)


def _level_or_none(v) -> int | None:
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return n if 1 <= n <= 99 else None


class FlowFrame(tk.Frame):
    """Lays its children out left to right and wraps them onto new rows when the window is narrow."""

    def __init__(self, parent, gap_x: int = 6, gap_y: int = 6, **kw):
        super().__init__(parent, **kw)
        self.gap_x, self.gap_y = gap_x, gap_y
        self.items: list[tk.Widget] = []
        self._width = 0
        self.bind("<Configure>", self._on_configure)

    def add(self, w: tk.Widget) -> tk.Widget:
        self.items.append(w)
        self.after_idle(self._layout)
        return w

    def _on_configure(self, e):
        if e.width != self._width:
            self._width = e.width
            self._layout()

    def _layout(self):
        width = max(self.winfo_width(), 1)
        x = y = row_h = 0
        for w in self.items:
            ww, wh = w.winfo_reqwidth(), w.winfo_reqheight()
            if x and x + ww > width:
                x, y = 0, y + row_h + self.gap_y
                row_h = 0
            w.place(x=x, y=y)
            x += ww + self.gap_x
            row_h = max(row_h, wh)
        h = y + row_h
        if int(self["height"]) != h:
            self.configure(height=h)


class StyledMenu:
    """
    A right-click menu in the app's own style (Windows draws tk.Menu natively and ignores most colours).
    Same calls as tk.Menu where the app uses them: add_command / add_separator / delete / entryconfigure /
    tk_popup / post / unpost. Closes on a click elsewhere, Esc, or when the window loses focus.
    """

    def __init__(self, root: tk.Tk, font):
        self.root, self.font = root, font
        self.items: list[dict | None] = []          # None = separator
        self.win: tk.Toplevel | None = None
        self._click_bind = None

    # tk.Menu-like API
    def add_command(self, label: str, command, state: str = "normal", selected: bool = False):
        self.items.append({"label": label, "command": command, "state": state, "selected": selected})

    def add_separator(self):
        self.items.append(None)

    def delete(self, first, last=None):
        start = int(first)
        end = len(self.items) if last == "end" else (int(last) + 1 if last is not None else start + 1)
        del self.items[start:end]

    def entryconfigure(self, index: int, **kw):
        item = self.items[index]
        if item is not None:
            item.update({k: v for k, v in kw.items() if k in ("label", "state", "command", "selected")})

    def tk_popup(self, x: int, y: int):
        self.post(x, y)

    def post(self, x: int, y: int, right: bool = False):
        self.unpost()
        win = self.win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg=BORDER)
        box = tk.Frame(win, bg=SURFACE_2, padx=0, pady=4)
        box.pack(padx=1, pady=1, fill="both", expand=True)
        win.minsize(150, 1)
        for item in self.items:
            if item is None:
                tk.Frame(box, bg=BORDER, height=1).pack(fill="x", padx=8, pady=4)
                continue
            on = item["state"] != "disabled"
            rest = ACCENT if item.get("selected") else FG
            row = tk.Label(box, text=item["label"], bg=SURFACE_2, fg=rest if on else FG_FAINT, font=self.font,
                           anchor="w", padx=14, pady=5, cursor="hand2" if on else "")
            row.pack(fill="x")
            if on:
                row.bind("<Enter>", lambda e, r=row: r.config(bg=HOVER, fg=ACCENT))
                row.bind("<Leave>", lambda e, r=row, c=rest: r.config(bg=SURFACE_2, fg=c))
                row.bind("<ButtonRelease-1>", lambda e, c=item["command"]: self._choose(c))
        win.update_idletasks()
        w, h = max(win.winfo_reqwidth(), 150), win.winfo_reqheight()
        if right:
            x -= w
        x = max(4, min(x, win.winfo_screenwidth() - w - 4))
        y = y if y + h < win.winfo_screenheight() - 4 else y - h
        win.geometry(f"+{x}+{y}")
        win.bind("<Escape>", lambda e: self.unpost())
        win.bind("<FocusOut>", lambda e: self.root.after(50, self._maybe_close))
        win.focus_force()
        # a click anywhere else in the app closes it (bound after this click has finished dispatching)
        self.root.after(1, self._watch_clicks)

    def _watch_clicks(self):
        if self.win is not None and not self._click_bind:
            self._click_bind = self.root.bind_all("<ButtonPress>", self._outside, add="+")

    def _outside(self, e):
        w, me = str(e.widget), str(self.win)
        if self.win is not None and w != me and not w.startswith(me + "."):
            self.unpost()

    def _maybe_close(self):
        if self.win is not None and self.root.focus_get() is None:
            self.unpost()

    def _choose(self, command):
        self.unpost()
        command()

    def unpost(self):
        if self._click_bind:
            try:
                self.root.unbind_all("<ButtonPress>")
            except tk.TclError:
                pass
            self._click_bind = None
        if self.win is not None:
            try:
                self.win.destroy()
            except tk.TclError:
                pass
            self.win = None


class ThinScrollbar(tk.Canvas):
    """A slim scrollbar in the app's colours (the Windows one can't be themed). Hidden when nothing scrolls."""

    def __init__(self, parent, command, width: int = 8, bg: str = BG):
        super().__init__(parent, width=width, bg=bg, highlightthickness=0, bd=0)
        self.command = command
        self.lo, self.hi = 0.0, 1.0
        self._hover = False
        self._drag_from = None
        self.bind("<Configure>", lambda e: self._draw())
        self.bind("<Enter>", lambda e: self._set_hover(True))
        self.bind("<Leave>", lambda e: self._set_hover(False))
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<B1-Motion>", self._drag)
        self.bind("<ButtonRelease-1>", lambda e: self._release())

    def set(self, lo, hi):                      # called by the scrolled widget (yscrollcommand)
        self.lo, self.hi = float(lo), float(hi)
        self._draw()

    def _set_hover(self, on):
        self._hover = on
        self._draw()

    def _thumb(self):
        h = max(1, self.winfo_height())
        top = self.lo * h
        bottom = max(top + 24, self.hi * h)     # keep it grabbable on very long lists
        if bottom > h:
            top, bottom = h - (bottom - top), h
        return top, bottom

    def _draw(self):
        self.delete("all")
        if self.hi - self.lo >= 0.999:          # everything fits: no bar
            return
        w = int(self["width"])
        top, bottom = self._thumb()
        bar_w = w - 2 if (self._hover or self._drag_from) else max(3, w - 4)
        x0 = (w - bar_w) / 2
        col = FG_FAINT if (self._hover or self._drag_from) else BORDER
        r = bar_w / 2
        self.create_rectangle(x0, top + r, x0 + bar_w, bottom - r, fill=col, outline="")
        self.create_oval(x0, top, x0 + bar_w, top + bar_w, fill=col, outline="")
        self.create_oval(x0, bottom - bar_w, x0 + bar_w, bottom, fill=col, outline="")

    def _press(self, e):
        if self.hi - self.lo >= 0.999:
            return
        top, bottom = self._thumb()
        if top <= e.y <= bottom:
            self._drag_from = (e.y, self.lo)
        else:                                   # click the track: page towards it
            self.command("scroll", -1 if e.y < top else 1, "pages")

    def _drag(self, e):
        if self._drag_from is None:
            return
        y0, lo0 = self._drag_from
        self.command("moveto", max(0.0, lo0 + (e.y - y0) / max(1, self.winfo_height())))

    def _release(self):
        self._drag_from = None
        self._draw()


ICON_KEEP_S = 30 * 86400      # game icons never change
PORTRAIT_KEEP_S = 86400       # character portraits can


class ImageLoader:
    """
    Downloads images off the UI thread (PhotoImages are created on the UI thread) and keeps the
    downloaded files on disk, so after the first time portraits and icons appear instantly.
    """

    def __init__(self, cache_dir: str | None = None):
        self.cache_dir = cache_dir
        if cache_dir:
            try:
                os.makedirs(cache_dir, exist_ok=True)
                self._prune()
            except OSError:
                self.cache_dir = None
        self.enabled = Image is not None
        self._images: OrderedDict[tuple, object] = OrderedDict()
        self._pending: set[tuple] = set()
        self._results: queue.Queue = queue.Queue()
        self._pool = ThreadPoolExecutor(max_workers=6, thread_name_prefix="images")
        self._session = requests.Session()
        self._session.headers["User-Agent"] = USER_AGENT
        self._bytes: dict[str, bytes] = {}

    def get(self, url: str | None, size: int, radius: int = 10, crop_top: bool = False):
        if not url or not self.enabled:
            return None
        key = (url, size, radius, crop_top)
        img = self._images.get(key)
        if img is not None:
            self._images.move_to_end(key)
            return img or None
        if key not in self._pending:
            self._pending.add(key)
            self._pool.submit(self._fetch, key)
        return None

    def _disk_path(self, url: str) -> str | None:
        if not self.cache_dir:
            return None
        return os.path.join(self.cache_dir, hashlib.sha1(url.encode()).hexdigest()[:24] + ".img")

    @staticmethod
    def _keep_s(url: str) -> float:
        return PORTRAIT_KEEP_S if "profileimg." in url else ICON_KEEP_S

    def _read_disk(self, url: str) -> bytes | None:
        path = self._disk_path(url)
        try:
            if path and time.time() - os.path.getmtime(path) < self._keep_s(url):
                with open(path, "rb") as f:
                    return f.read()
        except OSError:
            pass
        return None

    def _write_disk(self, url: str, data: bytes) -> None:
        path = self._disk_path(url)
        if not path:
            return
        try:
            tmp = path + ".tmp"
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, path)
        except OSError:
            pass

    def _prune(self) -> None:
        now = time.time()
        for name in os.listdir(self.cache_dir):
            path = os.path.join(self.cache_dir, name)
            try:
                if now - os.path.getmtime(path) > ICON_KEEP_S:
                    os.remove(path)
            except OSError:
                pass

    def _fetch(self, key):
        url, size, radius, crop_top = key
        try:
            data = self._bytes.get(url) or self._read_disk(url)
            if data is None:
                r = self._session.get(url, timeout=10)
                r.raise_for_status()
                data = r.content
                self._write_disk(url, data)
            if len(self._bytes) < 400:
                self._bytes[url] = data
            im = Image.open(io.BytesIO(data)).convert("RGBA")
            w, h = im.size
            side = min(w, h)
            top = 0 if crop_top else (h - side) // 2
            im = im.crop(((w - side) // 2, top, (w + side) // 2, top + side)).resize((size, size), Image.LANCZOS)
            if radius:
                mask = Image.new("L", im.size, 0)
                ImageDraw.Draw(mask).rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=255)
                alpha = Image.composite(im.getchannel("A"), Image.new("L", im.size, 0), mask)
                im.putalpha(alpha)
            self._results.put((key, im))
        except Exception:  # noqa: BLE001
            self._results.put((key, None))

    def drain(self) -> bool:
        got = False
        while True:
            try:
                key, im = self._results.get_nowait()
            except queue.Empty:
                return got
            self._pending.discard(key)
            self._images[key] = False if im is None else ImageTk.PhotoImage(im)
            while len(self._images) > 600:
                self._images.popitem(last=False)
            got = True

    def close(self):
        self._pool.shutdown(wait=False, cancel_futures=True)


class SearchWindow:
    def __init__(self, api: Api, cfg: dict, on_close: Callable[[], None], favorites: Favorites | None = None,
                 updater=None, on_update: Callable[[], bool] = lambda: False, version: str = "",
                 initial_query: str | None = None, screenshot: str | None = None,
                 cache_dir: str | None = None):
        self.api = api
        self.cfg = cfg
        self.on_close_cb = on_close
        self.updater = updater                  # Updater or None
        self.on_update = on_update              # installs the downloaded update and relaunches
        self.favorites = favorites if favorites is not None else Favorites(None)

        self.mode = "search"          # search | favorites
        self.results: list[Character] = []
        self.fav_chars: list[Character] = []
        self.keyword = ""
        self.generation = 0
        self.region_state: dict[str, dict] = {}
        self.regions: set[str] = {r for r in cfg.get("regions", []) if r in SUB_REGIONS}
        self.factions: set[str] = {f for f in cfg.get("factions", []) if f in ("1", "2")}
        self.classes: set[str] = {c for c in cfg.get("classes", []) if c in CLASSES}
        self.sort_key = cfg.get("sort", "default") if cfg.get("sort") in SORTS else "default"
        self.sort_rev = bool(cfg.get("sort_rev")) and self.sort_key not in ("default", "latest")
        self.level_min: int | None = _level_or_none(cfg.get("level_min"))
        self.level_max: int | None = _level_or_none(cfg.get("level_max"))
        self._query_filters: dict = {}         # what the current search asked NCSOFT to filter
        self.nearby = None                     # NearbyService, set by the app
        self.set_nearby_enabled: Callable[[bool], None] = lambda on: None   # set by the app
        self.demo_teleport: Callable[[], None] = lambda: None              # --demo only
        self._nearby_rows: list = []
        self._recent_rows: list = []                # (side, character, left_at, fought_you)
        self.nearby_view = "nearby"                 # nearby | recent
        self._nearby_side: dict[str, str] = {}
        self._nearby_seen = None
        self._nearby_panel_key = None
        self._level_job = None
        self.inbox: queue.Queue = queue.Queue()
        self.hover_index = -1
        self.hover_star = False
        self.hover_grip = False
        self._drag: dict | None = None             # favorites being dragged by the grip: {"key", "to"}
        self._dirty = True
        self._debounce = None
        self._update_look = None
        self._view: list[Character] = []
        self._has_skeletons = False
        self._last_frame = 0.0
        self.profile_view: ProfileView | None = None
        self.settings_view = None
        self.settings_services = None            # SettingsServices, set by the app

        self.root = tk.Tk()
        self.root.title("Shugo Tracker")
        self.overlay = True                      # frameless window with our own title bar (always)
        self.root.configure(bg=BG)
        self.root.minsize(400, 380)
        w, h = cfg.get("window_size", [600, 760])
        x, y = cfg.get("window_pos", [80, 80])
        self.root.geometry(f"{int(w)}x{int(h)}+{int(x)}+{int(y)}")
        self.root.attributes("-topmost", bool(cfg.get("always_on_top", True)))
        self.root.protocol("WM_DELETE_WINDOW", self.close_button)
        self.root.bind("<Map>", self._on_map, add="+")
        self.root.bind("<Configure>", self._on_resize, add="+")
        self._compact = None
        self.tray_ok = False                     # tray icons work here (set by the app)
        self.tray_icon = (lambda: False, lambda: None)   # (show, remove) the tray icon; set by the app
        if self.overlay:
            self.root.overrideredirect(True)   # our own title bar replaces the Windows frame
        else:
            self._dark_titlebar()
        from .settings import migrate
        migrate(cfg)
        self.save_cfg: Callable[[], None] = lambda: None   # set by the app
        self._hidden_state: str | None = None   # "window" while hidden to the tray

        fams = set(tkfont.families())
        base = "Segoe UI Variable Text" if "Segoe UI Variable Text" in fams else "Segoe UI"
        self.base_font = base
        self.f_body = tkfont.Font(family=base, size=10)
        self.f_bold = tkfont.Font(family=base, size=10, weight="bold")
        self.f_small = tkfont.Font(family=base, size=9)
        self.f_sbold = tkfont.Font(family=base, size=9, weight="bold")
        self.f_tiny = tkfont.Font(family=base, size=8)
        self.f_name = tkfont.Font(family=base, size=12, weight="bold")
        self.f_cp = tkfont.Font(family=base, size=14, weight="bold")
        self.f_input = tkfont.Font(family=base, size=11)
        self.f_title = tkfont.Font(family=base, size=11, weight="bold")
        self.f_big = tkfont.Font(family=base, size=18, weight="bold")
        self.f_star = tkfont.Font(family="Segoe UI Symbol", size=11)

        self.images = ImageLoader(os.path.join(cache_dir, "images") if cache_dir else None)
        self._prefetch_job = None
        self._build(version)
        self.root.after(30, self._tick)
        self.search_entry.focus_set()
        if initial_query:
            self.search_var.set(initial_query)
            self.root.after(300, lambda: self._start_search(now=True))
        if screenshot:
            self._schedule_screenshots(screenshot)

    # ═════ layout ═════
    def _build(self, version: str):
        head = self.titlebar = tk.Frame(self.root, bg=BG)
        head.pack(fill="x", padx=(12, 6), pady=(7, 0))
        logo = tk.Canvas(head, width=20, height=20, bg=BG, highlightthickness=0)
        self._icons = {}
        self._icon_cache: dict = {}
        try:
            from PIL import ImageTk
            from .desktop import make_icon_image
            self._icons["logo"] = ImageTk.PhotoImage(make_icon_image(20))
            logo.create_image(10, 10, image=self._icons["logo"])
            self._icons["app"] = [ImageTk.PhotoImage(make_icon_image(s)) for s in (64, 32, 16)]
            self.root.iconphoto(True, *self._icons["app"])
        except Exception:  # noqa: BLE001  (no Pillow: plain gold disc)
            logo.create_oval(1, 1, 19, 19, fill=ACCENT, outline="")
        logo.pack(side="left", padx=(0, 10))
        self.logo = logo

        # the four tabs as one segmented control; a Back button takes its place on a profile / Settings
        self.tabs = tk.Frame(head, bg=SURFACE, padx=3, pady=3)
        self.tabs.pack(side="left")
        self.tab_search = self._segment(self.tabs, "Search", lambda: self._set_mode("search"))
        self.tab_fav = self._segment(self.tabs, "Favorites", lambda: self._set_mode("favorites"))
        self.tab_near = self._segment(self.tabs, "Nearby", lambda: self._set_mode("nearby"))
        self.tab_recent = self._segment(self.tabs, "Recent", lambda: self._set_mode("recent"), pack=False)
        self.tab_near.bind("<Button-3>", lambda e: self._tab_menu(e, "nearby"))
        self.tab_recent.bind("<Button-3>", lambda e: self._tab_menu(e, "recent"))
        self.back_btn = tk.Label(head, bg=BG, fg=FG_DIM, font=self.f_bold, cursor="hand2", compound="left", padx=2)
        self._back_cmd = lambda: None
        self.back_btn.bind("<Button-1>", lambda e: self._back_cmd())
        self.back_btn.bind("<Enter>", lambda e: self.back_btn.config(fg=FG))
        self.back_btn.bind("<Leave>", lambda e: self.back_btn.config(fg=FG_DIM))
        if self.overlay:
            for w in (head, logo):
                w.bind("<ButtonPress-1>", self._drag_start)
                w.bind("<B1-Motion>", self._drag_move)
                w.bind("<ButtonRelease-1>", lambda e: self._save_geometry())
            close = self._title_button(head, "close", self.close_button, hover=RED)
            close.pack(side="right")
            collapse = self._title_button(head, "minimize", self.collapse)
            collapse.pack(side="right")
        self.gear = self._title_button(head, "cog", self.open_settings, hover=ACCENT)
        self.gear.pack(side="right")
        self.pin = self._title_button(head, "pin", self._toggle_pin, hover=ACCENT, repaint=lambda: self._paint_pin())
        self.pin.pack(side="right")
        self._paint_pin()
        # update available: a green download icon left of the pin (hidden otherwise)
        self.upd_btn = self._title_button(head, "update", self._update_click, hover=GREEN,
                                          repaint=lambda: self._paint_gear())
        self._sync_update_button()

        self.top = tk.Frame(self.root, bg=BG)
        self.top.pack(fill="x", padx=PAD, pady=(10, 0))
        # a frame that loses all its packed children keeps its old height in Tk: this one is always there
        tk.Frame(self.top, bg=BG, height=1).pack(fill="x")

        # search box (searches as you type; Enter searches now)
        self.box = tk.Frame(self.top, bg=SURFACE, highlightthickness=1, highlightbackground=BORDER,
                            highlightcolor=ACCENT)
        self.box.pack(fill="x", pady=(0, 10))
        mag = tk.Label(self.box, bg=SURFACE, cursor="hand2")
        self._set_icon(mag, "search", FG_DIM)
        mag.pack(side="left", padx=(10, 4))
        mag.bind("<Button-1>", lambda e: self._start_search(now=True))
        self.search_var = tk.StringVar()
        self.search_entry = tk.Entry(self.box, textvariable=self.search_var, bg=SURFACE, fg=FG,
                                     insertbackground=FG, relief="flat", font=self.f_input, highlightthickness=0)
        self.search_entry.pack(side="left", fill="x", expand=True, ipady=7, padx=(2, 10))
        self.search_entry.bind("<Return>", lambda e: self._start_search(now=True))
        self.search_entry.bind("<Escape>", lambda e: self.search_var.set(""))
        self.search_var.trace_add("write", lambda *a: self._on_type())
        self.placeholder = tk.Label(self.box, text="Search by character name", bg=SURFACE, fg=FG_FAINT,
                                    font=self.f_input)
        self.placeholder.place(x=34, rely=0.5, anchor="w")
        self.placeholder.bind("<Button-1>", lambda e: self.search_entry.focus_set())

        # filters: region and faction as segmented toggles (nothing chosen = all), class and level under More
        self.filters = tk.Frame(self.top, bg=BG)
        self.filters.pack(fill="x")
        bar = tk.Frame(self.filters, bg=BG)
        bar.pack(fill="x")
        self.adv_toggle = tk.Label(bar, bg=BG, fg=FG_DIM, font=self.f_small, cursor="hand2", padx=4, pady=3)
        self.adv_toggle.pack(side="right", anchor="n")
        self.adv_toggle.bind("<Button-1>", lambda e: self._toggle_advanced())
        self.clear_chip = tk.Label(bar, text="Clear", bg=ACCENT, fg=ACCENT_FG, font=self.f_small,
                                   cursor="hand2", padx=10, pady=2)
        self.clear_chip.bind("<Button-1>", lambda e: self._clear_filters())
        flow = FlowFrame(bar, bg=BG, height=1, gap_x=8, gap_y=6)      # the two groups wrap when narrow
        flow.pack(side="left", fill="x", expand=True)
        seg = flow.add(tk.Frame(flow, bg=SURFACE, padx=2, pady=2))
        self.region_all = self._segment(seg, "All", self._all_regions, small=True)
        self.region_chips = [(r, self._segment(seg, REGION_NAMES[r], lambda k=r: self._toggle_region(k), small=True))
                             for r in SUB_REGIONS]
        seg = flow.add(tk.Frame(flow, bg=SURFACE, padx=2, pady=2))
        self.faction_chips = [(f, self._segment(seg, "Asmo" if f == "2" else label,
                                                lambda k=f: self._toggle_faction(k), small=True))
                              for f, label in FACTIONS]

        self.adv = tk.Frame(self.filters, bg=BG)
        self.adv.columnconfigure(1, weight=1)
        tk.Label(self.adv, text="Class", bg=BG, fg=FG_DIM, font=self.f_small, anchor="w", width=6, pady=3).grid(
            row=0, column=0, sticky="nw", pady=(8, 0))
        classes = FlowFrame(self.adv, bg=BG, height=1, gap_x=4, gap_y=4)
        classes.grid(row=0, column=1, sticky="ew", pady=(8, 0))
        self.class_chips = [(name, classes.add(self._chip(classes, name, lambda k=name: self._toggle_class(k),
                                                          pack=False))) for name in CLASSES]
        tk.Label(self.adv, text="Level", bg=BG, fg=FG_DIM, font=self.f_small, anchor="w", width=6).grid(
            row=1, column=0, sticky="w", pady=(6, 0))
        lv = tk.Frame(self.adv, bg=BG)
        lv.grid(row=1, column=1, sticky="ew", pady=(6, 0))
        self.level_min_var = self._level_box(lv, "min", self.level_min)       # either, both or neither
        tk.Label(lv, text="–", bg=BG, fg=FG_FAINT, font=self.f_small).pack(side="left", padx=6)
        self.level_max_var = self._level_box(lv, "max", self.level_max)
        self.advanced_open = bool(self.cfg.get("advanced_filters", False))
        self._paint_advanced()
        self._paint_chips()
        self._paint_tabs()

        # footer: what's shown on the left, "Latest first" (Favorites / Nearby / Recent) on the right
        self.status_row = tk.Frame(self.root, bg=BG)
        self.status_row.pack(side="bottom", fill="x")
        tk.Frame(self.status_row, bg=LINE, height=1).pack(fill="x")
        self.latest_lb = tk.Label(self.status_row, text="Latest first", bg=BG, fg=FG_DIM, font=self.f_small,
                                  cursor="hand2", padx=PAD, pady=6)
        self.latest_lb.bind("<Button-1>", lambda e: self._toggle_latest())
        self.status = tk.Label(self.status_row, text="", bg=BG, fg=FG_DIM, font=self.f_small, anchor="w",
                               padx=PAD, pady=6)
        self.status.pack(side="left", fill="x", expand=True)
        self.status.bind("<Shift-Button-1>", lambda e: self._nearby_record())   # hidden: Nearby capture

        # the table: sortable column headers over a virtualized list of rows
        self.list_wrap = tk.Frame(self.root, bg=BG)
        self.list_wrap.pack(fill="both", expand=True, padx=(PAD - 8, 4), pady=(8, 0))
        self.hdr = tk.Canvas(self.list_wrap, bg=BG, height=28, highlightthickness=0, bd=0)
        self.hdr.pack(fill="x")
        self.hdr.bind("<Button-1>", self._header_click)
        self.hdr.bind("<Motion>", lambda e: self.hdr.config(cursor="hand2" if self._header_hit(e.x) else ""))
        body = tk.Frame(self.list_wrap, bg=BG)
        body.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(body, bg=BG, highlightthickness=0, bd=0, yscrollincrement=16)
        self.scroll = ThinScrollbar(body, command=self._yview)
        self.scroll.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.configure(yscrollcommand=self.scroll.set)
        self._paint_sort()
        self.canvas.bind("<Configure>", lambda e: self._mark())
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.canvas.bind("<Button-4>", lambda e: self._scroll_units(-3))
        self.canvas.bind("<Button-5>", lambda e: self._scroll_units(3))
        self.canvas.bind("<Motion>", self._motion)
        self.canvas.bind("<Leave>", lambda e: self._set_hover(-1, False))
        self.canvas.bind("<Button-1>", self._click)
        self.canvas.bind("<B1-Motion>", self._fav_drag)
        self.canvas.bind("<ButtonRelease-1>", self._fav_drop)
        self.canvas.bind("<Button-3>", self._right_click)

        self.nearby_panel = tk.Frame(self.list_wrap, bg=BG)

        if self.overlay:
            self.grip = tk.Label(self.root, text="◢", bg=BG, fg=FG_FAINT, font=self.f_tiny, cursor="size_nw_se")
            self.grip.place(relx=1.0, rely=1.0, anchor="se")
            self._bind_resize(self.grip, "se")
            # resize from any edge or corner: thin grab zones along the border
            self._zones = []
            for edge, cursor, place in (
                    ("n", "sb_v_double_arrow", dict(x=12, y=0, relwidth=1, width=-24, height=4)),
                    ("s", "sb_v_double_arrow", dict(x=12, rely=1.0, y=-4, relwidth=1, width=-24, height=4)),
                    ("w", "sb_h_double_arrow", dict(x=0, y=12, width=4, relheight=1, height=-24)),
                    ("e", "sb_h_double_arrow", dict(relx=1.0, x=-4, y=12, width=4, relheight=1, height=-24)),
                    ("nw", "size_nw_se", dict(x=0, y=0, width=10, height=10)),
                    ("ne", "size_ne_sw", dict(relx=1.0, x=-10, y=0, width=10, height=10)),
                    ("sw", "size_ne_sw", dict(x=0, rely=1.0, y=-10, width=10, height=10))):
                z = tk.Frame(self.root, bg=BG, cursor=cursor)
                z.place(**place)
                self._bind_resize(z, edge)
                self._zones.append(z)
            # A click on a frameless window doesn't activate it on Windows: do it ourselves
            self.root.bind_all("<ButtonPress-1>", self._activate_on_click, add="+")
            self.root.after(50, self._style_window)
            # 1px border drawn as four edge lines (placed above the packed content)
            self._edges = [tk.Frame(self.root, bg=BORDER) for _ in range(4)]
            self._edges[0].place(x=0, y=0, relwidth=1, height=1)
            self._edges[1].place(x=0, rely=1.0, y=-1, relwidth=1, height=1)
            self._edges[2].place(x=0, y=0, width=1, relheight=1)
            self._edges[3].place(relx=1.0, x=-1, y=0, width=1, relheight=1)
            self._lift_chrome()

        self.menu = StyledMenu(self.root, self.f_small)
        self.menu.add_command(label="View profile", command=lambda: self._menu(self.open_profile))
        self.menu.add_command(label="Add to favorites", command=lambda: self._menu(self.toggle_favorite))
        self.menu.add_command(label="Copy name", command=lambda: self._menu(self._copy_name))
        self.menu.add_command(label="Refresh", command=lambda: self._menu(self._refresh))
        self._menu_base = 4                                  # Nearby / Recent add a Clear item below these
        self.list_menu = StyledMenu(self.root, self.f_small)
        self.list_menu.add_command(label="Clear", command=self._clear_list)
        self.tab_menu = StyledMenu(self.root, self.f_small)
        self._menu_char: Character | None = None

    def _segment(self, parent, text, cmd, small: bool = False, pack: bool = True):
        """One option in a segmented control."""
        lb = tk.Label(parent, text=text, bg=SURFACE, fg=FG_DIM, font=self.f_small,
                      padx=7 if small else 11, pady=2 if small else 4, cursor="hand2")
        if pack:
            lb.pack(side="left", padx=(0, 1))
        lb.bind("<Button-1>", lambda e: cmd())
        return lb

    def _on_resize(self, e):
        """Reflow the chrome as the window is resized (the table reflows on its own)."""
        if e.widget is not self.root:
            return
        compact = e.width < 480
        if compact == self._compact or not hasattr(self, "tabs"):
            return
        self._compact = compact
        if compact:
            self.logo.pack_forget()
        elif not self.logo.winfo_manager():
            self.logo.pack(side="left", padx=(0, 10), before=self.back_btn if self.back_btn.winfo_manager()
                           else self.tabs)
        for tab in (self.tab_search, self.tab_fav, self.tab_near, self.tab_recent):
            tab.config(padx=7 if compact else 11)

    def show_back(self, text: str, cmd):
        """Swap the tabs for a Back button (profile, Settings)."""
        self._back_cmd = cmd
        img = self._icon("back", FG_DIM)
        self.back_btn.config(text=f"  {text}" if img else f"‹  {text}", image=img or "")
        self.tabs.pack_forget()
        if not self.back_btn.winfo_manager():
            self.back_btn.pack(side="left")

    def show_tabs(self):
        self.back_btn.pack_forget()
        if not self.tabs.winfo_manager():
            self.tabs.pack(side="left")

    def _chip(self, parent, text, cmd, pack: bool = True):
        lb = tk.Label(parent, text=text, font=self.f_small, padx=8, pady=2, cursor="hand2")
        if pack:
            lb.pack(side="left", padx=(0, 4))
        lb.bind("<Button-1>", lambda e: cmd())
        return lb

    def _level_box(self, parent, hint: str, value: int | None) -> tk.StringVar:
        box = tk.Frame(parent, bg=SURFACE, highlightthickness=1, highlightbackground=SURFACE, highlightcolor=ACCENT)
        box.pack(side="left")
        var = tk.StringVar(value=str(value) if value else "")
        ok = (self.root.register(lambda new: new == "" or (new.isdigit() and len(new) <= 2)), "%P")
        ent = tk.Entry(box, textvariable=var, width=3, justify="center", bg=SURFACE, fg=FG, insertbackground=FG,
                       relief="flat", font=self.f_small, highlightthickness=0, validate="key", validatecommand=ok)
        ent.pack(ipady=3, padx=4)
        ph = tk.Label(box, text=hint, bg=SURFACE, fg=FG_FAINT, font=self.f_small)

        def paint(*_):
            if var.get():
                ph.place_forget()
            else:
                ph.place(relx=0.5, rely=0.5, anchor="center")
            box.config(highlightbackground=ACCENT if var.get() else SURFACE)   # filled = active filter
        ph.bind("<Button-1>", lambda e: ent.focus_set())
        ent.bind("<Return>", lambda e: self._apply_levels())
        ent.bind("<FocusOut>", lambda e: self._apply_levels())
        ent.bind("<Escape>", lambda e: var.set(""))
        var.trace_add("write", lambda *a: (paint(), self._levels_typed()))
        paint()
        return var

    def _paint_chips(self):
        def look(lb, on):                         # one highlight for every filter: gold
            lb.config(bg=GOLD_SOFT if on else SURFACE, fg=GOLD_TEXT if on else FG_DIM)
        look(self.region_all, not self.regions)
        for chips, chosen in ((self.region_chips, self.regions), (self.faction_chips, self.factions),
                              (self.class_chips, self.classes)):
            for key, lb in chips:
                look(lb, key in chosen)
        if self.regions or self.factions or self.classes or self.level_min or self.level_max:
            self.clear_chip.pack(side="right", padx=(0, 6), anchor="n", before=self.adv_toggle)
        else:
            self.clear_chip.pack_forget()
        if hasattr(self, "adv_toggle"):
            self._paint_advanced()

    def _paint_tabs(self):
        n = len(self.favorites)
        self.tab_fav.config(text=f"Favorites{f'  {n}' if n else ''}")
        near = len(self._nearby_rows) if self._nearby_on() else 0
        self.tab_near.config(text=f"Nearby{f'  {near}' if near else ''}")
        rec = len(self._recent_rows) if self._nearby_on() else 0
        self.tab_recent.config(text=f"Recent{f'  {rec}' if rec else ''}")
        if self._nearby_on():                    # Recent only means something with Nearby on
            if not self.tab_recent.winfo_manager():
                self.tab_recent.pack(side="left", padx=(0, 1))
        elif self.tab_recent.winfo_manager():
            self.tab_recent.pack_forget()
            if self.mode == "recent":
                self.root.after_idle(lambda: self._set_mode("nearby"))
        for tab, mode in ((self.tab_search, "search"), (self.tab_fav, "favorites"), (self.tab_near, "nearby"),
                          (self.tab_recent, "recent")):
            on = self.mode == mode
            tab.config(bg=SURFACE_2 if on else SURFACE, fg=FG if on else FG_DIM, font=self.f_sbold if on else self.f_small)

    def _paint_pin(self):
        on = bool(self.root.attributes("-topmost"))
        self._set_icon(self.pin, "pin", ACCENT if on else FG_FAINT)

    def _dark_titlebar(self):
        try:  # Windows 10/11 immersive dark title bar
            import ctypes
            self.root.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            val = ctypes.c_int(1)
            for attr in (20, 19):
                if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(val), ctypes.sizeof(val)) == 0:
                    break
        except Exception:  # noqa: BLE001
            pass

    # ═════ modes / filters ═════
    def _set_mode(self, mode: str):
        self.close_profile()
        if mode == self.mode:
            return
        self.mode = mode
        self.nearby_view = "recent" if mode == "recent" else "nearby"
        self._ensure_filters()
        if mode == "favorites":
            self.box.pack_forget()
            self.fav_chars = self.favorites.characters()
        elif mode in ("nearby", "recent"):
            self.box.pack_forget()
            self._refresh_nearby(force=True)
        else:
            self.box.pack(fill="x", pady=(0, 10), before=self.filters)
            self.search_entry.focus_set()
        self._paint_nearby_panel()
        self._paint_tabs()
        self._paint_sort()
        self.canvas.yview_moveto(0)
        self._mark()

    def _toggle_region(self, k):
        self.regions ^= {k}
        self.cfg["regions"] = sorted(self.regions)
        self._filters_changed()

    def _toggle_faction(self, k):
        self.factions ^= {k}
        self.cfg["factions"] = sorted(self.factions)
        self._filters_changed()

    def _toggle_advanced(self):
        self.advanced_open = not self.advanced_open
        self.cfg["advanced_filters"] = self.advanced_open
        self._paint_advanced()

    def _paint_advanced(self):
        if self.advanced_open:
            self.adv.pack(fill="x")
        else:
            self.adv.pack_forget()
        n = len(self.classes) + (self.level_min is not None or self.level_max is not None)
        hidden = f" {n}" if n and not self.advanced_open else ""
        self.adv_toggle.config(text=f"More{hidden}  {'▴' if self.advanced_open else '▾'}",
                               fg=ACCENT if hidden else FG_DIM)

    def _all_regions(self):
        if self.regions:
            self.regions.clear()
            self.cfg["regions"] = []
            self._filters_changed()

    def _toggle_class(self, k):
        self.classes ^= {k}
        self.cfg["classes"] = sorted(self.classes)
        self._filters_changed()

    def _levels_typed(self):
        if self._level_job:
            self.root.after_cancel(self._level_job)
        self._level_job = self.root.after(600, self._apply_levels)

    def _apply_levels(self):
        if self._level_job:
            self.root.after_cancel(self._level_job)
            self._level_job = None
        lo, hi = _level_or_none(self.level_min_var.get()), _level_or_none(self.level_max_var.get())
        if lo is not None and hi is not None and lo > hi:
            lo, hi = hi, lo
        if (lo, hi) == (self.level_min, self.level_max):
            return
        self.level_min, self.level_max = lo, hi
        self.cfg["level_min"], self.cfg["level_max"] = lo, hi
        self._filters_changed()

    def _clear_filters(self):
        self.regions.clear()
        self.factions.clear()
        self.classes.clear()
        self.level_min = self.level_max = None
        self.cfg["regions"], self.cfg["factions"], self.cfg["classes"] = [], [], []
        self.cfg["level_min"] = self.cfg["level_max"] = None
        for var in (self.level_min_var, self.level_max_var):
            if var.get():
                var.set("")
        if self._level_job:
            self.root.after_cancel(self._level_job)
            self._level_job = None
        self._filters_changed()

    def _level_range_local(self) -> bool:
        """A level range NCSOFT can't filter on (it only does exact levels): we filter what's loaded."""
        return (self.level_min is not None or self.level_max is not None) and \
            "level" not in self._query_filters

    def _server_filters(self) -> dict:
        return search_filters(self.classes, self.factions, self.level_min, self.level_max)

    def _filters_changed(self):
        self._paint_chips()
        self.canvas.yview_moveto(0)
        if self.mode == "search" and self.keyword and self._server_filters() != self._query_filters:
            self._run_search(self.keyword)       # NCSOFT applies class / faction / exact level itself
        self._mark()

    def _toggle_pin(self):
        on = not bool(self.root.attributes("-topmost"))
        self.root.attributes("-topmost", on)
        self.cfg["always_on_top"] = on
        self._paint_pin()

    # ═════ search ═════
    def _on_type(self):
        text = self.search_var.get()
        if text:
            self.placeholder.place_forget()
        else:
            self.placeholder.place(x=36, rely=0.5, anchor="w")
        if self._debounce:
            self.root.after_cancel(self._debounce)
            self._debounce = None
        if len(text.strip()) >= 2:
            self._debounce = self.root.after(350, lambda: self._start_search(now=False))

    def _start_search(self, now: bool):
        if self._debounce:
            self.root.after_cancel(self._debounce)
            self._debounce = None
        kw = self.search_var.get().strip()
        if not kw or (kw == self.keyword and not now):
            return
        if self.mode != "search":
            self._set_mode("search")
        self.close_profile()
        self._run_search(kw)

    def _run_search(self, kw: str):
        self.keyword = kw
        self._query_filters = self._server_filters()
        self.generation += 1
        self.api.new_generation()
        self.results = []
        # Always search every region: the region chips filter instantly without a new search.
        self.region_state = {r: {"page": 0, "total": None, "loading": True, "error": None} for r in SUB_REGIONS}
        self.canvas.yview_moveto(0)
        self._fetch_pages(SUB_REGIONS)
        self._mark()

    def _fetch_pages(self, regions):
        gen, kw, filters = self.generation, self.keyword, dict(self._query_filters)
        for r in regions:
            st = self.region_state[r]
            st["loading"] = True
            page = st["page"] + 1
            self.api.search(kw, [r], page=page, size=PAGE_SIZE, filters=filters,
                            on_done=lambda region, chars, total, err, g=gen, p=page:
                            self.inbox.put(("search", g, region, p, chars, total, err)))

    def _load_more_if_needed(self, last_visible: int, visible_count: int):
        if self.mode != "search" or not self.keyword or last_visible < visible_count - 8:
            return
        wanted = self.regions or set(SUB_REGIONS)
        more = [r for r, st in self.region_state.items()
                if r in wanted and not st["loading"] and st["error"] is None and st["total"] is not None
                and st["page"] * PAGE_SIZE < st["total"]
                and not (self._level_range_local() and st["page"] >= LOCAL_FILTER_PAGES)]
        if more:
            self._fetch_pages(more)

    # ═════ data in ═════
    def _drain(self):
        changed = False
        while True:
            try:
                msg = self.inbox.get_nowait()
            except queue.Empty:
                break
            kind = msg[0]
            if kind == "search":
                _, gen, region, page, chars, total, err = msg
                if gen != self.generation:
                    continue
                st = self.region_state.get(region)
                if st is None:
                    continue
                st["loading"] = False
                st["error"] = err
                if err:
                    continue
                st["page"] = page
                st["total"] = total
                seen = {c.key for c in self.results}
                new = [c for c in chars if c.key not in seen]
                if page == 1:
                    self.results = rank(self.results + new, self.keyword)
                else:
                    self.results += rank(new, self.keyword)
                changed = True
            elif kind == "detail":
                changed = True
            elif kind == "toggle":
                self.toggle_visible()
            elif kind == "show":
                if not self.is_visible():
                    self.show()
                else:
                    self.expand()
            elif kind == "quit":
                self.close()
                return
            elif kind == "profile":
                _, c, prof, err = msg
                if self.profile_view and self.profile_view.char.key == c.key:
                    self.profile_view.set_profile(prof, err)
                self.favorites.update(c)
                changed = True
        if self.images.drain():
            changed = True
            if self.profile_view:
                self.profile_view.refresh_images()
        if changed:
            self._mark()

    # ═════ list rendering ═════
    def _source(self) -> list[Character]:
        if self.mode in ("nearby", "recent"):
            if not self._nearby_on():
                return []
            if self.nearby_view == "recent":
                return [c for _side, c, _t, _f in self._recent_rows]
            return [c for _side, c in self._nearby_rows]
        return self.fav_chars if self.mode == "favorites" else self.results

    def _visible(self) -> list[Character]:
        out = self._source()
        if self.regions:
            out = [c for c in out if c.region in self.regions]
        if self.factions:
            out = [c for c in out if str(c.race) in self.factions]
        if self.classes:
            out = [c for c in out if c.class_name in self.classes]
        if self.level_min is not None:
            out = [c for c in out if c.level >= self.level_min]
        if self.level_max is not None:
            out = [c for c in out if c.level <= self.level_max]
        return self._sorted(out)

    def _sorted(self, chars: list[Character]) -> list[Character]:
        """Apply the chosen sort. Nearby / Recent keep enemies and allies in their own groups."""
        grouped = self.mode in ("nearby", "recent")
        return sort_chars(chars, self.sort_key, self._nearby_side if grouped else None, self._latest_times(),
                          reverse=self.sort_rev)

    def _clear_list(self):
        if self.nearby is None or not self._nearby_on():
            return
        if self.mode == "recent":
            self.nearby.clear_recent()
        elif self.mode == "nearby":
            self.nearby.clear_nearby()
        self._refresh_nearby(force=True)

    def _latest_times(self) -> dict:
        """When each listed character arrived: Nearby = first seen, Recent = left, Favorites = starred."""
        if self.mode == "nearby":
            return getattr(self, "_nearby_seen_at", {})
        if self.mode == "recent":
            return {c.name: t for _s, c, t, _f in self._recent_rows}
        if self.mode == "favorites":
            return {c.key: i for i, c in enumerate(self.fav_chars)}    # starred order acts as the time
        return {}

    # ───── table columns ─────
    COLUMNS = [("name", "Name"), ("legion", "Legion"), ("class", "Class"), ("level", "Lv"), ("server", "Server"),
               ("gs", "GS"), ("cp", "CP")]

    def _cols(self, width: int) -> dict:
        """Where each column sits for a list this wide (columns grow with the window and drop out when it's
        narrow: see columns.py). Cached per width."""
        if getattr(self, "_cols_cache", (None,))[0] != width:
            self._cols_cache = (width, layout_columns(width))
        return self._cols_cache[1]

    def _draw_header(self, width: int):
        hv = self.hdr
        hv.delete("all")
        if not self._view and self.mode != "search":
            return
        k = self._cols(width)
        for key, label in self.COLUMNS:
            if key not in k["spans"]:
                continue
            x0, xr, anchor = k["spans"][key]
            on = self.sort_key == key
            if on:
                natural_desc = SORTS[key][1]
                arrow = "↓" if natural_desc != self.sort_rev else "↑"
                label = f"{label} {arrow}" if anchor == "w" else f"{arrow} {label}"
            hv.create_text(x0 if anchor == "w" else xr, 14, text=label, anchor=anchor,
                           fill=ACCENT if on else FG_DIM, font=self.f_sbold if on else self.f_small)
        hv.create_line(0, 27, k["x1"], 27, fill=LINE)

    def _header_hit(self, x: int) -> str | None:
        k = self._cols(max(self.canvas.winfo_width(), 200))
        for key, (x0, xr, _a) in k["spans"].items():
            if x0 - 4 <= x <= xr + 4:
                return key
        return None

    def _header_click(self, e):
        key = self._header_hit(e.x)
        if key:
            self._set_sort(key)

    def _set_sort(self, key: str):
        """A column click: sort by it, then the other way, then back to the list's own order."""
        if key in ("default", "latest"):
            self.sort_key, self.sort_rev = key, False
        elif self.sort_key != key:
            self.sort_key, self.sort_rev = key, False
        elif not self.sort_rev:
            self.sort_rev = True
        else:
            self.sort_key, self.sort_rev = "default", False
        self.cfg["sort"], self.cfg["sort_rev"] = self.sort_key, self.sort_rev
        self._paint_sort()
        self.canvas.yview_moveto(0)
        self._mark()

    def _toggle_latest(self):
        self._set_sort("default" if self.sort_key == "latest" else "latest")

    def _paint_sort(self):
        if self.mode == "favorites" or (self.mode in ("nearby", "recent") and self._nearby_on()):
            self.latest_lb.config(fg=ACCENT if self.sort_key == "latest" else FG_DIM,
                                  font=self.f_sbold if self.sort_key == "latest" else self.f_small)
            if not self.latest_lb.winfo_manager():
                self.latest_lb.pack(side="right", before=self.status)
        else:
            self.latest_lb.pack_forget()
        self._mark()

    def _mark(self):
        self._dirty = True

    def _tick(self):
        try:
            self._drain()
            self._sync_update_button()
            now = time.monotonic()
            if self.nearby is not None and now - getattr(self, "_nearby_poll", 0) > 0.3:
                self._nearby_poll = now
                self._refresh_nearby()
                if self.mode in ("nearby", "recent") and self.nearby_view == "recent" and \
                        now - getattr(self, "_ago_tick", 0) > 15:
                    self._ago_tick = now
                    self._mark()
                if self.mode in ("nearby", "recent") and (self.nearby.recording() or getattr(self, "_rec_done_at", 0) is None
                                              or time.time() - (getattr(self, "_rec_done_at", 0) or 0) < 11):
                    self._mark()                   # keep the recording countdown / saved note current
            if self.profile_view is None:
                if self._dirty:
                    self._render()
                    self._last_frame = now
                elif self._has_skeletons and now - self._last_frame > 0.12:
                    self._render(shimmer_only=True)
                    self._last_frame = now
            elif self.profile_view.animating and now - self._last_frame > 0.03:   # smooth spinner
                self.profile_view.shimmer()
                self._last_frame = now
        finally:
            if not getattr(self, "_closed", False):
                self.root.after(30, self._tick)

    def _render(self, shimmer_only: bool = False) -> bool:
        cv = self.canvas
        if not shimmer_only:
            self._dirty = False
            self._view = self._visible()
            if self._drag:
                keys = [c.key for c in self._view]
                if self._drag["key"] in keys:
                    c = self._view.pop(keys.index(self._drag["key"]))
                    self._view.insert(max(0, min(self._drag["to"], len(self._view))), c)
        view = self._view
        width = max(cv.winfo_width(), 200)
        view_h = max(cv.winfo_height(), 1)
        loading_any = self.mode == "search" and any(
            st["loading"] for r, st in self.region_state.items() if not self.regions or r in self.regions)
        extra = 6 if loading_any else 0
        n = len(view) + extra
        total_h = max(n * (CARD_H + CARD_GAP), view_h)
        cv.configure(scrollregion=(0, 0, width, total_h))
        top = cv.canvasy(0)
        first = max(0, int(top // (CARD_H + CARD_GAP)) - 1)
        last = min(n - 1, int((top + view_h) // (CARD_H + CARD_GAP)) + 1)

        cv.delete("card")
        phase = (time.monotonic() * 1.6) % 2.0
        a, b = (SKEL_B, SKEL_A) if phase < 1.0 else (SKEL_A, SKEL_B)
        has_skel = False
        for i in range(first, last + 1):
            y = i * (CARD_H + CARD_GAP)
            if i >= len(view):
                self._draw_skeleton(cv, y, width, a, b)
                has_skel = True
                continue
            c = view[i]
            if not c.char_id:
                if self.mode in ("nearby", "recent") and self.nearby is not None:
                    self.nearby.want(c.name)        # on screen: ask NCSOFT who this is
            elif c.status == "none" or c.stale:
                self.api.want(c, lambda ch: self.inbox.put(("detail",)))
            dragging = self._drag is not None and c.key == self._drag["key"]
            has_skel |= self._draw_card(cv, c, y, width, i == self.hover_index or dragging, a, b, dragging)
        if not view and not loading_any:
            self._draw_empty(cv, width)
        self._update_status(view)
        if not shimmer_only:
            self._draw_header(width)
        if not shimmer_only and self.sort_key in ("cp", "gs"):
            for c in view[:300]:                     # sorting by numbers needs everyone's numbers
                if c.char_id and c.status == "none":
                    self.api.want(c, lambda ch: self.inbox.put(("detail",)), background=True)
        if not shimmer_only:
            self._load_more_if_needed(last, len(view))
        self._has_skeletons = has_skel
        return has_skel

    def _draw_empty(self, cv, width):
        if self.mode in ("nearby", "recent"):
            msg, sub = self._nearby_empty_text()
            if not msg:
                return
        elif self.mode == "favorites":
            if len(self.favorites):
                msg, sub = "No favorites match these filters", "Clear the filters to see them all."
            else:
                msg, sub = "No favorites yet", "Characters you star appear here."
        elif not self.keyword:
            msg, sub = "Find any AION 2 character", "Search every Global region at once."
        elif any(st["error"] for st in self.region_state.values()):
            msg, sub = "Search failed", "Check your connection and try again."
        elif self.results or self._query_filters:
            msg, sub = "No matches with these filters", "Clear the filters to see all results."
        else:
            msg, sub = f"No characters match “{self.keyword}”", "Try a different spelling."
        cv.create_text(width / 2, 70, text=msg, fill=FG, font=self.f_name, tags="card")
        cv.create_text(width / 2, 96, text=sub, fill=FG_DIM, font=self.f_small, tags="card")

    def _draw_skeleton(self, cv, y, width, a, b):
        sp = self._cols(width)["spans"]
        cy = y + CARD_H / 2
        n0, n1, _ = sp["name"]
        round_rect(cv, n0, cy - 13, n0 + PORTRAIT, cy + 13, 7, fill=a, outline="", tags="card")
        round_rect(cv, n0 + PORTRAIT + 9, cy - 5, max(n0 + PORTRAIT + 20, min(n1, n0 + PORTRAIT + 100)), cy + 5, 5,
                   fill=a, outline="", tags="card")
        for key, tone, w in (("legion", b, 50), ("class", b, 60), ("server", b, 70), ("gs", b, 34), ("cp", a, 50)):
            if key in sp:
                x0, x1_, anchor = sp[key]
                w = min(w, x1_ - x0)
                l, r = (x0, x0 + w) if anchor == "w" else (x1_ - w, x1_)
                round_rect(cv, l, cy - 5, r, cy + 5, 5, fill=tone, outline="", tags="card")

    def _star_box(self, width, y):
        x = self._cols(width)["star"]
        return x - 10, y + CARD_H / 2 - 10, x + 10, y + CARD_H / 2 + 10

    def _reorderable(self) -> bool:
        """Favorites can be dragged into your own order while the list shows that order."""
        return self.mode == "favorites" and len(self.fav_chars) > 1

    def _draw_grip(self, cv, y, hot: bool):
        col = ACCENT if hot else FG_FAINT
        cy = y + CARD_H / 2
        for dx in (0, 4):
            for dy in (-4, 0, 4):
                cv.create_oval(6 + dx - 1.2, cy + dy - 1.2, 6 + dx + 1.2, cy + dy + 1.2, fill=col, outline="",
                               tags="card")

    def _draw_card(self, cv, c: Character, y, width, hover: bool, a, b, dragging: bool = False) -> bool:
        """One table row: portrait, name <legion> •faction | class | Lv | server | GS | CP | ★"""
        k = self._cols(width)
        cy = y + CARD_H / 2
        if hover or dragging:
            round_rect(cv, 0, y + 2, k["x1"], y + CARD_H - 2, 7, fill=HOVER, outline=ACCENT if dragging else "",
                       tags="card")
        if self.mode in ("nearby", "recent"):
            side = self._nearby_side.get(c.name)
            if side in ("enemy", "ally"):          # a slim mark on the left edge: red enemy, green ally
                round_rect(cv, 0, cy - 9, 3, cy + 9, 1.5, fill=RED if side == "enemy" else GREEN, outline="",
                           tags="card")
        sp = k["spans"]
        x, name_r, _ = sp["name"]
        if self._reorderable():
            self._draw_grip(cv, y, dragging or (hover and self.hover_grip))
            x += 10
        img = self.images.get(c.portrait, PORTRAIT, crop_top=True)
        cls_col = CLASS_COLORS.get(c.class_name, FG_DIM)
        if img:
            cv.create_image(x, cy - PORTRAIT / 2, image=img, anchor="nw", tags="card")
        else:
            round_rect(cv, x, cy - 13, x + PORTRAIT, cy + 13, 7, fill=SURFACE_2 if hover else SURFACE, outline="",
                       tags="card")
            cv.create_text(x + PORTRAIT / 2, cy, text=(c.class_name[:1] or "?"), fill=cls_col, font=self.f_sbold,
                           tags="card")
        tx = x + PORTRAIT + 9
        # name cell: when they left (Recent), or the legion when its column doesn't fit, gives way first
        extra = f"<{c.legion}>" if c.legion and "legion" not in sp else ""
        if self.mode in ("nearby", "recent") and self.nearby_view == "recent":
            left_at, fought = getattr(self, "_recent_info", {}).get(c.name, (None, False))
            if left_at:
                extra = f"{'⚔ ' if fought else ''}{ago(time.time() - left_at)}"
        name = elide(self.f_bold, c.name, name_r - tx - 12)
        nid = cv.create_text(tx, cy, text=name, fill=FG, font=self.f_bold, anchor="w", tags="card")
        nx = cv.bbox(nid)[2] + 6
        extra = elide(self.f_small, extra, name_r - nx - 12)
        if len(extra) >= 3:
            eid = cv.create_text(nx, cy + 1, text=extra, fill=FG_DIM, font=self.f_small, anchor="w", tags="card")
            nx = cv.bbox(eid)[2] + 6
        if c.race in (1, 2):
            fc = ELYOS if c.race == 1 else ASMO
            cv.create_oval(nx, cy - 2.5, nx + 5, cy + 2.5, fill=fc, outline="", tags="card")

        def cell(key, text, fill, font=None):
            if key in sp and text:
                x0, x1_, anchor = sp[key]
                font = font or self.f_small
                cv.create_text(x0 if anchor == "w" else x1_, cy, text=elide(font, text, x1_ - x0), fill=fill,
                               font=font, anchor=anchor, tags="card")
        cell("legion", c.legion or "", FG_DIM)
        cell("class", c.class_name or "", cls_col)
        cell("level", str(c.level) if c.level else "", FG)
        if c.server_name:
            region = REGION_NAMES.get(c.region, (c.region or "").upper())
            cell("server", f"{c.server_name} · {region}" if region else c.server_name, FG_DIM)
        # favorite star: shown when starred, or on hover
        fav = c.key in self.favorites
        if fav or hover:
            name_ = "star_fill" if fav else "star"
            col = ACCENT if fav or (hover and self.hover_star) else FG_FAINT
            simg = self._icon(name_, col)
            if simg:
                cv.create_image(k["star"], cy, image=simg, tags="card")
            else:
                cv.create_text(k["star"], cy, text="★" if fav else "☆", fill=col, font=self.f_star, tags="card")
        # numbers
        gs_r, cp_r = sp["gs"][1], sp["cp"][1]
        if c.status == "ok":
            cv.create_text(gs_r, cy, text=fmt_int(c.gear_score), fill=FG, font=self.f_small, anchor="e",
                           tags="card")
            cv.create_text(cp_r, cy, text=fmt_int(c.combat_power), fill=ACCENT, font=self.f_bold, anchor="e",
                           tags="card")
            return False
        if c.status == "unresolved":                 # a nearby player NCSOFT couldn't identify: no numbers
            cv.create_text(cp_r, cy, text="—", fill=FG_FAINT, font=self.f_bold, anchor="e", tags="card")
            return False
        if c.status == "error":
            cv.create_text(cp_r, cy, text="Couldn't load", fill=RED, font=self.f_small, anchor="e", tags="card")
            return False
        round_rect(cv, gs_r - 34, cy - 5, gs_r, cy + 5, 5, fill=b, outline="", tags="card")
        round_rect(cv, cp_r - 50, cy - 5, cp_r, cy + 5, 5, fill=a, outline="", tags="card")
        return True

    def _update_status(self, view):
        if self.mode in ("nearby", "recent"):
            self.status.config(text=self._nearby_status_text(view), fg=FG_DIM)
            return
        if self.mode == "favorites":
            n = len(self.fav_chars)
            self.status.config(text=f"{len(view):,} of {n:,} favorites" if n else "", fg=FG_DIM)
            return
        if not self.keyword:
            self.status.config(text="", fg=FG_DIM)
            return
        wanted = self.regions or set(SUB_REGIONS)
        totals = {r: st["total"] for r, st in self.region_state.items() if r in wanted and st["total"] is not None}
        errors = [REGION_LABELS[r] for r, st in self.region_state.items() if r in wanted and st["error"]]
        loading = any(st["loading"] for r, st in self.region_state.items() if r in wanted)
        grand = sum(totals.values())
        parts = [f"{len(view):,} shown" + (f" of {grand:,} matches" if grand else "")]
        if loading:
            parts.append("searching…")
        elif self._level_range_local():
            checked = sum(min(st["total"] or 0, st["page"] * PAGE_SIZE)
                          for r, st in self.region_state.items() if r in wanted)
            if checked < grand:
                parts[0] = f"{len(view):,} in level range among the first {checked:,} of {grand:,} matches"
        if errors:
            parts.append("failed: " + ", ".join(errors))
        self.status.config(text="  ·  ".join(parts), fg=RED if errors and not grand else FG_DIM)

    # ═════ list interaction ═════
    def _hit(self, x, y_widget) -> tuple[int, bool]:
        y = self.canvas.canvasy(y_widget)
        i = int(y // (CARD_H + CARD_GAP))
        if y - i * (CARD_H + CARD_GAP) > CARD_H or i < 0 or i >= len(self._view):
            return -1, False
        sx0, sy0, sx1, sy1 = self._star_box(max(self.canvas.winfo_width(), 200), i * (CARD_H + CARD_GAP))
        return i, sx0 - 4 <= x <= sx1 + 4 and sy0 - 4 <= y <= sy1 + 4

    def _on_grip(self, x) -> bool:
        return self._reorderable() and x <= 16

    def _motion(self, e):
        if self._drag:
            return
        i, on_star = self._hit(e.x, e.y)
        grip = i >= 0 and self._on_grip(e.x)
        if grip != self.hover_grip:
            self.hover_grip = grip
            self.hover_index = -2                   # force a repaint below
        self._set_hover(i, on_star)

    def _set_hover(self, i, on_star):
        if i != self.hover_index or on_star != self.hover_star:
            self.hover_index, self.hover_star = i, on_star
            self.canvas.config(cursor="fleur" if i >= 0 and self.hover_grip else "hand2" if i >= 0 else "")
            self._mark()

    # drag a favorite by its grip
    def _drag_target(self, y_widget) -> int:
        y = self.canvas.canvasy(y_widget)
        return max(0, min(int(y // (CARD_H + CARD_GAP)), len(self._view) - 1))

    def _fav_drag(self, e):
        if not self._drag:
            return
        h = self.canvas.winfo_height()
        if e.y < 16:
            self.canvas.yview_scroll(-1, "units")
        elif e.y > h - 16:
            self.canvas.yview_scroll(1, "units")
        to = self._drag_target(e.y)
        if to != self._drag["to"]:
            self._drag["to"] = to
            self._mark()

    def _fav_drop(self, e):
        d, self._drag = self._drag, None
        if not d:
            return
        view = self._view                          # already shows the new order
        keys = [c.key for c in view]
        if d["key"] in keys and len(keys) > 1:
            t = keys.index(d["key"])
            full = [k for k in self.favorites.keys() if k != d["key"]]
            if t + 1 < len(keys) and keys[t + 1] in full:
                pos = full.index(keys[t + 1])
            elif t > 0 and keys[t - 1] in full:
                pos = full.index(keys[t - 1]) + 1
            else:
                pos = len(full)
            self.favorites.move(d["key"], pos)
            order = {k: n for n, k in enumerate(self.favorites.keys())}
            self.fav_chars.sort(key=lambda c: order.get(c.key, len(order)))
        self._motion(e)
        self._mark()

    def _click(self, e):
        i, on_star = self._hit(e.x, e.y)
        if i < 0:
            return
        if self._on_grip(e.x):
            key = self._view[i].key
            if self.sort_key != "default":          # reordering means your own order: show it, then drag
                self._set_sort("default")
                self._view = self._visible()
                i = next((n for n, c in enumerate(self._view) if c.key == key), i)
            self._drag = {"key": key, "to": i}
            self._mark()
            return
        c = self._view[i]
        if not c.char_id:                          # a nearby player NCSOFT hasn't identified (yet)
            return
        if on_star:
            self.toggle_favorite(c)
        else:
            self.open_profile(c)

    def _tab_menu(self, e, which: str):
        """Right-click on the Nearby / Recent tab: Clear that list (wherever you are)."""
        if self.nearby is None or not self._nearby_on():
            return
        rows = self._recent_rows if which == "recent" else self._nearby_rows
        label = "Clear Recent" if which == "recent" else "Clear Nearby"
        self.tab_menu.delete(0, "end")
        self.tab_menu.add_command(label=label, command=lambda: self._clear_which(which),
                                  state="normal" if rows else "disabled")
        self.tab_menu.tk_popup(e.x_root, e.y_root)

    def _clear_which(self, which: str):
        if which == "recent":
            self.nearby.clear_recent()
        else:
            self.nearby.clear_nearby()
        self._refresh_nearby(force=True)

    def _clear_label(self) -> str | None:
        if self.mode not in ("nearby", "recent") or not self._nearby_on():
            return None
        if self.mode == "recent":
            return "Clear Recent" if self._recent_rows else None
        return "Clear Nearby" if self._nearby_rows else None

    def _right_click(self, e, demo: bool = False):
        i, _ = self._hit(e.x, e.y)
        clear = self._clear_label()
        if i >= 0:
            self._menu_char = c = self._view[i]
            self.menu.delete(self._menu_base, "end")
            fav = c.key in self.favorites
            self.menu.entryconfigure(1, label="Remove from favorites" if fav else "Add to favorites")
            known = "normal" if c.char_id else "disabled"     # a nearby player NCSOFT hasn't identified
            for idx in (0, 1, 3):
                self.menu.entryconfigure(idx, state=known)
            if clear:
                self.menu.add_separator()
                self.menu.add_command(label=clear, command=self._clear_list)
            if demo:
                self.menu.post(e.x_root, e.y_root)
            else:
                self.menu.tk_popup(e.x_root, e.y_root)
        elif clear:                                       # empty space on the list
            self.list_menu.entryconfigure(0, label=clear)
            self.list_menu.tk_popup(e.x_root, e.y_root)

    def _menu(self, fn):
        if self._menu_char:
            fn(self._menu_char)

    def _copy_name(self, c: Character):
        self.root.clipboard_clear()
        self.root.clipboard_append(c.name)

    def _refresh(self, c: Character):
        c.status = "none"
        self.api.forget(c)
        self._mark()

    # ═════ nearby ═════
    def _nearby_on(self) -> bool:
        return self.nearby is not None and bool(self.cfg.get("nearby_enabled"))

    def _refresh_nearby(self, force: bool = False):
        if self.nearby is None:
            return
        v = (self.nearby.version(), bool(self.cfg.get("nearby_enabled")))
        if v == self._nearby_seen and not force:
            return
        self._nearby_seen = v
        rows = self.nearby.snapshot() if self._nearby_on() else []
        self._nearby_rows = [(side, c) for side, c, _p in rows]
        self._nearby_seen_at = {c.name: p.first_seen for _side, c, p in rows}
        self._recent_rows = self.nearby.recent() if self._nearby_on() else []
        self._nearby_side = {c.name: side for side, c, _t, _f in self._recent_rows}
        self._nearby_side.update({c.name: side for side, c in self._nearby_rows})
        self._recent_info = {c.name: (t, f) for _s, c, t, f in self._recent_rows}
        self._paint_tabs()
        self._paint_nearby_panel()
        if self.mode in ("nearby", "recent"):
            self._paint_sort()

    def _nearby_record(self):
        """Shift+click on the Live line: save 60 s of game traffic for fixing the decoder."""
        from .nearby import CAPTURING
        if self.mode in ("nearby", "recent") and self._nearby_on() and self.nearby.state == CAPTURING \
                and not self.nearby.recording():
            self.nearby.start_recording(60)
            self._mark()

    def _nearby_status_text(self, view) -> str:
        if not self._nearby_on():
            return ""
        from .nearby import CAPTURING
        if self.nearby.state != CAPTURING:
            return ""
        if self.nearby_view == "recent":
            return f"{len(view):,} recently nearby" if view else ""
        left = self.nearby.recording()
        if left:
            self._rec_done_at = None
            return f"● Recording  ·  {int(left)} s"
        if self.nearby.record_path:
            if getattr(self, "_rec_done_at", 0) is None:
                self._rec_done_at = time.time()
            if time.time() - (self._rec_done_at or 0) < 10:
                return f"Saved {os.path.basename(self.nearby.record_path)} in the diagnostics folder"
        name, _server = self.nearby.me()
        return "  ·  ".join(["● Live"] + ([name] if name else []) + ([f"{len(view):,} shown"] if view else []))

    def _nearby_empty_text(self) -> tuple[str, str]:
        if not self._nearby_on():
            return "", ""
        if self.nearby_view == "recent":
            if self._recent_rows:
                return "No players match these filters", "Clear the filters to see them all."
            return "No one yet", "Players you leave behind show up here."
        from .nearby import CAPTURING, ERROR, STARTING, WAITING
        st = self.nearby.state
        if st == WAITING:
            return "Waiting for AION 2", "Players show up here once you're in the game."
        if st == STARTING:
            return "Starting…", ""
        if st == ERROR:
            return "Couldn't read game traffic", self.nearby.detail
        if st == CAPTURING and self._nearby_rows:
            return "No players match these filters", "Clear the filters to see everyone nearby."
        if st == CAPTURING:
            return "No players nearby yet", "Players appear as the game shows them to you."
        return "", ""

    def _paint_nearby_panel(self):
        """The opt-in card (Nearby off) or the Npcap card, placed over the list."""
        from .nearby import NO_LIBS, NO_NPCAP
        if self.mode not in ("nearby", "recent") or self.nearby is None:
            key = None
        elif not self.cfg.get("nearby_enabled"):
            key = "optin"
        elif self.nearby.state in (NO_NPCAP, NO_LIBS):
            key = self.nearby.state
        else:
            key = None
        if key == self._nearby_panel_key:
            return
        self._nearby_panel_key = key
        for w in self.nearby_panel.winfo_children():
            w.destroy()
        if key is None:                            # filters do nothing behind the opt-in / Npcap card
            self._ensure_filters()
        elif self.mode in ("nearby", "recent"):
            self.filters.pack_forget()
        if key is None:
            self.nearby_panel.place_forget()
            return
        box = tk.Frame(self.nearby_panel, bg=SURFACE, padx=22, pady=20)
        box.pack(fill="x", pady=(10, 0))
        wrap = 440

        def text(t, font, fg, pady=(0, 0)):
            tk.Label(box, text=t, bg=SURFACE, fg=fg, font=font, justify="left", anchor="w", wraplength=wrap).pack(
                fill="x", pady=pady)

        buttons = tk.Frame(box, bg=SURFACE)
        if key == "optin":
            head = tk.Frame(box, bg=SURFACE)
            head.pack(fill="x")
            tk.Label(head, text="Nearby Players", bg=SURFACE, fg=FG, font=self.f_name).pack(side="left")
            tk.Label(head, text="BETA", bg=ACCENT, fg=ACCENT_FG, font=self.f_tiny, padx=5).pack(
                side="left", padx=(8, 0), pady=(2, 0))
            text("Disclaimer: reading game traffic may violate AION 2's Terms of Service. Use at your own risk; "
                 "Shugo Tracker is not responsible for any action taken against your account, including bans.",
                 self.f_small, FG_FAINT, (10, 0))
            self._panel_button(buttons, "Turn on Nearby", lambda: self.set_nearby_enabled(True), accent=True)
        else:
            text("Npcap is needed", self.f_name, FG)
            text("Nearby reads the game's traffic through Npcap, which isn't installed on this PC. Install it "
                 "(free, keep the default options), then check again." if key == NO_NPCAP else
                 f"The packet-capture part of Shugo Tracker couldn't load: {self.nearby.detail}",
                 self.f_body, FG_DIM, (8, 0))
            if key == NO_NPCAP:
                from .nearby import NPCAP_URL
                self._panel_button(buttons, "Get Npcap ↗", lambda: webbrowser.open(NPCAP_URL), accent=True)
            self._panel_button(buttons, "Check again", self.nearby.retry)
        buttons.pack(fill="x", pady=(14, 0))
        self.nearby_panel.place(x=0, y=0, relwidth=1, relheight=1)
        self.nearby_panel.lift()

    def _ensure_filters(self):
        gap = (0, 0)
        if not self.filters.winfo_manager():
            self.filters.pack(fill="x", pady=gap)
        else:
            self.filters.pack_configure(pady=gap)

    def _panel_button(self, parent, text, cmd, accent=False):
        b = tk.Label(parent, text=text, bg=ACCENT if accent else SURFACE_2, fg=ACCENT_FG if accent else FG,
                     font=self.f_body, padx=14, pady=5, cursor="hand2")
        b.pack(side="left", padx=(0, 8))
        b.bind("<Button-1>", lambda e: cmd())

    def toggle_favorite(self, c: Character):
        self.favorites.toggle(c)
        self._paint_tabs()
        if self.mode == "favorites" and c.key not in self.favorites:
            self.fav_chars = [x for x in self.fav_chars if x.key != c.key]
        if self.profile_view:
            self.profile_view.paint_star()
        self._mark()

    def _yview(self, *args):
        self.canvas.yview(*args)
        self._mark()

    def _scroll_units(self, n):
        self.canvas.yview_scroll(n, "units")
        self._mark()

    def _wheel(self, e):
        self._scroll_units(int(-e.delta / 40) or (-1 if e.delta > 0 else 1))

    # ═════ profile ═════
    def open_profile(self, c: Character):
        self.close_profile()
        self.top.pack_forget()
        self.status_row.pack_forget()
        self.list_wrap.pack_forget()
        self.profile_view = ProfileView(self, c)
        self.profile_view.frame.pack(fill="both", expand=True)
        self.show_back({"favorites": "Favorites", "nearby": "Nearby", "recent": "Recent"}.get(self.mode, "Search"),
                       self.close_profile)
        if self.overlay:
            self._lift_chrome()
        self.api.fetch_profile(c, lambda ch, prof, err: self.inbox.put(("profile", ch, prof, err)))

    def close_profile(self):
        if not self.profile_view:
            return
        self.profile_view.destroy()
        self.profile_view = None
        self._show_main()

    def _show_main(self):
        self.show_tabs()
        self.top.pack(fill="x", padx=PAD, pady=(10, 0))
        self.status_row.pack(side="bottom", fill="x")
        self.list_wrap.pack(fill="both", expand=True, padx=(PAD - 8, 4), pady=(8, 0))
        if self.overlay:
            self._lift_chrome()
        self._mark()

    # ═════ settings ═════
    def open_settings(self):
        if self.settings_view is not None:
            self.close_settings()
            return
        from .settings_ui import SettingsView
        if self.profile_view:
            self.profile_view.destroy()
            self.profile_view = None
        self.top.pack_forget()
        self.status_row.pack_forget()
        self.list_wrap.pack_forget()
        self.settings_view = SettingsView(self, self.settings_services)
        self.settings_view.frame.pack(fill="both", expand=True)
        self.show_back("Settings", self.close_settings)
        if self.overlay:
            self._lift_chrome()

    def close_settings(self):
        if self.settings_view is None:
            return
        self.settings_view.destroy()
        self.settings_view = None
        self._show_main()

    # ═════ overlay window ═════
    ICON_PX = 15

    def _icon(self, name: str, color: str, accent: str | None = None):
        """A drawn title-bar icon as a PhotoImage (cached); None without Pillow."""
        key = (name, color, accent)
        img = self._icon_cache.get(key)
        if img is None:
            try:
                from .desktop import ui_icon
                rgb = lambda h: tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))  # noqa: E731
                img = ImageTk.PhotoImage(ui_icon(name, self.ICON_PX, rgb(color), rgb(accent) if accent else None))
            except Exception:  # noqa: BLE001
                img = False
            self._icon_cache[key] = img
        return img or None

    GLYPHS = {"close": "✕", "minimize": "—", "cog": "⚙", "pin": "📌"}

    def _set_icon(self, widget, name: str, color: str, accent: str | None = None):
        img = self._icon(name, color, accent)
        if img:
            widget.config(image=img, text="")
        else:
            widget.config(text=self.GLYPHS.get(name, "?"), fg=accent or color)

    def _title_button(self, parent, name, cmd, hover=FG, repaint=None):
        b = tk.Label(parent, bg=BG, fg=FG_DIM, font=self.f_body, cursor="hand2")
        self._set_icon(b, name, FG_DIM)
        if b.cget("image"):
            b.config(width=32, height=26)          # image labels size in pixels: a comfortable hit area
        b.bind("<Button-1>", lambda e: cmd())
        b.bind("<Enter>", lambda e: (self._set_icon(b, name, hover), b.config(bg=SURFACE_2)))
        b.bind("<Leave>", lambda e: (b.config(bg=BG), repaint() if repaint else self._set_icon(b, name, FG_DIM)))
        return b

    def _lift_chrome(self):
        for w in getattr(self, "_zones", []) + getattr(self, "_edges", []):
            w.lift()
        self.grip.lift()

    def _style_window(self):
        from .desktop import round_corners, window_handle
        hwnd = window_handle(self.root)
        if hwnd:
            round_corners(hwnd)
        self.apply_opacity()

    def apply_opacity(self):
        from .settings import clamp_opacity
        try:
            self.root.attributes("-alpha", clamp_opacity(self.cfg.get("window_opacity", 1.0)))
        except tk.TclError:
            pass

    def _drag_start(self, e):
        self._drag = (e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y())

    def _drag_move(self, e):
        dx, dy = self._drag
        self.root.geometry(f"+{e.x_root - dx}+{e.y_root - dy}")

    def _bind_resize(self, widget, edge: str):
        widget.bind("<ButtonPress-1>", lambda e: self._resize_start(e, edge))
        widget.bind("<B1-Motion>", self._resize_move)
        widget.bind("<ButtonRelease-1>", lambda e: self._save_geometry())

    def _resize_start(self, e, edge: str = "se"):
        r = self.root
        self._resize = (edge, e.x_root, e.y_root, r.winfo_x(), r.winfo_y(), r.winfo_width(), r.winfo_height())

    def _resize_move(self, e):
        edge, px, py, x, y, w, h = self._resize
        min_w, min_h = self.root.minsize()
        dx, dy = e.x_root - px, e.y_root - py
        if "e" in edge:
            w = max(min_w, w + dx)
        if "w" in edge:
            nw = max(min_w, w - dx)
            x, w = x + (w - nw), nw
        if "s" in edge:
            h = max(min_h, h + dy)
        if "n" in edge:
            nh = max(min_h, h - dy)
            y, h = y + (h - nh), nh
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        self._mark()

    def _hwnd(self):
        if getattr(self, "_hwnd_cache", None) is None:
            from .desktop import window_handle
            self._hwnd_cache = window_handle(self.root)
        return self._hwnd_cache

    def is_foreground(self) -> bool:
        """Is the overlay the active window? (Asks Windows; Tk's own focus tracking is unreliable here.)"""
        from .desktop import foreground_hwnd, is_same_app_window
        fg, ours = foreground_hwnd(), self._hwnd()
        if fg is None or ours is None:
            return self.root.focus_get() is not None
        return is_same_app_window(fg, ours)

    def _activate_on_click(self, _e=None):
        if self.root.state() == "withdrawn" or self.is_foreground():
            return
        from .desktop import activate
        if self._hwnd():
            activate(self._hwnd())
        self.root.focus_force()

    # minimize to the taskbar. A frameless window can't be minimized as it is, so it briefly gets its normal
    # frame back, minimizes, and goes frameless again when it's restored.
    def collapse(self):
        self._save_geometry()
        self._hide_tooltips()
        if self.overlay:
            self._minimized = True
            self.root.overrideredirect(False)
        self.root.iconify()

    def _on_map(self, _e=None):
        if getattr(self, "_minimized", False) and self.root.state() == "normal":
            self._minimized = False
            self.root.after(10, self._restore_frameless)

    def _restore_frameless(self):
        self.root.overrideredirect(True)
        w, h = self.cfg.get("window_size", [560, 760])
        x, y = self.cfg.get("window_pos", [80, 80])
        self.root.geometry(f"{int(w)}x{int(h)}+{int(x)}+{int(y)}")
        self._hwnd_cache = None                  # the window was re-created
        self._style_window()
        self.root.attributes("-topmost", bool(self.cfg.get("always_on_top", True)))
        self.root.lift()
        self._lift_chrome()
        self._mark()

    def expand(self):
        self.root.deiconify()
        self.root.attributes("-topmost", bool(self.cfg.get("always_on_top", True)))
        self.apply_opacity()
        self.root.lift()
        self._mark()

    # hide / show everything (tray, second launch)
    def is_visible(self) -> bool:
        return self.root.state() not in ("withdrawn", "iconic")

    def toggle_visible(self):
        if self.is_visible():
            self.hide()
        else:
            self.show()

    def hide(self):
        self._hidden_state = "window"
        if self.root.state() != "iconic":
            self._save_geometry()
        self._hide_tooltips()
        self.root.withdraw()

    def show(self, focus: bool = True):
        self.tray_icon[1]()                      # back on screen: no tray icon
        self.expand()
        if focus:
            self.root.focus_force()
            if self.profile_view is None and self.settings_view is None and self.mode == "search":
                self.search_entry.focus_set()
                self.search_entry.select_range(0, "end")
        self._hidden_state = None

    def _hide_tooltips(self):
        if self.profile_view:
            self.profile_view._hide_tip()

    # ═════ updates (the button lives in Settings; the gear turns gold when one is waiting) ═════
    def _sync_update_button(self):
        if self.updater is None or not hasattr(self, "upd_btn"):
            return
        look = self.updater.button()
        if look == self._update_look:
            return
        self._update_look = look
        self._paint_gear()

    def _paint_gear(self):
        self._set_icon(self.gear, "cog", FG_DIM)
        self.gear.config(bg=BG)
        st = self.updater.state if self.updater is not None else None
        if st in ("available", "downloading", "ready"):
            self._set_icon(self.upd_btn, "update", FG_DIM if st == "downloading" else GREEN)
            self.upd_btn.config(bg=BG, cursor="watch" if st == "downloading" else "hand2")
            if not self.upd_btn.winfo_manager():
                self.upd_btn.pack(side="right", after=self.pin)
        elif self.upd_btn.winfo_manager():
            self.upd_btn.pack_forget()

    def _demo_card_menu(self):
        """Screenshots only: the right-click menu on the first card."""
        if not self._view:
            return
        x, y = self.canvas.winfo_rootx() + 200, self.canvas.winfo_rooty() + 30
        ev = type("E", (), {"x": 200, "y": 30, "x_root": x, "y_root": y})()
        self._right_click(ev, demo=True)
        self.root.update_idletasks()

    def _demo_fav_drag(self, start: bool):
        """Screenshots only: pick up the first favorite by its grip and hold it over the second slot."""
        ev = type("E", (), {"x": 10, "y": 30})()
        if start:
            if len(self._view) > 1:
                self._click(ev)
                ev.y = CARD_H + CARD_GAP + 30
                self._fav_drag(ev)
                self._render()
        elif self._drag:
            self._drag = None                   # drop without saving: the CI favorites stay as they were
            self._mark()

    def _demo_update_state(self, state):
        """Screenshots only: show how the title bar looks with an update waiting."""
        if self.updater is None:
            return
        if state:
            self._saved_update = (self.updater.state, self.updater.latest)
            self.updater.state, self.updater.latest = state, "9.9.9"
        elif getattr(self, "_saved_update", None):
            self.updater.state, self.updater.latest = self._saved_update
        self._update_look = None
        self._sync_update_button()
        self.root.update_idletasks()

    def _update_click(self):
        if self.updater is None:
            return
        if self.updater.click(webbrowser.open) == "restart":
            if self.on_update():         # installed; the app relaunches it once we're fully closed
                self.close()
                return
        self._sync_update_button()

    # ═════ screenshots (CI) ═════
    def _schedule_screenshots(self, path: str):
        base = path[:-4] if path.endswith(".png") else path
        steps = [
            (500, self._update_click),
            (900, lambda: self._grab(f"{base}-loading.png")),
            (7000, lambda: self._grab(f"{base}.png")),
            (7010, lambda: self.root.geometry("420x720")),
            (7080, lambda: self._grab(f"{base}-narrow.png")),
            (7090, lambda: self.root.geometry("900x720")),
            (7160, lambda: self._grab(f"{base}-wide.png")),
            (7170, lambda: self.root.geometry("600x720")),
            (7200, lambda: self._view and self.toggle_favorite(self._view[0])),
            (7250, lambda: len(self._view) > 2 and self.toggle_favorite(self._view[2])),   # 2 to show the grips
            (7300, lambda: self._view and self.api.forget(self._view[0])),     # so the loader is visible
            (7400, lambda: self._view and self.open_profile(self._view[0])),
            (7480, lambda: self._grab(f"{base}-profile-loading.png")),
        ]
        t = 11000
        for tab in ProfileView.TABS:
            steps.append((t, lambda tb=tab: self.profile_view and self.profile_view.show_tab(tb)))
            steps.append((t + 900, lambda tb=tab: self._grab(f"{base}-profile-{tb.lower()}.png")))
            t += 1400
        pv = lambda: self.profile_view  # noqa: E731
        steps.append((t - 200, lambda: self._ui_check(f"{base}-check.txt")))
        steps += [
            (t, lambda: pv() and pv().show_tab("Stats")),
            (t + 800, lambda: pv() and pv().demo_hover_first_stat()),
            (t + 1300, lambda: self._grab(f"{base}-profile-stats-hover.png")),
        ]
        t += 3000

        def set_levels(lo, hi):
            self.level_min_var.set(lo)
            self.level_max_var.set(hi)
            self._apply_levels()
        steps += [
            (t, self.close_profile),
            (t + 100, lambda: self.advanced_open or self._toggle_advanced()),
            (t + 200, lambda: self._toggle_class("Cleric")),
            (t + 400, lambda: set_levels("40", "45")),
            (t + 3500, lambda: self._grab(f"{base}-filters.png")),
            (t + 3600, lambda: self._set_sort("cp")),
            (t + 3800, lambda: self._grab(f"{base}-sort.png")),
            (t + 3900, lambda: self._set_sort("default")),
            (t + 3950, self._clear_filters),
        ]
        t += 4000
        steps += [
            (t, lambda: self._set_mode("nearby")),
            (t + 800, lambda: self._grab(f"{base}-nearby-optin.png")),
            (t + 1000, lambda: self.set_nearby_enabled(True)),
            (t + 4500, lambda: self._grab(f"{base}-nearby.png")),
            (t + 4520, lambda: self._demo_card_menu()),
            (t + 4560, lambda: self._grab(f"{base}-nearby-menu.png")),
            (t + 4580, lambda: self.menu.unpost()),
            (t + 4600, lambda: self.nearby and self.nearby.state == "capturing" and self.demo_teleport()),
            (t + 5200, lambda: self._set_mode("recent")),
            (t + 5800, lambda: self._grab(f"{base}-nearby-recent.png")),
            (t + 6000, lambda: self._set_mode("nearby")),
            (t + 6100, lambda: self.set_nearby_enabled(False)),
            (t + 6300, lambda: self._set_mode("search")),
        ]
        t += 6600
        steps += [
            (t, lambda: self._set_mode("favorites")),
            (t + 300, lambda: self._demo_fav_drag(True)),
            (t + 450, lambda: self._grab(f"{base}-favorites-drag.png")),
            (t + 500, lambda: self._demo_fav_drag(False)),
            (t + 600, lambda: self._toggle_faction("2")),
            (t + 2500, lambda: self._grab(f"{base}-favorites.png")),
            (t + 2700, self.open_settings),
            (t + 3500, lambda: self._grab(f"{base}-settings.png")),
            (t + 3700, self.close_settings),
            (t + 3750, lambda: self._demo_update_state("available")),
            (t + 3850, lambda: self._grab(f"{base}-update-available.png")),
            (t + 3880, lambda: self._demo_update_state(None)),
            (t + 3900, self.collapse),
            (t + 4900, self.expand),
            (t + 5500, lambda: self._grab(f"{base}-expanded.png")),
            (t + 6100, self.close),
        ]
        for delay, fn in steps:
            self.root.after(delay, fn)

    def _ui_check(self, path: str):
        """CI self-test: once a profile has loaded, no placeholder may remain and the tab must have content."""
        pv = self.profile_view
        problems = []
        if pv is None:
            problems.append("profile did not open")
        else:
            if pv.loading:
                problems.append("profile still loading")
            if pv._transient is not None and not pv.animating:
                problems.append("placeholder left on screen after load")
            if not pv._frames:
                problems.append("no tab content was built")
            visible = [w for w in pv.body_root.pack_slaves()]
            if len(visible) != 1:
                problems.append(f"{len(visible)} frames packed in the profile body (expected 1)")
        with open(path, "w", encoding="utf-8") as f:
            f.write("FAIL: " + "; ".join(problems) if problems else "OK")

    def _grab_area(self, path: str, widget, pad: int = 0):
        try:
            from PIL import ImageGrab
            widget.update()
            x, y = widget.winfo_rootx() - pad, widget.winfo_rooty() - pad
            ImageGrab.grab(bbox=(max(0, x), max(0, y), x + widget.winfo_width() + 2 * pad,
                                 y + widget.winfo_height() + 2 * pad)).save(path)
        except Exception as e:  # noqa: BLE001
            print(f"screenshot failed: {e}")

    def _grab(self, path: str):
        try:
            from PIL import ImageGrab
            self.root.update()
            x, y = self.root.winfo_rootx(), self.root.winfo_rooty()
            ImageGrab.grab(bbox=(x, y, x + self.root.winfo_width(), y + self.root.winfo_height())).save(path)
        except Exception as e:  # noqa: BLE001
            print(f"screenshot failed: {e}")

    # ═════ lifecycle ═════
    def _save_geometry(self):
        if self.root.state() in ("withdrawn", "iconic"):
            return
        try:
            self.cfg["window_size"] = [self.root.winfo_width(), self.root.winfo_height()]
            self.cfg["window_pos"] = [self.root.winfo_x(), self.root.winfo_y()]
        except tk.TclError:
            pass

    def close_button(self):
        """✕: quit, or tuck away into the tray when "Close to tray" is on."""
        if self.cfg.get("close_to_tray") and self.tray_ok and self.tray_icon[0]():
            self.hide()
        else:
            self.close()

    def close(self):
        if getattr(self, "_closed", False):
            return
        self._closed = True
        self._save_geometry()
        self.favorites.save()
        self.images.close()
        self.on_close_cb()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


# Imported late: profile_ui uses the theme constants above.
from .profile_ui import ProfileView  # noqa: E402
