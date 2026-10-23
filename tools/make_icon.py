"""Regenerate assets/ShugoTracker.ico from the drawing in shugotracker/desktop.py."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from shugotracker.desktop import make_bubble_image, make_icon_image, save_ico  # noqa: E402

here = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
save_ico(os.path.join(here, "ShugoTracker.ico"))
make_icon_image(256).save(os.path.join(here, "icon.png"))
make_bubble_image(92).save(os.path.join(here, "bubble.png"))
print("written to", here)
