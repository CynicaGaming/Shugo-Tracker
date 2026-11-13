"""In-app character profile: identity, a stat strip, and tabs (gear table, skills, Daevanion, stats, …)."""
from __future__ import annotations

import threading
import time
from dataclasses import asdict
import tkinter as tk
from typing import TYPE_CHECKING

from . import skilldata
from .aion2api import Character
from .profile import (GEAR_ACCESSORIES, GEAR_ARCANA, GEAR_MAIN, SKILL_CATEGORIES, Item, Profile, fmt_delta,
                      parse_board, slot_name, stat_deltas)
from .search_ui import (ACCENT, ASMO, BG, BORDER, CLASS_COLORS, ELYOS, FG, FG_DIM, FG_FAINT, GRADE_COLORS, HOVER,
                        LINE, PAD, RED, REGION_NAMES, SURFACE, SURFACE_2, fmt_int, round_rect, ThinScrollbar)

if TYPE_CHECKING:
    from .search_ui import SearchWindow

ICON = 36
HERO = 44


def wrapped_lines(text: str, measure, avail: int) -> int:
    """How many lines text takes when word-wrapped to avail pixels (measure: text -> pixels)."""
    n = 0
    for para in text.split("\n"):
        line = ""
        n += 1
        for word in para.split(" "):
            trial = f"{line} {word}" if line else word
            if line and measure(trial) > avail:
                n += 1
                line = word
            else:
                line = trial
    return max(1, n)


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
        # the whole profile is loaded before it's shown (info, gear and every item's details), so tabs and
        # tooltips never wait; a cached one shows at once
        self._ready = False
        self._opened = time.monotonic()
        self._batch = False
        self._details: dict[tuple, object] = {}
        self._ring: tuple | None = None
        self._boards: dict[int, object] = {}          # board id -> raw layout, None while loading, False if failed
        # compare: your character's profile (for holding Alt over an item), and whether Alt is held
        self._mine: Profile | None = None
        self._compare = False
        self._alt_tk = False                     # Alt from Tk's own key events (where the system can't be asked)
        self._alt_job = None
        self._tip2 = None
        for seq, on in (("<KeyPress-Alt_L>", True), ("<KeyPress-Alt_R>", True),
                        ("<KeyRelease-Alt_L>", False), ("<KeyRelease-Alt_R>", False)):
            app.root.bind_all(seq, lambda e, on=on: self._alt_key(on))

        self.frame = tk.Frame(app.root, bg=BG)
        self._build_header()
        self._build_tabs()
        self._build_body()
        self.render()
        self._want_mine()

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
        self._stop_alt_poll()
        self.app.root.unbind_all("<MouseWheel>")
        for seq in ("<KeyPress-Alt_L>", "<KeyPress-Alt_R>", "<KeyRelease-Alt_L>", "<KeyRelease-Alt_R>"):
            self.app.root.unbind_all(seq)
        self.frame.destroy()

    # ───── state ─────
    @property
    def animating(self) -> bool:
        return not self.error and (self.loading or not self._ready)

    @staticmethod
    def _worn(p: Profile) -> list[Item]:
        """The items with a tooltip: everything worn, Arcana included."""
        return [it for s in GEAR_MAIN + GEAR_ACCESSORIES + GEAR_ARCANA
                if (it := p.gear.get(s)) is not None and it.slot_pos and it.item_id]

    def _progress(self) -> tuple[int, int] | None:
        """(done, total) steps while loading; None until the gear list is known."""
        p = self.profile
        if p is None or p.equipment_pending:
            return None
        items = self._worn(p)
        done = sum(1 for it in items if self._details.get(self._dkey(it)) is not None)
        return done + 2, len(items) + 2                  # + info and equipment, already in

    def _check_ready(self):
        """Show the profile once everything it needs is here."""
        if self._ready or self._batch or self.loading:
            return
        prog = self._progress()
        p = self.profile
        if p is not None and (p.equipment_error or (prog is not None and prog[0] >= prog[1])):
            self._ready = True
            if getattr(self.app, "_screenshot", False):          # CI: how long a full load took
                print(f"profile ready: {self.char.name}, {len(self._worn(p))} items, "
                      f"{1000 * (time.monotonic() - self._opened):.0f} ms", flush=True)
            self.render()
            self._prebuild()
            self._want_my_items()

    def _want_all(self, p: Profile):
        """Ask for every worn item's details at once (saved ones answer immediately)."""
        self._batch = True
        try:
            for it in self._worn(p):
                self._want_detail(it)
        finally:
            self._batch = False
        self._check_ready()

    def _prebuild(self):
        """Build the tabs not shown yet, one per idle moment, so switching to them is instant."""
        p = self.profile
        if p is None or not self._ready:
            return
        todo = [t for t in self.TABS if t not in self._frames]
        if not todo:
            if getattr(self.app, "_screenshot", False):
                print(f"profile tabs prebuilt: {1000 * (time.monotonic() - self._opened):.0f} ms", flush=True)
            return

        def build(name=todo[0], p=p):
            try:
                if self.profile is not p or not self._ready or not self.frame.winfo_exists():
                    return
            except tk.TclError:
                return
            if name not in self._frames:
                frame = self._frames[name] = tk.Frame(self.body_root, bg=BG)
                shown, self.body = self.body, frame
                try:
                    getattr(self, f"_tab_{name.lower()}")(p)
                finally:
                    self.body = shown
            self._prebuild()
        self.frame.after(15, build)

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
        if prof is not None and not prof.equipment_pending:
            if self._ready:                               # a refreshed copy: redraw, then rebuild the rest
                self.render(keep_scroll=True)
                self._want_all(prof)
                self._prebuild()
                return
            self._want_all(prof)                          # saved items answer at once: shown right away
            if not self._ready:
                self.render()                             # …otherwise the ring, until they're in
            return
        self.render(keep_scroll=True)

    def reload(self):
        self._details = {}
        self._boards = {}
        self._ready = False
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
        if name == "Daevanion" and self._ready:
            self._want_board(self._board_sel())

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
        self._ring = None

        p = self.profile
        if not self.error and (self.loading or not self._ready):
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
        """A progress ring while the profile loads: it fills as the gear's details come in."""
        cv = tk.Canvas(self.body, bg=BG, height=220, highlightthickness=0)
        cv.pack(fill="x")
        r, w = 22, 4
        ring = cv.create_oval(0, 0, 0, 0, outline=SURFACE_2, width=w)
        arc = cv.create_arc(0, 0, 0, 0, start=90, extent=100, style="arc", outline=ACCENT, width=w)
        text = cv.create_text(0, 0, text="", fill=FG_DIM, font=self.app.f_small)

        def place(e):
            cx, cy = e.width / 2, 90
            for item in (ring, arc):
                cv.coords(item, cx - r, cy - r, cx + r, cy + r)
            cv.coords(text, cx, cy + r + 22)
        cv.bind("<Configure>", place)
        self._ring = (cv, arc, text)
        self.shimmer()

    def shimmer(self):
        ring = self._ring
        if ring is None:
            return
        cv, arc, text = ring
        prog = self._progress() if not self.loading else None
        try:
            if prog is None:                                  # not knowing how much is left: spin
                cv.itemconfigure(arc, start=-(time.monotonic() * 360) % 360, extent=100)
                cv.itemconfigure(text, text="Loading profile…")
            else:
                done, total = prog
                cv.itemconfigure(arc, start=90, extent=-max(6.0, 359.9 * done / total))
                cv.itemconfigure(text, text=f"Loading gear  {done - 2} / {total - 2}")
        except tk.TclError:
            self._ring = None

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
            tk.Label(self.body, text="Couldn't load gear", bg=BG, fg=RED,
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
            if threading.current_thread() is threading.main_thread():
                self.item_detail_ready(key, det)            # saved: answered right here
            else:
                self.app.inbox.put(("item_detail", self, key, det))
        self.app.api.fetch_item_detail(self.char, it, done)

    def item_detail_ready(self, key: tuple, det):
        """(main thread) an item's details arrived: keep them, and refresh its tooltip if it's showing."""
        if det is not None:
            self._details[key] = det
        elif self._details.get(key) is None:
            self._details[key] = False                       # failed: the tooltip says so
        if not self._ready:
            self._check_ready()
            return
        hover = getattr(self, "_hover_item", None)
        if hover is None or not hover[1].winfo_exists():
            return
        mine = self._my_item(hover[0])
        if self._dkey(hover[0]) == key or (self._compare and mine is not None and ("me",) + self._dkey(mine) == key):
            self._show_item_tip(*hover)

    def _item_hover(self, widgets, it: Item):
        anchor = widgets[1]

        def enter(_e):
            self._hover_item = (it, anchor)
            self._compare = self._alt_held()
            self._show_item_tip(it, anchor)
            self._start_alt_poll()

        def leave(_e):
            x, y = anchor.winfo_pointerxy()
            row = [w for w in widgets if w.winfo_exists()]
            if any(w.winfo_rootx() <= x < w.winfo_rootx() + w.winfo_width() and
                   w.winfo_rooty() <= y < w.winfo_rooty() + w.winfo_height() for w in row):
                return                                       # moving between the row's own parts
            self._hover_item = None
            self._stop_alt_poll()
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
    SET_NAME = "#3fbf8a"      # the set's name (green, like the game)

    def _badge(self, parent, n: int, on: bool) -> tk.Canvas:
        """A small diamond with a number in it: pieces equipped / needed."""
        cv = tk.Canvas(parent, width=16, height=16, bg=self.TIP_BG, highlightthickness=0)
        col = FG if on else FG_FAINT
        cv.create_polygon(8, 1, 15, 8, 8, 15, 1, 8, outline=col, fill="", width=1)
        cv.create_text(8, 8, text=str(n), fill=col, font=self.app.f_tiny)
        return cv

    def _show_item_tip(self, it: Item, anchor):
        """The item's tooltip; holding Alt adds yours from the same slot beside it, with ▲/▼ on the hovered one."""
        self._hide_tip()
        det = self._details.get(self._dkey(it))
        if not (self._compare and self._can_compare()):
            self._place_tip(self._item_tip(it, det, hint=self._can_compare()), anchor)
            return
        me = self.app.my_char
        heading = f"Equipped  ·  {me.name}"
        mine = self._my_item(it)
        if mine is None:
            waiting = self._mine is None or self._mine.equipment_pending
            yours = self._note_tip(heading, None if waiting else "Nothing equipped in this slot")
            deltas = None
        else:
            self._want_my_detail(mine)
            mdet = self._details.get(("me",) + self._dkey(mine))
            yours = self._item_tip(mine, mdet, heading=heading)
            deltas = stat_deltas(mdet, det) if det and mdet else None
        self._place_pair(self._item_tip(it, det, deltas=deltas), yours, anchor)

    def _new_tip(self) -> tuple[tk.Toplevel, tk.Frame]:
        tip = tk.Toplevel(self.frame)
        tip.overrideredirect(True)
        tip.attributes("-topmost", True)
        tip.configure(bg=BORDER)
        outer = tk.Frame(tip, bg=self.TIP_BG, width=self.TIP_W)
        outer.pack(padx=1, pady=1)
        return tip, outer

    def _tip_heading(self, outer, text: str):
        """The strip above your item when comparing ("Equipped · name"), like the game's."""
        tk.Label(outer, text=text.upper(), bg=self.TIP_BG, fg=FG_DIM, font=self.app.f_tiny, anchor="w",
                 padx=12, pady=5).pack(fill="x")

    def _note_tip(self, heading: str, text: str | None) -> tk.Toplevel:
        """Your side when there's no item to show: a message, or a spinner while your profile loads."""
        tip, outer = self._new_tip()
        self._tip_heading(outer, heading)
        body = tk.Frame(outer, bg=self.TIP_BG, padx=12, pady=6)
        body.pack(fill="x")
        if text is None:
            self._tip_spinner(body)
        else:
            tk.Label(body, text=text, bg=self.TIP_BG, fg=FG_FAINT, font=self.app.f_small, width=34).pack(pady=10)
        return tip

    def _item_tip(self, it: Item, det, heading: str | None = None, deltas: dict | None = None,
                  hint: bool = False) -> tk.Toplevel:
        f = self.app
        tip, outer = self._new_tip()
        if heading:
            self._tip_heading(outer, heading)
        deltas = deltas or {}
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
        kind = tk.Frame(left, bg=hb)                   # "Unique Longsword": the grade in its colour, like the game
        kind.pack(fill="x")
        if it.grade:
            tk.Label(kind, text=it.grade, bg=hb, fg=col, font=f.f_small, bd=0, padx=0).pack(side="left")
        if det and det.category:
            tk.Label(kind, text=(" " if it.grade else "") + det.category, bg=hb, fg=FG, font=f.f_small, bd=0,
                     padx=0).pack(side="left")
        if det and det.item_level:
            tk.Label(left, text="Item Level", bg=hb, fg=FG_DIM, font=f.f_tiny, anchor="w").pack(fill="x", pady=(4, 0))
            lvl = str(det.item_level) + (f"   ✦{it.exceed}" if it.exceed else "")
            lv = tk.Frame(left, bg=hb)
            lv.pack(fill="x")
            tk.Label(lv, text=lvl, bg=hb, fg=FG, font=f.f_title, anchor="w").pack(side="left")
            if "Item Level" in deltas:
                d, _ = deltas["Item Level"]
                tk.Label(lv, text=fmt_delta(d), bg=hb, fg=self.GOOD if d > 0 else RED, font=f.f_bold).pack(
                    side="left", padx=(8, 0), anchor="s", pady=(0, 2))

        body = tk.Frame(outer, bg=self.TIP_BG, padx=12, pady=6)
        body.pack(fill="x")
        if not det:
            if det is False:
                tk.Label(body, text="Couldn't load details", bg=self.TIP_BG, fg=FG_FAINT,
                         font=f.f_small).pack(pady=10)
            else:
                self._tip_spinner(body)
            return tip

        def line():
            tk.Frame(body, bg=BORDER, height=1).pack(fill="x", pady=5)

        def row(name, value, fg=FG, vfg=None, font=None, delta=None):
            r = tk.Frame(body, bg=self.TIP_BG)
            r.pack(fill="x")
            tk.Label(r, text=name, bg=self.TIP_BG, fg=fg, font=font or f.f_small, anchor="w").pack(side="left")
            if delta is not None:                    # compared with yours: packed first so it sits rightmost
                d, pct = delta
                tk.Label(r, text=fmt_delta(d, pct), bg=self.TIP_BG, fg=self.GOOD if d > 0 else RED,
                         font=f.f_small, anchor="e", width=7).pack(side="right")
            tk.Label(r, text=value, bg=self.TIP_BG, fg=vfg or fg, font=font or f.f_small, anchor="e").pack(side="right")

        shown = set()                                # each stat's difference once, on its first row
        for name, value, extra in det.main_stats:
            low = det.main_min.get(name)
            row(name, (f"{low}–" if low else "") + value + (f"(+{extra})" if extra else ""),
                delta=None if name in shown else deltas.get(name))
            shown.add(name)
        for name, value in det.exceed_stats:
            row(name, value, fg=self.EXCEED, delta=None if name in shown else deltas.get(name))
            shown.add(name)
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
            tk.Label(body, text="Set Effects", bg=self.TIP_BG, fg=FG, font=f.f_sbold).pack(pady=(0, 2))
            tk.Frame(body, bg=BORDER, height=1).pack(fill="x", pady=(0, 6))
            head = tk.Frame(body, bg=self.TIP_BG)
            head.pack(fill="x")
            tk.Label(head, text=det.set_name, bg=self.TIP_BG, fg=self.SET_NAME, font=f.f_bold).pack(side="left")
            self._badge(head, det.set_equipped, True).pack(side="left", padx=(5, 0))
            for need, effects in det.set_bonuses:
                on = det.set_equipped >= need
                for i, e in enumerate(effects):
                    r = tk.Frame(body, bg=self.TIP_BG)
                    r.pack(fill="x", pady=(5 if i == 0 else 1, 0))
                    (self._badge(r, need, on) if i == 0 else tk.Frame(r, bg=self.TIP_BG, width=16)).pack(
                        side="left", anchor="n", padx=(0, 6))
                    tk.Label(r, text=e, bg=self.TIP_BG, fg=FG if on else FG_FAINT, font=f.f_small, anchor="w",
                             justify="left", wraplength=self.TIP_W - 52).pack(side="left", fill="x")
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
        if hint:
            tk.Label(outer, text="Hold ALT to compare", bg=self.TIP_BG, fg=FG_FAINT, font=f.f_tiny,
                     anchor="w", padx=12).pack(fill="x", pady=(0, 8))
        return tip

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
        self._guard_tip()

    def _place_pair(self, tip, yours, anchor):
        """Hovered tooltip next to the window, yours beside it on the outside (flipped when there's no room)."""
        tip.update_idletasks()
        yours.update_idletasks()
        from .desktop import monitor_rect
        left, top, right, bottom = monitor_rect(anchor, anchor.winfo_rootx(), anchor.winfo_rooty())
        w1, w2, gap = tip.winfo_reqwidth(), yours.winfo_reqwidth(), 6
        total = w1 + gap + w2
        root = self.app.root
        rx, rw = root.winfo_rootx(), root.winfo_width()
        x, on_right = rx + rw + 6, True
        if x + total > right - 4:
            x, on_right = rx - total - 6, False
        if x < left + 4:
            x, on_right = max(left + 4, min(anchor.winfo_rootx() + anchor.winfo_width() + 8, right - total - 4)), True
        x_tip, x_yours = (x, x + w1 + gap) if on_right else (x + w2 + gap, x)
        for t, tx in ((tip, x_tip), (yours, x_yours)):
            y = max(top + 8, min(anchor.winfo_rooty() - 20, bottom - t.winfo_reqheight() - 8))
            t.geometry(f"+{int(tx)}+{int(y)}")
        self._tip, self._tip2 = tip, yours
        self._guard_tip()

    # ───── compare: your own gear, for holding Alt over an item ─────
    def _can_compare(self) -> bool:
        me = self.app.my_char
        return me is not None and me.key != self.char.key

    def _want_mine(self):
        """Load your profile in the background (usually cached) so Alt-compare is instant."""
        if not self._can_compare():
            return
        self.app.api.fetch_profile(self.app.my_char,
                                   lambda ch, p, e: self.app.inbox.put(("my_profile", self, p, e)))

    def mine_ready(self, prof: Profile | None, err: str | None):
        """(main thread) your profile arrived (cached copy, partial, then fresh)."""
        if prof is None and self._mine is not None:
            return
        self._mine = prof
        self._want_my_items()
        hover = getattr(self, "_hover_item", None)
        if self._compare and hover is not None and hover[1].winfo_exists():
            self._show_item_tip(*hover)

    def _want_my_items(self):
        """Your side of Alt-compare, ready before you ask: loaded once the profile on screen is complete, so it
        never slows that down."""
        mine = self._mine
        if self._ready and mine is not None and not mine.equipment_pending:
            for it in self._worn(mine):
                self._want_my_detail(it)

    def _my_item(self, it: Item) -> Item | None:
        return self._mine.gear.get(it.slot) if self._mine is not None else None

    def _want_my_detail(self, it: Item):
        key = ("me",) + self._dkey(it)
        if key in self._details or not it.slot_pos or not it.item_id:
            return
        self._details[key] = None

        def done(det, key=key):
            if threading.current_thread() is threading.main_thread():
                self.item_detail_ready(key, det)
            else:
                self.app.inbox.put(("item_detail", self, key, det))
        self.app.api.fetch_item_detail(self.app.my_char, it, done)

    def _alt_key(self, down: bool):
        self._alt_tk = down
        return "break"                               # no menu traversal on Alt

    def _alt_held(self) -> bool:
        from .desktop import alt_down
        state = alt_down()
        return self._alt_tk if state is None else state

    def _start_alt_poll(self):
        if self._alt_job is not None:                # keep _compare: enter() just set it
            self.frame.after_cancel(self._alt_job)
            self._alt_job = None

        def tick():
            self._alt_job = None
            hover = getattr(self, "_hover_item", None)
            if hover is None or not hover[1].winfo_exists():
                return
            held = self._alt_held()
            if held != self._compare:
                self._compare = held
                if self._can_compare():
                    self._show_item_tip(*hover)
            self._alt_job = self.frame.after(50, tick)
        self._alt_job = self.frame.after(50, tick)

    def _stop_alt_poll(self):
        if self._alt_job is not None:
            try:
                self.frame.after_cancel(self._alt_job)
            except tk.TclError:
                pass
            self._alt_job = None
        self._compare = False

    def _tab_skills(self, p: Profile):
        if p.equipment_error:
            tk.Label(self.body, text="Couldn't load skills", bg=BG, fg=RED,
                     font=self.app.f_small).pack(anchor="w", pady=8)
            return
        for cat, title in SKILL_CATEGORIES:
            skills = p.skills_in(cat)
            if not skills:
                continue
            self._section(self.body, title)
            grid = tk.Frame(self.body, bg=BG)
            grid.pack(fill="x")
            grid.columnconfigure(0, weight=1, uniform="s")
            grid.columnconfigure(1, weight=1, uniform="s")
            for i, s in enumerate(skills):
                cell = tk.Frame(grid, bg=SURFACE, padx=8, pady=5)
                cell.grid(row=i // 2, column=i % 2, sticky="nsew", padx=(0 if i % 2 == 0 else 4, 0 if i % 2 else 4),
                          pady=2)
                stigma_on = s.category == "Dp" and s.level >= 1           # a Stigma in use: gold around the icon
                icon = self._icon(cell, s.icon, 30, border=self.SKILL_NUM if stigma_on else BORDER)
                icon.pack(side="left")
                txt = tk.Frame(cell, bg=SURFACE)
                txt.pack(side="left", fill="x", expand=True, padx=8)
                name = self._fit_label(txt, s.name, self.app.f_small,   # the skill's own tooltip shows the name
                                       tip=skilldata.describe(s.skill_id, 1, s.name, p.class_name) is None, bg=SURFACE,
                                       fg=FG)
                name.pack(fill="x")
                shown = s.level or s.category == "Dp"                   # Stigmas show Level 0 too
                sub_lb = tk.Label(txt, text=f"Level {s.level}" if shown else "", bg=SURFACE, fg=FG_DIM,
                                  font=self.app.f_tiny, anchor="w")
                sub_lb.pack(fill="x")
                self._skill_tip(s, p.class_name, [cell, txt, name, sub_lb])

    # the game's skill window, as a tooltip: name, level and the icon on top; the text with the numbers that grow
    # per level in gold; then label / value rows (cooldown, MP)
    SKILL_TIP_W = 320
    SKILL_HEAD_BG = "#20232a"

    def _skill_tip(self, s, cls: str, widgets):
        """Hover: the skill's description at this character's level (from MetaBot.GG)."""
        info = skilldata.describe(s.skill_id, s.level or 1, s.name, cls)
        if info is None:
            return
        self._hover_tip(widgets, s.name, [], show=lambda cell, s=s, info=info: self._show_skill_tip(s, info, cell))

    def _show_skill_tip(self, s, info, anchor):
        self._hide_tip()
        f = self.app
        tip, outer = self._new_tip()
        outer.configure(width=self.SKILL_TIP_W)
        hb = self.SKILL_HEAD_BG

        # header: name, "Level N" in gold, icon on the right (gold frame for a Stigma in use)
        head = tk.Frame(outer, bg=hb, padx=12, pady=10)
        head.pack(fill="x")
        stigma_on = s.category == "Dp" and s.level >= 1
        icon_box = tk.Frame(head, bg=self.SKILL_NUM if stigma_on else BORDER, padx=1, pady=1)
        icon_box.pack(side="right", anchor="n", padx=(10, 0))
        icon = tk.Label(icon_box, bg=SURFACE_2, image=self._blank(44), bd=0)
        icon.pack()
        self._set_image(icon, s.icon, 44)
        left = tk.Frame(head, bg=hb)
        left.pack(side="left", fill="x", expand=True)
        tk.Label(left, text=s.name, bg=hb, fg=FG, font=f.f_title, anchor="w").pack(fill="x")
        if s.level or s.category == "Dp":                        # Stigmas show Level 0 too
            tk.Label(left, text=f"Level {s.level}", bg=hb, fg=self.SKILL_NUM if s.level else FG_DIM,
                     font=f.f_sbold, anchor="w").pack(fill="x", pady=(3, 0))

        # description, numbers that scale with level in gold
        body = tk.Frame(outer, bg=self.TIP_BG, padx=12, pady=10)
        body.pack(fill="x")
        self._rich_text(body, info.text, info.spans, bg=self.TIP_BG, width_px=self.SKILL_TIP_W - 26).pack(fill="x")

        # label / value rows
        rows = [(k, v) for k, v in (("Cooldown", info.cooldown), ("MP Cost", info.mp)) if v]
        if rows:
            tk.Frame(body, bg=BORDER, height=1).pack(fill="x", pady=(10, 6))
            for k, v in rows:
                r = tk.Frame(body, bg=self.TIP_BG)
                r.pack(fill="x", pady=1)
                tk.Label(r, text=k, bg=self.TIP_BG, fg=FG, font=f.f_small).pack(side="left")
                tk.Label(r, text=v, bg=self.TIP_BG, fg=FG, font=f.f_small).pack(side="right")

        # credit
        foot = tk.Frame(outer, bg=self.TIP_BG, padx=12)
        foot.pack(fill="x", pady=(0, 8))
        tk.Frame(foot, bg=BORDER, height=1).pack(fill="x", pady=(0, 6))
        tk.Label(foot, text=f"Info provided by {skilldata.SOURCE}", bg=self.TIP_BG, fg=FG_FAINT, font=f.f_tiny,
                 anchor="w").pack(fill="x")
        self._place_tip(tip, anchor)

    def _tab_daevanion(self, p: Profile):
        if not p.boards:
            tk.Label(self.body, text="No boards opened", bg=BG, fg=FG_DIM,
                     font=self.app.f_small).pack(anchor="w", pady=8)
            return
        total_open = sum(b.opened for b in p.boards)
        total = sum(b.total for b in p.boards)
        self._section(self.body, "Daevanion boards", f"{total_open}/{total} nodes")
        # the boards to pick from, three to a row
        grid = tk.Frame(self.body, bg=BG)
        grid.pack(fill="x")
        for c in range(3):
            grid.columnconfigure(c, weight=1, uniform="b")
        self._chips: dict[int, tk.Frame] = {}
        for i, b in enumerate(p.boards):
            chip = tk.Frame(grid, bg=SURFACE, padx=8, pady=6, cursor="hand2", highlightthickness=1,
                            highlightbackground=BG, highlightcolor=BG)
            chip.grid(row=i // 3, column=i % 3, sticky="nsew", padx=(0 if i % 3 == 0 else 3, 0), pady=3)
            icon = self._icon(chip, b.icon, 24)
            icon.pack(side="left")
            mid = tk.Frame(chip, bg=SURFACE)
            mid.pack(side="left", fill="x", expand=True, padx=(8, 0))
            name = self._fit_label(mid, b.name, self.app.f_sbold, tip=False, bg=SURFACE, fg=FG)
            name.pack(fill="x")
            count = tk.Label(mid, text=f"{b.opened}/{b.total}  ·  {b.percent}%", bg=SURFACE, fg=FG_DIM,
                             font=self.app.f_tiny, anchor="w")
            count.pack(fill="x")
            bar = tk.Canvas(mid, height=4, bg=SURFACE, highlightthickness=0)
            bar.pack(fill="x", pady=(3, 0))
            bar.bind("<Configure>", lambda e, cv=bar, pct=b.percent: self._bar(cv, e.width, pct, 4))
            for w in (chip, icon, *icon.winfo_children(), mid, name, count, bar):
                w.bind("<Button-1>", lambda e, bid=b.board_id: self._pick_board(bid))
            self._chips[b.board_id] = chip
        self._board_area = tk.Frame(self.body, bg=BG)
        self._board_area.pack(fill="x", pady=(8, 0))
        self._paint_chips()
        self._draw_board_area()
        if self.tab == "Daevanion":                      # (not while the tab is built in the background)
            self._want_board(self._board_sel())

    # ───── Daevanion: one board drawn like the game's grid ─────
    def _board_sel(self) -> int:
        p = self.profile
        boards = p.boards if p else []
        want = self.app.cfg.get("daevanion_board")
        for b in boards:
            if b.name == want:
                return b.board_id
        return boards[0].board_id if boards else 0

    def _board(self, board_id: int):
        return next((b for b in (self.profile.boards if self.profile else []) if b.board_id == board_id), None)

    def _pick_board(self, board_id: int):
        b = self._board(board_id)
        if b is None:
            return
        self.app.cfg["daevanion_board"] = b.name
        self._paint_chips()
        self._draw_board_area()
        self._want_board(board_id)

    def _paint_chips(self):
        sel = self._board_sel()
        for bid, chip in getattr(self, "_chips", {}).items():
            try:
                col = ACCENT if bid == sel else BG
                chip.configure(highlightbackground=col, highlightcolor=col)
            except tk.TclError:
                pass

    def _want_board(self, board_id: int):
        b = self._board(board_id)
        if b is None or board_id in self._boards:
            return
        self._boards[board_id] = None                       # asked for

        def done(raw, bid=board_id):
            if threading.current_thread() is threading.main_thread():
                self.board_ready(bid, raw)
            else:
                self.app.inbox.put(("board", self, bid, raw))
        self.app.api.fetch_board(self.char, board_id, b.opened, done)

    def board_ready(self, board_id: int, raw):
        """(main thread) a board's layout arrived."""
        self._boards[board_id] = raw if raw is not None else False
        if board_id == self._board_sel():
            self._draw_board_area()

    def _draw_board_area(self):
        area = getattr(self, "_board_area", None)
        try:
            if area is None or not area.winfo_exists():
                return
        except tk.TclError:
            return
        for w in area.winfo_children():
            w.destroy()
        raw = self._boards.get(self._board_sel())
        if not raw:
            text = "Couldn't load this board" if raw is False else "Loading board…"
            tk.Label(area, text=text, bg=BG, fg=FG_DIM if raw is None else RED, font=self.app.f_small,
                     height=6).pack(fill="x")
            self._refresh_scroll()
            return
        d = parse_board(raw)
        cv = tk.Canvas(area, bg=BG, highlightthickness=0, height=360)
        cv.pack(fill="x")
        cv.bind("<Configure>", lambda e, cv=cv, d=d: self._paint_board(cv, d, e.width))
        cv.bind("<Motion>", lambda e, cv=cv, d=d: self._board_hover(cv, d, e))
        cv.bind("<Leave>", lambda e: (setattr(self, "_node_tip", None), self._hide_tip()))
        self._board_view = (cv, d)
        for title, effects in (("Stat bonuses", d.stat_effects), ("Skill bonuses", d.skill_effects)):
            if not effects:
                continue
            self._section(area, title, str(len(effects)))
            grid = tk.Frame(area, bg=BG)
            grid.pack(fill="x")
            for c in range(2):
                grid.columnconfigure(c, weight=1, uniform="e")
            for i, e in enumerate(effects):
                tk.Label(grid, text=e, bg=SURFACE, fg=FG, font=self.app.f_small, anchor="w", padx=10, pady=4).grid(
                    row=i // 2, column=i % 2, sticky="nsew", padx=(0 if i % 2 == 0 else 3, 0), pady=1)
        self._refresh_scroll()

    def _refresh_scroll(self):
        try:
            self.body_root.update_idletasks()
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        except tk.TclError:
            pass

    NODE_START = "#e8c46a"

    @staticmethod
    def _blend(c1: str, c2: str, t: float) -> str:
        """c1 mixed toward c2 by t (0 = c1, 1 = c2)."""
        a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
        b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
        return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b))

    @staticmethod
    def _board_geometry(d, width: int) -> tuple[float, float, float]:
        """(x, y) of grid cell (1, 1) and the cell size: the board cropped to where its nodes are (the game's
        15x15 grid has empty outer rows), as large as fits, centred."""
        rows = [n.row for n in d.nodes] or [1]
        cols = [n.col for n in d.nodes] or [1]
        r0, c0 = min(rows), min(cols)
        nr, nc = max(rows) - r0 + 1, max(cols) - c0 + 1
        cell = min(max(width, 200) / nc, 460 / max(nr, nc), 40)
        ox = (width - nc * cell) / 2 - (c0 - 1) * cell
        oy = 4 - (r0 - 1) * cell
        return ox, oy, cell

    def _paint_board(self, cv: tk.Canvas, d, width: int):
        """The grid: links between neighbouring nodes (gold where both are open), then the nodes, by grade."""
        ox, oy, cell = self._board_geometry(d, width)
        rows = [n.row for n in d.nodes] or [1]
        cv.configure(height=int((max(rows) - min(rows) + 1) * cell) + 8)
        cv.delete("all")
        at = {(n.row, n.col): n for n in d.nodes}
        lit = lambda n: n.opened or n.kind == "Start"            # noqa: E731
        centre = lambda r, c: (ox + (c - 0.5) * cell, oy + (r - 0.5) * cell)  # noqa: E731
        for (r, c), n in at.items():
            for nr, nc in ((r, c + 1), (r + 1, c)):
                m = at.get((nr, nc))
                if m is None:
                    continue
                on = lit(n) and lit(m)
                cv.create_line(*centre(r, c), *centre(nr, nc), fill=ACCENT if on else BORDER, width=3 if on else 2)
        for (r, c), n in at.items():
            x, y = centre(r, c)
            if n.kind == "Start":
                k = cell * 0.36
                cv.create_oval(x - k, y - k, x + k, y + k, fill=BG, outline=self.NODE_START, width=2)
                cv.create_oval(x - k / 2.4, y - k / 2.4, x + k / 2.4, y + k / 2.4, fill=self.NODE_START, outline="")
                continue
            col = GRADE_COLORS.get(n.grade, FG_DIM)
            fill = col if n.opened else self._blend(col, BG, 0.78)
            line = self._blend(col, "#ffffff", 0.35) if n.opened else self._blend(col, BG, 0.45)
            if n.kind == "SkillLevel":                               # skill nodes: diamonds
                k = cell * 0.36
                cv.create_polygon(x, y - k, x + k, y, x, y + k, x - k, y, fill=fill, outline=line, width=1.5)
            else:                                                    # stat nodes: rounded squares
                k = cell * 0.27
                round_rect(cv, x - k, y - k, x + k, y + k, max(2, k * 0.35), fill=fill, outline=line, width=1.5)

    def _board_hover(self, cv: tk.Canvas, d, e):
        ox, oy, cell = self._board_geometry(d, cv.winfo_width())
        c, r = int((e.x - ox) // cell) + 1, int((e.y - oy) // cell) + 1
        node = next((n for n in d.nodes if n.row == r and n.col == c), None)
        if node is getattr(self, "_node_tip", None):
            return
        self._node_tip = node
        if node is None:
            self._hide_tip()
            return
        state = "Opened" if node.opened else "Not opened"
        sub = state if node.kind == "Start" else f"{node.grade}  ·  {state}"
        lines = [("ok", e2) for e2 in node.effects] + [("dim", sub)]
        self._show_tip(cv, node.name or node.kind, lines, at=(e.x_root, e.y_root))

    @staticmethod
    def _bar(cv: tk.Canvas, width: int, pct: int, h: int = 8):
        cv.delete("all")
        round_rect(cv, 0, 0, width, h, h / 2, fill=SURFACE_2, outline="")
        if pct > 0:
            round_rect(cv, 0, 0, max(h, width * pct / 100), h, h / 2, fill=ACCENT, outline="")

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

    def demo_hover_node(self):
        """Screenshots only: hover the first opened node on the board shown."""
        cv, d = getattr(self, "_board_view", (None, None))
        node = next((n for n in (d.nodes if d else []) if n.opened and n.kind != "Start"), None)
        if node is None:
            return
        ox, oy, cell = self._board_geometry(d, cv.winfo_width())
        x, y = int(ox + (node.col - 0.5) * cell), int(oy + (node.row - 0.5) * cell)
        ev = type("E", (), {"x": x, "y": y, "x_root": cv.winfo_rootx() + x, "y_root": cv.winfo_rooty() + y})()
        self._board_hover(cv, d, ev)

    def demo_hover_first_stat(self):
        """Used by the screenshot run: show the first stat's tooltip as if hovered."""
        if getattr(self, "_first_tip", None):
            cell, title, lines, foot = self._first_tip
            self._show_tip(cell, title, lines, foot)

    # ───── tooltips ─────
    def _hover_tip(self, widgets, title: str, lines: list[str], foot: list[str] | None = None, show=None):
        """Highlight the cell and show its effects in a small popup while the mouse is over it.
        show(cell), when given, draws the popup instead of the plain one."""
        cell = widgets[0]

        def enter(_e):
            for w in widgets:
                w.config(bg=HOVER)
            if show is not None:
                show(cell)
            else:
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

    def _show_tip(self, anchor: tk.Widget, title: str, lines: list[str], foot: list[str] | None = None,
                  at: tuple[int, int] | None = None):
        """A small popup below anchor, or beside the screen point `at` (a node on a Daevanion board)."""
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
            if kind == "rich":                           # text with highlighted spans: (text, [(start, end), …])
                self._rich_text(box, *text).pack(fill="x")
                continue
            if kind == "h":                              # a section heading inside the tooltip
                tk.Label(box, text=text, bg=SURFACE_2, fg=ACCENT, font=self.app.f_sbold, anchor="w").pack(
                    fill="x", pady=(6, 0))
            else:
                tk.Label(box, text=text, bg=SURFACE_2, font=self.app.f_small, anchor="w", justify="left",
                         wraplength=320, fg={"dim": FG_FAINT, "ok": FG}.get(kind, FG_DIM)).pack(fill="x")
        for ln in foot or []:
            tk.Label(box, text=ln, bg=SURFACE_2, fg=FG_FAINT, font=self.app.f_tiny, anchor="w").pack(fill="x", pady=(3, 0))
        tip.update_idletasks()
        x = anchor.winfo_rootx() if at is None else at[0] + 16
        y = anchor.winfo_rooty() + anchor.winfo_height() + 4 if at is None else at[1] + 16
        # keep it on screen: flip above the cell near the bottom edge
        from .desktop import monitor_rect
        left, top, right, bottom = monitor_rect(anchor, anchor.winfo_rootx(), anchor.winfo_rooty())
        h = tip.winfo_reqheight()
        if y + h > bottom - 8:
            y = (anchor.winfo_rooty() if at is None else at[1] - 8) - h - 4
        y = max(top + 8, min(y, bottom - h - 8))               # a tall tooltip still fits on the monitor
        x = max(left + 8, min(x, right - tip.winfo_reqwidth() - 8))
        tip.geometry(f"+{x}+{y}")
        self._tip = tip
        self._guard_tip()

    SKILL_NUM = "#f2b84b"        # numbers that grow with skill level (gold, like the game's skill window)

    def _rich_text(self, parent, text: str, spans, bg: str = SURFACE_2, width_px: int = 320) -> tk.Text:
        """Wrapped text with some spans in gold: a read-only Text sized to its wrapped lines."""
        font = self.app.f_small
        chars = max(20, width_px // max(1, font.measure("0")))
        t = tk.Text(parent, bg=bg, fg=FG, font=font, bd=0, highlightthickness=0, wrap="word", padx=0,
                    pady=0, cursor="arrow", width=chars, height=1)
        t.tag_configure("num", foreground=self.SKILL_NUM)
        pos = 0
        for a, b in sorted(spans):
            t.insert("end", text[pos:a])
            t.insert("end", text[a:b], "num")
            pos = b
        t.insert("end", text[pos:])
        t.configure(height=wrapped_lines(text, font.measure, chars * font.measure("0") - 4), state="disabled")
        return t

    def _guard_tip(self):
        """A safety net for tooltips: gone once the pointer is off the tracker or the window is hidden, even if
        the hover-out event never came (a fast move out, a click into the game)."""
        if getattr(self, "_tip_guard", None) is not None:
            return
        root = self.app.root

        def tick():
            self._tip_guard = None
            if getattr(self, "_tip", None) is None:
                return
            try:
                x, y = root.winfo_pointerxy()
                over = root.winfo_rootx() <= x < root.winfo_rootx() + root.winfo_width() and \
                    root.winfo_rooty() <= y < root.winfo_rooty() + root.winfo_height()
                shown = root.state() not in ("withdrawn", "iconic")
            except tk.TclError:
                return
            if not (over and shown):
                self._hover_item = None
                self._stop_alt_poll()
                self._hide_tip()
                return
            self._tip_guard = root.after(150, tick)
        self._tip_guard = root.after(150, tick)

    def _hide_tip(self):
        for attr in ("_tip", "_tip2"):
            tip = getattr(self, attr, None)
            if tip is not None:
                try:
                    tip.destroy()
                except tk.TclError:
                    pass
                setattr(self, attr, None)

    def _tab_cosmetics(self, p: Profile):
        if p.equipment_error:
            tk.Label(self.body, text="Couldn't load cosmetics", bg=BG, fg=RED,
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
            tk.Label(self.body, text="No titles", bg=BG, fg=FG_DIM, font=self.app.f_small).pack(anchor="w")
        order = {"attack": 0, "offense": 0, "defense": 1}          # always Offense, Defense, Other
        for t in sorted(p.titles, key=lambda t: order.get((t.category or "").lower(), 2)):
            card = tk.Frame(self.body, bg=SURFACE, padx=12, pady=8)
            card.pack(fill="x", pady=3)
            top = tk.Frame(card, bg=SURFACE)
            top.pack(fill="x")
            tk.Label(top, text=t.name, bg=SURFACE, fg=GRADE_COLORS.get(t.grade, FG), font=self.app.f_bold).pack(
                side="left")
            label = {0: "Offense", 1: "Defense"}.get(order.get((t.category or "").lower(), 2), "Other")
            tk.Label(top, text=label, bg=SURFACE_2, fg=FG_DIM, font=self.app.f_tiny, padx=6).pack(
                side="left", padx=8)
            if t.owned_percent is not None:
                tk.Label(top, text=f"Owned by {t.owned_percent}% of players", bg=SURFACE, fg=FG_FAINT,
                         font=self.app.f_tiny).pack(side="right")
            for eff in t.effects:
                tk.Label(card, text=f"•  {eff}", bg=SURFACE, fg=FG_DIM, font=self.app.f_small, anchor="w").pack(
                    fill="x")
