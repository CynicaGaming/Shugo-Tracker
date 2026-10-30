"""Builds the README images (docs/images) from the CI screenshots: python tools/readme_images.py <shots folder>."""
import sys
sys.path.insert(0, ".")
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from shugotracker.desktop import make_icon_image

S = sys.argv[1] if len(sys.argv) > 1 else "shots/"   # a folder with the CI screenshots (ci-screenshots branch)
OUT = "docs/images/"
BOLD = "/usr/share/fonts/opentype/inter/Inter-Bold.otf"
REG = "/usr/share/fonts/opentype/inter/Inter-Regular.otf"
GOLD = (217, 169, 58)


def bg(w, h):
    """Graphite with a soft gold glow, top left."""
    im = Image.new("RGB", (w, h), (13, 14, 17))
    glow = Image.new("RGB", (w, h), (0, 0, 0))
    d = ImageDraw.Draw(glow)
    d.ellipse((-w * 0.25, -h * 0.9, w * 0.55, h * 0.8), fill=(70, 52, 14))
    d.ellipse((w * 0.6, h * 0.3, w * 1.3, h * 1.6), fill=(22, 26, 40))
    glow = glow.filter(ImageFilter.GaussianBlur(min(w, h) * 0.25))
    return Image.blend(im, glow, 0.9)


def rounded(img, r=14):
    m = Image.new("L", img.size, 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, img.size[0] - 1, img.size[1] - 1), r, fill=255)
    out = Image.new("RGBA", img.size)
    out.paste(img, (0, 0), m)
    return out


def drop(canvas, img, xy, r=14, blur=22):
    sh = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle((xy[0] + 6, xy[1] + 14, xy[0] + img.size[0] + 6, xy[1] + img.size[1] + 14), r,
                                         fill=(0, 0, 0, 170))
    canvas.alpha_composite(sh.filter(ImageFilter.GaussianBlur(blur)))
    canvas.alpha_composite(rounded(img, r), xy)


def framed(name, out, crop=None, pad=60):
    shot = Image.open(S + name).convert("RGB")
    if crop:
        shot = shot.crop(crop)
    w, h = shot.size[0] + pad * 2, shot.size[1] + pad * 2
    c = bg(w, h).convert("RGBA")
    drop(c, shot, (pad, pad))
    c.convert("RGB").save(OUT + out, optimize=True)


# banner
W, H = 1280, 360
c = bg(W, H).convert("RGBA")
icon = make_icon_image(132)
c.alpha_composite(icon.convert("RGBA"), (120, (H - 132) // 2))
d = ImageDraw.Draw(c)
d.text((290, 98), "Shugo Tracker", font=ImageFont.truetype(BOLD, 76), fill=(236, 237, 241))
d.text((294, 196), "Every AION 2 player's gear, power and build, a glance away.", font=ImageFont.truetype(REG, 30),
       fill=(170, 174, 186))
d.text((294, 246), "A fast, free overlay for Windows", font=ImageFont.truetype(REG, 24), fill=GOLD)
c.convert("RGB").save(OUT + "banner.png", optimize=True)

# hero: the list + a profile with an item tooltip beside it
win = Image.open(S + "ui-demo.png").convert("RGB")
prof = Image.open(S + "ui-demo-profile-gear-tip.png").convert("RGB")
pwin, tip = prof.crop((0, 0, 600, 720)), prof.crop((606, 240, 839, 603))
W, H = 1440, 900
c = bg(W, H).convert("RGBA")
drop(c, win.resize((540, 648)), (90, 150))
drop(c, pwin, (560, 90))
drop(c, tip.resize((int(tip.size[0] * 1.25), int(tip.size[1] * 1.25))), (1100, 230), r=10)
c.convert("RGB").save(OUT + "hero.png", optimize=True)

framed("ui-demo.png", "search.png")
framed("ui-demo-filters.png", "filters.png")
framed("ui-demo-nearby.png", "nearby.png")
framed("ui-demo-nearby-recent.png", "recent.png")
framed("ui-demo-favorites-drag.png", "favorites.png", crop=(0, 0, 600, 320))
framed("ui-demo-profile-stats-hover.png", "stats.png", crop=(0, 0, 600, 470))
framed("ui-demo-columns-menu.png", "columns.png", crop=(0, 0, 600, 470))
# tooltip + arcana side by side
arc = Image.open(S + "ui-demo-profile-arcana-tip.png").convert("RGB")
print("arcana", arc.size)
