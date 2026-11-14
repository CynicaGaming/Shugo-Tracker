"""The app icon and README badge, drawn with Pillow (used by make_icon.py and readme_images.py)."""
from __future__ import annotations

import math

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


def make_bubble_image(size: int = 46):
    """Collapsed-window bubble: the app icon as a gold disc with a dark bolt."""
    from PIL import Image, ImageDraw
    ss = 8
    S = size * ss
    grad = Image.new("RGBA", (S, S))
    g = ImageDraw.Draw(grad)
    for y in range(S):
        t = y / (S - 1)
        g.line([(0, y), (S, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(GOLD_TOP, GOLD_BOTTOM)) + (255,))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).ellipse((ss, ss, S - ss, S - ss), fill=255)
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    im.paste(grad, (0, 0), mask)
    d = ImageDraw.Draw(im)
    d.ellipse((ss, ss, S - ss, S - ss), outline=INK + (255,), width=int(S * 0.03))
    pad = S * 0.17
    _bolt(d, (pad, pad, S - pad, S - pad), INK + (255,), ss)
    return im.resize((size, size), Image.LANCZOS)


def ui_icon(name: str, size: int, color: tuple, accent: tuple | None = None):
    """Small line-weight UI icons drawn at 8x and scaled down: cog, pin, minimize, close, refresh, update, search,
    back, star, star_fill."""
    import math
    from PIL import Image, ImageDraw
    ss = 8
    S = size * ss
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    col = tuple(color) + (255,)
    c = S / 2
    w = max(ss, int(S * 0.11))                     # stroke width
    if name == "cog":
        teeth, r_out, r_in = 8, S * 0.47, S * 0.35
        pts = []
        for i in range(teeth * 4):
            ang = (i / (teeth * 4)) * 2 * math.pi - math.pi / 2
            r = r_out if i % 4 in (1, 2) else r_in
            pts.append((c + r * math.cos(ang), c + r * math.sin(ang)))
        d.polygon(pts, fill=col)
        hole = S * 0.15
        d.ellipse((c - hole, c - hole, c + hole, c + hole), fill=(0, 0, 0, 0))
        if accent:                                   # update waiting: a small dot, top right
            r = S * 0.15
            d.ellipse((S - 2 * r - ss, ss, S - ss, 2 * r + ss), fill=tuple(accent) + (255,))
    elif name in ("pin", "pin_on"):
        g = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        gd = ImageDraw.Draw(g)
        cx = c
        gd.rounded_rectangle((cx - S * 0.17, S * 0.08, cx + S * 0.17, S * 0.2), radius=S * 0.04, fill=col)
        body = [(cx - S * 0.12, S * 0.2), (cx + S * 0.12, S * 0.2), (cx + S * 0.15, S * 0.5), (cx - S * 0.15, S * 0.5)]
        gd.polygon(body, fill=col)
        gd.rounded_rectangle((cx - S * 0.26, S * 0.5, cx + S * 0.26, S * 0.6), radius=S * 0.04, fill=col)
        gd.line([(cx, S * 0.6), (cx, S * 0.92)], fill=col, width=int(w * 0.8))
        im = g.rotate(-40, resample=Image.BICUBIC, center=(c, c))
    elif name == "update":                       # a tray with an arrow into it: "download update"
        d.line([(S * 0.16, S * 0.58), (S * 0.16, S * 0.84), (S * 0.84, S * 0.84), (S * 0.84, S * 0.58)],
               fill=col, width=w, joint="curve")
        d.line([(c, S * 0.12), (c, S * 0.6)], fill=col, width=w)
        d.polygon([(c - S * 0.2, S * 0.42), (c + S * 0.2, S * 0.42), (c, S * 0.66)], fill=col)
    elif name == "minimize":
        d.line([(S * 0.22, c), (S * 0.78, c)], fill=col, width=w)
    elif name == "close":
        a, b2 = S * 0.25, S * 0.75
        d.line([(a, a), (b2, b2)], fill=col, width=w)
        d.line([(a, b2), (b2, a)], fill=col, width=w)
    elif name == "refresh":
        box = (S * 0.18, S * 0.18, S * 0.82, S * 0.82)
        d.arc(box, start=-60, end=250, fill=col, width=w)
        ang = math.radians(-60)
        tip = (c + S * 0.32 * math.cos(ang), c + S * 0.32 * math.sin(ang))
        d.polygon([(tip[0] - S * 0.16, tip[1] - S * 0.02), (tip[0] + S * 0.1, tip[1] - S * 0.14),
                   (tip[0] + S * 0.05, tip[1] + S * 0.16)], fill=col)
    elif name.startswith("progress"):            # "progress:NN": a ring that fills clockwise (downloading)
        pct = max(0, min(100, int(name.split(":")[1]) if ":" in name else 0))
        box = (S * 0.14, S * 0.14, S * 0.86, S * 0.86)
        d.ellipse(box, outline=tuple(accent or (60, 62, 70)) + (255,), width=w)
        if pct:
            d.arc(box, start=-90, end=-90 + 360 * pct / 100, fill=col, width=w)
    elif name == "person":                         # nobody chosen yet: a plain head and shoulders
        r = S * 0.17
        d.ellipse((c - r, S * 0.16, c + r, S * 0.16 + 2 * r), fill=col)
        d.pieslice((S * 0.18, S * 0.56, S * 0.82, S * 1.2), start=180, end=360, fill=col)
    elif name == "search":
        r = S * 0.27
        cx, cy = S * 0.43, S * 0.43
        d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=col, width=w)
        d.line([(cx + r * 0.72, cy + r * 0.72), (S * 0.86, S * 0.86)], fill=col, width=w)
    elif name == "back":
        d.line([(S * 0.62, S * 0.2), (S * 0.32, c), (S * 0.62, S * 0.8)], fill=col, width=w, joint="curve")
    elif name in ("star", "star_fill"):
        pts = []
        for i in range(10):
            ang = -math.pi / 2 + i * math.pi / 5
            r = S * (0.45 if i % 2 == 0 else 0.19)
            pts.append((c + r * math.cos(ang), c * 1.06 + r * math.sin(ang)))
        if name == "star_fill":
            d.polygon(pts, fill=col)
        else:
            d.line(pts + pts[:2], fill=col, width=int(w * 0.85), joint="curve")
    return im.resize((size, size), Image.LANCZOS)


def save_ico(path: str) -> None:
    make_icon_image(256).save(path, sizes=[(s, s) for s in (16, 20, 24, 32, 40, 48, 64, 128, 256)])
