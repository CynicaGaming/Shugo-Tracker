"""Shugo Tracker main window: character search, favorites, and full character profiles."""
from __future__ import annotations

import io
import queue
import time
import tkinter as tk
import tkinter.font as tkfont
import webbrowser
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

import requests

from .aion2api import REGION_LABELS, SUB_REGIONS, USER_AGENT, Api, Character, rank
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
LEGION = "#9fd0a8"
SKEL_A = "#22262f"
SKEL_B = "#2c313c"

CARD_H = 72
CARD_GAP = 8
PAD = 14
PORTRAIT = 48
PAGE_SIZE = 30

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


def round_rect(cv: tk.Canvas, x0, y0, x1, y1, r, **kw):
    r = max(0, min(r, (x1 - x0) / 2, (y1 - y0) / 2))
    pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1, x1 - r, y1,
           x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
    return cv.create_polygon(pts, smooth=True, **kw)


class ImageLoader:
    """Downloads images off the UI thread; PhotoImages are created on the UI thread."""

    def __init__(self):
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

    def _fetch(self, key):
        url, size, radius, crop_top = key
        try:
            data = self._bytes.get(url)
            if data is None:
                r = self._session.get(url, timeout=10)
                r.raise_for_status()
                data = r.content
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
                 update_banner: Callable[[], str | None] = lambda: None,
                 on_update: Callable[[], bool] = lambda: False, version: str = "",
                 initial_query: str | None = None, screenshot: str | None = None):
        self.api = api
        self.cfg = cfg
        self.on_close_cb = on_close
        self.update_banner = update_banner
        self.on_update = on_update
        self.favorites = favorites or Favorites(None)

        self.mode = "search"          # search | favorites
        self.results: list[Character] = []
        self.fav_chars: list[Character] = []
        self.keyword = ""
        self.generation = 0
        self.region_state: dict[str, dict] = {}
        self.regions: set[str] = {r for r in cfg.get("regions", []) if r in SUB_REGIONS}
        self.factions: set[str] = {f for f in cfg.get("factions", []) if f in ("1", "2")}
        self.inbox: queue.Queue = queue.Queue()
        self.hover_index = -1
        self.hover_star = False
        self._dirty = True
        self._debounce = None
        self._banner_text = None
        self._view: list[Character] = []
        self._has_skeletons = False
        self._last_frame = 0.0
        self.profile_view: ProfileView | None = None

        self.root = tk.Tk()
        self.root.title("Shugo Tracker")
        self.root.configure(bg=BG)
        self.root.minsize(460, 420)
        w, h = cfg.get("window_size", [560, 760])
        x, y = cfg.get("window_pos", [80, 80])
        self.root.geometry(f"{int(w)}x{int(h)}+{int(x)}+{int(y)}")
        self.root.attributes("-topmost", bool(cfg.get("always_on_top", True)))
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self._dark_titlebar()

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

        self.images = ImageLoader()
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
        self.top = tk.Frame(self.root, bg=BG)
        self.top.pack(fill="x", padx=PAD, pady=(PAD, 4))

        head = tk.Frame(self.top, bg=BG)
        head.pack(fill="x")
        tk.Label(head, text="Shugo Tracker", bg=BG, fg=FG, font=self.f_title).pack(side="left")
        tk.Label(head, text=f"v{version}", bg=BG, fg=FG_FAINT, font=self.f_tiny).pack(side="left", padx=(6, 0), pady=(3, 0))
        self.pin = tk.Label(head, bg=BG, font=self.f_small, cursor="hand2", padx=4)
        self.pin.pack(side="right")
        self.pin.bind("<Button-1>", lambda e: self._toggle_pin())
        self._paint_pin()

        # Search / Favorites tabs
        tabs = tk.Frame(self.top, bg=BG)
        tabs.pack(fill="x", pady=(10, 0))
        self.tab_search = tk.Label(tabs, text="Search", font=self.f_bold, padx=2, pady=4, cursor="hand2", bg=BG)
        self.tab_search.pack(side="left")
        self.tab_fav = tk.Label(tabs, font=self.f_bold, padx=2, pady=4, cursor="hand2", bg=BG)
        self.tab_fav.pack(side="left", padx=(18, 0))
        self.tab_search.bind("<Button-1>", lambda e: self._set_mode("search"))
        self.tab_fav.bind("<Button-1>", lambda e: self._set_mode("favorites"))
        self.tab_line = tk.Frame(self.top, bg=BORDER, height=1)
        self.tab_line.pack(fill="x")

        self.banner = tk.Label(self.root, text="", bg="#203a2a", fg="#bff0cf", font=self.f_small,
                               anchor="w", padx=PAD, pady=5, cursor="hand2")
        self.banner.bind("<Button-1>", lambda e: self._update_now())

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
        self.placeholder = tk.Label(self.box, text="Search character name…", bg=SURFACE_2, fg=FG_FAINT,
                                    font=self.f_input)
        self.placeholder.place(x=36, rely=0.5, anchor="w")
        self.placeholder.bind("<Button-1>", lambda e: self.search_entry.focus_set())
        go = tk.Label(self.box, text="Search", bg=ACCENT, fg=ACCENT_FG, font=self.f_body, padx=14, pady=6,
                      cursor="hand2")
        go.pack(side="right", padx=4, pady=4)
        go.bind("<Button-1>", lambda e: self._start_search(now=True))

        # filter chips: toggles; nothing selected means "all"
        self.filters = tk.Frame(self.top, bg=BG)
        self.filters.pack(fill="x", pady=(2, 0))
        row1 = tk.Frame(self.filters, bg=BG)
        row1.pack(fill="x")
        self.region_chips = [(r, self._chip(row1, REGION_LABELS[r], lambda k=r: self._toggle_region(k)))
                             for r in SUB_REGIONS]
        row2 = tk.Frame(self.filters, bg=BG)
        row2.pack(fill="x", pady=(6, 0))
        self.faction_chips = [(f, self._chip(row2, label, lambda k=f: self._toggle_faction(k)))
                              for f, label in FACTIONS]
        self.clear_chip = tk.Label(row2, text="Clear filters", bg=BG, fg=FG_FAINT, font=self.f_small,
                                   cursor="hand2", padx=6)
        self.clear_chip.bind("<Button-1>", lambda e: self._clear_filters())
        self._paint_chips()
        self._paint_tabs()

        self.status = tk.Label(self.root, text="Type a character name and press Enter.", bg=BG, fg=FG_DIM,
                               font=self.f_small, anchor="w", padx=PAD)
        self.status.pack(fill="x", pady=(4, 4))

        # virtualized card list
        self.list_wrap = tk.Frame(self.root, bg=BG)
        self.list_wrap.pack(fill="both", expand=True, padx=(PAD, 4), pady=(0, PAD))
        self.canvas = tk.Canvas(self.list_wrap, bg=BG, highlightthickness=0, bd=0, yscrollincrement=16)
        self.scroll = tk.Scrollbar(self.list_wrap, orient="vertical", command=self._yview, width=10)
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

        self.menu = tk.Menu(self.root, tearoff=0, bg=SURFACE_2, fg=FG, activebackground=HOVER,
                            activeforeground=FG, bd=0)
        self.menu.add_command(label="View profile", command=lambda: self._menu(self.open_profile))
        self.menu.add_command(label="Add / remove favorite", command=lambda: self._menu(self.toggle_favorite))
        self.menu.add_command(label="Open on Shugo.GG", command=lambda: self._menu(lambda c: webbrowser.open(c.shugo_url)))
        self.menu.add_command(label="Copy name", command=lambda: self._menu(self._copy_name))
        self.menu.add_command(label="Refresh", command=lambda: self._menu(self._refresh))
        self._menu_char: Character | None = None

    def _chip(self, parent, text, cmd):
        lb = tk.Label(parent, text=text, font=self.f_small, padx=10, pady=3, cursor="hand2")
        lb.pack(side="left", padx=(0, 6))
        lb.bind("<Button-1>", lambda e: cmd())
        return lb

    def _paint_chips(self):
        for key, lb in self.region_chips:
            on = key in self.regions
            lb.config(bg=ACCENT if on else SURFACE, fg=ACCENT_FG if on else FG_DIM)
        for key, lb in self.faction_chips:
            on = key in self.factions
            col = ELYOS if key == "1" else ASMO
            lb.config(bg=col if on else SURFACE, fg=BG if on else FG_DIM)
        if self.regions or self.factions:
            self.clear_chip.pack(side="right")
        else:
            self.clear_chip.pack_forget()

    def _paint_tabs(self):
        n = len(self.favorites)
        self.tab_fav.config(text=f"★ Favorites{f'  {n}' if n else ''}")
        for tab, mode in ((self.tab_search, "search"), (self.tab_fav, "favorites")):
            tab.config(fg=ACCENT if self.mode == mode else FG_DIM)

    def _paint_pin(self):
        on = bool(self.root.attributes("-topmost"))
        self.pin.config(text="📌 On top" if on else "📌 Pin on top", fg=ACCENT if on else FG_FAINT)

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
        if mode == "favorites":
            self.box.pack_forget()
            self.fav_chars = self.favorites.characters()
        else:
            self.box.pack(fill="x", pady=(10, 8), before=self.filters)
            self.search_entry.focus_set()
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

    def _clear_filters(self):
        self.regions.clear()
        self.factions.clear()
        self.cfg["regions"], self.cfg["factions"] = [], []
        self._filters_changed()

    def _filters_changed(self):
        self._paint_chips()
        self.canvas.yview_moveto(0)
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
            self._debounce = self.root.after(500, lambda: self._start_search(now=False))

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
        self.keyword = kw
        self.generation += 1
        self.api.new_generation()
        self.results = []
        # Always search every region: the region chips filter instantly without a new search.
        self.region_state = {r: {"page": 0, "total": None, "loading": True, "error": None} for r in SUB_REGIONS}
        self.canvas.yview_moveto(0)
        self._fetch_pages(SUB_REGIONS)
        self._mark()

    def _fetch_pages(self, regions):
        gen, kw = self.generation, self.keyword
        for r in regions:
            st = self.region_state[r]
            st["loading"] = True
            page = st["page"] + 1
            self.api.search(kw, [r], page=page, size=PAGE_SIZE,
                            on_done=lambda region, chars, total, err, g=gen, p=page:
                            self.inbox.put(("search", g, region, p, chars, total, err)))

    def _load_more_if_needed(self, last_visible: int, visible_count: int):
        if self.mode != "search" or not self.keyword or last_visible < visible_count - 8:
            return
        wanted = self.regions or set(SUB_REGIONS)
        more = [r for r, st in self.region_state.items()
                if r in wanted and not st["loading"] and st["error"] is None and st["total"] is not None
                and st["page"] * PAGE_SIZE < st["total"]]
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
        return self.fav_chars if self.mode == "favorites" else self.results

    def _visible(self) -> list[Character]:
        out = self._source()
        if self.regions:
            out = [c for c in out if c.region in self.regions]
        if self.factions:
            out = [c for c in out if str(c.race) in self.factions]
        return out

    def _mark(self):
        self._dirty = True

    def _tick(self):
        try:
            self._drain()
            self._sync_banner()
            now = time.monotonic()
            if self.profile_view is None:
                if self._dirty:
                    self._render()
                    self._last_frame = now
                elif self._has_skeletons and now - self._last_frame > 0.12:
                    self._render(shimmer_only=True)
                    self._last_frame = now
            elif self.profile_view.loading and now - self._last_frame > 0.12:
                self.profile_view.shimmer()
                self._last_frame = now
        finally:
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
            if c.status == "none":
                self.api.want(c, lambda ch: self.inbox.put(("detail",)))
            has_skel |= self._draw_card(cv, c, y, width, i == self.hover_index, a, b)
        if not view and not loading_any:
            self._draw_empty(cv, width)
        self._update_status(view)
        if not shimmer_only:
            self._load_more_if_needed(last, len(view))
        self._has_skeletons = has_skel
        return has_skel

    def _draw_empty(self, cv, width):
        if self.mode == "favorites":
            if len(self.favorites):
                msg, sub = "No favorites match these filters", "Clear the filters to see them all."
            else:
                msg, sub = "No favorites yet", "Click ☆ on any search result to keep it here."
        elif not self.keyword:
            msg, sub = "Find any AION 2 character", "Search every Global region at once."
        elif any(st["error"] for st in self.region_state.values()):
            msg, sub = "Search failed", "Check your connection and try again."
        elif self.results:
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
        name_id = cv.create_text(tx, y + 23, text=c.name, fill=FG, font=self.f_name, anchor="w", tags="card")
        bx = cv.bbox(name_id)[2] + 8
        if c.legion:
            leg_id = cv.create_text(bx - 2, y + 24, text=f"<{c.legion}>", fill=LEGION, font=self.f_body, anchor="w",
                                    tags="card")
            bx = cv.bbox(leg_id)[2] + 8
        fac_col = ELYOS if c.race == 1 else ASMO if c.race == 2 else FG_DIM
        pill_w = self.f_tiny.measure(c.faction) + 12
        round_rect(cv, bx, y + 15, bx + pill_w, y + 31, 8, fill=SURFACE_2, outline=fac_col, tags="card")
        cv.create_text(bx + pill_w / 2, y + 23, text=c.faction, fill=fac_col, font=self.f_tiny, tags="card")
        cls_col = CLASS_COLORS.get(c.class_name, FG_DIM)
        cid = cv.create_text(tx, y + 49, text=c.class_name or "Unknown", fill=cls_col, font=self.f_small,
                             anchor="w", tags="card")
        rest = f"  ·  Lv {c.level}  ·  {c.server_name} ({REGION_LABELS.get(c.region, c.region.upper())})"
        cv.create_text(cv.bbox(cid)[2], y + 49, text=rest, fill=FG_DIM, font=self.f_small, anchor="w", tags="card")

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
        if c.status == "error":
            cv.create_text(rx, y + 22, text="couldn't load", fill=RED, font=self.f_small, anchor="e", tags="card")
            cv.create_text(rx, y + 49, text="right-click → refresh", fill=FG_FAINT, font=self.f_tiny, anchor="e",
                           tags="card")
            return False
        round_rect(cv, rx - 80, y + 14, rx, y + 31, 6, fill=a, outline="", tags="card")
        round_rect(cv, rx - 54, y + 42, rx, y + 55, 6, fill=b, outline="", tags="card")
        return True

    def _update_status(self, view):
        if self.mode == "favorites":
            n = len(self.fav_chars)
            self.status.config(text=f"{len(view):,} of {n:,} favorites" if n else "", fg=FG_DIM)
            return
        if not self.keyword:
            self.status.config(text="Type a character name and press Enter.", fg=FG_DIM)
            return
        wanted = self.regions or set(SUB_REGIONS)
        totals = {r: st["total"] for r, st in self.region_state.items() if r in wanted and st["total"] is not None}
        errors = [REGION_LABELS[r] for r, st in self.region_state.items() if r in wanted and st["error"]]
        loading = any(st["loading"] for r, st in self.region_state.items() if r in wanted)
        grand = sum(totals.values())
        parts = [f"{len(view):,} shown" + (f" of {grand:,} matches" if grand else "")]
        if loading:
            parts.append("searching…")
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
        if on_star:
            self.toggle_favorite(c)
        else:
            self.open_profile(c)

    def _right_click(self, e):
        i, _ = self._hit(e.x, e.y)
        if i >= 0:
            self._menu_char = self._view[i]
            self.menu.tk_popup(e.x_root, e.y_root)

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
        self.status.pack_forget()
        self.list_wrap.pack_forget()
        self.profile_view = ProfileView(self, c)
        self.profile_view.frame.pack(fill="both", expand=True)
        self.api.fetch_profile(c, lambda ch, prof, err: self.inbox.put(("profile", ch, prof, err)))

    def close_profile(self):
        if not self.profile_view:
            return
        self.profile_view.destroy()
        self.profile_view = None
        self.top.pack(fill="x", padx=PAD, pady=(PAD, 4))
        self.status.pack(fill="x", pady=(4, 4))
        self.list_wrap.pack(fill="both", expand=True, padx=(PAD, 4), pady=(0, PAD))
        self._mark()

    # ═════ update banner ═════
    def _sync_banner(self):
        text = self.update_banner()
        if text == self._banner_text:
            return
        self._banner_text = text
        if text:
            self.banner.config(text=text)
            first = next((w for w in self.root.pack_slaves() if w is not self.banner), None)
            if first is not None:
                self.banner.pack(fill="x", side="top", before=first)
            else:
                self.banner.pack(fill="x", side="top")
        else:
            self.banner.pack_forget()

    def _update_now(self):
        if self._banner_text and "restart" in self._banner_text:
            self._save_geometry()
            if self.on_update():
                self.images.close()
                self.root.destroy()

    # ═════ screenshots (CI) ═════
    def _schedule_screenshots(self, path: str):
        base = path[:-4] if path.endswith(".png") else path
        steps = [
            (900, lambda: self._grab(f"{base}-loading.png")),
            (7000, lambda: self._grab(f"{base}.png")),
            (7200, lambda: self._view and self.toggle_favorite(self._view[0])),
            (7400, lambda: self._view and self.open_profile(self._view[0])),
        ]
        t = 11000
        for tab in ProfileView.TABS:
            steps.append((t, lambda tb=tab: self.profile_view and self.profile_view.show_tab(tb)))
            steps.append((t + 900, lambda tb=tab: self._grab(f"{base}-profile-{tb.lower()}.png")))
            t += 1400
        steps += [
            (t, lambda: self._set_mode("favorites")),
            (t + 600, lambda: self._toggle_faction("2")),
            (t + 2500, lambda: self._grab(f"{base}-favorites.png")),
            (t + 3000, self.close),
        ]
        for delay, fn in steps:
            self.root.after(delay, fn)

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
        try:
            self.cfg["window_size"] = [self.root.winfo_width(), self.root.winfo_height()]
            self.cfg["window_pos"] = [self.root.winfo_x(), self.root.winfo_y()]
        except tk.TclError:
            pass

    def close(self):
        self._save_geometry()
        self.favorites.save()
        self.images.close()
        self.on_close_cb()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


# Imported late: profile_ui uses the theme constants above.
from .profile_ui import ProfileView  # noqa: E402
