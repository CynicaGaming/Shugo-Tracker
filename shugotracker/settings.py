"""User settings: defaults, migration of older keys, and small rules shared by the window and Settings page."""
from __future__ import annotations

SETTING_DEFAULTS = {
    "always_on_top": True,
    "close_to_tray": False,         # ✕ hides to the tray instead of quitting
    "hotkey": "ctrl+shift+s",
    "auto_update": True,
    "start_with_windows": False,
}

# Keys older versions wrote that no longer mean anything (removed on load).
RETIRED = ("overlay", "idle_opacity", "opacity", "opacity_focused", "opacity_unfocused", "opacity_full_on_hover",
           "requests_per_second", "detail_workers", "region", "faction", "max_level_only", "stat_details")


def migrate(cfg: dict) -> dict:
    """Bring settings saved by older versions up to date (in place). Returns cfg."""
    for old in RETIRED:
        cfg.pop(old, None)
    for k, v in SETTING_DEFAULTS.items():
        cfg.setdefault(k, v)
    return cfg
