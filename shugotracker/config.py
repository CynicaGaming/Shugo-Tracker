"""data\\config.json: defaults, reading and writing, and bringing older versions' settings and folders up to date."""
from __future__ import annotations

import json
import os
import shutil
import threading

DEFAULTS = {
    "window_opacity": 1.0,          # the whole window; 100% unless you turn it down
    "always_on_top": True,
    "update_check_s": 1800,         # look for updates this often (also at start and when Settings opens); 0 = never
    "clock": "ST",                  # footer clock: ST = server time (US Eastern), LT = this PC's time
    "recent_max": 250,              # players kept on Recent; 0 = unlimited
    "nearby_autoclear_s": 0,
    "pvp_range": None,              # PVP Log dates: {"preset": "7d"} or {"from": "2026-11-01", "to": "…"}; None = all time        # move everyone on Nearby to Recent every N s; 0 = never
    "regions": [],
    "factions": [],
    "window_pos": [80, 80],
    "my_server": "",                # Nearby: your server, when it can't tell from the game
    "forget_after_s": 900,          # Nearby: drop players not seen for this long
    "opcodes": {},                  # Nearby: overrides if a game patch moves them (see protocol.Opcodes)
}
RECENT_CHOICES = (50, 100, 250, 500, 1000, 0)
AUTOCLEAR_CHOICES = (0, 60, 300, 900, 1800, 3600)
UPDATE_CHOICES = (0, 1800, 3600, 21600, 43200, 86400)
OPACITY_MIN = 0.3                   # never so faint that you lose the window

# Keys older versions wrote that no longer mean anything (removed on load).
RETIRED = ("pill_pos", "overlay", "idle_opacity", "opacity", "opacity_focused", "opacity_unfocused",
           "opacity_full_on_hover", "requests_per_second", "detail_workers", "region", "faction", "max_level_only",
           "stat_details", "start_with_windows", "layout", "close_to_tray", "borderless", "update_repo",
           "pvp_within_s")

_write_lock = threading.Lock()


def load_config(path: str) -> dict:
    """The saved settings over the defaults, migrated (a missing or broken file gives the defaults)."""
    cfg = dict(DEFAULTS)
    try:
        with open(path, encoding="utf-8") as f:
            cfg.update(json.load(f))
    except (OSError, ValueError):
        pass
    return migrate(cfg)


def save_config(path: str, cfg: dict) -> None:
    """Write atomically (a temporary file, then swapped in), so a crash or two saves at once never leave a
    half-written config.json."""
    tmp = f"{path}.tmp"
    with _write_lock:
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
            os.replace(tmp, path)
        except OSError:
            pass


def migrate(cfg: dict) -> dict:
    """Bring settings saved by older versions up to date (in place). Returns cfg."""
    if "auto_update" in cfg:                 # v2.3.4 and earlier: an on/off switch
        if not cfg.pop("auto_update"):
            cfg["update_check_s"] = 0
    if "nearby_autoclear" in cfg:            # v1.28–1.33: an on/off switch beside the interval
        if not cfg.pop("nearby_autoclear"):
            cfg["nearby_autoclear_s"] = 0
    for old in RETIRED:
        cfg.pop(old, None)
    if cfg.get("layout_version", 1) == 2:
        cfg.pop("window_size", None)          # v1.9.0's compact size: back to the regular default
    cfg["layout_version"] = 3
    for k, v in DEFAULTS.items():
        cfg.setdefault(k, v)
    cfg["window_opacity"] = clamp_opacity(cfg["window_opacity"])
    if cfg.get("recent_max") not in RECENT_CHOICES:
        cfg["recent_max"] = 250
    if cfg.get("update_check_s") not in UPDATE_CHOICES:
        cfg["update_check_s"] = 1800
    if cfg.get("nearby_autoclear_s") not in AUTOCLEAR_CHOICES:
        cfg["nearby_autoclear_s"] = 0
    return cfg


def clamp_opacity(v) -> float:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return 1.0
    return round(min(1.0, max(OPACITY_MIN, v)), 2)


# ───── very old versions' folders ─────
USER_FILES = ("config.json", "favorites.json", "character_cache.json")


def migrate_user_files(old_dir: str, new_dir: str) -> list[str]:
    """Bring settings / favorites an older version kept in old_dir into the data folder. Returns what moved."""
    moved: list[str] = []
    if os.path.normcase(os.path.abspath(old_dir)) == os.path.normcase(os.path.abspath(new_dir)):
        return moved
    os.makedirs(new_dir, exist_ok=True)
    for name in USER_FILES:
        src, dst = os.path.join(old_dir, name), os.path.join(new_dir, name)
        if not os.path.isfile(src):
            continue
        try:
            if name == "favorites.json" and os.path.exists(dst):
                from .favorites import Favorites
                merged = Favorites(dst)
                if merged.merge_from(src):
                    merged.save()
            elif not os.path.exists(dst):
                shutil.copy2(src, dst)
            else:
                continue
            os.replace(src, src + ".moved")      # leave a trace, never read again
            moved.append(name)
        except OSError:
            pass
    return moved


def migrate_to_app_folder(root: str, old: str | None = None) -> list[str]:
    """v1.22 and earlier kept everything in %APPDATA%\\ShugoTracker (and before that, loose next to the exe). Move
    it all into the app's own folders, then remove the old folder. Returns what moved."""
    if old is None:
        old = os.path.join(os.environ["APPDATA"], "ShugoTracker") if os.environ.get("APPDATA") else None
    data, cache, logs = (os.path.join(root, d) for d in ("data", "cache", "logs"))
    moved = migrate_user_files(root, data)                  # loose files next to the exe (oldest versions)
    if not old or not os.path.isdir(old) or \
            os.path.normcase(os.path.abspath(old)) == os.path.normcase(os.path.abspath(root)):
        return moved
    moved += migrate_user_files(old, data)
    failed = False
    for src, dst in ((os.path.join(old, "cache"), cache),
                     (os.path.join(old, "diagnostics"), os.path.join(logs, "diagnostics"))):
        if not os.path.isdir(src):
            continue
        for dirpath, _dirs, files in os.walk(src):
            target = os.path.join(dst, os.path.relpath(dirpath, src))
            os.makedirs(target, exist_ok=True)
            for f in files:
                if not os.path.exists(os.path.join(target, f)):
                    try:
                        shutil.move(os.path.join(dirpath, f), os.path.join(target, f))
                        moved.append(os.path.relpath(os.path.join(dirpath, f), old))
                    except OSError:
                        failed = True
    failed = failed or any(os.path.isfile(os.path.join(old, n)) for n in ("config.json", "favorites.json"))
    if not failed:
        shutil.rmtree(old, ignore_errors=True)              # what's left: old logs and ".moved" traces
    return moved
