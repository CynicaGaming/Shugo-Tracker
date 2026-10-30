"""Settings page (opened with ⚙): window, startup, updates, data."""
from __future__ import annotations

import os
import tkinter as tk
import webbrowser
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from . import desktop
from .search_ui import (ACCENT, ACCENT_FG, BG, BORDER, FG, FG_DIM, FG_FAINT, GOLD_SOFT, GOLD_TEXT, GREEN, PAD, RED,
                        SURFACE, SURFACE_2, ThinScrollbar)
from .settings import AUTOCLEAR_CHOICES, OPACITY_MIN, RECENT_CHOICES, clamp_opacity

if TYPE_CHECKING:
    from .search_ui import SearchWindow

REPO_URL = "https://github.com/CynicaGaming/Shugo-Tracker"


@dataclass
class SettingsServices:
    """What the Settings page needs from the app."""
    clear_cache: Callable[[], int]           # returns bytes freed
    cache_size: Callable[[], int]
    data_dir: str


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


class Slider(tk.Canvas):
    """Flat slider: drag or click the track. on_change(value, final)."""

    def __init__(self, parent, value: float, lo: float, hi: float, on_change, step: float = 0.05,
                 width: int = 180, fmt=lambda v: f"{v:.0%}"):
        super().__init__(parent, width=width + 54, height=20, bg=SURFACE, highlightthickness=0, cursor="hand2")
        self.lo, self.hi, self.step, self.fmt, self.on_change, self.track_w = lo, hi, step, fmt, on_change, width
        self.value = value
        for ev, final in (("<ButtonPress-1>", False), ("<B1-Motion>", False), ("<ButtonRelease-1>", True)):
            self.bind(ev, lambda e, f=final: self._set_from(e.x, f))
        self._draw()

    def _x_for(self, v):
        return 7 + (v - self.lo) / (self.hi - self.lo) * (self.track_w - 14)

    def _v_for(self, x):
        v = self.lo + (min(max(x, 7), self.track_w - 7) - 7) / (self.track_w - 14) * (self.hi - self.lo)
        return round(round(v / self.step) * self.step, 4)

    def _draw(self):
        self.delete("all")
        x = self._x_for(self.value)
        self.create_line(7, 10, self.track_w - 7, 10, fill=SURFACE_2, width=4, capstyle="round")
        self.create_line(7, 10, x, 10, fill=ACCENT, width=4, capstyle="round")
        self.create_oval(x - 6, 4, x + 6, 16, fill=FG, outline=ACCENT, width=2)
        self.create_text(self.track_w + 52, 10, text=self.fmt(self.value), fill=FG, anchor="e",
                         font=("Segoe UI Semibold", 9))

    def _set_from(self, x, final):
        v = self._v_for(x)
        if v != self.value or final:
            self.value = v
            self._draw()
            self.on_change(v, final)


class Switch(tk.Canvas):
    def __init__(self, parent, on: bool, on_toggle, enabled: bool = True):
        super().__init__(parent, width=40, height=22, bg=SURFACE, highlightthickness=0,
                         cursor="hand2" if enabled else "")
        self.on, self.on_toggle, self.enabled = on, on_toggle, enabled
        self.bind("<Button-1>", self._click)
        self._draw()

    def _draw(self):
        self.delete("all")
        col = (ACCENT if self.on else SURFACE_2) if self.enabled else BORDER
        self.create_oval(1, 1, 21, 21, fill=col, outline="")
        self.create_oval(19, 1, 39, 21, fill=col, outline="")
        self.create_rectangle(11, 1, 29, 21, fill=col, outline="")
        x = 29 if self.on else 11
        self.create_oval(x - 8, 3, x + 8, 19, fill=FG if self.enabled else FG_FAINT, outline="")

    def _click(self, _e):
        if not self.enabled:
            return
        self.on = not self.on
        self._draw()
        self.on_toggle(self.on)


class SettingsView:
    def __init__(self, app: "SearchWindow", services: SettingsServices | None):
        self.app = app
        self.cfg = app.cfg
        self.services = services
        self.frame = tk.Frame(app.root, bg=BG)

        wrap = tk.Frame(self.frame, bg=BG)
        wrap.pack(fill="both", expand=True, padx=(PAD, 4), pady=(6, PAD))
        self.canvas = tk.Canvas(wrap, bg=BG, highlightthickness=0, bd=0, yscrollincrement=16)
        sb = ThinScrollbar(wrap, command=self.canvas.yview)
        sb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.configure(yscrollcommand=sb.set)
        self.body = tk.Frame(self.canvas, bg=BG)
        win = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.body.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(win, width=e.width - 6))
        app.root.bind_all("<MouseWheel>", self._wheel)
        self._build()

    def _wheel(self, e):
        try:
            self.canvas.yview_scroll(int(-e.delta / 40) or (-1 if e.delta > 0 else 1), "units")
        except tk.TclError:
            pass

    def destroy(self):
        self.app.root.unbind_all("<MouseWheel>")
        self.frame.destroy()

    # ───── layout helpers ─────
    def _section(self, title: str):
        tk.Label(self.body, text=title, bg=BG, fg=FG_DIM, font=self.app.f_small, anchor="w").pack(
            fill="x", pady=(14, 4))
        card = tk.Frame(self.body, bg=SURFACE)
        card.pack(fill="x")
        return card

    def _row(self, card, label: str, sub: str | None = None):
        row = tk.Frame(card, bg=SURFACE, padx=12, pady=9)
        row.pack(fill="x")
        if card.winfo_children()[:-1]:
            tk.Frame(card, bg=BG, height=1).pack(fill="x", before=row)
        left = tk.Frame(row, bg=SURFACE)
        left.pack(side="left", fill="x", expand=True)
        tk.Label(left, text=label, bg=SURFACE, fg=FG, font=self.app.f_body, anchor="w").pack(fill="x")
        sub_lb = tk.Label(left, text=sub or "", bg=SURFACE, fg=FG_FAINT, font=self.app.f_tiny, anchor="w")
        if sub:
            sub_lb.pack(fill="x")
        right = tk.Frame(row, bg=SURFACE)
        right.pack(side="right")
        return right, sub_lb

    def _button(self, parent, text, cmd, accent=False):
        b = tk.Label(parent, text=text, bg=ACCENT if accent else SURFACE_2, fg=ACCENT_FG if accent else FG,
                     font=self.app.f_small, padx=12, pady=4, cursor="hand2")
        b.bind("<Button-1>", lambda e: cmd())
        return b

    def _save(self):
        self.app.save_cfg()

    # ───── content ─────
    def _build(self):
        a, cfg = self.app, self.cfg

        card = self._section("Window")
        r, _ = self._row(card, "Borderless")
        Switch(r, bool(cfg.get("borderless", True)), lambda on: (a.set_borderless(on), self._save())).pack()
        r, _ = self._row(card, "Opacity")
        Slider(r, clamp_opacity(cfg.get("window_opacity", 1.0)), OPACITY_MIN, 1.0, self._opacity).pack()
        r, _ = self._row(card, "Always on top")
        Switch(r, bool(cfg["always_on_top"]), self._always_on_top).pack()

        if a.nearby is not None:
            card = self._section("Nearby  ·  BETA")
            r, _ = self._row(card, "Show Nearby")
            Switch(r, bool(cfg.get("nearby_enabled")), self._nearby).pack()
            r, _ = self._row(card, "Auto-clear")
            secs = [c[0] for c in AUTOCLEAR_CHOICES]
            names = [c[1] for c in AUTOCLEAR_CHOICES]
            cur = secs.index(cfg.get("nearby_autoclear_s", 0)) if cfg.get("nearby_autoclear_s", 0) in secs else 0
            Slider(r, cur, 0, len(secs) - 1, lambda v, final: self._set_every(secs[int(v)], final), step=1,
                   fmt=lambda v: names[int(v)]).pack()

            card = self._section("Recent")
            r, _ = self._row(card, "Recent Players")
            keep = [c[0] for c in RECENT_CHOICES]
            keep_names = [c[1] for c in RECENT_CHOICES]
            cur = keep.index(cfg.get("recent_max", 250)) if cfg.get("recent_max", 250) in keep else 2
            self._recent_btn = self._button(r, "Clear", self._clear_recent)
            self._recent_btn.pack(side="right", padx=(12, 0))
            Slider(r, cur, 0, len(keep) - 1, lambda v, final: self._set_recent_max(keep[int(v)], final), step=1,
                   fmt=lambda v: keep_names[int(v)]).pack(side="right")

        card = self._section("Updates")
        r, _ = self._row(card, "Automatic updates")
        Switch(r, bool(cfg["auto_update"]), lambda on: self._set("auto_update", on)).pack()
        if a.updater is not None:
            r, _ = self._row(card, f"Version {a.updater.current}")
            self.update_btn = self._button(r, "", self._update_click)
            self.update_btn.pack()
            self._sync_update()

        card = self._section("Data")
        r, self._cache_sub = self._row(card, "Clear Cache", " ")
        self._button(r, "Clear", self._clear_cache).pack(side="right")
        self._show_cache_size()
        if self.services:
            r, _ = self._row(card, "Application Folder")
            self._button(r, "Open", lambda: desktop.open_folder(self.services.data_dir)).pack()

        about = tk.Frame(self.body, bg=BG)
        about.pack(fill="x", pady=(16, 6))
        link = tk.Label(about, text="Shugo Tracker on GitHub ↗", bg=BG, fg=FG_DIM, font=self.app.f_small,
                        cursor="hand2")
        link.pack(anchor="w")
        link.bind("<Button-1>", lambda e: webbrowser.open(REPO_URL))

    # ───── actions ─────
    def _set(self, key, value):
        self.cfg[key] = value
        self._save()

    def _opacity(self, value: float, final: bool):
        self.cfg["window_opacity"] = clamp_opacity(value)
        self.app.apply_opacity()
        if final:
            self._save()

    def _set_every(self, secs: int, final: bool = True):
        self.cfg["nearby_autoclear_s"] = secs
        self.app.autoclear_reset()
        if final:
            self._save()

    def _set_recent_max(self, n: int, final: bool = True):
        self.cfg["recent_max"] = n
        if self.app.nearby is not None:
            self.app.nearby.set_recent_max(n)
            self.app._refresh_nearby(force=True)
        if final:
            self._save()

    def _clear_recent(self):
        if self.app.nearby is not None:
            self.app.nearby.clear_recent()
            self.app._refresh_nearby(force=True)
        self._recent_btn.config(text="Cleared")
        self.app.root.after(1500, lambda: self._recent_btn.winfo_exists() and self._recent_btn.config(text="Clear"))

    def _nearby(self, on: bool):
        self.app.set_nearby_enabled(on)

    def _always_on_top(self, on: bool):
        self._set("always_on_top", on)
        self.app.root.attributes("-topmost", on)
        self.app._paint_pin()

    def _choice(self, parent, options, current, on_pick):
        """A small segmented control: one of options [(value, label)]."""
        seg = tk.Frame(parent, bg=SURFACE_2, padx=2, pady=2)
        seg.pack()
        labels = {}

        def paint(v):
            for val, lb in labels.items():
                on = val == v
                lb.config(bg=GOLD_SOFT if on else SURFACE_2, fg=GOLD_TEXT if on else FG_DIM,
                          font=self.app.f_sbold if on else self.app.f_small)

        def pick(v):
            paint(v)
            on_pick(v)
        for val, text in options:
            lb = tk.Label(seg, text=text, padx=10, pady=2, cursor="hand2")
            lb.pack(side="left", padx=(0, 1))
            lb.bind("<Button-1>", lambda e, v=val: pick(v))
            labels[val] = lb
        paint(current)

    def _update_click(self):
        self.app._update_click()
        self._sync_update()

    def _sync_update(self):
        if not self.frame.winfo_exists() or self.app.updater is None:
            return
        text, style = self.app.updater.button()
        self.update_btn.config(text=text, bg=ACCENT if style == "accent" else SURFACE_2,
                               fg=ACCENT_FG if style == "accent" else (GREEN if style == "ok" else
                                                                        RED if style == "error" else FG))
        self.app.root.after(400, self._sync_update)

    def _show_cache_size(self):
        if self.services:
            self._cache_sub.config(text=human_size(self.services.cache_size()))

    def _clear_cache(self):
        if not self.services:
            return
        freed = self.services.clear_cache()
        self._cache_sub.config(text=f"Cleared {human_size(freed)}")
