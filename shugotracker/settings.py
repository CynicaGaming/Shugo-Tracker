"""User settings: defaults, migration of older keys, and small rules shared by the window and Settings page."""
from __future__ import annotations

SETTING_DEFAULTS = {
    "opacity_focused": 1.0,         # while the overlay is the active window
    "opacity_unfocused": 0.6,       # while you're in the game / another window
    "opacity_full_on_hover": True,  # pointing at it brings it back to focused opacity
    "always_on_top": True,
    "overlay": True,                # frameless overlay window (False = normal Windows title bar)
    "hotkey": "ctrl+shift+s",
    "auto_update": True,
    "start_with_windows": False,
    "requests_per_second": 6.0,
}

OPACITY_MIN = 0.2   # never fully invisible: you'd lose the window


def migrate(cfg: dict) -> dict:
    """Bring settings saved by older versions up to date (in place). Returns cfg."""
    if "opacity_unfocused" not in cfg and "idle_opacity" in cfg:
        cfg["opacity_unfocused"] = cfg["idle_opacity"]
    # v1.7.0 defaulted "opacity" to 0.97, which left the focused overlay slightly see-through: not carried over
    for old in ("idle_opacity", "opacity", "region", "faction", "max_level_only", "stat_details"):
        cfg.pop(old, None)
    for k, v in SETTING_DEFAULTS.items():
        cfg.setdefault(k, v)
    for k in ("opacity_focused", "opacity_unfocused"):
        cfg[k] = clamp_opacity(cfg[k])
    return cfg


def clamp_opacity(v) -> float:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return 1.0
    return round(min(1.0, max(OPACITY_MIN, v)), 2)


def decide_opacity(cfg: dict, foreground: bool, hovering: bool) -> float:
    """Opacity for the overlay right now."""
    if foreground or (hovering and cfg.get("opacity_full_on_hover", True)):
        return clamp_opacity(cfg.get("opacity_focused", 1.0))
    return clamp_opacity(cfg.get("opacity_unfocused", 0.6))
