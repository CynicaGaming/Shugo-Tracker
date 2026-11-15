"""The app icon, drawn with Pillow (make_icon.py writes desktop/build/icon.ico; readme_images.py uses it too)."""
from __future__ import annotations


# ───── icons ─────
# Lightning bolt, in 0..1 coordinates of the icon square.
BOLT = [(0.585, 0.08), (0.215, 0.565), (0.465, 0.565), (0.405, 0.92), (0.785, 0.425), (0.535, 0.425), (0.655, 0.08)]
GOLD_TOP, GOLD_BOTTOM, INK = (246, 205, 98), (210, 154, 42), (26, 19, 6)


def _bolt(draw, box, fill, ss):
    x0, y0, x1, y1 = box
    pts = [(x0 + x * (x1 - x0), y0 + y * (y1 - y0)) for x, y in BOLT]
    draw.polygon(pts, fill=fill)
    draw.line(pts + pts[:1], fill=fill, width=max(1, int((x1 - x0) * 0.035)), joint="curve")  # soften the tips


def make_icon_image(size: int = 64):
    """App icon: a gold rounded square with a dark lightning bolt."""
    from PIL import Image, ImageDraw
    ss = 8
    S = size * ss
    grad = Image.new("RGBA", (S, S))
    g = ImageDraw.Draw(grad)
    for y in range(S):
        t = y / (S - 1)
        g.line([(0, y), (S, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(GOLD_TOP, GOLD_BOTTOM)) + (255,))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, S - 1, S - 1), radius=int(S * 0.24), fill=255)
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    im.paste(grad, (0, 0), mask)
    _bolt(ImageDraw.Draw(im), (0, 0, S, S), INK + (255,), ss)
    return im.resize((size, size), Image.LANCZOS)


def save_ico(path: str) -> None:
    make_icon_image(256).save(path, sizes=[(s, s) for s in (16, 20, 24, 32, 40, 48, 64, 128, 256)])
