"""Settings: migration from older versions, hotkey capture text, cache clearing, request ceiling."""
import json
import os
import tempfile
import unittest

from shugotracker import aion2api as a
from shugotracker.settings import SETTING_DEFAULTS, migrate


class MigrateTests(unittest.TestCase):
    def test_old_configs(self):
        cfg = migrate({"opacity": 0.97, "idle_opacity": 0.45, "opacity_unfocused": 0.6, "requests_per_second": 50,
                       "hotkey": "alt+f9", "region": "nae"})
        self.assertEqual(cfg["hotkey"], "alt+f9")
        for gone in ("opacity", "idle_opacity", "opacity_unfocused", "requests_per_second", "region"):
            self.assertNotIn(gone, cfg)
        for k in SETTING_DEFAULTS:
            self.assertIn(k, cfg)


class RequestCeilingTests(unittest.TestCase):
    def test_recovery_never_passes_the_ceiling(self):
        api = a.Api()
        self.addCleanup(api.close)
        api.limiter.throttled(0)
        for _ in range(500):
            api.limiter.ok()
        self.assertEqual(api.limiter.rate, a.REQUESTS_PER_SECOND)


class HotkeyCaptureTests(unittest.TestCase):
    def test_keys(self):
        try:
            from shugotracker.settings_ui import keys_from_event
        except ImportError as e:  # no tkinter on this machine
            self.skipTest(str(e))
        self.assertEqual(keys_from_event(0x4 | 0x1, "S"), "ctrl+shift+s")
        self.assertEqual(keys_from_event(0x20000, "F9"), "alt+f9")
        self.assertEqual(keys_from_event(0x4, "Prior"), "ctrl+pageup")
        self.assertIsNone(keys_from_event(0x4, "Return"))


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
