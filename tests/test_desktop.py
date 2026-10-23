"""Overlay helpers: hotkey parsing, single-instance handoff, tray icon."""
import threading
import unittest

from shugotracker import desktop as d


class HotkeyParseTests(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(d.parse_hotkey("ctrl+shift+s"), (d.MOD_CONTROL | d.MOD_SHIFT, ord("S")))
        self.assertEqual(d.parse_hotkey("Alt + F9"), (d.MOD_ALT, 0x78))
        self.assertEqual(d.parse_hotkey("ctrl-`"), (d.MOD_CONTROL, 0xC0))
        self.assertEqual(d.parse_hotkey("F10"), (0, 0x79))          # a bare F-key is fine

    def test_rejects(self):
        for bad in ("", "s", "ctrl", "ctrl+shift+s+d", "ctrl+banana"):
            self.assertIsNone(d.parse_hotkey(bad), bad)              # a bare letter would steal game input

    def test_label(self):
        self.assertEqual(d.hotkey_label("ctrl+shift+s"), "Ctrl+Shift+S")
        self.assertEqual(d.hotkey_label("alt+f9"), "Alt+F9")


class SingleInstanceTests(unittest.TestCase):
    def test_second_launch_shows_first(self):
        port = 47999
        first = d.SingleInstance(port)
        self.assertTrue(first.acquire())
        self.addCleanup(first.release)
        shown = threading.Event()
        first.on_show = shown.set
        second = d.SingleInstance(port)
        self.assertFalse(second.acquire())
        self.assertTrue(second.notify_running())
        self.assertTrue(shown.wait(2))

    def test_nobody_running(self):
        self.assertFalse(d.SingleInstance(47998).notify_running())


class IconTests(unittest.TestCase):
    def test_bolt_icons(self):
        try:
            import PIL  # noqa: F401
        except ImportError:
            self.skipTest("no Pillow")
        im = d.make_icon_image(32)
        self.assertEqual((im.size, im.getpixel((0, 0))[3]), ((32, 32), 0))     # rounded corner is clear
        self.assertGreater(im.getpixel((16, 2))[0], 200)                      # gold edge
        b = d.make_bubble_image(46)
        self.assertEqual((b.size, b.getpixel((0, 0))[3]), ((46, 46), 0))

    def test_icon(self):
        try:
            import PIL  # noqa: F401
        except ImportError:
            self.skipTest("Pillow not installed")
        im = d.make_icon_image(64)
        self.assertEqual(im.size, (64, 64))
        self.assertEqual(im.getpixel((32, 4))[3], 255)               # gold disc is opaque
        self.assertEqual(im.getpixel((0, 0))[3], 0)                  # corners transparent


if __name__ == "__main__":
    unittest.main()
