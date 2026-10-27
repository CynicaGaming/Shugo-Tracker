"""User settings: defaults, migration of older keys, and small rules shared by the window and Settings page."""
from __future__ import annotations

SETTING_DEFAULTS = {
    "window_opacity": 1.0,          # the whole window; 100% unless you turn it down
    "always_on_top": True,
    "close_to_tray": False,         # ✕ hides to the tray instead of quitting
    "auto_update": True,
    "layout": "full",               # full | compact
    "borderless": True,             # our own title bar; off = the normal Windows frame
    "nearby_autoclear": False,      # move everyone on Nearby to Recent every so often (those still around return)
    "nearby_autoclear_s": 60,
}
AUTOCLEAR_CHOICES = [(15, "15 s"), (30, "30 s"), (60, "60 s"), (300, "5 min"), (900, "15 min"), (1800, "30 min"),
                     (3600, "1 hour")]

OPACITY_MIN = 0.3   # never so faint that you lose the window

# Keys older versions wrote that no longer mean anything (removed on load).
RETIRED = ("pill_pos", "overlay", "idle_opacity", "opacity", "opacity_focused", "opacity_unfocused", "opacity_full_on_hover",
           "requests_per_second", "detail_workers", "region", "faction", "max_level_only", "stat_details",
           "start_with_windows")


def migrate(cfg: dict) -> dict:
    """Bring settings saved by older versions up to date (in place). Returns cfg."""
    for old in RETIRED:
        cfg.pop(old, None)
    if cfg.get("layout_version", 1) == 2:
        cfg.pop("window_size", None)      # v1.9.0's compact size: back to the regular default
    cfg["layout_version"] = 3
    for k, v in SETTING_DEFAULTS.items():
        cfg.setdefault(k, v)
    cfg["window_opacity"] = clamp_opacity(cfg["window_opacity"])
    if cfg.get("nearby_autoclear_s") not in dict(AUTOCLEAR_CHOICES):
        cfg["nearby_autoclear_s"] = 60
    if cfg.get("layout") not in ("full", "compact"):
        cfg["layout"] = "full"
    return cfg


def clamp_opacity(v) -> float:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return 1.0
    return round(min(1.0, max(OPACITY_MIN, v)), 2)
