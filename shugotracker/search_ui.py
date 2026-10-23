"""Shugo Tracker search window: type a name, get every matching AION 2 character with gear score and combat power."""
from __future__ import annotations

import io
import queue
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
import webbrowser
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

import requests

from .aion2api import REGION_LABELS, SUB_REGIONS, USER_AGENT, Api, Character, rank

try:  # portraits are optional
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


def fmt_int(n: int | None) -> str:
    return "—" if n is None else f"{n:,}"


def round_rect(cv: tk.Canvas, x0, y0, x1, y1, r, **kw):
    r = max(0, min(r, (x1 - x0) / 2, (y1 - y0) / 2))
    pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1, x1 - r, y1,
           x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
    return cv.create_polygon(pts, smooth=True, **kw)


class PortraitLoader:
    """Downloads portraits off the UI thread; PhotoImages are made on the UI thread from the results."""

    def __init__(self, size: int):
        self.size = size
        self.enabled = Image is not None
        self._images: OrderedDict[str, object] = OrderedDict()
        self._pending: set[str] = set()
        self._results: queue.Queue = queue.Queue()
        self._pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="portrait")
        self._session = requests.Session()
        self._session.headers["User-Agent"] = USER_AGENT

    def get(self, url: str | None):
        if not url or not self.enabled:
            return None
        img = self._images.get(url)
        if img is not None:
            self._images.move_to_end(url)
            return img
        if url not in self._pending:
            self._pending.add(url)
            self._pool.submit(self._fetch, url)
        return None

    def _fetch(self, url: str):
        try:
            r = self._session.get(url, timeout=10)
            r.raise_for_status()
            im = Image.open(io.BytesIO(r.content)).convert("RGBA")
            w, h = im.size
            side = min(w, h)
            im = im.crop(((w - side) // 2, 0, (w + side) // 2, side)).resize((self.size, self.size), Image.LANCZOS)
            mask = Image.new("L", im.size, 0)
            ImageDraw.Draw(mask).rounded_rectangle((0, 0, self.size - 1, self.size - 1), radius=10, fill=255)
            im.putalpha(mask)
            self._results.put((url, im))
        except Exception:  # noqa: BLE001
            self._results.put((url, None))

    def drain(self) -> bool:
        """Turn finished downloads into PhotoImages; True if anything new arrived."""
        got = False
        while True:
            try:
                url, im = self._results.get_nowait()
            except queue.Empty:
                return got
            self._pending.discard(url)
            if im is None:
                self._images[url] = False  # remember failures; fall back to initials
            else:
                self._images[url] = ImageTk.PhotoImage(im)
            while len(self._images) > 300:
                self._images.popitem(last=False)
            got = True

    def close(self):
        self._pool.shutdown(wait=False, cancel_futures=True)


class SearchWindow:
    def __init__(self, api: Api, cfg: dict, on_close: Callable[[], None],
                 update_banner: Callable[[], str | None] = lambda: None,
                 on_update: Callable[[], bool] = lambda: False, version: str = "",
                 initial_query: str | None = None, screenshot: str | None = None):
        self.api = api
        self.cfg = cfg
        self.on_close_cb = on_close
        self.update_banner = update_banner
        self.on_update = on_update

        self.results: list[Character] = []
        self.keyword = ""
        self.generation = 0
        self.region_state: dict[str, dict] = {}   # region -> {page, total, loading, error}
        self.inbox: queue.Queue = queue.Queue()
        self.hover_index = -1
        self._dirty = True
        self._debounce = None
        self._banner_text = None

        self.root = tk.Tk()
        self.root.title("Shugo Tracker")
        self.root.configure(bg=BG)
        self.root.minsize(420, 360)
        w, h = cfg.get("window_size", [520, 720])
        x, y = cfg.get("window_pos", [80, 80])
        self.root.geometry(f"{int(w)}x{int(h)}+{int(x)}+{int(y)}")
        self.root.attributes("-topmost", bool(cfg.get("always_on_top", True)))
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self._dark_titlebar()

        fams = set(tkfont.families())
        base = "Segoe UI Variable Text" if "Segoe UI Variable Text" in fams else "Segoe UI"
        self.f_body = tkfont.Font(family=base, size=10)
        self.f_small = tkfont.Font(family=base, size=9)
        self.f_tiny = tkfont.Font(family=base, size=8)
        self.f_name = tkfont.Font(family=base, size=12, weight="bold")
        self.f_cp = tkfont.Font(family=base, size=14, weight="bold")
        self.f_input = tkfont.Font(family=base, size=12)
        self.f_title = tkfont.Font(family=base, size=11, weight="bold")

        self.portraits = PortraitLoader(PORTRAIT)
        self._build(version)
        self.root.after(30, self._tick)
        self.search_entry.focus_set()
        if initial_query:
            self.search_var.set(initial_query)
            self.root.after(300, lambda: self._start_search(now=True))
        if screenshot:
            # Two captures for checking the UI on a build machine: mid-load (skeletons) and settled.
            self.root.after(900, lambda: self._grab(screenshot.replace(".png", "-loading.png")))
            self.root.after(8000, lambda: self._grab(screenshot))
            self.root.after(8600, self.close)

    # ───── layout ─────
    def _build(self, version: str):
        top = tk.Frame(self.root, bg=BG)
        top.pack(fill="x", padx=PAD, pady=(PAD, 6))

        head = tk.Frame(top, bg=BG)
        head.pack(fill="x")
        tk.Label(head, text="Shugo Tracker", bg=BG, fg=FG, font=self.f_title).pack(side="left")
        tk.Label(head, text=f"v{version}", bg=BG, fg=FG_FAINT, font=self.f_tiny).pack(side="left", padx=(6, 0), pady=(3, 0))
        self.pin = tk.Label(head, bg=BG, font=self.f_small, cursor="hand2", padx=4)
        self.pin.pack(side="right")
        self.pin.bind("<Button-1>", lambda e: self._toggle_pin())
        self._paint_pin()

        self.banner = tk.Label(self.root, text="", bg="#203a2a", fg="#bff0cf", font=self.f_small,
                               anchor="w", padx=PAD, pady=5, cursor="hand2")
        self.banner.bind("<Button-1>", lambda e: self._update_now())

        # search box
        box = tk.Frame(top, bg=SURFACE_2, highlightthickness=1, highlightbackground=BORDER,
                       highlightcolor=ACCENT)
        box.pack(fill="x", pady=(10, 8))
        tk.Label(box, text="⌕", bg=SURFACE_2, fg=FG_DIM, font=self.f_input).pack(side="left", padx=(10, 2))
        self.search_var = tk.StringVar()
        self.search_entry = tk.Entry(box, textvariable=self.search_var, bg=SURFACE_2, fg=FG, insertbackground=FG,
                                     relief="flat", font=self.f_input, highlightthickness=0)
        self.search_entry.pack(side="left", fill="x", expand=True, ipady=8, padx=(2, 4))
        self.search_entry.bind("<Return>", lambda e: self._start_search(now=True))
        self.search_entry.bind("<Escape>", lambda e: self.search_var.set(""))
        self.search_var.trace_add("write", lambda *a: self._on_type())
        self.placeholder = tk.Label(box, text="Search character name…", bg=SURFACE_2, fg=FG_FAINT, font=self.f_input)
        self.placeholder.place(x=36, rely=0.5, anchor="w")
        self.placeholder.bind("<Button-1>", lambda e: self.search_entry.focus_set())
        go = tk.Label(box, text="Search", bg=ACCENT, fg=ACCENT_FG, font=self.f_body, padx=14, pady=6, cursor="hand2")
        go.pack(side="right", padx=4, pady=4)
        go.bind("<Button-1>", lambda e: self._start_search(now=True))

        # filters
        self.region = self.cfg.get("region", "all")
        self.faction = self.cfg.get("faction", "all")
        self.max_level_only = bool(self.cfg.get("max_level_only", False))
        filt = tk.Frame(top, bg=BG)
        filt.pack(fill="x")
        self.region_chips = self._chips(filt, [("all", "All regions")] + [(r, REGION_LABELS[r]) for r in SUB_REGIONS],
                                        lambda: self.region, self._set_region)
        filt2 = tk.Frame(top, bg=BG)
        filt2.pack(fill="x", pady=(6, 0))
        self.faction_chips = self._chips(filt2, [("all", "Both factions"), ("1", "Elyos"), ("2", "Asmodian")],
                                         lambda: self.faction, self._set_faction)
        self.lvl_chip = tk.Label(filt2, font=self.f_small, padx=10, pady=3, cursor="hand2")
        self.lvl_chip.pack(side="left", padx=(8, 0))
        self.lvl_chip.bind("<Button-1>", lambda e: self._toggle_level())
        self._paint_chips()

        self.status = tk.Label(self.root, text="Type a character name and press Enter.", bg=BG, fg=FG_DIM,
                               font=self.f_small, anchor="w", padx=PAD)
        self.status.pack(fill="x", pady=(2, 4))

        # virtualized result list
        wrap = tk.Frame(self.root, bg=BG)
        wrap.pack(fill="both", expand=True, padx=(PAD, 4), pady=(0, PAD))
        self.canvas = tk.Canvas(wrap, bg=BG, highlightthickness=0, bd=0, yscrollincrement=16)
        self.scroll = tk.Scrollbar(wrap, orient="vertical", command=self._yview, width=10)
        self.scroll.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.configure(yscrollcommand=self.scroll.set)
        self.canvas.bind("<Configure>", lambda e: self._mark())
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.canvas.bind("<Button-4>", lambda e: self._scroll_units(-3))
        self.canvas.bind("<Button-5>", lambda e: self._scroll_units(3))
        self.canvas.bind("<Motion>", self._motion)
        self.canvas.bind("<Leave>", lambda e: self._set_hover(-1))
        self.canvas.bind("<Button-1>", self._click)
        self.canvas.bind("<Button-3>", self._right_click)

        self.menu = tk.Menu(self.root, tearoff=0, bg=SURFACE_2, fg=FG, activebackground=HOVER,
                            activeforeground=FG, bd=0)
        self.menu.add_command(label="Open on Shugo.GG", command=lambda: self._menu(lambda c: webbrowser.open(c.shugo_url)))
        self.menu.add_command(label="Copy name", command=lambda: self._menu(self._copy_name))
        self.menu.add_command(label="Refresh details", command=lambda: self._menu(self._refresh))
        self._menu_char: Character | None = None

    def _chips(self, parent, items, get, set_):
        chips = []
        for key, label in items:
            lb = tk.Label(parent, text=label, font=self.f_small, padx=10, pady=3, cursor="hand2")
            lb.pack(side="left", padx=(0, 6))
            lb.bind("<Button-1>", lambda e, k=key: set_(k))
            chips.append((key, lb, get))
        return chips

    def _paint_chips(self):
        for key, lb, get in self.region_chips + self.faction_chips:
            on = key == get()
            lb.config(bg=ACCENT if on else SURFACE, fg=ACCENT_FG if on else FG_DIM)
        on = self.max_level_only
        self.lvl_chip.config(text="Max level only", bg=ACCENT if on else SURFACE, fg=ACCENT_FG if on else FG_DIM)

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

    # ───── filters / search ─────
    def _set_region(self, k):
        self.region = self.cfg["region"] = k
        self._paint_chips()
        if self.keyword:
            self._start_search(now=True)

    def _set_faction(self, k):
        self.faction = self.cfg["faction"] = k
        self._paint_chips()
        self.canvas.yview_moveto(0)
        self._mark()

    def _toggle_level(self):
        self.max_level_only = self.cfg["max_level_only"] = not self.max_level_only
        self._paint_chips()
        self.canvas.yview_moveto(0)
        self._mark()

    def _toggle_pin(self):
        on = not bool(self.root.attributes("-topmost"))
        self.root.attributes("-topmost", on)
        self.cfg["always_on_top"] = on
        self._paint_pin()

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
        if not kw:
            return
        if kw == self.keyword and not now:
            return
        self.keyword = kw
        self.generation += 1
        self.api.new_generation()
        self.results = []
        regions = SUB_REGIONS if self.region == "all" else [self.region]
        self.region_state = {r: {"page": 0, "total": None, "loading": True, "error": None} for r in regions}
        self.canvas.yview_moveto(0)
        self._fetch_pages(regions)
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
        if not self.keyword or last_visible < visible_count - 8:
            return
        more = [r for r, st in self.region_state.items()
                if not st["loading"] and st["error"] is None and st["total"] is not None
                and st["page"] * PAGE_SIZE < st["total"]]
        if more:
            self._fetch_pages(more)

    # ───── data in ─────
    def _drain(self):
        changed = False
        while True:
            try:
                msg = self.inbox.get_nowait()
            except queue.Empty:
                break
            if msg[0] == "search":
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
            elif msg[0] == "detail":
                changed = True
        if self.portraits.drain():
            changed = True
        if changed:
            self._mark()

    # ───── rendering ─────
    def _visible(self) -> list[Character]:
        out = self.results
        if self.faction != "all":
            out = [c for c in out if str(c.race) == self.faction]
        if self.max_level_only:
            top = max((c.level for c in self.results), default=0)
            out = [c for c in out if c.level >= max(top, 45)]
        return out

    def _mark(self):
        self._dirty = True

    def _tick(self):
        self._drain()
        self._sync_banner()
        now = time.monotonic()
        if self._dirty:
            self._render()
            self._last_frame = now
        elif self._has_skeletons and now - self._last_frame > 0.12:
            self._render(shimmer_only=True)  # animate placeholder shimmer
            self._last_frame = now
        self.root.after(30, self._tick)

    _last_frame = 0.0

    _has_skeletons = False
    _view: list[Character] = []

    def _render(self, shimmer_only: bool = False) -> bool:
        cv = self.canvas
        if not shimmer_only:
            self._dirty = False
            self._view = self._visible()
        view = self._view
        width = max(cv.winfo_width(), 200)
        view_h = max(cv.winfo_height(), 1)
        loading_any = any(st["loading"] for st in self.region_state.values())
        extra = 3 if loading_any else 0                     # skeleton cards while a page loads
        n = len(view) + extra
        total_h = max(n * (CARD_H + CARD_GAP), view_h)
        cv.configure(scrollregion=(0, 0, width, total_h))
        top = cv.canvasy(0)
        first = max(0, int(top // (CARD_H + CARD_GAP)) - 1)
        last = min(n - 1, int((top + view_h) // (CARD_H + CARD_GAP)) + 1)

        cv.delete("card")
        phase = (time.monotonic() * 1.6) % 2.0
        skel = SKEL_B if phase < 1.0 else SKEL_A
        skel2 = SKEL_A if phase < 1.0 else SKEL_B
        has_skel = False
        for i in range(first, last + 1):
            y = i * (CARD_H + CARD_GAP)
            if i >= len(view):
                self._draw_skeleton(cv, y, width, skel, skel2)
                has_skel = True
                continue
            c = view[i]
            if c.status in ("none",):
                self.api.want(c, lambda ch, g=self.generation: self.inbox.put(("detail", g)))
            has_skel |= self._draw_card(cv, c, y, width, i == self.hover_index, skel, skel2)
        if not view and not loading_any:
            self._draw_empty(cv, width)
        self._update_status(view)
        if not shimmer_only:
            self._load_more_if_needed(last, len(view))
        self._has_skeletons = has_skel
        return has_skel

    def _draw_empty(self, cv, width):
        if not self.keyword:
            msg, sub = "Find any AION 2 character", "Search every Global region at once. Results link to Shugo.GG."
        elif any(st["error"] for st in self.region_state.values()):
            msg, sub = "Search failed", "Check your connection and try again."
        else:
            msg, sub = f"No characters match “{self.keyword}”", "Try a different spelling or region."
        cv.create_text(width / 2, 70, text=msg, fill=FG, font=self.f_name, tags="card")
        cv.create_text(width / 2, 96, text=sub, fill=FG_DIM, font=self.f_small, tags="card")

    def _draw_skeleton(self, cv, y, width, a, b):
        x0, x1 = 0, width - 6
        round_rect(cv, x0, y, x1, y + CARD_H, 12, fill=SURFACE, outline="", tags="card")
        round_rect(cv, 12, y + 12, 12 + PORTRAIT, y + 12 + PORTRAIT, 10, fill=a, outline="", tags="card")
        round_rect(cv, 72, y + 16, 72 + 130, y + 30, 6, fill=a, outline="", tags="card")
        round_rect(cv, 72, y + 42, 72 + 190, y + 54, 6, fill=b, outline="", tags="card")
        round_rect(cv, x1 - 96, y + 16, x1 - 14, y + 32, 6, fill=a, outline="", tags="card")
        round_rect(cv, x1 - 70, y + 42, x1 - 14, y + 54, 6, fill=b, outline="", tags="card")

    def _draw_card(self, cv, c: Character, y, width, hover: bool, a, b) -> bool:
        x0, x1 = 0, width - 6
        round_rect(cv, x0, y, x1, y + CARD_H, 12, fill=HOVER if hover else SURFACE,
                   outline=BORDER if hover else "", tags="card")
        # portrait / initials
        px, py = 12, y + 12
        img = self.portraits.get(c.portrait)
        if img:
            cv.create_image(px, py, image=img, anchor="nw", tags="card")
        else:
            col = CLASS_COLORS.get(c.class_name, FG_DIM)
            round_rect(cv, px, py, px + PORTRAIT, py + PORTRAIT, 10, fill=SURFACE_2, outline="", tags="card")
            cv.create_text(px + PORTRAIT / 2, py + PORTRAIT / 2, text=(c.class_name[:1] or "?"), fill=col,
                           font=self.f_name, tags="card")
        # name + faction pill
        tx = 72
        name_id = cv.create_text(tx, y + 23, text=c.name, fill=FG, font=self.f_name, anchor="w", tags="card")
        bx = cv.bbox(name_id)[2] + 8
        fac_col = ELYOS if c.race == 1 else ASMO if c.race == 2 else FG_DIM
        pill_w = self.f_tiny.measure(c.faction) + 12
        round_rect(cv, bx, y + 15, bx + pill_w, y + 31, 8, fill=SURFACE_2, outline=fac_col, tags="card")
        cv.create_text(bx + pill_w / 2, y + 23, text=c.faction, fill=fac_col, font=self.f_tiny, tags="card")
        # class · level · server
        cls_col = CLASS_COLORS.get(c.class_name, FG_DIM)
        cid = cv.create_text(tx, y + 49, text=c.class_name or "Unknown", fill=cls_col, font=self.f_small,
                             anchor="w", tags="card")
        rest = f"  ·  Lv {c.level}  ·  {c.server_name} ({REGION_LABELS.get(c.region, c.region.upper())})"
        cv.create_text(cv.bbox(cid)[2], y + 49, text=rest, fill=FG_DIM, font=self.f_small, anchor="w", tags="card")
        # stats
        rx = x1 - 14
        if c.status == "ok":
            cv.create_text(rx, y + 22, text=fmt_int(c.combat_power), fill=ACCENT, font=self.f_cp, anchor="e", tags="card")
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
        round_rect(cv, rx - 82, y + 14, rx, y + 31, 6, fill=a, outline="", tags="card")
        round_rect(cv, rx - 56, y + 42, rx, y + 55, 6, fill=b, outline="", tags="card")
        return True

    def _update_status(self, view):
        if not self.keyword:
            return
        totals = {r: st["total"] for r, st in self.region_state.items() if st["total"] is not None}
        errors = [REGION_LABELS[r] for r, st in self.region_state.items() if st["error"]]
        loading = any(st["loading"] for st in self.region_state.values())
        grand = sum(totals.values())
        parts = [f"{len(view):,} shown" + (f" of {grand:,} matches" if grand else "")]
        if loading:
            parts.append("searching…")
        if errors:
            parts.append("failed: " + ", ".join(errors))
        self.status.config(text="  ·  ".join(parts), fg=RED if errors and not grand else FG_DIM)

    # ───── interaction ─────
    def _index_at(self, y_widget: int) -> int:
        y = self.canvas.canvasy(y_widget)
        i = int(y // (CARD_H + CARD_GAP))
        if y - i * (CARD_H + CARD_GAP) > CARD_H or i < 0 or i >= len(self._view):
            return -1
        return i

    def _motion(self, e):
        self._set_hover(self._index_at(e.y))

    def _set_hover(self, i):
        if i != self.hover_index:
            self.hover_index = i
            self.canvas.config(cursor="hand2" if i >= 0 else "")
            self._mark()

    def _click(self, e):
        i = self._index_at(e.y)
        if i >= 0:
            webbrowser.open(self._view[i].shugo_url)

    def _right_click(self, e):
        i = self._index_at(e.y)
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

    def _yview(self, *args):
        self.canvas.yview(*args)
        self._mark()

    def _scroll_units(self, n):
        self.canvas.yview_scroll(n, "units")
        self._mark()

    def _wheel(self, e):
        self._scroll_units(int(-e.delta / 40) or (-1 if e.delta > 0 else 1))

    # ───── update banner ─────
    def _sync_banner(self):
        text = self.update_banner()
        if text == self._banner_text:
            return
        self._banner_text = text
        if text:
            self.banner.config(text=text)
            self.banner.pack(fill="x", before=self.status)
        else:
            self.banner.pack_forget()

    def _update_now(self):
        if self._banner_text and "restart" in self._banner_text:
            self._save_geometry()
            if self.on_update():
                self.portraits.close()
                self.root.destroy()

    def _grab(self, path: str):
        try:
            from PIL import ImageGrab
            self.root.update()
            x, y = self.root.winfo_rootx(), self.root.winfo_rooty()
            ImageGrab.grab(bbox=(x, y, x + self.root.winfo_width(), y + self.root.winfo_height())).save(path)
        except Exception as e:  # noqa: BLE001
            print(f"screenshot failed: {e}")

    # ───── lifecycle ─────
    def _save_geometry(self):
        try:
            self.cfg["window_size"] = [self.root.winfo_width(), self.root.winfo_height()]
            self.cfg["window_pos"] = [self.root.winfo_x(), self.root.winfo_y()]
        except tk.TclError:
            pass

    def close(self):
        self._save_geometry()
        self.portraits.close()
        self.on_close_cb()
        self.root.destroy()

    def run(self):
        self.root.mainloop()
