"""Purity Seal – wax seals stamped in blessing.

A red wax seal embossed with the cog-skull stamps down with a shockwave
every few seconds over fluttering parchment strips, each time with a new
litany of sanctification.
"""

from __future__ import annotations

import math
import random

from PIL import Image, ImageDraw

from ._common import Session, text_center

NAME = "purity_seal"

_session = Session()


_PURITY_LITANIES = ["BLESSED BE THIS UNIT", "PURGED OF TAINT", "SANCTIFIED BY THE OMNISSIAH",
                    "WARDED AGAINST THE WARP", "RITES OF MAINTENANCE OBSERVED", "SEALED IN FAITH"]
_purity_state = {"seal": None, "stamp": -99.0, "litany": ""}


def _build_wax_seal():
    rng = random.Random(41)
    pts = []
    for k in range(40):
        a = 2 * math.pi * k / 40
        r = 42 + rng.uniform(-3, 4) + 3 * math.sin(a * 5)
        pts.append((r * math.cos(a), r * math.sin(a)))
    return pts


def render(bezel, mask, now):
    if _session.fresh(now):
        _purity_state["stamp"] = -99.0
    st = _purity_state
    if st["seal"] is None:
        st["seal"] = _build_wax_seal()
    if now - st["stamp"] > 14.0:
        st["stamp"], st["litany"] = now, random.choice(_PURITY_LITANIES)
    age = now - st["stamp"]
    scale = 1.0 + max(0.0, 0.5 - age) * 1.2
    img = Image.new("RGB", (240, 240), (14, 8, 6))
    d = ImageDraw.Draw(img)
    d.ellipse([10, 10, 230, 230], outline=(120, 90, 40), width=2)
    for i in range(36):
        a = math.radians(i * 10 + now * 3)
        d.point((120 + 104 * math.cos(a), 120 + 104 * math.sin(a)), fill=(170, 130, 60))

    cx, cy = 120, 90
    # Parchment strips fluttering below the seal
    for j, x0 in enumerate((96, 120, 144)):
        left, right = [], []
        for s in range(13):
            y = cy + 20 + s * 8
            wave = 6 * math.sin(now * 2.4 + s * 0.45 + j * 1.3) * (s / 12)
            left.append((x0 - 8 + wave, y))
            right.append((x0 + 8 + wave, y))
        d.polygon(left + right[::-1], fill=(205, 185, 140), outline=(120, 95, 60))
        for s in range(1, 12, 2):
            (lx, ly), (rx, _) = left[s], right[s]
            d.line([(lx + 3, ly), (rx - 3 - (s % 3) * 2, ly)], fill=(70, 45, 25), width=1)

    if age < 0.5:
        ring = age * 180
        c = int(200 * (1 - age / 0.5))
        d.ellipse([cx - ring, cy - ring, cx + ring, cy + ring], outline=(c, c // 3, c // 4), width=2)

    # Wax seal with embossed cog-skull
    poly = [(cx + x * scale, cy + y * scale) for x, y in st["seal"]]
    d.polygon(poly, fill=(150, 18, 16))
    r1 = 30 * scale
    d.ellipse([cx - r1, cy - r1, cx + r1, cy + r1], fill=(125, 12, 12), outline=(190, 50, 40), width=2)
    for i in range(10):
        a = math.radians(i * 36)
        x1, y1 = cx + 22 * scale * math.cos(a), cy + 22 * scale * math.sin(a)
        x2, y2 = cx + 27 * scale * math.cos(a), cy + 27 * scale * math.sin(a)
        d.line([(x1, y1), (x2, y2)], fill=(95, 8, 8), width=int(5 * scale))
    d.ellipse([cx - 22 * scale, cy - 22 * scale, cx + 22 * scale, cy + 22 * scale], outline=(95, 8, 8), width=int(3 * scale))
    d.ellipse([cx - 11 * scale, cy - 13 * scale, cx + 11 * scale, cy + 7 * scale], fill=(95, 8, 8))
    d.rectangle([cx - 6 * scale, cy + 4 * scale, cx + 6 * scale, cy + 12 * scale], fill=(95, 8, 8))
    for ex in (-5, 5):
        d.ellipse([cx + (ex - 3) * scale, cy - 6 * scale, cx + (ex + 3) * scale, cy], fill=(170, 30, 25))
    gl = math.radians(now * 25)
    d.arc([cx - r1 + 4, cy - r1 + 4, cx + r1 - 4, cy + r1 - 4], math.degrees(gl), math.degrees(gl) + 40, fill=(230, 110, 90), width=2)

    if age < 0.2:
        d.ellipse([cx - 45, cy - 45, cx + 45, cy + 45], fill=(255, 200, 160))
    text_center(d, 30, "PURITY SEAL", (170, 130, 60), 9)
    if age > 0.5:
        text_center(d, 208, st["litany"], (200, 160, 80), 8)
    return img
