"""Always-on-top tkinter overlay: every player in render range, split into collapsible Enemies / Allies sections."""
from __future__ import annotations

import time
import tkinter as tk
import webbrowser
from typing import Callable

from . import servers as sv
from .tracker import ALLY, ENEMY, UNKNOWN, Player, Tracker

BG = "#14161c"
BG_HEAD = "#1d2029"
BG_SECTION = "#191c24"
BG_ROW_HOVER = "#262a36"
FG = "#e6e6e6"
FG_DIM = "#8a8f9c"
RED = "#ff5c5c"
AMBER = "#f2b84b"
GREEN = "#6fd38a"
BLUE = "#7fb8ff"
ELYOS = "#7fb8ff"
ASMO = "#c58cff"
FONT = ("Segoe UI", 9)
FONT_B = ("Segoe UI Semibold", 9)
FONT_HEAD = ("Segoe UI Semibold", 9)
FONT_SMALL = ("Segoe UI", 8)

SECTIONS = [
    (ENEMY, "ENEMIES", RED),
    (ALLY, "ALLIES", BLUE),
    (UNKNOWN, "UNIDENTIFIED", FG_DIM),
]
COLS = (("", 2), ("Name", 14), ("Class", 10), ("GS", 6), ("CP", 7))


def fmt(n: int | None) -> str:
    if n is None:
        return "—"
    return f"{n/1000:.1f}k" if n >= 10_000 else f"{n:,}"


class Overlay:
    def __init__(self, tracker: Tracker, cfg: dict, on_tick: Callable[[], None],
                 status: Callable[[], str], on_close: Callable[[], None],
                 update_banner: Callable[[], str | None] = lambda: None,
                 on_update: Callable[[], bool] = lambda: False):
        self.tracker = tracker
        self.cfg = cfg
        self.on_tick = on_tick
        self.status = status
        self.on_close = on_close
        self.update_banner = update_banner
        self.on_update = on_update
        self.collapsed_sections: set[str] = set(cfg.get("collapsed_sections", []))
        self.minimized = False
        self._rendered_version = -1
        self._last_render = 0.0
        self.max_height = int(cfg.get("max_height", 520))

        self.root = tk.Tk()
        self.root.title("Shugo Tracker")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        try:
            self.root.attributes("-alpha", float(cfg.get("opacity", 0.9)))
        except tk.TclError:
            pass
        x, y = cfg.get("position", [40, 200])
        self.root.geometry(f"+{int(x)}+{int(y)}")
        self.root.configure(bg=BG)

        # title bar
        self.head = tk.Frame(self.root, bg=BG_HEAD)
        self.head.pack(fill="x")
        self.banner = tk.Label(self.root, text="", bg="#23402d", fg="#c9f5d6", font=FONT_SMALL,
                               anchor="w", padx=6, pady=2, cursor="hand2")
        self.banner.bind("<Button-1>", lambda e: self._update_now())
        self._banner_text: str | None = None
        self.title = tk.Label(self.head, text="⚔ Shugo Tracker", bg=BG_HEAD, fg=FG, font=FONT_HEAD, padx=6, pady=3)
        self.title.pack(side="left")
        for txt, cmd in (("✕", self._close), ("–", self._toggle_minimize), ("⟲", self._clear)):
            b = tk.Label(self.head, text=txt, bg=BG_HEAD, fg=FG_DIM, font=FONT_HEAD, padx=5, cursor="hand2")
            b.pack(side="right")
            b.bind("<Button-1>", lambda e, c=cmd: c())
        for w in (self.head, self.title):
            w.bind("<ButtonPress-1>", self._drag_start)
            w.bind("<B1-Motion>", self._drag)

        # scrollable body
        self.wrap = tk.Frame(self.root, bg=BG)
        self.wrap.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(self.wrap, bg=BG, highlightthickness=0, bd=0, width=320, height=60)
        self.scroll = tk.Scrollbar(self.wrap, orient="vertical", command=self.canvas.yview, width=8)
        self.canvas.configure(yscrollcommand=self.scroll.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.body = tk.Frame(self.canvas, bg=BG)
        self._body_win = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.body.bind("<Configure>", lambda e: self._fit())
        self.root.bind_all("<MouseWheel>", self._wheel)

        self.foot = tk.Label(self.root, text="", bg=BG, fg=FG_DIM, font=FONT_SMALL, anchor="w", padx=6)
        self.foot.pack(fill="x")

        self.menu = tk.Menu(self.root, tearoff=0)
        self._menu_player: Player | None = None
        self.menu.add_command(label="Open on Shugo.GG", command=self._menu_open)
        self.menu.add_command(label="Retry lookup", command=self._menu_retry)
        self.menu.add_command(label="Copy name", command=self._menu_copy)

        self.root.after(100, self._loop)
        self.root.after(3000, self._keep_on_top)

    def run(self) -> None:
        self.root.mainloop()

    # ───── window plumbing ─────
    def _drag_start(self, e):
        self._dx, self._dy = e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y()

    def _drag(self, e):
        x, y = e.x_root - self._dx, e.y_root - self._dy
        self.root.geometry(f"+{x}+{y}")
        self.cfg["position"] = [x, y]

    def _keep_on_top(self):
        self.root.attributes("-topmost", True)
        self.root.lift()
        self.root.after(3000, self._keep_on_top)

    def _wheel(self, e):
        if self.scroll.winfo_ismapped():
            self.canvas.yview_scroll(int(-e.delta / 120) or (-1 if e.delta > 0 else 1), "units")

    def _fit(self):
        w = self.body.winfo_reqwidth()
        h = self.body.winfo_reqheight()
        self.canvas.configure(scrollregion=(0, 0, w, h), width=w, height=min(h, self.max_height))
        if h > self.max_height:
            if not self.scroll.winfo_ismapped():
                self.scroll.pack(side="right", fill="y")
        elif self.scroll.winfo_ismapped():
            self.scroll.pack_forget()
            self.canvas.yview_moveto(0)

    def _sync_banner(self):
        text = self.update_banner()
        if text == self._banner_text:
            return
        self._banner_text = text
        if text:
            self.banner.config(text=text)
            self.banner.pack(fill="x", after=self.head)
        else:
            self.banner.pack_forget()

    def _update_now(self):
        if self._banner_text and "restart" in self._banner_text:
            self.cfg["collapsed_sections"] = sorted(self.collapsed_sections)
            if self.on_update():
                self.root.destroy()

    def _close(self):
        self.cfg["collapsed_sections"] = sorted(self.collapsed_sections)
        self.on_close()
        self.root.destroy()

    def _toggle_minimize(self):
        self.minimized = not self.minimized
        if self.minimized:
            self.wrap.pack_forget()
            self.foot.pack_forget()
        else:
            self.wrap.pack(fill="both", expand=True)
            self.foot.pack(fill="x")
        self._rendered_version = -1

    def _toggle_section(self, key: str):
        self.collapsed_sections ^= {key}
        self.cfg["collapsed_sections"] = sorted(self.collapsed_sections)
        self._rendered_version = -1
        self._render()

    def _clear(self):
        self.tracker.clear()

    # ───── loop ─────
    def _loop(self):
        try:
            self.on_tick()
        finally:
            now = time.time()
            if (self.tracker.version != self._rendered_version and now - self._last_render > 0.4) \
                    or now - self._last_render > 2:
                self._render()
            self.root.after(100, self._loop)

    def _render(self):
        self._rendered_version = self.tracker.version
        self._last_render = time.time()
        groups = self.tracker.groups()
        n_enemy, n_ally = len(groups[ENEMY]), len(groups[ALLY])
        self.title.config(text=f"⚔ Shugo Tracker   {n_enemy} enemies · {n_ally} allies", fg=RED if n_enemy else FG)
        self.foot.config(text=self._footer())
        self._sync_banner()
        if self.minimized:
            return
        for w in self.body.winfo_children():
            w.destroy()
        for key, label, color in SECTIONS:
            players = groups[key]
            if key == UNKNOWN and not players:
                continue
            self._section(key, label, color, players)

    def _section(self, key: str, label: str, color: str, players: list[Player]):
        collapsed = key in self.collapsed_sections
        hdr = tk.Frame(self.body, bg=BG_SECTION, cursor="hand2")
        hdr.pack(fill="x", pady=(2, 0))
        arrow = "▸" if collapsed else "▾"
        extra = ""
        if key == ENEMY and players:
            cps = [p.lookup.combat_power for p in players if p.lookup.combat_power]
            if cps:
                extra = f"   top {fmt(max(cps))} CP"
        lb = tk.Label(hdr, text=f"{arrow} {label}  {len(players)}{extra}", bg=BG_SECTION, fg=color,
                      font=FONT_HEAD, anchor="w", padx=6, pady=2)
        lb.pack(fill="x")
        for w in (hdr, lb):
            w.bind("<Button-1>", lambda e, k=key: self._toggle_section(k))
        if collapsed:
            return
        if not players:
            tk.Label(self.body, text="  nobody in range", bg=BG, fg=FG_DIM, font=FONT_SMALL, anchor="w").pack(fill="x")
            return
        cols = tk.Frame(self.body, bg=BG)
        cols.pack(fill="x")
        for c, (txt, w) in enumerate(COLS):
            tk.Label(cols, text=txt, width=w, anchor="w", bg=BG, fg=FG_DIM, font=FONT_SMALL).grid(row=0, column=c)
        for p in players:
            self._row(p, key)

    def _footer(self) -> str:
        me = self.tracker.me
        parts = []
        if me.name:
            mine = me.name
            if me.lookup.combat_power:
                mine += f" {fmt(me.lookup.combat_power)} CP"
            parts.append(mine)
        elif me.server:
            parts.append(sv.label(me.server))
        else:
            parts.append("waiting for your character…")
        st = self.status()
        if st:
            parts.append(st)
        return "  ·  ".join(parts)

    def _row(self, p: Player, side: str):
        lk = p.lookup
        fr = tk.Frame(self.body, bg=BG, cursor="hand2")
        fr.pack(fill="x")
        fac = p.faction
        dot_color = ELYOS if fac == sv.ELYOS else ASMO if fac == sv.ASMODIAN else FG_DIM
        recent = p.last_combat and time.time() - p.last_combat < 15
        if p.dead:
            name_fg = FG_DIM
        else:
            name_fg = RED if side == ENEMY else BLUE if side == ALLY else FG
        if lk.status == "ok":
            gs, cp = fmt(lk.gear_score), fmt(lk.combat_power)
        elif lk.status == "queued":
            gs, cp = "…", "…"
        elif lk.status == "notfound":
            gs, cp = "n/a", "n/a"
        elif lk.status == "error":
            gs, cp = "err", "err"
        else:
            gs, cp = "", ""
        prefix = "✝" if p.dead else "⚡" if recent else ""
        name = prefix + p.name + (" ?" if lk.status == "ok" and lk.guessed else "")
        cls = lk.class_name or p.class_name or ""
        cells = [("●", 2, dot_color, FONT), (name[:16], 14, name_fg, FONT_B), (cls[:11], 10, FG_DIM, FONT),
                 (gs, 6, FG, FONT), (cp, 7, self._cp_color(lk.combat_power, side), FONT_B)]
        labels = []
        for col, (txt, w, fg, font) in enumerate(cells):
            lb = tk.Label(fr, text=txt, width=w, anchor="w", bg=BG, fg=fg, font=font)
            lb.grid(row=0, column=col)
            labels.append(lb)
        tip = self._tooltip(p)
        for w in [fr, *labels]:
            w.bind("<Button-1>", lambda e, pl=p: self._open(pl))
            w.bind("<Button-3>", lambda e, pl=p: self._popup(e, pl))
            w.bind("<Enter>", lambda e, ls=labels, t=tip: self._hover(ls, True, t), add="+")
            w.bind("<Leave>", lambda e, ls=labels: self._hover(ls, False, None), add="+")

    def _hover(self, labels, on: bool, tip: str | None):
        for lb in labels:
            lb.config(bg=BG_ROW_HOVER if on else BG)
        self.foot.config(text=tip if on and tip else self._footer())

    def _tooltip(self, p: Player) -> str:
        lk = p.lookup
        bits = []
        if lk.level:
            bits.append(f"Lv{lk.level}")
        srv = lk.server or p.server
        if srv:
            bits.append(sv.label(srv) + (" (guessed)" if lk.guessed or p.server_source == "scan" else ""))
        if lk.legion:
            bits.append(lk.legion)
        if p.hits_on_you:
            bits.append(f"{p.hits_on_you} hits on you")
        if p.dead:
            bits.append("dead")
        if lk.status == "notfound":
            bits.append("not found on Shugo — right-click to retry")
        return "  ·  ".join(bits) or p.name

    def _cp_color(self, cp: int | None, side: str) -> str:
        mine = self.tracker.me.lookup.combat_power
        if cp is None or not mine or side != ENEMY:
            return FG
        r = cp / mine
        return RED if r >= 1.10 else AMBER if r >= 0.90 else GREEN

    # ───── actions ─────
    def _url(self, p: Player) -> str:
        from .shugo import profile_url
        if p.lookup.url:
            return p.lookup.url
        if p.server:
            u = profile_url(p.name, p.server, self.cfg.get("kr_tw_region", "kr"))
            if u:
                return u
        return "https://shugo.gg/character"

    def _open(self, p: Player):
        webbrowser.open(self._url(p))

    def _popup(self, e, p: Player):
        self._menu_player = p
        self.menu.tk_popup(e.x_root, e.y_root)

    def _menu_open(self):
        if self._menu_player:
            self._open(self._menu_player)

    def _menu_retry(self):
        if self._menu_player:
            self.tracker.retry(self._menu_player.name)

    def _menu_copy(self):
        if self._menu_player:
            self.root.clipboard_clear()
            self.root.clipboard_append(self._menu_player.name)
