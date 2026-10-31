"""User settings: defaults, migration of older keys, and small rules shared by the window and Settings page."""
from __future__ import annotations

SETTING_DEFAULTS = {
    "window_opacity": 1.0,          # the whole window; 100% unless you turn it down
    "always_on_top": True,
    "auto_update": True,
    "borderless": True,             # our own title bar; off = the normal Windows frame
    "clock": "ST",                  # footer clock: ST = server time (US Eastern), LT = this PC's time
    "recent_max": 250,              # players kept on Recent; 0 = unlimited
    "nearby_autoclear_s": 0,        # move everyone on Nearby to Recent every N s (those still around return); 0 = never
}
RECENT_CHOICES = [(50, "50"), (100, "100"), (250, "250"), (500, "500"), (1000, "1,000"), (0, "Unlimited")]
AUTOCLEAR_CHOICES = [(0, "Never"), (60, "1m"), (300, "5m"), (900, "15m"), (1800, "30m"), (3600, "60m")]

OPACITY_MIN = 0.3   # never so faint that you lose the window

# Keys older versions wrote that no longer mean anything (removed on load).
RETIRED = ("pill_pos", "overlay", "idle_opacity", "opacity", "opacity_focused", "opacity_unfocused", "opacity_full_on_hover",
           "requests_per_second", "detail_workers", "region", "faction", "max_level_only", "stat_details",
           "start_with_windows", "layout", "close_to_tray")


def migrate(cfg: dict) -> dict:
    """Bring settings saved by older versions up to date (in place). Returns cfg."""
    if "nearby_autoclear" in cfg:            # v1.28–1.33: an on/off switch beside the interval
        if not cfg.pop("nearby_autoclear"):
            cfg["nearby_autoclear_s"] = 0
    for old in RETIRED:
        cfg.pop(old, None)
    if cfg.get("layout_version", 1) == 2:
        cfg.pop("window_size", None)      # v1.9.0's compact size: back to the regular default
    cfg["layout_version"] = 3
    for k, v in SETTING_DEFAULTS.items():
        cfg.setdefault(k, v)
    cfg["window_opacity"] = clamp_opacity(cfg["window_opacity"])
    if cfg.get("recent_max") not in dict(RECENT_CHOICES):
        cfg["recent_max"] = 250
    if cfg.get("nearby_autoclear_s") not in dict(AUTOCLEAR_CHOICES):
        cfg["nearby_autoclear_s"] = 0
    return cfg


def clamp_opacity(v) -> float:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return 1.0
    return round(min(1.0, max(OPACITY_MIN, v)), 2)
