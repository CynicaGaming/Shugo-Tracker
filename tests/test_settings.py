"""Settings: migration from older versions, opacity, cache clearing, request ceiling, favorites on disk."""
import json
import os
import tempfile
import unittest

from shugotracker import aion2api as a
from shugotracker.settings import OPACITY_MIN, SETTING_DEFAULTS, clamp_opacity, migrate


class MigrateTests(unittest.TestCase):
    def test_old_configs(self):
        cfg = migrate({"opacity": 0.97, "idle_opacity": 0.45, "opacity_unfocused": 0.6, "requests_per_second": 50,
                       "hotkey": "alt+f9", "region": "nae", "overlay": False})
        self.assertEqual(cfg["window_opacity"], 1.0)                  # old 0.97 "opacity" isn't carried over
        for gone in ("overlay", "opacity", "idle_opacity", "opacity_unfocused", "requests_per_second", "region"):
            self.assertNotIn(gone, cfg)
        for k in SETTING_DEFAULTS:
            self.assertIn(k, cfg)


class OpacityAndLayoutTests(unittest.TestCase):
    def test_opacity(self):
        self.assertEqual(migrate({"window_opacity": 0.05})["window_opacity"], OPACITY_MIN)
        self.assertEqual(migrate({"window_opacity": 0.8})["window_opacity"], 0.8)
        self.assertEqual(clamp_opacity("x"), 1.0)

    def test_window_size(self):
        self.assertEqual(migrate({"window_size": [560, 700]})["window_size"], [560, 700])   # kept
        self.assertNotIn("window_size", migrate({"window_size": [420, 600], "layout_version": 2}))  # v1.9.0 reset


class FavoritesOnDiskTests(unittest.TestCase):
    def test_saved_immediately_and_moved_to_data_folder(self):
        from shugotracker import app
        from shugotracker.favorites import Favorites
        chars, _ = a.parse_search({"list": [
            {"characterId": "abc%3D", "name": "Luna", "race": 2, "pcId": 36, "level": 45, "serverId": 2101,
             "serverName": "Israphel", "region": "nae"},
            {"characterId": "def%3D", "name": "Sol", "race": 1, "pcId": 6, "level": 45, "serverId": 1109,
             "serverName": "Hithanya", "region": "nae"}], "pagination": {"total": 2}})
        with tempfile.TemporaryDirectory() as old, tempfile.TemporaryDirectory() as new:
            f = Favorites(os.path.join(old, "favorites.json"))
            f.toggle(chars[0])                                         # written on click, no close needed
            self.assertIn(chars[0].key, Favorites(os.path.join(old, "favorites.json")))
            g = Favorites(os.path.join(new, "favorites.json"))
            g.toggle(chars[1])
            with open(os.path.join(old, "config.json"), "w") as fh:
                json.dump({"always_on_top": False}, fh)
            moved = app.migrate_user_files(old, new)
            self.assertEqual(sorted(moved), ["config.json", "favorites.json"])
            merged = Favorites(os.path.join(new, "favorites.json"))
            self.assertEqual(len(merged), 2)                           # both copies kept
            self.assertTrue(os.path.exists(os.path.join(new, "config.json")))
            self.assertEqual(app.migrate_user_files(old, new), [])      # nothing left to move


class RequestCeilingTests(unittest.TestCase):
    def test_recovery_never_passes_the_ceiling(self):
        api = a.Api()
        self.addCleanup(api.close)
        api.limiter.throttled(0)
        for _ in range(500):
            api.limiter.ok()
        self.assertEqual(api.limiter.rate, a.REQUESTS_PER_SECOND)


class ClearCacheTests(unittest.TestCase):
    def test_clear(self):
        with tempfile.TemporaryDirectory() as tmp:
            cp, pd = os.path.join(tmp, "details.json"), os.path.join(tmp, "profiles")
            with open(cp, "w") as f:
                json.dump({"x": {"combat_power": 1, "ts": 9e12}}, f)
            api = a.Api(cache_path=cp, profile_dir=pd)
            self.addCleanup(api.close)
            with open(os.path.join(pd, "p.json"), "w") as f:
                f.write("{}")
            api._search_cache[("a",)] = (0, {})
            api.clear_caches()
            self.assertEqual((api._cache, api._search_cache, os.listdir(pd), os.path.exists(cp)), ({}, {}, [], False))


if __name__ == "__main__":
    unittest.main()
