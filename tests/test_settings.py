"""Settings: migration from older versions, opacity, cache clearing, request ceiling, favorites on disk."""
import json
import time
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


class AppFolderTests(unittest.TestCase):
    def test_appdata_moves_into_the_app_folder(self):
        from shugotracker import app
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as appdata:
            old = os.path.join(appdata, "ShugoTracker")
            os.makedirs(os.path.join(old, "cache", "images"))
            os.makedirs(os.path.join(old, "diagnostics"))
            with open(os.path.join(old, "config.json"), "w") as f:
                json.dump({"always_on_top": False}, f)
            for rel in (("cache", "shugo.db"), ("cache", "images", "a.png"), ("diagnostics", "rec.bin"),
                        ("shugo-tracker.log",)):
                with open(os.path.join(old, *rel), "w") as f:
                    f.write("x")
            app.migrate_to_app_folder(root, old)
            for rel in (("data", "config.json"), ("cache", "shugo.db"), ("cache", "images", "a.png"),
                        ("logs", "diagnostics", "rec.bin")):
                self.assertTrue(os.path.exists(os.path.join(root, *rel)), rel)
            self.assertFalse(os.path.exists(old))            # the old folder is gone
            self.assertEqual(app.migrate_to_app_folder(root, old), [])


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
                json.dump({"x": {"combat_power": 1, "legion": None, "ts": time.time()}}, f)
            os.makedirs(pd)
            with open(os.path.join(pd, "p.json"), "w") as f:
                f.write("{}")
            api = a.Api(db_path=os.path.join(tmp, "shugo.db"), migrate_from=(cp, pd))
            # the old files were imported and removed
            self.assertEqual((os.path.exists(cp), os.path.exists(pd)), (False, False))
            self.assertIn("x", api._cache)
            api._search_cache[("a",)] = (0, {})
            api.clear_caches()
            self.assertEqual((api._cache, api._search_cache, api.store.counts()["details"]), ({}, {}, 0))
            api.close()                    # (Windows can't delete the folder while the database is open)


if __name__ == "__main__":
    unittest.main()


class EmptyFavoritesTests(unittest.TestCase):
    def test_empty_store_is_not_falsy(self):
        # v1.10 and earlier: `favorites or Favorites(None)` replaced an empty store with one that never saved
        from shugotracker.favorites import Favorites
        with tempfile.TemporaryDirectory() as d:
            f = Favorites(os.path.join(d, "favorites.json"))
            self.assertEqual(len(f), 0)
            self.assertTrue(f)


class AutoClearMigrationTests(unittest.TestCase):
    def test_switch_folds_into_the_interval(self):
        from shugotracker.settings import migrate
        self.assertEqual(migrate({"nearby_autoclear": False, "nearby_autoclear_s": 300})["nearby_autoclear_s"], 0)
        self.assertEqual(migrate({"nearby_autoclear": True, "nearby_autoclear_s": 300})["nearby_autoclear_s"], 300)
        self.assertEqual(migrate({})["nearby_autoclear_s"], 0)
        self.assertNotIn("layout", migrate({"layout": "compact"}))
