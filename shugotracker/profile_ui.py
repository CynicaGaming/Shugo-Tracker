"""In-app character profile: identity, a stat strip, and tabs (gear table, skills, Daevanion, stats, …)."""
from __future__ import annotations

import time
from dataclasses import asdict
import tkinter as tk
from typing import TYPE_CHECKING

from .aion2api import Character
from .profile import GEAR_ACCESSORIES, GEAR_ARCANA, GEAR_MAIN, SKILL_CATEGORIES, Item, Profile, slot_name
from .search_ui import (ACCENT, ASMO, BG, BORDER, CLASS_COLORS, ELYOS, FG, FG_DIM, FG_FAINT, GRADE_COLORS, HOVER,
                        LINE, PAD, RED, REGION_NAMES, SURFACE, SURFACE_2, fmt_int, round_rect, ThinScrollbar)

if TYPE_CHECKING:
    from .search_ui import SearchWindow

ICON = 36
HERO = 44


class ProfileView:
    TABS = ["Gear", "Skills", "Daevanion", "Stats", "Cosmetics", "Titles"]

    def __init__(self, app: "SearchWindow", char: Character):
        self.app = app
        self.char = char
        self.profile: Profile | None = None
        self.error: str | None = None
        self.loading = True
        self.tab = app.cfg.get("profile_tab", "Gear")
        if self.tab not in self.TABS:
            self.tab = "Gear"
        self._img_slots: list[tuple[tk.Label, str, int, bool]] = []
        self._blanks: dict[int, tk.PhotoImage] = {}
        self._skel_items: list[tuple[tk.Canvas, int, int]] = []

        self.frame = tk.Frame(app.root, bg=BG)
        self._build_header()
        self._build_tabs()
        self._build_body()
        self.render()

    # ───── chrome ─────
    def _build_header(self):
        f = self.app
        top = tk.Frame(self.frame, bg=BG)
        top.pack(fill="x", padx=PAD, pady=(12, 10))
        self.portrait = tk.Label(top, bg=SURFACE, image=self._blank(HERO), bd=0)
        self.portrait.pack(side="left")
        # actions (right): favorite, refresh
        self.star = tk.Label(top, bg=BG, cursor="hand2", width=30, height=28)
        self.star.pack(side="right", anchor="n")
        self.star.bind("<Button-1>", lambda e: f.toggle_favorite(self.char))
        refresh = tk.Label(top, bg=BG, cursor="hand2", width=30, height=28)
        f._set_icon(refresh, "refresh", FG_DIM)
        refresh.pack(side="right", anchor="n")
        refresh.bind("<Button-1>", lambda e: self.reload())
        refresh.bind("<Enter>", lambda e: f._set_icon(refresh, "refresh", FG))
        refresh.bind("<Leave>", lambda e: f._set_icon(refresh, "refresh", FG_DIM))
        self.paint_star()
        mid = tk.Frame(top, bg=BG)
        mid.pack(side="left", fill="x", expand=True, padx=(12, 0))
        line1 = tk.Frame(mid, bg=BG)
        line1.pack(fill="x", anchor="w")
        self.h_name = tk.Label(line1, bg=BG, fg=FG, font=f.f_name, anchor="w")
        self.h_name.pack(side="left")
        self.h_legion = tk.Label(line1, bg=BG, fg=FG_DIM, font=f.f_small, anchor="w")
        self.h_legion.pack(side="left", padx=(6, 0), pady=(3, 0))
        self.h_faction = tk.Canvas(line1, width=10, height=10, bg=BG, highlightthickness=0)
        self.h_faction.pack(side="left", padx=(4, 0), pady=(4, 0))
        line2 = tk.Frame(mid, bg=BG)
        line2.pack(fill="x", anchor="w", pady=(2, 0))
        self.h_class = tk.Label(line2, bg=BG, font=f.f_small, anchor="w")
        self.h_class.pack(side="left")
        self.h_line = self._fit_label(line2, "", f.f_small, bg=BG, fg=FG_DIM)
        self.h_line.pack(side="left", fill="x", expand=True)

        # stat strip
        strip = tk.Frame(self.frame, bg=SURFACE)
        strip.pack(fill="x", padx=PAD)
        self.h_stats = {}
        for i, (key, label) in enumerate((("cp", "Combat power"), ("gs", "Gear score"), ("lv", "Level"))):
            strip.columnconfigure(i * 2, weight=1, uniform="strip")
            if i:
                tk.Frame(strip, bg=BORDER, width=1).grid(row=0, column=i * 2 - 1, sticky="ns", pady=8)
            cell = tk.Frame(strip, bg=SURFACE, padx=12, pady=7)
            cell.grid(row=0, column=i * 2, sticky="ew")
            tk.Label(cell, text=label, bg=SURFACE, fg=FG_DIM, font=f.f_tiny, anchor="w").pack(fill="x")
            v = tk.Label(cell, bg=SURFACE, fg=ACCENT if key == "cp" else FG, font=f.f_title, anchor="w")
            v.pack(fill="x")
            self.h_stats[key] = v
        self._paint_hero()

    def _build_tabs(self):
        f = self.app
        bar = tk.Frame(self.frame, bg=SURFACE, padx=3, pady=3)
        bar.pack(fill="x", padx=PAD, pady=(12, 0))
        self.tab_labels = {}
        for name in self.TABS:
            lb = tk.Label(bar, text=name, bg=SURFACE, fg=FG_DIM, font=f.f_small, pady=4, cursor="hand2")
            lb.pack(side="left", fill="x", expand=True, padx=(0, 1))
            lb.bind("<Button-1>", lambda e, n=name: self.show_tab(n))
            self.tab_labels[name] = lb

    def _build_body(self):
        wrap = tk.Frame(self.frame, bg=BG)
        wrap.pack(fill="both", expand=True, padx=(PAD, 4), pady=(6, 10))
        self.canvas = tk.Canvas(wrap, bg=BG, highlightthickness=0, bd=0, yscrollincrement=16)
        sb = ThinScrollbar(wrap, command=self.canvas.yview)
        sb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.configure(yscrollcommand=sb.set)
        self.body_root = tk.Frame(self.canvas, bg=BG)
        self.body = self.body_root
        self._win = self.canvas.create_window((0, 0), window=self.body_root, anchor="nw")
        self.body_root.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._win, width=e.width - 6))
        self.app.root.bind_all("<MouseWheel>", self._wheel)

    def _wheel(self, e):
        try:
            self.canvas.yview_scroll(int(-e.delta / 40) or (-1 if e.delta > 0 else 1), "units")
        except tk.TclError:
            pass

    def destroy(self):
        self._hide_tip()
        self.app.root.unbind_all("<MouseWheel>")
        self.frame.destroy()

    # ───── state ─────
    GEAR_TABS = {"Gear", "Skills", "Cosmetics"}   # need the equipment call

    @property
    def animating(self) -> bool:
        p = self.profile
        return self.loading or bool(p and p.equipment_pending and self.tab in self.GEAR_TABS)

    @staticmethod
    def _fingerprint(prof: Profile | None):
        if prof is None:
            return None
        d = asdict(prof)
        d.pop("cached_at", None)
        return hash(repr(d))

    def set_profile(self, prof: Profile | None, err: str | None):
        """Called with a cached copy, then a partial (gear pending), then the fresh profile."""
        if err and self.profile is not None:
            return  # keep showing what we have; a failed background refresh shouldn't blank the page
        if prof is not None and self._fingerprint(prof) == self._fingerprint(self.profile):
            self.profile = prof   # identical data (e.g. cache confirmed by refresh): nothing to redraw
            return
        self.loading = False
        self.profile, self.error = prof, err
        self._drop_frames()
        self._paint_hero()
        self.render(keep_scroll=True)

    def reload(self):
        self._details = {}
        self.app.api.forget(self.char)
        self.loading, self.profile, self.error = True, None, None
        self._drop_frames()
        self.render()
        self.app.api.fetch_profile(self.char, lambda ch, p, e: self.app.inbox.put(("profile", ch, p, e)),
                                   force=True)

    def show_tab(self, name: str):
        self.tab = name
        self.app.cfg["profile_tab"] = name
        self.render()

    def paint_star(self):
        fav = self.char.key in self.app.favorites
        self.app._set_icon(self.star, "star_fill" if fav else "star", ACCENT if fav else FG_DIM)

    def _paint_hero(self):
        c, p = self.char, self.profile
        name = p.name if p and p.name else c.name
        race = p.race if p and p.race else c.race
        cls = (p.class_name if p and p.class_name else c.class_name) or "Unknown"
        level = p.level if p and p.level else c.level
        server = p.server_name if p and p.server_name else c.server_name
        self.h_name.config(text=name)
        legion = (p.legion if p else None) or c.legion
        self.h_legion.config(text=f"<{legion}>" if legion else "")
        self.h_faction.delete("all")
        if race in (1, 2):
            self.h_faction.create_oval(2, 2, 8, 8, fill=ELYOS if race == 1 else ASMO, outline="")
        self.h_class.config(text=cls, fg=CLASS_COLORS.get(cls, FG_DIM))
        bits = [f"Lv {level}" if level else "", f"{server} · {REGION_NAMES.get(c.region, c.region)}" if server else "",
                {1: "Elyos", 2: "Asmodian"}.get(race, ""), p.title if p and p.title else ""]
        self._set_fit(self.h_line, "  ·  " + "  ·  ".join(b for b in bits if b))
        cp = p.combat_power if p else c.combat_power
        gs = p.gear_score if p else c.gear_score
        wait = "…" if self.loading else "—"
        self.h_stats["cp"].config(text=fmt_int(cp) if cp is not None else wait)
        self.h_stats["gs"].config(text=fmt_int(gs) if gs is not None else wait)
        self.h_stats["lv"].config(text=str(level) if level else wait)
        self._set_image(self.portrait, (p.portrait if p and p.portrait else c.portrait), HERO, crop_top=True)

    # ───── images ─────
    def _blank(self, size: int) -> tk.PhotoImage:
        """Transparent placeholder so empty image slots are sized in pixels, not characters."""
        img = self._blanks.get(size)
        if img is None:
            img = self._blanks[size] = tk.PhotoImage(width=size, height=size)
        return img

    def _set_image(self, label: tk.Label, url: str | None, size: int, crop_top: bool = False):
        img = self.app.images.get(url, size, radius=12 if size > 50 else 6, crop_top=crop_top)
        if img:
            label.config(image=img)
            label.image = img
        elif url:
            self._img_slots.append((label, url, size, crop_top))

    def refresh_images(self):
        slots, self._img_slots = self._img_slots, []
        for label, url, size, crop_top in slots:
            try:
                if label.winfo_exists():
                    self._set_image(label, url, size, crop_top)
            except tk.TclError:
                pass

    # ───── content ─────
    def _drop_frames(self):
        for f in getattr(self, "_frames", {}).values():
            f.destroy()
        if getattr(self, "_transient", None) is not None:
            self._transient.destroy()     # skeleton / error placeholder
        self._frames: dict[str, tk.Frame] = {}
        self._transient = None

    def render(self, keep_scroll: bool = False):
        """Show the current tab. Each tab is built once per profile and then just shown again."""
        self._hide_tip()
        for name, lb in self.tab_labels.items():
            on = name == self.tab
            lb.config(bg=SURFACE_2 if on else SURFACE, fg=FG if on else FG_DIM,
                      font=self.app.f_sbold if on else self.app.f_small)
        if not hasattr(self, "_frames"):
            self._drop_frames()
        y = self.canvas.yview()[0] if keep_scroll else 0
        for f in self._frames.values():
            f.pack_forget()
        if self._transient is not None:
            self._transient.destroy()
            self._transient = None
        self._skel_items = []

        p = self.profile
        if self.loading or (p and p.equipment_pending and self.tab in self.GEAR_TABS):
            self.body = self._transient = tk.Frame(self.body_root, bg=BG)
            self.body.pack(fill="x")
            self._skeleton()
        elif self.error or not p:
            self.body = self._transient = tk.Frame(self.body_root, bg=BG)
            self.body.pack(fill="x")
            box = tk.Frame(self.body, bg=BG)
            box.pack(fill="x", pady=30)
            tk.Label(box, text="Couldn't load this profile", bg=BG, fg=FG, font=self.app.f_name).pack()
            tk.Label(box, text=self.error or "", bg=BG, fg=FG_FAINT, font=self.app.f_small, wraplength=420).pack(pady=4)
            retry = tk.Label(box, text="Try again", bg=ACCENT, fg=BG, font=self.app.f_body, padx=12, pady=4,
                             cursor="hand2")
            retry.pack(pady=8)
            retry.bind("<Button-1>", lambda e: self.reload())
        else:
            frame = self._frames.get(self.tab)
            if frame is None:
                frame = self._frames[self.tab] = tk.Frame(self.body_root, bg=BG)
                self.body = frame
                getattr(self, f"_tab_{self.tab.lower()}")(p)
            self.body = frame
            frame.pack(fill="x")
        self.body_root.update_idletasks()
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self.canvas.yview_moveto(y)

    def _skeleton(self):
        """A spinning ring while the profile (or its gear) loads."""
        cv = tk.Canvas(self.body, bg=BG, height=220, highlightthickness=0)
        cv.pack(fill="x")
        r, w = 18, 4
        ring = cv.create_oval(0, 0, 0, 0, outline=SURFACE_2, width=w)
        arc = cv.create_arc(0, 0, 0, 0, start=90, extent=100, style="arc", outline=ACCENT, width=w)

        def place(e):
            cx, cy = e.width / 2, 90
            for item in (ring, arc):
                cv.coords(item, cx - r, cy - r, cx + r, cy + r)
        cv.bind("<Configure>", place)
        self._skel_items.append((cv, arc, 0))

    def shimmer(self):
        start = -(time.monotonic() * 360) % 360          # one turn per second
        for cv, arc, _tone in self._skel_items:
            try:
                cv.itemconfigure(arc, start=start)
            except tk.TclError:
                pass

    # helpers
    def _section(self, parent, title: str, extra: str = ""):
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", pady=(10, 4))
        tk.Label(row, text=title, bg=BG, fg=FG_DIM, font=self.app.f_small).pack(side="left")
        if extra:
            tk.Label(row, text=extra, bg=BG, fg=FG_FAINT, font=self.app.f_tiny).pack(side="left", padx=6)

    def _icon(self, parent, url: str | None, size: int = ICON, border: str = BORDER):
        box = tk.Frame(parent, bg=border, padx=1, pady=1)
        lb = tk.Label(box, bg=SURFACE_2, image=self._blank(size), bd=0)
        lb.pack()
        self._set_image(lb, url, size)
        return box

    def _set_fit(self, lb: tk.Label, text: str):
        lb._full = text
        lb._fit()

    def _fit_label(self, parent, text: str, font, tip: bool = True, **kw) -> tk.Label:
        """A label that never pushes its neighbours out: long text is cut to the space it gets, with "…",
        and the full text shows on hover."""
        lb = tk.Label(parent, text=text, font=font, width=1, anchor="w", **kw)
        lb._full = text
        state = {"cut": False}

        def fit(e=None):
            text = lb._full
            avail = (e.width if e is not None else lb.winfo_width()) - 2
            if avail <= 1:
                lb.config(text=text)
                return
            if font.measure(text) <= avail:
                shown, state["cut"] = text, False
            else:
                lo, hi = 0, len(text)
                while lo < hi:                       # longest prefix that fits with the ellipsis
                    mid = (lo + hi + 1) // 2
                    if font.measure(text[:mid].rstrip() + "…") <= avail:
                        lo = mid
                    else:
                        hi = mid - 1
                shown, state["cut"] = text[:lo].rstrip() + "…", True
            if lb.cget("text") != shown:
                lb.config(text=shown)
        lb.bind("<Configure>", fit, add="+")
        lb._fit = fit
        if tip:
            lb.bind("<Enter>", lambda e: state["cut"] and self._show_tip(lb, lb._full, []), add="+")
            lb.bind("<Leave>", lambda e: state["cut"] and self._hide_tip(), add="+")
        return lb

    def _item_row(self, parent, item: Item | None, label: str):
        row = tk.Frame(parent, bg=SURFACE, padx=8, pady=6)
        row.pack(fill="x", pady=2)
        if item is None:
            self._icon(row, None).pack(side="left")
            tk.Label(row, text=label, bg=SURFACE, fg=FG_FAINT, font=self.app.f_small, anchor="w").pack(
                side="left", padx=8)
            return
        col = GRADE_COLORS.get(item.grade, FG)
        self._icon(row, item.icon, border=col).pack(side="left")
        if item.enchant or item.exceed:            # packed first so a long name can't push it out
            ench = f"+{item.enchant}" + (f"  ✦{item.exceed}" if item.exceed else "")
            tk.Label(row, text=ench, bg=SURFACE, fg=ACCENT if item.enchant >= 10 else FG, font=self.app.f_bold).pack(
                side="right", padx=(6, 0))
        txt = tk.Frame(row, bg=SURFACE)
        txt.pack(side="left", fill="x", expand=True, padx=(8, 0))
        self._fit_label(txt, item.name, self.app.f_bold, bg=SURFACE, fg=col).pack(fill="x")
        sub = f"{label}  ·  {item.grade}" + (f"  ·  Lv {item.level}" if item.level else "")
        self._fit_label(txt, sub, self.app.f_tiny, bg=SURFACE, fg=FG_FAINT).pack(fill="x")

    def _columns(self):
        cols = tk.Frame(self.body, bg=BG)
        cols.pack(fill="x")
        left, right = tk.Frame(cols, bg=BG), tk.Frame(cols, bg=BG)
        left.pack(side="left", fill="both", expand=True, padx=(0, 4))
        right.pack(side="left", fill="both", expand=True, padx=(4, 0))
        return left, right

    # ───── tabs ─────
    def _tab_gear(self, p: Profile):
        if p.equipment_error:
            tk.Label(self.body, text="Couldn't load gear.", bg=BG, fg=RED,
                     font=self.app.f_small).pack(anchor="w", pady=8)
            return
        rows = [(slot_name(s), p.gear.get(s)) for s in GEAR_MAIN + GEAR_ACCESSORIES]
        rows += [(slot_name(s), it) for s in GEAR_ARCANA if (it := p.gear.get(s))]
        self._gear_table(rows)

    def _gear_table(self, rows: list[tuple[str, Item | None]]):
        """Slot | Item | Grade | +, one line each, so a whole loadout reads at a glance."""
        f = self.app
        t = tk.Frame(self.body, bg=BG)
        t.pack(fill="x", pady=(6, 0))
        t.columnconfigure(0, minsize=84)
        t.columnconfigure(1, weight=1)
        t.columnconfigure(2, minsize=64)
        t.columnconfigure(3, minsize=56)
        for i, (text, anchor) in enumerate((("Slot", "w"), ("Item", "w"), ("Grade", "w"), ("+", "e"))):
            tk.Label(t, text=text, bg=BG, fg=FG_DIM, font=f.f_tiny, anchor=anchor).grid(
                row=0, column=i, sticky="ew", padx=(8 if i == 0 else 0, 8), pady=(0, 4))
        tk.Frame(t, bg=LINE, height=1).grid(row=1, column=0, columnspan=4, sticky="ew", pady=(0, 2))
        self._details: dict[str, object] = getattr(self, "_details", {})
        for r, (label, it) in enumerate(rows, start=2):
            slot_lb = tk.Label(t, text=label, bg=BG, fg=FG_DIM, font=f.f_small, anchor="w")
            slot_lb.grid(row=r, column=0, sticky="ew", padx=(8, 8), pady=3)
            cell = tk.Frame(t, bg=BG)
            cell.grid(row=r, column=1, sticky="ew", padx=(0, 8), pady=3)
            if it is None:                          # nothing worn here: just the empty slot
                self._icon(cell, None, 20).pack(side="left")
                continue
            col = GRADE_COLORS.get(it.grade, FG)
            icon = self._icon(cell, it.icon, 20, border=col)
            icon.pack(side="left")
            name = self._fit_label(cell, it.name, f.f_body, tip=False, bg=BG, fg=col)
            name.pack(side="left", fill="x", expand=True, padx=(8, 0))
            grade = tk.Label(t, text=it.grade or "", bg=BG, fg=col, font=f.f_small, anchor="w")
            grade.grid(row=r, column=2, sticky="ew", padx=(0, 8), pady=3)
            ench = (f"+{it.enchant}" if it.enchant else "") + (f" ✦{it.exceed}" if it.exceed else "")
            plus = tk.Label(t, text=ench, bg=BG, fg=ACCENT if (it.enchant or 0) >= 10 else FG, font=f.f_bold,
                            anchor="e")
            plus.grid(row=r, column=3, sticky="ew", padx=(0, 8), pady=3)
            if it.slot_pos and it.item_id:
                self._item_hover([slot_lb, cell, icon, *icon.winfo_children(), name, grade, plus], it)
                self._row_anchor = getattr(self, "_row_anchor", {})
                self._row_anchor[it.slot] = cell
                self._want_detail(it)               # fetched in the background: ready by the time you hover

    # ───── item details (mana stones, theostone, stats, Arcana linked skills / set) ─────
    @staticmethod
    def _dkey(it: Item) -> tuple:
        return (it.slot, it.item_id, it.enchant)

    def _want_detail(self, it: Item):
        key = self._dkey(it)
        if key in self._details:
            return
        self._details[key] = None                            # asked for

        def done(det, key=key):
            self.app.inbox.put(("item_detail", self, key, det))
        self.app.api.fetch_item_detail(self.char, it, done)

    def item_detail_ready(self, key: tuple, det):
        """(main thread) an item's details arrived: keep them, and refresh its tooltip if it's showing."""
        if det is not None:
            self._details[key] = det
        elif self._details.get(key) is None:
            self._details[key] = False                       # failed: the tooltip says so
        hover = getattr(self, "_hover_item", None)
        if hover is not None and self._dkey(hover[0]) == key and hover[1].winfo_exists():
            self._show_item_tip(*hover)

    def _item_hover(self, widgets, it: Item):
        anchor = widgets[1]

        def enter(_e):
            self._hover_item = (it, anchor)
            self._show_item_tip(it, anchor)

        def leave(_e):
            x, y = anchor.winfo_pointerxy()
            row = [w for w in widgets if w.winfo_exists()]
            if any(w.winfo_rootx() <= x < w.winfo_rootx() + w.winfo_width() and
                   w.winfo_rooty() <= y < w.winfo_rooty() + w.winfo_height() for w in row):
                return                                       # moving between the row's own parts
            self._hover_item = None
            self._hide_tip()
        for w in widgets:
            w.bind("<Enter>", enter, add="+")
            w.bind("<Leave>", leave, add="+")

    # the game's own item tooltip, as closely as we can: a header tinted by grade with the icon on the right,
    # stats as name / value rows, soul imprint, mana stones two to a row, theostone, appearance, required level
    TIP_W = 300
    HEAD_BG = {"Common": "#34373e", "Rare": "#1e3d27", "Legend": "#1b3350", "Unique": "#4a3a16", "Epic": "#4a2814",
               "Special": "#163f3c", "Mythic": "#4a1a2c"}
    TIP_BG = "#17191e"
    EXCEED = "#ff9a3c"        # stats from exceeding (orange, like the game)
    SOUL = "#5aa9ff"          # soul binding rate (blue)
    FUSE = "#b98cff"          # linked / fused skills (purple)
    GOOD = "#6fd38a"          # better mana stones (green)
    SKIN = "#4fd1c5"

    def _show_item_tip(self, it: Item, anchor):
        det = self._details.get(self._dkey(it))
        self._hide_tip()
        f = self.app
        tip = tk.Toplevel(self.frame)
        tip.overrideredirect(True)
        tip.attributes("-topmost", True)
        tip.configure(bg=BORDER)
        outer = tk.Frame(tip, bg=self.TIP_BG, width=self.TIP_W)
        outer.pack(padx=1, pady=1)
        col = GRADE_COLORS.get(it.grade, FG)
        hb = self.HEAD_BG.get(it.grade, "#2a2d34")

        # header
        head = tk.Frame(outer, bg=hb, padx=12, pady=10)
        head.pack(fill="x")
        icon_box = tk.Frame(head, bg=col, padx=1, pady=1)
        icon_box.pack(side="right", anchor="n", padx=(10, 0))
        icon = tk.Label(icon_box, bg=SURFACE_2, image=self._blank(44), bd=0)
        icon.pack()
        self._set_image(icon, it.icon, 44)
        left = tk.Frame(head, bg=hb)
        left.pack(side="left", fill="x", expand=True)
        ench = f"+{it.enchant} " if it.enchant else ""
        tk.Label(left, text=ench + it.name, bg=hb, fg=col, font=f.f_bold, anchor="w", justify="left",
                 wraplength=self.TIP_W - 90).pack(fill="x")
        kind = f"{it.grade} {det.category}".strip() if det else it.grade
        tk.Label(left, text=kind, bg=hb, fg=FG, font=f.f_small, anchor="w").pack(fill="x")
        if det and det.item_level:
            tk.Label(left, text="Item Level", bg=hb, fg=FG_DIM, font=f.f_tiny, anchor="w").pack(fill="x", pady=(4, 0))
            lvl = str(det.item_level) + (f"   ✦{it.exceed}" if it.exceed else "")
            tk.Label(left, text=lvl, bg=hb, fg=FG, font=f.f_title, anchor="w").pack(fill="x")

        body = tk.Frame(outer, bg=self.TIP_BG, padx=12, pady=6)
        body.pack(fill="x")
        if not det:
            if det is False:
                tk.Label(body, text="Couldn't load this item's details", bg=self.TIP_BG, fg=FG_FAINT,
                         font=f.f_small).pack(pady=10)
            else:
                self._tip_spinner(body)
            self._place_tip(tip, anchor)
            return

        def line():
            tk.Frame(body, bg=BORDER, height=1).pack(fill="x", pady=5)

        def row(name, value, fg=FG, vfg=None, font=None):
            r = tk.Frame(body, bg=self.TIP_BG)
            r.pack(fill="x")
            tk.Label(r, text=name, bg=self.TIP_BG, fg=fg, font=font or f.f_small, anchor="w").pack(side="left")
            tk.Label(r, text=value, bg=self.TIP_BG, fg=vfg or fg, font=font or f.f_small, anchor="e").pack(side="right")

        for name, value, extra in det.main_stats:
            low = det.main_min.get(name)
            row(name, (f"{low}–" if low else "") + value + (f"(+{extra})" if extra else ""))
        for name, value in det.exceed_stats:
            row(name, value, fg=self.EXCEED)
        if det.soul_bind or det.sub_stats:
            line()
        if det.soul_bind:
            row("Soul Binding Rate", f"{det.soul_bind}%", fg=self.SOUL)
            bar = tk.Canvas(body, height=3, bg=self.TIP_BG, highlightthickness=0, width=self.TIP_W - 26)
            bar.pack(fill="x", pady=(2, 4))
            try:
                pct = max(0.0, min(100.0, float(det.soul_bind))) / 100
            except ValueError:
                pct = 0
            w = self.TIP_W - 26
            bar.create_rectangle(0, 0, w, 3, fill=SURFACE_2, outline="")
            bar.create_rectangle(0, 0, w * pct, 3, fill=self.SOUL, outline="")
        for name, value in det.sub_stats:
            row(name, value)
        for name, lv, _icon in det.linked_skills if not det.set_name else []:
            row(name, f"Lvl. +{lv}")                 # a skill the item adds: a row like the stats above
        if det.mana_slots or det.mana_stones:
            line()
            grid = tk.Frame(body, bg=self.TIP_BG)
            grid.pack(fill="x")
            grid.columnconfigure(0, weight=1, uniform="ms")
            grid.columnconfigure(1, weight=1, uniform="ms")
            stones = list(det.mana_stones) + [None] * max(0, det.mana_slots - len(det.mana_stones))
            for i, st in enumerate(stones):
                cell = tk.Frame(grid, bg=self.TIP_BG)
                cell.grid(row=i // 2, column=i % 2, sticky="w", pady=2)
                ic = tk.Label(cell, bg=self.TIP_BG, image=self._blank(16), bd=0)
                ic.pack(side="left")
                if st is None:
                    tk.Label(cell, text="Empty", bg=self.TIP_BG, fg=FG_FAINT, font=f.f_small).pack(side="left", padx=6)
                    continue
                name, value, grade, url = st
                self._set_image(ic, url, 16)
                better = grade not in ("", "Common")
                tk.Label(cell, text=f"{name}{value}", bg=self.TIP_BG, fg=self.GOOD if better else FG,
                         font=f.f_small).pack(side="left", padx=6)
        if det.theo_slots or det.theostones:
            line()
            for t in det.theostones or ["Theostone Engravable"]:
                tk.Label(body, text=f"◇  {t}", bg=self.TIP_BG, fg=FG if det.theostones else FG_FAINT,
                         font=f.f_small, anchor="w", justify="left", wraplength=self.TIP_W - 30).pack(fill="x")
        if det.set_name:                             # Arcana: linked skills, then the set
            if det.linked_skills:
                line()
                tk.Label(body, text="LINKED SKILLS", bg=self.TIP_BG, fg=FG_DIM, font=f.f_tiny, anchor="w").pack(fill="x")
                for name, lv, url in det.linked_skills:
                    r = tk.Frame(body, bg=self.TIP_BG)
                    r.pack(fill="x", pady=1)
                    ic = tk.Label(r, bg=self.TIP_BG, image=self._blank(18), bd=0)
                    ic.pack(side="left")
                    self._set_image(ic, url, 18)
                    tk.Label(r, text=name, bg=self.TIP_BG, fg=FG, font=f.f_small).pack(side="left", padx=6)
                    tk.Label(r, text=f"Lvl. +{lv}", bg=self.TIP_BG, fg=FG, font=f.f_small).pack(side="right")
            line()
            tk.Label(body, text=f"{det.set_name.upper()} · {det.set_equipped} EQUIPPED", bg=self.TIP_BG,
                     fg=FG, font=f.f_sbold, anchor="w").pack(fill="x")
            for need, effects in det.set_bonuses:
                on = det.set_equipped >= need
                tk.Label(body, text=f"{need} pieces", bg=self.TIP_BG, fg=FG if on else FG_FAINT, font=f.f_sbold,
                         anchor="w").pack(fill="x", pady=(4, 0))
                for e in effects:
                    tk.Label(body, text=e, bg=self.TIP_BG, fg=FG_DIM if on else FG_FAINT, font=f.f_small,
                             anchor="w", justify="left", wraplength=self.TIP_W - 30).pack(fill="x")
        if det.costumes:
            line()
            row("Skin Info", "", fg=self.SKIN)
            for c in det.costumes[:3]:
                tk.Label(body, text=c, bg=self.TIP_BG, fg=ACCENT, font=f.f_small, anchor="w").pack(fill="x")
        foot = tk.Frame(outer, bg=self.TIP_BG, padx=12)
        foot.pack(fill="x", pady=(2, 8))
        tk.Frame(foot, bg=BORDER, height=1).pack(fill="x", pady=(0, 6))
        if det.equip_level:
            tk.Label(foot, text=f"Required Level {det.equip_level}", bg=self.TIP_BG, fg=FG_DIM,
                     font=f.f_tiny).pack(side="left")
        if det.max_enchant:
            tk.Label(foot, text=f"Max +{det.max_enchant}" + (f" · ✦{det.max_exceed}" if det.max_exceed else ""),
                     bg=self.TIP_BG, fg=FG_FAINT, font=f.f_tiny).pack(side="right")
        self._place_tip(tip, anchor)

    def _tip_spinner(self, parent):
        """A small spinning ring while the item's details load."""
        cv = tk.Canvas(parent, width=self.TIP_W - 26, height=56, bg=self.TIP_BG, highlightthickness=0)
        cv.pack()
        cx, r = (self.TIP_W - 26) / 2, 11
        cv.create_oval(cx - r, 28 - r, cx + r, 28 + r, outline=SURFACE_2, width=3)
        arc = cv.create_arc(cx - r, 28 - r, cx + r, 28 + r, start=90, extent=100, style="arc", outline=ACCENT,
                            width=3)

        def spin():
            try:
                cv.itemconfigure(arc, start=-(time.monotonic() * 360) % 360)
                cv.after(30, spin)
            except tk.TclError:
                pass                                 # the tooltip closed
        spin()

    def _place_tip(self, tip, anchor):
        tip.update_idletasks()
        from .desktop import monitor_rect
        left, top, right, bottom = monitor_rect(anchor, anchor.winfo_rootx(), anchor.winfo_rooty())
        w, h = tip.winfo_reqwidth(), tip.winfo_reqheight()
        # just outside the tracker window, on whichever side has room (like the game's, beside its inventory);
        # over the window only when neither side does
        root = self.app.root
        rx, rw = root.winfo_rootx(), root.winfo_width()
        x = rx + rw + 6
        if x + w > right - 4:
            x = rx - w - 6
        if x < left + 4:
            x = max(left + 4, min(anchor.winfo_rootx() + anchor.winfo_width() + 8, right - w - 4))
        y = max(top + 8, min(anchor.winfo_rooty() - 20, bottom - h - 8))
        tip.geometry(f"+{int(x)}+{int(y)}")
        self._tip = tip

    def _tab_skills(self, p: Profile):
        if p.equipment_error:
            tk.Label(self.body, text="Couldn't load skills.", bg=BG, fg=RED,
                     font=self.app.f_small).pack(anchor="w", pady=8)
            return
        for cat, title in SKILL_CATEGORIES:
            skills = p.skills_in(cat)
            if not skills:
                continue
            learned = sum(s.acquired for s in skills)
            self._section(self.body, title, f"{learned}/{len(skills)} learned")
            grid = tk.Frame(self.body, bg=BG)
            grid.pack(fill="x")
            grid.columnconfigure(0, weight=1, uniform="s")
            grid.columnconfigure(1, weight=1, uniform="s")
            for i, s in enumerate(skills):
                cell = tk.Frame(grid, bg=SURFACE, padx=8, pady=5)
                cell.grid(row=i // 2, column=i % 2, sticky="nsew", padx=(0 if i % 2 == 0 else 4, 0 if i % 2 else 4),
                          pady=2)
                self._icon(cell, s.icon, 30, border=ACCENT if s.equipped else BORDER).pack(side="left")
                txt = tk.Frame(cell, bg=SURFACE)
                txt.pack(side="left", fill="x", expand=True, padx=8)
                self._fit_label(txt, s.name, self.app.f_small, bg=SURFACE,
                                fg=FG if s.acquired else FG_FAINT).pack(fill="x")
                sub = ("Not learned" if not s.acquired else f"Lv {s.level}" if s.level else "Learned") + \
                      ("  ·  Equipped" if s.equipped else "")
                tk.Label(txt, text=sub, bg=SURFACE, fg=ACCENT if s.equipped and s.acquired else FG_FAINT,
                         font=self.app.f_tiny, anchor="w").pack(fill="x")

    def _tab_daevanion(self, p: Profile):
        if not p.boards:
            tk.Label(self.body, text="No Daevanion boards opened yet.", bg=BG, fg=FG_DIM,
                     font=self.app.f_small).pack(anchor="w", pady=8)
            return
        total_open = sum(b.opened for b in p.boards)
        total = sum(b.total for b in p.boards)
        self._section(self.body, "Daevanion boards", f"{total_open}/{total} nodes")
        for b in p.boards:
            row = tk.Frame(self.body, bg=SURFACE, padx=10, pady=8)
            row.pack(fill="x", pady=3)
            self._icon(row, b.icon, 30).pack(side="left")
            mid = tk.Frame(row, bg=SURFACE)
            mid.pack(side="left", fill="x", expand=True, padx=10)
            top = tk.Frame(mid, bg=SURFACE)
            top.pack(fill="x")
            tk.Label(top, text=f"{b.opened}/{b.total}  ·  {b.percent}%", bg=SURFACE, fg=FG_DIM,
                     font=self.app.f_small).pack(side="right")
            self._fit_label(top, b.name, self.app.f_bold, bg=SURFACE, fg=FG).pack(side="left", fill="x", expand=True)
            bar = tk.Canvas(mid, height=8, bg=SURFACE, highlightthickness=0)
            bar.pack(fill="x", pady=(5, 0))
            bar.bind("<Configure>", lambda e, cv=bar, pct=b.percent: self._bar(cv, e.width, pct))

    @staticmethod
    def _bar(cv: tk.Canvas, width: int, pct: int):
        cv.delete("all")
        round_rect(cv, 0, 0, width, 8, 4, fill=SURFACE_2, outline="")
        if pct > 0:
            round_rect(cv, 0, 0, max(8, width * pct / 100), 8, 4, fill=ACCENT, outline="")

    def _tab_stats(self, p: Profile):
        self._first_tip = None
        self._first_zero = False
        for title, stats in (("Primary stats", p.primary_stats), ("Deity stats", p.deity_stats)):
            if not stats:
                continue
            self._section(self.body, title)
            grid = tk.Frame(self.body, bg=BG)
            grid.pack(fill="x")
            cols = 3
            for c in range(cols):
                grid.columnconfigure(c, weight=1, uniform="t")
            for i, s in enumerate(stats):
                col = i % cols
                cell = tk.Frame(grid, bg=SURFACE, padx=10, pady=5)
                cell.grid(row=i // cols, column=col, sticky="nsew",
                          padx=(0 if col == 0 else 3, 0 if col == cols - 1 else 3), pady=2)
                top = tk.Frame(cell, bg=SURFACE)
                top.pack(fill="x")
                val = tk.Label(top, text=str(s.value), bg=SURFACE, fg=ACCENT if s.value else FG_FAINT,
                               font=self.app.f_bold)
                val.pack(side="right")
                name = self._fit_label(top, s.name, self.app.f_small, tip=False, bg=SURFACE, fg=FG)
                name.pack(side="left", fill="x", expand=True)
                lines, foot = self._stat_tip(s)
                if lines or foot:
                    self._hover_tip([cell, top, name, val], s.name, lines, foot)
                    if getattr(self, "_first_tip", None) is None or (not s.value and not self._first_zero):
                        self._first_tip = (cell, s.name, lines, foot)
                        self._first_zero = not s.value

    @staticmethod
    def _stat_tip(s) -> tuple[list[str], list[str]]:
        """(bonus lines, faint footer) for a stat's tooltip; empty stats show what each point would add."""
        from .profile import STAT_BONUSES, STAT_PER_POINT
        bonuses = STAT_BONUSES.get(s.type, ())
        foot = [f"{bonuses[0][1]}{STAT_PER_POINT:g}% per point"] if bonuses else []
        if s.value and s.effects:
            return list(s.effects), foot
        if bonuses:                                   # no points yet: the same lines, at 0%
            return [f"{label} {sign}0%" for label, sign in bonuses], foot
        return list(s.effects), []

    def demo_hover_item(self, slot_prefix: str):
        """Screenshots only: show the tooltip of the first gear row whose slot starts with slot_prefix."""
        p = self.profile
        if not p:
            return
        for slot, it in p.gear.items():
            if slot.startswith(slot_prefix) and it.slot_pos:
                anchor = getattr(self, "_row_anchor", {}).get(slot) or self.body
                self._hover_item = (it, anchor)
                self._show_item_tip(it, anchor)
                return

    def demo_hover_first_stat(self):
        """Used by the screenshot run: show the first stat's tooltip as if hovered."""
        if getattr(self, "_first_tip", None):
            cell, title, lines, foot = self._first_tip
            self._show_tip(cell, title, lines, foot)

    # ───── tooltips ─────
    def _hover_tip(self, widgets, title: str, lines: list[str], foot: list[str] | None = None):
        """Highlight the cell and show its effects in a small popup while the mouse is over it."""
        cell = widgets[0]

        def enter(_e):
            for w in widgets:
                w.config(bg=HOVER)
            self._show_tip(cell, title, lines, foot)

        def leave(e):
            # moving between the cell's own children isn't leaving the cell
            x, y = cell.winfo_pointerxy()
            inside = cell.winfo_rootx() <= x < cell.winfo_rootx() + cell.winfo_width() and \
                cell.winfo_rooty() <= y < cell.winfo_rooty() + cell.winfo_height()
            if inside:
                return
            for w in widgets:
                w.config(bg=SURFACE)
            self._hide_tip()

        for w in widgets:
            w.bind("<Enter>", enter, add="+")
            w.bind("<Leave>", leave, add="+")

    def _show_tip(self, anchor: tk.Widget, title: str, lines: list[str], foot: list[str] | None = None):
        self._hide_tip()
        tip = tk.Toplevel(self.frame)
        tip.overrideredirect(True)
        tip.attributes("-topmost", True)
        tip.configure(bg=BORDER)
        box = tk.Frame(tip, bg=SURFACE_2, padx=10, pady=7)
        box.pack(padx=1, pady=1)
        tk.Label(box, text=title, bg=SURFACE_2, fg=FG, font=self.app.f_bold, anchor="w").pack(fill="x")
        for ln in lines:
            kind, text = ln if isinstance(ln, tuple) else ("", ln)
            if kind == "h":                              # a section heading inside the tooltip
                tk.Label(box, text=text, bg=SURFACE_2, fg=ACCENT, font=self.app.f_sbold, anchor="w").pack(
                    fill="x", pady=(6, 0))
            else:
                tk.Label(box, text=text, bg=SURFACE_2, font=self.app.f_small, anchor="w", justify="left",
                         wraplength=320, fg={"dim": FG_FAINT, "ok": FG}.get(kind, FG_DIM)).pack(fill="x")
        for ln in foot or []:
            tk.Label(box, text=ln, bg=SURFACE_2, fg=FG_FAINT, font=self.app.f_tiny, anchor="w").pack(fill="x", pady=(3, 0))
        tip.update_idletasks()
        x = anchor.winfo_rootx()
        y = anchor.winfo_rooty() + anchor.winfo_height() + 4
        # keep it on screen: flip above the cell near the bottom edge
        from .desktop import monitor_rect
        left, top, right, bottom = monitor_rect(anchor, anchor.winfo_rootx(), anchor.winfo_rooty())
        h = tip.winfo_reqheight()
        if y + h > bottom - 8:
            y = anchor.winfo_rooty() - h - 4
        y = max(top + 8, min(y, bottom - h - 8))               # a tall tooltip still fits on the monitor
        x = max(left + 8, min(x, right - tip.winfo_reqwidth() - 8))
        tip.geometry(f"+{x}+{y}")
        self._tip = tip

    def _hide_tip(self):
        tip = getattr(self, "_tip", None)
        if tip is not None:
            try:
                tip.destroy()
            except tk.TclError:
                pass
            self._tip = None

    def _tab_cosmetics(self, p: Profile):
        if p.equipment_error:
            tk.Label(self.body, text="Couldn't load cosmetics.", bg=BG, fg=RED,
                     font=self.app.f_small).pack(anchor="w", pady=8)
            return
        self._section(self.body, "Wings & pet")
        for it, label in ((p.wing, "Wings"), (p.wing_skin, "Wing appearance"), (p.pet, "Pet")):
            if it:
                self._item_row(self.body, it, label)
        if p.skins:
            self._section(self.body, "Appearance", f"{len(p.skins)} items")
            left, right = self._columns()
            for i, it in enumerate(p.skins):
                self._item_row(left if i % 2 == 0 else right, it, it.slot_label)

    def _tab_titles(self, p: Profile):
        extra = f"{p.titles_owned}/{p.titles_total} collected" if p.titles_owned is not None else ""
        self._section(self.body, "Equipped titles", extra)
        if not p.titles:
            tk.Label(self.body, text="No titles equipped.", bg=BG, fg=FG_DIM, font=self.app.f_small).pack(anchor="w")
        for t in p.titles:
            card = tk.Frame(self.body, bg=SURFACE, padx=12, pady=8)
            card.pack(fill="x", pady=3)
            top = tk.Frame(card, bg=SURFACE)
            top.pack(fill="x")
            tk.Label(top, text=t.name, bg=SURFACE, fg=GRADE_COLORS.get(t.grade, FG), font=self.app.f_bold).pack(
                side="left")
            tk.Label(top, text=t.category, bg=SURFACE_2, fg=FG_DIM, font=self.app.f_tiny, padx=6).pack(
                side="left", padx=8)
            if t.owned_percent is not None:
                tk.Label(top, text=f"Owned by {t.owned_percent}% of players", bg=SURFACE, fg=FG_FAINT,
                         font=self.app.f_tiny).pack(side="right")
            for eff in t.effects:
                tk.Label(card, text=f"•  {eff}", bg=SURFACE, fg=FG_DIM, font=self.app.f_small, anchor="w").pack(
                    fill="x")
