"""Regenerate desktop/build/icon.ico (the exe's and window's icon) from the drawing in tools/icons.py."""
import os

from icons import save_ico

path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "desktop", "build", "icon.ico")
save_ico(path)
print("written", path)
