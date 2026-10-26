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

try:  # images are optional
    from PIL import Image, ImageDraw, ImageTk
except ImportError:  # pragma: no cover
    Image = ImageDraw = ImageTk = None

# ───── theme ─────
BG = "#0f1117"
SURFACE = "#171a22"
SURFACE_2 = "#1e2230"
HOVER = "#232838"
BORDER = "#2a2f3d"
FG = "#e8eaf0"
FG_DIM = "#8b91a1"
FG_FAINT = "#5c6273"
ACCENT = "#d9a93a"        # Shugo gold
ACCENT_FG = "#1a1306"
ELYOS = "#6aa8ff"
ASMO = "#b98cff"
RED = "#ff6b6b"
GREEN = "#5fd38a"
LEGION = "#9fd0a8"
SKEL_A = "#22262f"
SKEL_B = "#2c313c"

CARD_H = 72
CARD_GAP = 8
PAD = 14
PORTRAIT = 48
PAGE_SIZE = 30
SORTS = [("default", "Default"), ("latest", "Latest"), ("name", "Name (A–Z)"), ("cp", "Combat power"),
         ("gs", "Gear score"), ("level", "Level")]
SIDE_ORDER = {"enemy": 0, "ally": 1}
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


def sort_chars(chars: list, key: str, side_of: dict | None = None, when: dict | None = None) -> list:
    """Sort cards. side_of (name -> 'enemy'/'ally') keeps sides grouped, enemies first; when (key or name ->
    time) drives 'latest', newest first. Unknown numbers go last; with nothing to sort by, order is kept."""
    when = when or {}
    side = (lambda c: SIDE_ORDER.get(side_of.get(c.name), 2)) if side_of is not None else (lambda c: 0)
    if key == "latest" and when:
        k = lambda c: (side(c), -when.get(c.key, when.get(c.name, 0)))                       # noqa: E731
    elif key == "name":
        k = lambda c: (side(c), c.name.casefold())                                             # noqa: E731
    elif key in ("cp", "gs", "level"):
        attr = {"cp": "combat_power", "gs": "gear_score", "level": "level"}[key]
        k = lambda c: (side(c), not getattr(c, attr), -(getattr(c, attr) or 0))               # noqa: E731
    elif side_of is not None:
        k = side                                                                               # noqa: E731
    else:
        return list(chars)
    return sorted(chars, key=k)


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
        self.sort_key = cfg.get("sort", "default") if cfg.get("sort") in dict(SORTS) else "default"
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
        self.root.minsize(460, 420)
        w, h = cfg.get("window_size", [560, 760])
        x, y = cfg.get("window_pos", [80, 80])
        self.root.geometry(f"{int(w)}x{int(h)}+{int(x)}+{int(y)}")
        self.root.attributes("-topmost", bool(cfg.get("always_on_top", True)))
        self.root.protocol("WM_DELETE_WINDOW", self.close_button)
        self.root.bind("<Map>", self._on_map, add="+")
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
        self.f_tiny = tkfont.Font(family=base, size=8)
        self.f_name = tkfont.Font(family=base, size=12, weight="bold")
        self.f_cp = tkfont.Font(family=base, size=14, weight="bold")
        self.f_input = tkfont.Font(family=base, size=12)
        self.f_title = tkfont.Font(family=base, size=11, weight="bold")
        self.f_big = tkfont.Font(family=base, size=18, weight="bold")
        self.f_star = tkfont.Font(family="Segoe UI Symbol", size=13)

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
        head.pack(fill="x", padx=(PAD, 6), pady=(8, 0))
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
        logo.pack(side="left", padx=(0, 7))
        title = tk.Label(head, text="Shugo Tracker", bg=BG, fg=FG, font=self.f_title)
        title.pack(side="left")
        ver = tk.Label(head, text=f"v{version}", bg=BG, fg=FG_FAINT, font=self.f_tiny)
        ver.pack(side="left", padx=(6, 0), pady=(3, 0))
        if self.overlay:
            for w in (head, logo, title, ver):
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
        self.top.pack(fill="x", padx=PAD, pady=(6, 4))

        # Search / Favorites tabs
        tabs = tk.Frame(self.top, bg=BG)
        tabs.pack(fill="x", pady=(4, 0))
        self.tab_search = tk.Label(tabs, text="Search", font=self.f_bold, padx=2, pady=4, cursor="hand2", bg=BG)
        self.tab_search.pack(side="left")
        self.tab_fav = tk.Label(tabs, font=self.f_bold, padx=2, pady=4, cursor="hand2", bg=BG)
        self.tab_fav.pack(side="left", padx=(18, 0))
        self.tab_near = tk.Label(tabs, font=self.f_bold, padx=2, pady=4, cursor="hand2", bg=BG)
        self.tab_near.pack(side="left", padx=(18, 0))
        self.tab_search.bind("<Button-1>", lambda e: self._set_mode("search"))
        self.tab_fav.bind("<Button-1>", lambda e: self._set_mode("favorites"))
        self.tab_near.bind("<Button-1>", lambda e: self._set_mode("nearby"))
        self.tab_recent = tk.Label(tabs, font=self.f_bold, padx=2, pady=4, cursor="hand2", bg=BG)
        self.tab_recent.bind("<Button-1>", lambda e: self._set_mode("recent"))
        self.tab_near.bind("<Button-3>", lambda e: self._tab_menu(e, "nearby"))
        self.tab_recent.bind("<Button-3>", lambda e: self._tab_menu(e, "recent"))
        self.tab_line = tk.Frame(self.top, bg=BORDER, height=1)
        self.tab_line.pack(fill="x")


        # search box
        self.box = tk.Frame(self.top, bg=SURFACE_2, highlightthickness=1, highlightbackground=BORDER,
                            highlightcolor=ACCENT)
        self.box.pack(fill="x", pady=(10, 8))
        tk.Label(self.box, text="⌕", bg=SURFACE_2, fg=FG_DIM, font=self.f_input).pack(side="left", padx=(10, 2))
        self.search_var = tk.StringVar()
        self.search_entry = tk.Entry(self.box, textvariable=self.search_var, bg=SURFACE_2, fg=FG,
                                     insertbackground=FG, relief="flat", font=self.f_input, highlightthickness=0)
        self.search_entry.pack(side="left", fill="x", expand=True, ipady=8, padx=(2, 4))
        self.search_entry.bind("<Return>", lambda e: self._start_search(now=True))
        self.search_entry.bind("<Escape>", lambda e: self.search_var.set(""))
        self.search_var.trace_add("write", lambda *a: self._on_type())
        self.placeholder = tk.Label(self.box, text="Search by character name…", bg=SURFACE_2, fg=FG_FAINT,
                                    font=self.f_input)
        self.placeholder.place(x=36, rely=0.5, anchor="w")
        self.placeholder.bind("<Button-1>", lambda e: self.search_entry.focus_set())
        go = tk.Label(self.box, text="Search", bg=ACCENT, fg=ACCENT_FG, font=self.f_body, padx=14, pady=6,
                      cursor="hand2")
        go.pack(side="right", padx=4, pady=4)
        go.bind("<Button-1>", lambda e: self._start_search(now=True))

        # filters, one labelled row each; chips toggle and nothing selected means "all"
        self.filters = tk.Frame(self.top, bg=BG)
        self.filters.pack(fill="x", pady=(2, 0))
        self.filters.columnconfigure(1, weight=1)

        self._advanced_rows: list[tk.Widget] = []

        def row(r, title, advanced=False):
            gap = 0 if r == 0 else 5
            # same font and padding as a chip, so it lines up with the first row of chips
            lb = tk.Label(self.filters, text=title, bg=BG, fg=FG_FAINT, font=self.f_small, anchor="w", width=8,
                          pady=3)
            lb.grid(row=r, column=0, sticky="nw", pady=(gap, 0))
            flow = FlowFrame(self.filters, bg=BG, height=1)
            flow.grid(row=r, column=1, sticky="ew", pady=(gap, 0))
            if advanced:
                self._advanced_rows += [lb, flow]
            return flow

        regions = row(0, "Region")
        self.region_chips = [(r, regions.add(self._chip(regions, REGION_LABELS[r], lambda k=r: self._toggle_region(k),
                                                        pack=False))) for r in SUB_REGIONS]
        factions = row(1, "Faction")
        self.faction_chips = [(f, factions.add(self._chip(factions, label, lambda k=f: self._toggle_faction(k),
                                                          pack=False))) for f, label in FACTIONS]
        # Advanced filters (class, level) fold away to keep the window minimal
        bar = tk.Frame(self.filters, bg=BG)
        bar.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(5, 0))
        self.adv_toggle = tk.Label(bar, bg=BG, fg=FG_DIM, font=self.f_small, cursor="hand2", pady=3)
        self.adv_toggle.pack(side="left")
        self.adv_toggle.bind("<Button-1>", lambda e: self._toggle_advanced())
        self.clear_chip = tk.Label(bar, text="Clear", bg=ACCENT, fg=ACCENT_FG, font=self.f_small,
                                   cursor="hand2", padx=12, pady=3)
        self.clear_chip.bind("<Button-1>", lambda e: self._clear_filters())
        classes = row(3, "Class", advanced=True)
        self.class_chips = [(name, classes.add(self._chip(classes, name, lambda k=name: self._toggle_class(k),
                                                          pack=False))) for name in CLASSES]
        lv_label = tk.Label(self.filters, text="Level", bg=BG, fg=FG_FAINT, font=self.f_small, anchor="w", width=8)
        lv_label.grid(row=4, column=0, sticky="w", pady=(5, 0))
        lv = tk.Frame(self.filters, bg=BG)
        lv.grid(row=4, column=1, sticky="ew", pady=(5, 0))
        self._advanced_rows += [lv_label, lv]
        self.level_min_var = self._level_box(lv, "min", self.level_min)       # either, both or neither
        tk.Label(lv, text="–", bg=BG, fg=FG_FAINT, font=self.f_small).pack(side="left", padx=6)
        self.level_max_var = self._level_box(lv, "max", self.level_max)
        self.advanced_open = bool(self.cfg.get("advanced_filters", False))
        self._paint_advanced()
        self._paint_chips()
        self._paint_tabs()

        # status line, with the sort menu at its right end
        self.status_row = tk.Frame(self.root, bg=BG)
        self.status_row.pack(fill="x", pady=(4, 4))
        self.sort_lb = tk.Label(self.status_row, bg=BG, fg=FG_DIM, font=self.f_small, cursor="hand2", padx=PAD)
        self.sort_lb.pack(side="right")
        self.sort_lb.bind("<Button-1>", self._sort_menu_open)
        self.status = tk.Label(self.status_row, text="", bg=BG, fg=FG_DIM, font=self.f_small, anchor="w",
                               padx=PAD)
        self.status.pack(side="left", fill="x", expand=True)
        self.sort_menu = tk.Menu(self.root, tearoff=0, bg=SURFACE_2, fg=FG, activebackground=HOVER,
                                 activeforeground=FG, bd=0)
        for key, label in SORTS:
            self.sort_menu.add_command(label=label, command=lambda k=key: self._set_sort(k))
        self._paint_sort()
        self.status.bind("<Shift-Button-1>", lambda e: self._nearby_record())   # hidden: Nearby capture
        # virtualized card list
        self.list_wrap = tk.Frame(self.root, bg=BG)
        self.list_wrap.pack(fill="both", expand=True, padx=(PAD, 4), pady=(0, PAD))
        self.canvas = tk.Canvas(self.list_wrap, bg=BG, highlightthickness=0, bd=0, yscrollincrement=16)
        self.scroll = ThinScrollbar(self.list_wrap, command=self._yview)
        self.scroll.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.configure(yscrollcommand=self.scroll.set)
        self.canvas.bind("<Configure>", lambda e: self._mark())
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.canvas.bind("<Button-4>", lambda e: self._scroll_units(-3))
        self.canvas.bind("<Button-5>", lambda e: self._scroll_units(3))
        self.canvas.bind("<Motion>", self._motion)
        self.canvas.bind("<Leave>", lambda e: self._set_hover(-1, False))
        self.canvas.bind("<Button-1>", self._click)
        self.canvas.bind("<Button-3>", self._right_click)

        self.nearby_panel = tk.Frame(self.list_wrap, bg=BG)

        if self.overlay:
            self.grip = tk.Label(self.root, text="◢", bg=BG, fg=FG_FAINT, font=self.f_tiny, cursor="size_nw_se")
            self.grip.place(relx=1.0, rely=1.0, anchor="se")
            self.grip.bind("<ButtonPress-1>", self._resize_start)
            self.grip.bind("<B1-Motion>", self._resize_move)
            self.grip.bind("<ButtonRelease-1>", lambda e: self._save_geometry())
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

        self.menu = tk.Menu(self.root, tearoff=0, bg=SURFACE_2, fg=FG, activebackground=HOVER,
                            activeforeground=FG, bd=0)
        self.menu.add_command(label="View profile", command=lambda: self._menu(self.open_profile))
        self.menu.add_command(label="Add to favorites", command=lambda: self._menu(self.toggle_favorite))
        self.menu.add_command(label="Copy name", command=lambda: self._menu(self._copy_name))
        self.menu.add_command(label="Refresh", command=lambda: self._menu(self._refresh))
        self._menu_base = 4                                  # Nearby / Recent add a Clear item below these
        self.list_menu = tk.Menu(self.root, tearoff=0, bg=SURFACE_2, fg=FG, activebackground=HOVER,
                                 activeforeground=FG, bd=0)
        self.list_menu.add_command(label="Clear", command=self._clear_list)
        self.tab_menu = tk.Menu(self.root, tearoff=0, bg=SURFACE_2, fg=FG, activebackground=HOVER,
                                activeforeground=FG, bd=0)
        self._menu_char: Character | None = None

    def _chip(self, parent, text, cmd, pack: bool = True):
        lb = tk.Label(parent, text=text, font=self.f_small, padx=10, pady=3, cursor="hand2")
        if pack:
            lb.pack(side="left", padx=(0, 6))
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
        for chips, chosen in ((self.region_chips, self.regions), (self.faction_chips, self.factions),
                              (self.class_chips, self.classes)):
            for key, lb in chips:                # one highlight colour for every filter
                on = key in chosen
                lb.config(bg=ACCENT if on else SURFACE, fg=ACCENT_FG if on else FG_DIM)
        if self.regions or self.factions or self.classes or self.level_min or self.level_max:
            self.clear_chip.pack(side="right")
        else:
            self.clear_chip.pack_forget()
        if hasattr(self, "adv_toggle"):
            self._paint_advanced()

    def _paint_tabs(self):
        n = len(self.favorites)
        self.tab_fav.config(text=f"★ Favorites{f'  {n}' if n else ''}")
        near = len(self._nearby_rows) if self._nearby_on() else 0
        self.tab_near.config(text=f"◉ Nearby{f'  {near}' if near else ''}")
        rec = len(self._recent_rows) if self._nearby_on() else 0
        self.tab_recent.config(text=f"↺ Recent{f'  {rec}' if rec else ''}")
        if self._nearby_on():                    # Recent only means something with Nearby on
            if not self.tab_recent.winfo_manager():
                self.tab_recent.pack(side="left", padx=(18, 0))
        elif self.tab_recent.winfo_manager():
            self.tab_recent.pack_forget()
            if self.mode == "recent":
                self.root.after_idle(lambda: self._set_mode("nearby"))
        for tab, mode in ((self.tab_search, "search"), (self.tab_fav, "favorites"), (self.tab_near, "nearby"),
                          (self.tab_recent, "recent")):
            tab.config(fg=ACCENT if self.mode == mode else FG_DIM)

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
            self.box.pack(fill="x", pady=(10, 8), before=self.filters)
            self.search_entry.focus_set()
        self._paint_nearby_panel()
        self._paint_tabs()
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
        for w in self._advanced_rows:
            if self.advanced_open:
                w.grid()
            else:
                w.grid_remove()
        n = len(self.classes) + (self.level_min is not None or self.level_max is not None)
        hidden = f" ({n})" if n and not self.advanced_open else ""
        self.adv_toggle.config(text=f"Advanced filters{hidden}  {'▴' if self.advanced_open else '▾'}",
                               fg=ACCENT if hidden else FG_DIM)

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
        return sort_chars(chars, self.sort_key, self._nearby_side if grouped else None, self._latest_times())

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

    def _sort_menu_open(self, e):
        self.sort_menu.tk_popup(e.x_root, e.y_root)

    def _set_sort(self, key: str):
        self.sort_key = key
        self.cfg["sort"] = key
        self._paint_sort()
        self.canvas.yview_moveto(0)
        self._mark()

    def _paint_sort(self):
        label = dict(SORTS)[self.sort_key]
        self.sort_lb.config(text=f"Sort: {label}  ▾", fg=ACCENT if self.sort_key != "default" else FG_DIM)

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
        view = self._view
        width = max(cv.winfo_width(), 200)
        view_h = max(cv.winfo_height(), 1)
        loading_any = self.mode == "search" and any(
            st["loading"] for r, st in self.region_state.items() if not self.regions or r in self.regions)
        extra = 3 if loading_any else 0
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
            has_skel |= self._draw_card(cv, c, y, width, i == self.hover_index, a, b)
        if not view and not loading_any:
            self._draw_empty(cv, width)
        self._update_status(view)
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
        x1 = width - 6
        round_rect(cv, 0, y, x1, y + CARD_H, 12, fill=SURFACE, outline="", tags="card")
        round_rect(cv, 12, y + 12, 12 + PORTRAIT, y + 12 + PORTRAIT, 10, fill=a, outline="", tags="card")
        round_rect(cv, 72, y + 16, 72 + 130, y + 30, 6, fill=a, outline="", tags="card")
        round_rect(cv, 72, y + 42, 72 + 190, y + 54, 6, fill=b, outline="", tags="card")
        round_rect(cv, x1 - 120, y + 16, x1 - 40, y + 32, 6, fill=a, outline="", tags="card")
        round_rect(cv, x1 - 94, y + 42, x1 - 40, y + 54, 6, fill=b, outline="", tags="card")

    def _star_box(self, width, y):
        x1 = width - 6
        return x1 - 34, y + 8, x1 - 6, y + 36

    def _draw_card(self, cv, c: Character, y, width, hover: bool, a, b) -> bool:
        x1 = width - 6
        round_rect(cv, 0, y, x1, y + CARD_H, 12, fill=HOVER if hover else SURFACE,
                   outline=BORDER if hover else "", tags="card")
        px, py = 12, y + 12
        img = self.images.get(c.portrait, PORTRAIT, crop_top=True)
        if img:
            cv.create_image(px, py, image=img, anchor="nw", tags="card")
        else:
            col = CLASS_COLORS.get(c.class_name, FG_DIM)
            round_rect(cv, px, py, px + PORTRAIT, py + PORTRAIT, 10, fill=SURFACE_2, outline="", tags="card")
            cv.create_text(px + PORTRAIT / 2, py + PORTRAIT / 2, text=(c.class_name[:1] or "?"), fill=col,
                           font=self.f_name, tags="card")
        tx = 72
        if self.mode in ("nearby", "recent"):
            side = self._nearby_side.get(c.name)
            if side in ("enemy", "ally"):          # a slim marker on the left edge: red enemy, green ally
                round_rect(cv, 0, y + 10, 4, y + CARD_H - 10, 2, fill=RED if side == "enemy" else GREEN,
                           outline="", tags="card")
        fac_col = ELYOS if c.race == 1 else ASMO if c.race == 2 else FG_DIM
        pill_w = self.f_tiny.measure(c.faction) + 12
        # line 1 must stop before the CP number: the legion gives way first, then the name
        limit = x1 - 44 - self.f_cp.measure("000,000") - self.f_tiny.measure("CP") - 18
        room = limit - tx - pill_w - 8
        name_w = self.f_name.measure(c.name)
        legion = f"<{c.legion}>" if c.legion else ""
        if legion:
            legion = elide(self.f_body, legion, room - name_w - 6)
            if len(legion) < 3:
                legion = ""
        name = elide(self.f_name, c.name, room - (self.f_body.measure(legion) + 6 if legion else 0))
        name_id = cv.create_text(tx, y + 23, text=name, fill=FG, font=self.f_name, anchor="w", tags="card")
        bx = cv.bbox(name_id)[2] + 8
        if legion:
            leg_id = cv.create_text(bx - 2, y + 24, text=legion, fill=LEGION, font=self.f_body, anchor="w",
                                    tags="card")
            bx = cv.bbox(leg_id)[2] + 8
        round_rect(cv, bx, y + 15, bx + pill_w, y + 31, 8, fill=SURFACE_2, outline=fac_col, tags="card")
        cv.create_text(bx + pill_w / 2, y + 23, text=c.faction, fill=fac_col, font=self.f_tiny, tags="card")
        cls_col = CLASS_COLORS.get(c.class_name, FG_DIM)
        cid = cv.create_text(tx, y + 49, text=c.class_name or "Unknown", fill=cls_col, font=self.f_small,
                             anchor="w", tags="card")
        region = REGION_LABELS.get(c.region, c.region.upper())
        where = (f"{c.server_name} ({region})" if region else c.server_name) if c.server_name else ""
        rest = (f"  ·  Lv {c.level}" if c.level else "") + (f"  ·  {where}" if where else "")
        if self.mode in ("nearby", "recent") and self.nearby_view == "recent":
            left_at, fought = getattr(self, "_recent_info", {}).get(c.name, (None, False))
            if left_at:
                rest += f"  ·  {'⚔ ' if fought else ''}{ago(time.time() - left_at)}"
        rx2 = cv.bbox(cid)[2]
        rest = elide(self.f_small, rest, x1 - 44 - self.f_small.measure("GS 0,000") - 12 - rx2)
        cv.create_text(rx2, y + 49, text=rest, fill=FG_DIM, font=self.f_small, anchor="w", tags="card")

        # favorite star (top right)
        fav = c.key in self.favorites
        sx0, sy0, sx1, sy1 = self._star_box(width, y)
        star_hover = hover and self.hover_star
        cv.create_text((sx0 + sx1) / 2, (sy0 + sy1) / 2, text="★" if fav else "☆",
                       fill=ACCENT if fav or star_hover else FG_FAINT, font=self.f_star, tags="card")

        rx = x1 - 44
        if c.status == "ok":
            cv.create_text(rx, y + 22, text=fmt_int(c.combat_power), fill=ACCENT, font=self.f_cp, anchor="e",
                           tags="card")
            cv.create_text(rx - self.f_cp.measure(fmt_int(c.combat_power)) - 6, y + 24, text="CP", fill=FG_FAINT,
                           font=self.f_tiny, anchor="e", tags="card")
            cv.create_text(rx, y + 49, text=f"GS {fmt_int(c.gear_score)}", fill=FG, font=self.f_small, anchor="e",
                           tags="card")
            return False
        if c.status == "unresolved":                 # a nearby player NCSOFT couldn't identify: no numbers
            cv.create_text(rx, y + 22, text="—", fill=FG_FAINT, font=self.f_cp, anchor="e", tags="card")
            return False
        if c.status == "error":
            cv.create_text(rx, y + 22, text="Couldn't load", fill=RED, font=self.f_small, anchor="e", tags="card")
            return False
        round_rect(cv, rx - 80, y + 14, rx, y + 31, 6, fill=a, outline="", tags="card")
        round_rect(cv, rx - 54, y + 42, rx, y + 55, 6, fill=b, outline="", tags="card")
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

    def _motion(self, e):
        self._set_hover(*self._hit(e.x, e.y))

    def _set_hover(self, i, on_star):
        if i != self.hover_index or on_star != self.hover_star:
            self.hover_index, self.hover_star = i, on_star
            self.canvas.config(cursor="hand2" if i >= 0 else "")
            self._mark()

    def _click(self, e):
        i, on_star = self._hit(e.x, e.y)
        if i < 0:
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
        label = "Clear Recent" if which == "recent" else "Clear Nearby (move everyone to Recent)"
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
        return "Clear Nearby (move everyone to Recent)" if self._nearby_rows else None

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
            self._mark()

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
        gap = (2, 0) if self.mode == "search" else (10, 0)     # no search box above: give the filters room
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
        self.top.pack(fill="x", padx=PAD, pady=(6, 4))
        self.status_row.pack(fill="x", pady=(4, 4))
        self.list_wrap.pack(fill="both", expand=True, padx=(PAD, 4), pady=(0, PAD))
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
        for w in getattr(self, "_edges", []):
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

    def _resize_start(self, e):
        self._resize = (e.x_root, e.y_root, self.root.winfo_width(), self.root.winfo_height())

    def _resize_move(self, e):
        x0, y0, w0, h0 = self._resize
        w = max(460, w0 + e.x_root - x0)
        h = max(420, h0 + e.y_root - y0)
        self.root.geometry(f"{w}x{h}")
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
            (7200, lambda: self._view and self.toggle_favorite(self._view[0])),
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
