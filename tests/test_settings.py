"""Settings: migration from older versions, the opacity rule, hotkey capture text, cache clearing."""
import json
import os
import tempfile
import unittest

from shugotracker import aion2api as a
from shugotracker.settings import OPACITY_MIN, SETTING_DEFAULTS, clamp_opacity, decide_opacity, migrate


class MigrateTests(unittest.TestCase):
    def test_old_v170_config(self):
        cfg = migrate({"opacity": 0.97, "idle_opacity": 0.45, "hotkey": "alt+f9", "region": "nae"})
        self.assertEqual(cfg["opacity_focused"], 1.0)      # old 0.97 is not carried: active = solid
        self.assertEqual(cfg["opacity_unfocused"], 0.45)
        self.assertEqual(cfg["hotkey"], "alt+f9")
        for gone in ("opacity", "idle_opacity", "region"):
            self.assertNotIn(gone, cfg)

    def test_defaults_and_clamp(self):
        cfg = migrate({"opacity_unfocused": 0.01, "opacity_focused": "junk"})
        self.assertEqual(cfg["opacity_unfocused"], OPACITY_MIN)
        self.assertEqual(cfg["opacity_focused"], 1.0)
        for k in SETTING_DEFAULTS:
            self.assertIn(k, cfg)
        self.assertEqual(clamp_opacity(3), 1.0)


class OpacityRuleTests(unittest.TestCase):
    cfg = {"opacity_focused": 0.9, "opacity_unfocused": 0.5, "opacity_full_on_hover": True}

    def test_rule(self):
        self.assertEqual(decide_opacity(self.cfg, True, False), 0.9)
        self.assertEqual(decide_opacity(self.cfg, False, False), 0.5)
        self.assertEqual(decide_opacity(self.cfg, False, True), 0.9)
        self.assertEqual(decide_opacity({**self.cfg, "opacity_full_on_hover": False}, False, True), 0.5)


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
            api.set_rate(3)
            self.assertEqual(api.limiter.rate, 3)
            api.clear_caches()
            self.assertEqual((api._cache, api._search_cache, os.listdir(pd), os.path.exists(cp)), ({}, {}, [], False))


if __name__ == "__main__":
    unittest.main()
