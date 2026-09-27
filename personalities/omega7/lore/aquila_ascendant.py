"""Aquila Ascendant – the double-headed eagle in gold.

A gilded Aquila with a crimson-eyed skull on its breast, a specular sweep
travelling across the gold and a rotating halo of rays behind it.
"""

from __future__ import annotations

import math

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from ._common import text_center

NAME = "aquila_ascendant"

_YY, _XX = np.mgrid[0:240, 0:240].astype(np.float32)
_RR = np.hypot(_XX - 120, _YY - 120)


_aquila_state = {"mask": None}


def _aquila_mask():
    s = 1.0
    wing = [(6, -10), (22, -26), (44, -38), (70, -46), (98, -44), (92, -32), (84, -34),
            (80, -18), (70, -22), (66, -4), (56, -10), (50, 8), (40, 2), (32, 18), (22, 12), (12, 20), (4, 14)]
    head = [(3, -14), (6, -30), (10, -40), (18, -47), (27, -46), (34, -40), (38, -34),
            (31, -35), (27, -30), (20, -30), (14, -24), (10, -12)]
    tail = [(0, 16), (9, 16), (14, 40), (8, 36), (6, 50), (0, 44)]
    m = Image.new("L", (240, 240), 0)
    d = ImageDraw.Draw(m)
    for poly in (wing, head, tail):
        for sign in (1, -1):
            d.polygon([(120 + sign * x * s, 124 + y * s) for x, y in poly], fill=255)
    d.ellipse([108, 104, 132, 144], fill=255)
    return m


def render(bezel, mask, now):
    st = _aquila_state
    if st["mask"] is None:
        st["mask"] = _aquila_mask()
    img = Image.new("RGB", (240, 240), (12, 4, 2))
    d = ImageDraw.Draw(img)

    # Rotating halo rays
    pulse = 0.6 + 0.4 * math.sin(now * 1.5)
    for i in range(24):
        a = math.radians(i * 15 + now * 6)
        r1 = 112 if i % 2 == 0 else 96
        c = (int(90 * pulse), int(55 * pulse), 10)
        d.polygon([(120, 120), (120 + r1 * math.cos(a - 0.05), 120 + r1 * math.sin(a - 0.05)),
                   (120 + r1 * math.cos(a + 0.05), 120 + r1 * math.sin(a + 0.05))], fill=c)
    d.ellipse([60, 60, 180, 180], fill=(30, 10, 4))

    # Gold with a travelling specular sweep
    sweep = ((now * 90) % 520) - 140
    diag = _XX + _YY * 0.6
    hl = np.clip(1 - np.abs(diag - sweep) / 22.0, 0, 1)
    shade = 0.62 + 0.2 * (1 - _YY / 240.0) + 0.55 * hl
    gold = np.stack([np.clip(235 * shade, 0, 255), np.clip(170 * shade, 0, 255), np.clip(55 * shade + 120 * hl, 0, 255)], -1)
    gold_img = Image.fromarray(gold.astype(np.uint8))
    img.paste(gold_img, (0, 0), st["mask"])
    edge = st["mask"].filter(ImageFilter.FIND_EDGES)
    img.paste((110, 60, 10), (0, 0), edge)

    # Skull on the breast, crimson eyes
    d.ellipse([112, 110, 128, 126], fill=(40, 20, 8))
    d.rectangle([115, 124, 125, 131], fill=(40, 20, 8))
    d.ellipse([114, 115, 119, 120], fill=(220, 20, 10))
    d.ellipse([121, 115, 126, 120], fill=(220, 20, 10))

    text_center(d, 196, "AVE IMPERATOR", (230, 170, 60), 12)
    return img
