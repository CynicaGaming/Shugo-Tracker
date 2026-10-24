"""In-app character profile (gear, skills, Daevanion, stats, cosmetics, titles), styled like Shugo.GG's."""
from __future__ import annotations

import time
from dataclasses import asdict
import tkinter as tk
import webbrowser
from typing import TYPE_CHECKING

from .aion2api import REGION_LABELS, Character
from .profile import GEAR_ACCESSORIES, GEAR_ARCANA, GEAR_MAIN, SKILL_CATEGORIES, Item, Profile
from .search_ui import (ACCENT, ASMO, BG, BORDER, CLASS_COLORS, ELYOS, FG, FG_DIM, FG_FAINT, GRADE_COLORS, HOVER,
                        LEGION, PAD, RED, SKEL_A, SKEL_B, SURFACE, SURFACE_2, fmt_int, round_rect, ThinScrollbar)

if TYPE_CHECKING:
    from .search_ui import SearchWindow

ICON = 36
HERO = 84


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
        bar = tk.Frame(self.frame, bg=BG)
        bar.pack(fill="x", padx=PAD, pady=(PAD, 6))
        back = tk.Label(bar, text="←  Back", bg=BG, fg=FG_DIM, font=f.f_bold, cursor="hand2")
        back.pack(side="left")
        back.bind("<Button-1>", lambda e: f.close_profile())
        self.star = tk.Label(bar, bg=BG, font=f.f_small, cursor="hand2", padx=6)
        self.star.pack(side="right")
        self.star.bind("<Button-1>", lambda e: f.toggle_favorite(self.char))
        shugo = tk.Label(bar, text="Shugo.GG ↗", bg=BG, fg=FG_DIM, font=f.f_small, cursor="hand2", padx=6)
        shugo.pack(side="right")
        shugo.bind("<Button-1>", lambda e: webbrowser.open(self.char.shugo_url))
        refresh = tk.Label(bar, text="⟳ Refresh", bg=BG, fg=FG_DIM, font=f.f_small, cursor="hand2", padx=6)
        refresh.pack(side="right")
        refresh.bind("<Button-1>", lambda e: self.reload())
        self.paint_star()

        hero = tk.Frame(self.frame, bg=SURFACE, highlightthickness=1, highlightbackground=BORDER)
        hero.pack(fill="x", padx=PAD, pady=(0, 8))
        inner = tk.Frame(hero, bg=SURFACE)
        inner.pack(fill="x", padx=12, pady=12)
        self.portrait = tk.Label(inner, bg=SURFACE_2, image=self._blank(HERO), bd=0)
        self.portrait.pack(side="left")
        mid = tk.Frame(inner, bg=SURFACE)
        mid.pack(side="left", fill="x", expand=True, padx=(12, 0))
        top = tk.Frame(mid, bg=SURFACE)
        top.pack(fill="x", anchor="w")
        self.h_name = tk.Label(top, bg=SURFACE, fg=FG, font=f.f_big, anchor="w")
        self.h_name.pack(side="left")
        self.h_legion = tk.Label(top, bg=SURFACE, fg=LEGION, font=f.f_title, anchor="w")
        self.h_legion.pack(side="left", padx=(6, 0), pady=(4, 0))
        self.h_faction = tk.Label(top, bg=SURFACE, font=f.f_tiny, padx=6, pady=1, highlightthickness=1)
        self.h_faction.pack(side="left", padx=(8, 0), pady=(6, 0))
        self.h_line = tk.Label(mid, bg=SURFACE, fg=FG_DIM, font=f.f_small, anchor="w")
        self.h_line.pack(fill="x")
        self.h_line2 = tk.Label(mid, bg=SURFACE, fg=FG_FAINT, font=f.f_small, anchor="w")
        self.h_line2.pack(fill="x")
        right = tk.Frame(inner, bg=SURFACE)
        right.pack(side="right", anchor="n")
        self.h_cp = tk.Label(right, bg=SURFACE, fg=ACCENT, font=f.f_big, anchor="e")
        self.h_cp.pack(anchor="e")
        tk.Label(right, text="COMBAT POWER", bg=SURFACE, fg=FG_FAINT, font=f.f_tiny, anchor="e").pack(anchor="e")
        self.h_gs = tk.Label(right, bg=SURFACE, fg=FG, font=f.f_bold, anchor="e")
        self.h_gs.pack(anchor="e", pady=(6, 0))
        tk.Label(right, text="GEAR SCORE", bg=SURFACE, fg=FG_FAINT, font=f.f_tiny, anchor="e").pack(anchor="e")
        self._paint_hero()

    def _build_tabs(self):
        f = self.app
        bar = tk.Frame(self.frame, bg=BG)
        bar.pack(fill="x", padx=PAD)
        self.tab_labels = {}
        for name in self.TABS:
            lb = tk.Label(bar, text=name, bg=BG, font=f.f_bold, padx=8, pady=6, cursor="hand2")
            lb.pack(side="left")
            lb.bind("<Button-1>", lambda e, n=name: self.show_tab(n))
            self.tab_labels[name] = lb
        tk.Frame(self.frame, bg=BORDER, height=1).pack(fill="x", padx=PAD)

    def _build_body(self):
        wrap = tk.Frame(self.frame, bg=BG)
        wrap.pack(fill="both", expand=True, padx=(PAD, 4), pady=(6, PAD))
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
        self.star.config(text="★ Favorite" if fav else "☆ Favorite", fg=ACCENT if fav else FG_DIM)

    def _paint_hero(self):
        c, p = self.char, self.profile
        name = p.name if p and p.name else c.name
        race = p.race if p and p.race else c.race
        cls = (p.class_name if p and p.class_name else c.class_name) or "Unknown"
        level = p.level if p and p.level else c.level
        server = p.server_name if p and p.server_name else c.server_name
        self.h_name.config(text=name)
        col = ELYOS if race == 1 else ASMO if race == 2 else FG_DIM
        self.h_faction.config(text={1: "Elyos", 2: "Asmodian"}.get(race, "?"), fg=col, bg=SURFACE_2,
                              highlightbackground=col)
        self.h_line.config(text=f"{cls}  ·  Lv {level}  ·  {server} ({REGION_LABELS.get(c.region, c.region)})",
                           fg=CLASS_COLORS.get(cls, FG_DIM))
        legion = (p.legion if p else None) or c.legion
        self.h_legion.config(text=f"<{legion}>" if legion else "")
        bits = []
        if p and p.title:
            bits.append(f"“{p.title}”")
        self.h_line2.config(text="   ".join(bits))
        cp = p.combat_power if p else c.combat_power
        gs = p.gear_score if p else c.gear_score
        self.h_cp.config(text=fmt_int(cp) if cp is not None or not self.loading else "…")
        self.h_gs.config(text=fmt_int(gs) if gs is not None or not self.loading else "…")
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
            lb.config(fg=ACCENT if name == self.tab else FG_DIM)
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
        cv = tk.Canvas(self.body, bg=BG, height=420, highlightthickness=0)
        cv.pack(fill="x")
        for i in range(8):
            y = i * 52
            for (x0, x1, h, tone) in ((0, ICON, ICON, 0), (48, 220, 12, 0), (48, 150, 10, 1)):
                yy = y + (0 if tone == 0 and x0 == 0 else 6 if x0 and tone == 0 else 24)
                rid = round_rect(cv, x0, yy, x1, yy + h, 5, fill=SKEL_A, outline="")
                self._skel_items.append((cv, rid, tone))

    def shimmer(self):
        phase = (time.monotonic() * 1.6) % 2.0
        for cv, rid, tone in self._skel_items:
            try:
                cv.itemconfigure(rid, fill=(SKEL_B if (phase < 1.0) ^ bool(tone) else SKEL_A))
            except tk.TclError:
                pass

    # helpers
    def _section(self, parent, title: str, extra: str = ""):
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", pady=(10, 4))
        tk.Label(row, text=title.upper(), bg=BG, fg=FG_DIM, font=self.app.f_tiny).pack(side="left")
        if extra:
            tk.Label(row, text=extra, bg=BG, fg=FG_FAINT, font=self.app.f_tiny).pack(side="left", padx=6)

    def _icon(self, parent, url: str | None, size: int = ICON, border: str = BORDER):
        box = tk.Frame(parent, bg=border, padx=1, pady=1)
        lb = tk.Label(box, bg=SURFACE_2, image=self._blank(size), bd=0)
        lb.pack()
        self._set_image(lb, url, size)
        return box

    def _item_row(self, parent, item: Item | None, label: str):
        row = tk.Frame(parent, bg=SURFACE, padx=8, pady=6)
        row.pack(fill="x", pady=2)
        if item is None:
            self._icon(row, None).pack(side="left")
            tk.Label(row, text=label, bg=SURFACE, fg=FG_FAINT, font=self.app.f_small, anchor="w").pack(
                side="left", padx=8)
            tk.Label(row, text="empty", bg=SURFACE, fg=FG_FAINT, font=self.app.f_tiny).pack(side="right")
            return
        col = GRADE_COLORS.get(item.grade, FG)
        self._icon(row, item.icon, border=col).pack(side="left")
        txt = tk.Frame(row, bg=SURFACE)
        txt.pack(side="left", fill="x", expand=True, padx=8)
        tk.Label(txt, text=item.name, bg=SURFACE, fg=col, font=self.app.f_bold, anchor="w").pack(fill="x")
        sub = f"{label}  ·  {item.grade}" + (f"  ·  Lv {item.level}" if item.level else "")
        tk.Label(txt, text=sub, bg=SURFACE, fg=FG_FAINT, font=self.app.f_tiny, anchor="w").pack(fill="x")
        if item.enchant or item.exceed:
            ench = f"+{item.enchant}" + (f"  ✦{item.exceed}" if item.exceed else "")
            tk.Label(row, text=ench, bg=SURFACE, fg=ACCENT if item.enchant >= 10 else FG, font=self.app.f_bold).pack(
                side="right")

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
            tk.Label(self.body, text="Gear couldn't be loaded — try Refresh.", bg=BG, fg=RED,
                     font=self.app.f_small).pack(anchor="w", pady=8)
            return
        left, right = self._columns()
        self._section(left, "Equipment")
        for slot in GEAR_MAIN:
            it = p.gear.get(slot)
            self._item_row(left, it, it.slot_label if it else slot)
        self._section(right, "Accessories")
        for slot in GEAR_ACCESSORIES:
            it = p.gear.get(slot)
            self._item_row(right, it, it.slot_label if it else slot)
        arc = [p.gear.get(s) for s in GEAR_ARCANA]
        if any(arc):
            self._section(self.body, "Arcana")
            for it in arc:
                if it:
                    self._item_row(self.body, it, "Arcana")

    def _tab_skills(self, p: Profile):
        if p.equipment_error:
            tk.Label(self.body, text="Skills couldn't be loaded — try Refresh.", bg=BG, fg=RED,
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
                tk.Label(txt, text=s.name, bg=SURFACE, fg=FG if s.acquired else FG_FAINT, font=self.app.f_small,
                         anchor="w").pack(fill="x")
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
            tk.Label(top, text=b.name, bg=SURFACE, fg=FG, font=self.app.f_bold).pack(side="left")
            tk.Label(top, text=f"{b.opened}/{b.total}  ·  {b.percent}%", bg=SURFACE, fg=FG_DIM,
                     font=self.app.f_small).pack(side="right")
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
                name = tk.Label(top, text=s.name, bg=SURFACE, fg=FG, font=self.app.f_small, anchor="w")
                name.pack(side="left")
                val = tk.Label(top, text=str(s.value), bg=SURFACE, fg=ACCENT if s.value else FG_FAINT,
                               font=self.app.f_bold)
                val.pack(side="right")
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
            tk.Label(box, text=ln, bg=SURFACE_2, fg=FG_DIM, font=self.app.f_small, anchor="w").pack(fill="x")
        for ln in foot or []:
            tk.Label(box, text=ln, bg=SURFACE_2, fg=FG_FAINT, font=self.app.f_tiny, anchor="w").pack(fill="x", pady=(3, 0))
        tip.update_idletasks()
        x = anchor.winfo_rootx()
        y = anchor.winfo_rooty() + anchor.winfo_height() + 4
        # keep it on screen: flip above the cell near the bottom edge
        if y + tip.winfo_reqheight() > anchor.winfo_screenheight() - 8:
            y = anchor.winfo_rooty() - tip.winfo_reqheight() - 4
        x = min(x, anchor.winfo_screenwidth() - tip.winfo_reqwidth() - 8)
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
            tk.Label(self.body, text="Cosmetics couldn't be loaded — try Refresh.", bg=BG, fg=RED,
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
                tk.Label(top, text=f"{t.owned_percent}% of players own", bg=SURFACE, fg=FG_FAINT,
                         font=self.app.f_tiny).pack(side="right")
            for eff in t.effects:
                tk.Label(card, text=f"•  {eff}", bg=SURFACE, fg=FG_DIM, font=self.app.f_small, anchor="w").pack(
                    fill="x")
