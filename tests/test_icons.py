"""The app icon drawing (tools/icons.py)."""
import unittest


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

    def test_icon(self):
        im = self.icons.make_icon_image(64)
        self.assertEqual(im.size, (64, 64))
        self.assertEqual(im.getpixel((32, 4))[3], 255)               # gold disc is opaque
        self.assertEqual(im.getpixel((0, 0))[3], 0)                  # corners transparent


if __name__ == "__main__":
    unittest.main()
