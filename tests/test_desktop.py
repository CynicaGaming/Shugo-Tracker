"""Overlay helpers: hotkey parsing, single-instance handoff."""
import threading
import unittest

from shugotracker import desktop as d


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
