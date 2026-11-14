"""The app icon drawing (tools/icons.py) and the core's small Windows helpers."""
import os
import tempfile
import unittest

from shugotracker import desktop as d


class IconTests(unittest.TestCase):
    def setUp(self):
        try:
            import PIL  # noqa: F401
        except ImportError:
            self.skipTest("Pillow not installed")
        from tools import icons
        self.icons = icons

    def test_bolt_icons(self):
        im = self.icons.make_icon_image(32)
        self.assertEqual((im.size, im.getpixel((0, 0))[3]), ((32, 32), 0))     # rounded corner is clear
        self.assertGreater(im.getpixel((16, 2))[0], 200)                      # gold edge
        b = self.icons.make_bubble_image(46)
        self.assertEqual((b.size, b.getpixel((0, 0))[3]), ((46, 46), 0))

    def test_icon(self):
        im = self.icons.make_icon_image(64)
        self.assertEqual(im.size, (64, 64))
        self.assertEqual(im.getpixel((32, 4))[3], 255)               # gold disc is opaque
        self.assertEqual(im.getpixel((0, 0))[3], 0)                  # corners transparent


class HelperTests(unittest.TestCase):
    def test_folder_size(self):
        with tempfile.TemporaryDirectory() as t:
            os.makedirs(os.path.join(t, "a"))
            for rel, n in ((("x",), 10), (("a", "y"), 5)):
                with open(os.path.join(t, *rel), "wb") as f:
                    f.write(b"0" * n)
            self.assertEqual(d.folder_size(t), 15)

    def test_alt_down_off_windows(self):
        if os.name != "nt":
            self.assertIsNone(d.alt_down())


if __name__ == "__main__":
    unittest.main()
