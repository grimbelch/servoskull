"""Censer Thurible – a swinging censer sanctifies the air.

A brass thurible swings on its chain before a gothic window, embers glowing
through its vents, leaving a trail of incense smoke that rises and lingers.
"""

from __future__ import annotations

import math
import random

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from ._common import Session, text_center

NAME = "censer_thurible"

_session = Session()


_censer_state = {"smoke": None, "bg": None}


def _censer_background():
    img = Image.new("RGB", (240, 240), (8, 5, 6))
    d = ImageDraw.Draw(img)
    # Gothic window: lancet arch with tracery, faint stained glass
    d.polygon([(70, 230), (70, 110), (95, 60), (120, 44), (145, 60), (170, 110), (170, 230)], fill=(18, 12, 26))
    for x, col in ((85, (40, 12, 16)), (120, (14, 22, 44)), (155, (40, 30, 10))):
        d.rectangle([x - 12, 110, x + 12, 230], fill=col)
    d.ellipse([104, 66, 136, 98], outline=(50, 40, 60), width=2)
    for x in (97, 143):
        d.line([(x, 110), (x, 230)], fill=(8, 5, 6), width=3)
    return img


def render(bezel, mask, now):
    if _session.fresh(now):
        _censer_state["smoke"] = np.zeros((240, 240), np.float32)
    st = _censer_state
    if st["bg"] is None:
        st["bg"] = _censer_background()
        st["smoke"] = np.zeros((240, 240), np.float32)
    sm = st["smoke"]
    sm[:-1] = sm[1:]
    sm[-1] = 0
    sm *= 0.975
    drift = int(round(math.sin(now * 0.4) * 1.0))
    if drift:
        sm[:] = np.roll(sm, drift, axis=1)

    ang = 0.5 * math.sin(now * 1.4)
    px, py, L = 120, 18, 118
    cx, cy = px + L * math.sin(ang), py + L * math.cos(ang)

    layer = Image.fromarray(np.clip(sm, 0, 255).astype(np.uint8))
    ld = ImageDraw.Draw(layer)
    for _ in range(3):
        sx, sy = cx + random.uniform(-10, 10), cy - 8 + random.uniform(-6, 4)
        r = random.uniform(3, 6)
        ld.ellipse([sx - r, sy - r, sx + r, sy + r], fill=random.randint(150, 220))
    layer = layer.filter(ImageFilter.BoxBlur(1))
    st["smoke"] = np.asarray(layer, dtype=np.float32).copy()

    smoke_col = Image.new("RGB", (240, 240), (170, 160, 150))
    img = Image.composite(smoke_col, st["bg"], layer.point(lambda v: min(255, int(v * 0.8))))
    d = ImageDraw.Draw(img)

    # Chain of links
    for i in range(0, int(L) - 20, 6):
        t = i / L
        x, y = px + (cx - px) * t, py + (cy - py) * t
        d.ellipse([x - 2, y - 2, x + 2, y + 2], outline=(150, 110, 50))
    d.ellipse([px - 4, py - 4, px + 4, py + 4], fill=(180, 140, 60))

    # Censer body: dome lid, pierced vents with ember glow, finial
    ca, sa = math.cos(-ang), math.sin(-ang)

    def rp(x, y):
        return (cx + x * ca - y * sa, cy + x * sa + y * ca)

    body = [rp(18 * math.cos(math.radians(a)), 16 * math.sin(math.radians(a))) for a in range(0, 181, 15)]
    d.polygon(body + [rp(-18, -2), rp(18, -2)], fill=(150, 100, 35), outline=(220, 170, 80))
    dome = [rp(16 * math.cos(math.radians(a)), -2 - 18 * math.sin(math.radians(a))) for a in range(0, 181, 15)]
    d.polygon(dome, fill=(120, 80, 30), outline=(210, 160, 70))
    ember = 140 + int(100 * (0.5 + 0.5 * math.sin(now * 6)))
    for vx, vy in ((-8, -8), (0, -12), (8, -8), (-4, -4), (4, -4)):
        x, y = rp(vx, vy)
        d.ellipse([x - 2, y - 2, x + 2, y + 2], fill=(255, ember, 40))
    x, y = rp(0, 18)
    d.ellipse([x - 3, y - 3, x + 3, y + 3], fill=(210, 160, 70))
    x, y = rp(0, -22)
    d.line([rp(0, -20), rp(0, -28)], fill=(210, 160, 70), width=2)
    text_center(d, 214, "SANCTIFIED AIR", (160, 120, 60), 8)
    return img
