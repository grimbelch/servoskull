"""Render the Omega-7 home-screen icons (the cog sigil) into core/static.

Run after changing the icon: python generate_icons.py
"""
import math
from PIL import Image, ImageDraw

BG = (4, 18, 10, 255)
GREEN = (70, 255, 120, 255)
DIM = (24, 92, 44, 255)


def draw_icon(size: int, pad_ratio: float) -> Image.Image:
    ss = 8  # supersample
    s = size * ss
    img = Image.new("RGBA", (s, s), BG)
    d = ImageDraw.Draw(img)
    c = s / 2
    r = (s / 2) * (1 - pad_ratio)          # sigil radius inside the safe area

    # outer tooth ring: eight trapezoids, the AdMech cog
    teeth = 8
    for i in range(teeth):
        a = (2 * math.pi / teeth) * i - math.pi / 2
        inner, outer = r * 0.70, r * 1.00
        half = 0.085 * math.pi
        pts = [
            (c + inner * math.cos(a - half), c + inner * math.sin(a - half)),
            (c + outer * math.cos(a - half * 0.62), c + outer * math.sin(a - half * 0.62)),
            (c + outer * math.cos(a + half * 0.62), c + outer * math.sin(a + half * 0.62)),
            (c + inner * math.cos(a + half), c + inner * math.sin(a + half)),
        ]
        d.polygon(pts, fill=GREEN)

    # cog body ring
    ring_w = r * 0.13
    d.ellipse([c - r * 0.72, c - r * 0.72, c + r * 0.72, c + r * 0.72], fill=GREEN)
    d.ellipse([c - r * 0.72 + ring_w, c - r * 0.72 + ring_w,
               c + r * 0.72 - ring_w, c + r * 0.72 - ring_w], fill=BG)

    # inner eye: a lit lens
    d.ellipse([c - r * 0.40, c - r * 0.40, c + r * 0.40, c + r * 0.40], outline=DIM, width=int(r * 0.07))
    d.ellipse([c - r * 0.22, c - r * 0.22, c + r * 0.22, c + r * 0.22], fill=GREEN)

    return img.resize((size, size), Image.LANCZOS)


for name, size, pad in (
    ("icon-180.png", 180, 0.12),
    ("icon-192.png", 192, 0.12),
    ("icon-512.png", 512, 0.12),
    ("icon-maskable-512.png", 512, 0.26),
):
    draw_icon(size, pad).save(f"core/static/{name}")
    print("wrote core/static/" + name)
