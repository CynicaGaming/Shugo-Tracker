"""Builds the README images (docs/images) from the CI screenshots: python tools/readme_images.py <shots folder>."""
import sys
sys.path.insert(0, ".")
from PIL import Image, ImageDraw, ImageFilter, ImageFont
sys.path.insert(0, "tools")
from icons import make_icon_image  # noqa: E402

S = sys.argv[1] if len(sys.argv) > 1 else "shots/"   # a folder with the CI screenshots (ci-screenshots branch)
P = sys.argv[2] if len(sys.argv) > 2 else "phone/"   # the phone screenshots (tools/phone_shots.js)
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
d.text((294, 246), "A fast, free overlay for Windows, and an app for Android", font=ImageFont.truetype(REG, 24), fill=GOLD)
c.convert("RGB").save(OUT + "banner.png", optimize=True)

# hero: the list, and a profile with an item tooltip, side by side
win = Image.open(S + "show-search.png").convert("RGB")
prof = Image.open(S + "show-profile-gear-tip.png").convert("RGB")
W, H = 1440, 900
c = bg(W, H).convert("RGBA")
drop(c, win, (110, (H - win.size[1]) // 2 + 40))
drop(c, prof, (W - prof.size[0] - 110, (H - prof.size[1]) // 2 - 40))
c.convert("RGB").save(OUT + "hero.png", optimize=True)

framed("show-search.png", "search.png")
framed("show-filters.png", "filters.png")
framed("show-nearby.png", "nearby.png")
framed("show-recent.png", "recent.png", crop=(0, 0, 560, 480))
framed("show-favorites.png", "favorites.png", crop=(0, 0, 560, 320))
framed("show-columns-menu.png", "columns.png", crop=(0, 0, 560, 470))
framed("show-profile-gear-tip.png", "gear.png")
framed("show-profile-skills-tip.png", "skills.png")
framed("show-profile-daevanion.png", "daevanion.png")

# download buttons (self-hosted, so they never depend on a badge service)
def button(label, glyph, out, fill=GOLD, ink=(26, 19, 6), edge=None):
    f = ImageFont.truetype(BOLD, 30)
    tw = int(f.getlength(label))
    bw, bh = tw + 140, 76
    btn = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    d = ImageDraw.Draw(btn)
    d.rounded_rectangle((0, 0, bw - 1, bh - 1), radius=18, fill=fill, outline=edge, width=3 if edge else 0)
    glyph(d, 40, 24, ink)
    d.text((40 + 29 + 22, bh // 2), label, font=f, fill=ink, anchor="lm")
    btn.save(OUT + out, optimize=True)


def windows(d, x0, y0, ink, s=13):          # four squares
    for dx in (0, s + 3):
        for dy in (0, s + 3):
            d.rectangle((x0 + dx, y0 + dy, x0 + dx + s, y0 + dy + s), fill=ink)


def phone(d, x0, y0, ink):                  # a phone
    d.rounded_rectangle((x0 + 4, y0 - 3, x0 + 24, y0 + 32), radius=4, outline=ink, width=3)
    d.line((x0 + 11, y0 + 26, x0 + 17, y0 + 26), fill=ink, width=3)


button("Download for Windows", windows, "download.png")
button("Download for Android", phone, "download-android.png", fill=(22, 24, 30), ink=GOLD, edge=GOLD)

# the Android app: three phones side by side
def handset(name, h=1180):
    shot = Image.open(P + name).convert("RGB")
    shot = shot.resize((round(shot.size[0] * h / shot.size[1]), h), Image.LANCZOS)
    b = 16                                   # the bezel
    body = Image.new("RGBA", (shot.size[0] + b * 2, h + b * 2), (0, 0, 0, 0))
    ImageDraw.Draw(body).rounded_rectangle((0, 0, body.size[0] - 1, body.size[1] - 1), 58, fill=(24, 26, 32),
                                           outline=(58, 62, 72), width=3)
    body.alpha_composite(rounded(shot, 44), (b, b))
    return body


phones = [handset(n) for n in ("search.png", "gear-tip.png", "stats.png")]
gap = 70
W = sum(p.size[0] for p in phones) + gap * 4
H = phones[0].size[1] + 160
c = bg(W, H).convert("RGBA")
x = gap
for i, ph in enumerate(phones):
    drop(c, ph, (x, 80 + (0 if i == 1 else 40)), r=58, blur=30)
    x += ph.size[0] + gap
c = c.resize((W // 2, H // 2), Image.LANCZOS)
c.convert("RGB").save(OUT + "android.png", optimize=True)
