"""Settings page (opened with ⚙): transparency, window behaviour, hotkey, startup, updates, speed, data."""
from __future__ import annotations

import os
import time
import tkinter as tk
import webbrowser
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from . import desktop
from .settings import OPACITY_MIN, clamp_opacity
from .search_ui import (ACCENT, ACCENT_FG, BG, BORDER, FG, FG_DIM, FG_FAINT, GREEN, HOVER, PAD, RED, SURFACE,
                        SURFACE_2)

if TYPE_CHECKING:
    from .search_ui import SearchWindow

REPO_URL = "https://github.com/CynicaGaming/Shugo-Tracker"


@dataclass
class SettingsServices:
    """What the Settings page needs from the app."""
    change_hotkey: Callable[[str], tuple[bool, str | None]]
    clear_cache: Callable[[], int]           # returns bytes freed
    cache_size: Callable[[], int]
    data_dir: str
    set_request_rate: Callable[[float], None]


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


class Slider(tk.Canvas):
    """Flat slider: drag or click the track. on_change(value, final)."""

    def __init__(self, parent, value: float, lo: float, hi: float, on_change, fmt=lambda v: f"{v:.0%}",
                 step: float = 0.05, width: int = 220):
        super().__init__(parent, width=width + 54, height=24, bg=SURFACE, highlightthickness=0, cursor="hand2")
        self.lo, self.hi, self.step, self.fmt, self.on_change = lo, hi, step, fmt, on_change
        self.track_w = width
        self.value = value
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<B1-Motion>", self._drag)
        self.bind("<ButtonRelease-1>", self._release)
        self._draw()

    def _x_for(self, v):
        return 8 + (v - self.lo) / (self.hi - self.lo) * (self.track_w - 16)

    def _v_for(self, x):
        v = self.lo + (min(max(x, 8), self.track_w - 8) - 8) / (self.track_w - 16) * (self.hi - self.lo)
        return round(round(v / self.step) * self.step, 4)

    def _draw(self):
        self.delete("all")
        x = self._x_for(self.value)
        self.create_line(8, 12, self.track_w - 8, 12, fill=SURFACE_2, width=4, capstyle="round")
        self.create_line(8, 12, x, 12, fill=ACCENT, width=4, capstyle="round")
        self.create_oval(x - 7, 5, x + 7, 19, fill=FG, outline=ACCENT, width=2)
        self.create_text(self.track_w + 50, 12, text=self.fmt(self.value), fill=FG, anchor="e",
                         font=("Segoe UI Semibold", 10))

    def _set_from(self, x, final):
        v = self._v_for(x)
        if v != self.value or final:
            self.value = v
            self._draw()
            self.on_change(v, final)

    def _press(self, e):
        self._set_from(e.x, False)

    def _drag(self, e):
        self._set_from(e.x, False)

    def _release(self, e):
        self._set_from(e.x, True)


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
        self._revert_job = None
        self._capturing = False
        f = app
        self.frame = tk.Frame(app.root, bg=BG)

        bar = tk.Frame(self.frame, bg=BG)
        bar.pack(fill="x", padx=PAD, pady=(10, 4))
        back = tk.Label(bar, text="←  Back", bg=BG, fg=FG_DIM, font=f.f_bold, cursor="hand2")
        back.pack(side="left")
        back.bind("<Button-1>", lambda e: app.close_settings())
        tk.Label(bar, text="Settings", bg=BG, fg=FG, font=f.f_title).pack(side="left", padx=(14, 0))

        wrap = tk.Frame(self.frame, bg=BG)
        wrap.pack(fill="both", expand=True, padx=(PAD, 4), pady=(4, PAD))
        self.canvas = tk.Canvas(wrap, bg=BG, highlightthickness=0, bd=0, yscrollincrement=16)
        sb = tk.Scrollbar(wrap, orient="vertical", command=self.canvas.yview, width=10)
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
        self._stop_capture()
        if self._revert_job:
            self.app.root.after_cancel(self._revert_job)
        self.app.root.unbind_all("<MouseWheel>")
        self.frame.destroy()
        self.app._update_opacity(time.monotonic(), immediate=True)

    # ───── layout helpers ─────
    def _section(self, title: str):
        tk.Label(self.body, text=title.upper(), bg=BG, fg=FG_DIM, font=self.app.f_tiny, anchor="w").pack(
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

        card = self._section("Transparency")
        r, _ = self._row(card, "While active")
        Slider(r, clamp_opacity(cfg["opacity_focused"]), OPACITY_MIN, 1.0,
               lambda v, final: self._opacity("opacity_focused", v, final)).pack()
        r, _ = self._row(card, "While in the game")
        Slider(r, clamp_opacity(cfg["opacity_unfocused"]), OPACITY_MIN, 1.0,
               lambda v, final: self._opacity("opacity_unfocused", v, final)).pack()
        r, _ = self._row(card, "Solid while the mouse is over it")
        Switch(r, bool(cfg["opacity_full_on_hover"]), lambda on: self._set("opacity_full_on_hover", on)).pack()

        card = self._section("Window")
        r, _ = self._row(card, "Always on top")
        Switch(r, bool(cfg["always_on_top"]), self._always_on_top).pack()
        r, self._overlay_sub = self._row(card, "Overlay style (no Windows title bar)")
        self._overlay_initial = bool(cfg["overlay"])
        Switch(r, bool(cfg["overlay"]), self._overlay).pack()

        card = self._section("Shortcut")
        r, self._hotkey_sub = self._row(card, "Show / hide")
        self.hotkey_btn = self._button(r, desktop.hotkey_label(cfg["hotkey"]), self._start_capture)
        self.hotkey_btn.pack()

        card = self._section("Startup & updates")
        r, _ = self._row(card, "Start with Windows",
                         None if desktop.autostart_supported() else "Available in the installed app")
        Switch(r, desktop.get_autostart() if desktop.autostart_supported() else False, self._autostart,
               enabled=desktop.autostart_supported()).pack()
        r, _ = self._row(card, "Check for updates automatically")
        Switch(r, bool(cfg["auto_update"]), lambda on: self._set("auto_update", on)).pack()
        if a.updater is not None:
            r, _ = self._row(card, f"Version {a.updater.current}")
            self.update_btn = self._button(r, "", self._update_click)
            self.update_btn.pack()
            self._sync_update()

        card = self._section("Lookups")
        r, _ = self._row(card, "Requests per second")
        Slider(r, float(cfg["requests_per_second"]), 1.0, 8.0, self._rate,
               fmt=lambda v: f"{v:.0f}/s", step=1.0).pack()

        card = self._section("Data")
        r, self._cache_sub = self._row(card, "Cached profiles, portraits and icons", " ")
        self._button(r, "Clear", self._clear_cache).pack(side="right")
        self._show_cache_size()
        if self.services:
            r, _ = self._row(card, "Settings, favorites and cache folder")
            self._button(r, "Open", lambda: desktop.open_folder(self.services.data_dir)).pack()

        about = tk.Frame(self.body, bg=BG)
        about.pack(fill="x", pady=(16, 6))
        link = tk.Label(about, text="Shugo Tracker on GitHub ↗", bg=BG, fg=FG_DIM, font=self.app.f_small,
                        cursor="hand2")
        link.pack(anchor="w")
        link.bind("<Button-1>", lambda e: webbrowser.open(REPO_URL))
        tk.Label(about, text="Character data from NCSOFT's public AION 2 site  ·  profiles link to Shugo.GG",
                 bg=BG, fg=FG_FAINT, font=self.app.f_tiny).pack(anchor="w", pady=(2, 0))

    # ───── actions ─────
    def _set(self, key, value):
        self.cfg[key] = value
        self._save()

    def _opacity(self, key: str, value: float, final: bool):
        self.cfg[key] = clamp_opacity(value)
        self.app.preview_opacity(self.cfg[key])          # show it while dragging
        if final:
            self._save()
            if self._revert_job:
                self.app.root.after_cancel(self._revert_job)
            # after previewing the in-game value, go back to whatever applies right now
            self._revert_job = self.app.root.after(
                1200, lambda: self.app._update_opacity(time.monotonic(), immediate=True))

    def _always_on_top(self, on: bool):
        self._set("always_on_top", on)
        self.app.root.attributes("-topmost", on)
        self.app._paint_pin()

    def _overlay(self, on: bool):
        self._set("overlay", on)
        changed = on != self._overlay_initial
        self._overlay_sub.config(text="Applies next time you start Shugo Tracker" if changed else "")
        if changed:
            self._overlay_sub.pack(fill="x")
        else:
            self._overlay_sub.pack_forget()

    def _autostart(self, on: bool):
        ok = desktop.set_autostart(on)
        self.cfg["start_with_windows"] = on if ok else desktop.get_autostart()
        self._save()

    def _rate(self, value: float, final: bool):
        if final:
            self._set("requests_per_second", float(value))
            if self.services:
                self.services.set_request_rate(float(value))

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

    # ───── hotkey capture ─────
    def _start_capture(self):
        if self._capturing:
            return
        self._capturing = True
        self.hotkey_btn.config(text="Press keys…", bg=ACCENT, fg=ACCENT_FG)
        self._hotkey_sub.pack_forget()
        self.app.root.focus_force()
        self._bind_id = self.app.root.bind("<KeyPress>", self._on_key, add="+")

    def _stop_capture(self):
        if self._capturing:
            self._capturing = False
            try:
                self.app.root.unbind("<KeyPress>", self._bind_id)
            except tk.TclError:
                pass

    MODIFIER_KEYS = {"Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R", "Meta_L", "Meta_R",
                     "Win_L", "Win_R", "Super_L", "Super_R"}

    def _on_key(self, e):
        if e.keysym in self.MODIFIER_KEYS:
            return
        if e.keysym == "Escape":
            self._stop_capture()
            self.hotkey_btn.config(text=desktop.hotkey_label(self.cfg["hotkey"]), bg=SURFACE_2, fg=FG)
            return "break"
        text = keys_from_event(e.state, e.keysym)
        if text is None or desktop.parse_hotkey(text) is None:
            self._hotkey_sub.config(text="Use Ctrl, Alt or Shift with a letter, number or F-key", fg=FG_FAINT)
            self._hotkey_sub.pack(fill="x")
            return "break"
        self._stop_capture()
        ok, err = self.services.change_hotkey(text) if self.services else (False, "unavailable")
        if ok:
            self.cfg["hotkey"] = text
            self._save()
            self._hotkey_sub.pack_forget()
        else:
            self._hotkey_sub.config(text=f"{desktop.hotkey_label(text)} is {err}", fg=RED)
            self._hotkey_sub.pack(fill="x")
        self.hotkey_btn.config(text=desktop.hotkey_label(self.cfg["hotkey"]), bg=SURFACE_2, fg=FG)
        return "break"


def keys_from_event(state: int, keysym: str) -> str | None:
    """Tk key event -> 'ctrl+shift+s' style text."""
    mods = []
    if state & 0x4:
        mods.append("ctrl")
    if state & 0x20000 or state & 0x8:      # Alt on Windows / Mod1 elsewhere
        mods.append("alt")
    if state & 0x1:
        mods.append("shift")
    k = keysym.lower()
    if len(k) == 1 and k.isalnum():
        key = k
    elif k.startswith("f") and k[1:].isdigit():
        key = k
    elif k in ("grave", "quoteleft"):
        key = "`"
    elif k in ("space", "home", "end", "insert", "delete", "pause"):
        key = k
    elif k in ("prior", "next"):
        key = "pageup" if k == "prior" else "pagedown"
    else:
        return None
    return "+".join(mods + [key])
