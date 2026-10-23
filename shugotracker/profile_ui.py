"""In-app character profile (gear, skills, Daevanion, stats, cosmetics, titles), styled like Shugo.GG's."""
from __future__ import annotations

import time
import tkinter as tk
import webbrowser
from typing import TYPE_CHECKING

from .aion2api import REGION_LABELS, Character
from .profile import GEAR_ACCESSORIES, GEAR_ARCANA, GEAR_MAIN, SKILL_CATEGORIES, Item, Profile
from .search_ui import (ACCENT, ASMO, BG, BORDER, CLASS_COLORS, ELYOS, FG, FG_DIM, FG_FAINT, GRADE_COLORS, HOVER,
                        LEGION, PAD, RED, SKEL_A, SKEL_B, SURFACE, SURFACE_2, fmt_int, round_rect)

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
        sb = tk.Scrollbar(wrap, orient="vertical", command=self.canvas.yview, width=10)
        sb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.configure(yscrollcommand=sb.set)
        self.body = tk.Frame(self.canvas, bg=BG)
        self._win = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.body.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._win, width=e.width - 6))
        self.app.root.bind_all("<MouseWheel>", self._wheel)

    def _wheel(self, e):
        try:
            self.canvas.yview_scroll(int(-e.delta / 40) or (-1 if e.delta > 0 else 1), "units")
        except tk.TclError:
            pass

    def destroy(self):
        self.app.root.unbind_all("<MouseWheel>")
        self.frame.destroy()

    # ───── state ─────
    def set_profile(self, prof: Profile | None, err: str | None):
        self.loading = False
        self.profile, self.error = prof, err
        self._paint_hero()
        self.render()

    def reload(self):
        self.app.api.forget(self.char)
        self.loading, self.profile, self.error = True, None, None
        self.render()
        self.app.api.fetch_profile(self.char, lambda ch, p, e: self.app.inbox.put(("profile", ch, p, e)))

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
    def render(self):
        for name, lb in self.tab_labels.items():
            lb.config(fg=ACCENT if name == self.tab else FG_DIM)
        for w in self.body.winfo_children():
            w.destroy()
        self._img_slots = [s for s in self._img_slots if s[0] is self.portrait]
        self._skel_items = []
        self.canvas.yview_moveto(0)
        if self.loading:
            self._skeleton()
            return
        if self.error or not self.profile:
            box = tk.Frame(self.body, bg=BG)
            box.pack(fill="x", pady=30)
            tk.Label(box, text="Couldn't load this profile", bg=BG, fg=FG, font=self.app.f_name).pack()
            tk.Label(box, text=self.error or "", bg=BG, fg=FG_FAINT, font=self.app.f_small, wraplength=420).pack(pady=4)
            retry = tk.Label(box, text="Try again", bg=ACCENT, fg=BG, font=self.app.f_body, padx=12, pady=4,
                             cursor="hand2")
            retry.pack(pady=8)
            retry.bind("<Button-1>", lambda e: self.reload())
            return
        getattr(self, f"_tab_{self.tab.lower()}")(self.profile)

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
        for title, stats in (("Primary stats", p.primary_stats), ("Deity stats", p.deity_stats)):
            if not stats:
                continue
            self._section(self.body, title)
            grid = tk.Frame(self.body, bg=BG)
            grid.pack(fill="x")
            grid.columnconfigure(0, weight=1, uniform="t")
            grid.columnconfigure(1, weight=1, uniform="t")
            for i, s in enumerate(stats):
                cell = tk.Frame(grid, bg=SURFACE, padx=10, pady=6)
                cell.grid(row=i // 2, column=i % 2, sticky="nsew", padx=(0 if i % 2 == 0 else 4, 0 if i % 2 else 4),
                          pady=2)
                top = tk.Frame(cell, bg=SURFACE)
                top.pack(fill="x")
                tk.Label(top, text=s.name, bg=SURFACE, fg=FG, font=self.app.f_small, anchor="w").pack(side="left")
                tk.Label(top, text=str(s.value), bg=SURFACE, fg=ACCENT if s.value else FG_FAINT,
                         font=self.app.f_bold).pack(side="right")
                for eff in s.effects:
                    tk.Label(cell, text=eff, bg=SURFACE, fg=FG_FAINT, font=self.app.f_tiny, anchor="w").pack(fill="x")

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
