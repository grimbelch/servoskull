"""Votive Candle – the skull's candle-lantern keeps its vigil.

A layered, swaying flame flickers over a wax candle with drips and a brass
dish, casting a pulsing amber halo; smoke curls off the tip. The candle burns
down over a five-minute showing. "IN DEATH / STILL I SERVE".
"""

from __future__ import annotations

import math
import random

import numpy as np
from PIL import Image, ImageDraw

from ._common import Session, text_center

NAME = "votive_candle"

_session = Session()

_YY, _XX = np.mgrid[0:240, 0:240].astype(np.float32)
_RR = np.hypot(_XX - 120, _YY - 120)


_votive_state = {"halo": None, "smoke": [], "start": None}


def render(bezel, mask, now):
    if _session.fresh(now):
        _votive_state["start"] = now
        _votive_state["smoke"] = []
    st = _votive_state
    if st["halo"] is None:
        g = np.clip(1.0 - np.hypot(_XX - 120, (_YY - 96) * 1.2) / 125.0, 0, 1) ** 2.2
        st["halo"] = np.stack([g * 255, g * 130, g * 35], axis=-1).astype(np.float32)
        st["start"] = now
    flick = 0.78 + 0.12 * math.sin(now * 7.3) + 0.07 * math.sin(now * 13.1) + random.uniform(-0.05, 0.05)
    base = np.clip(st["halo"] * flick + np.array([6, 3, 2], np.float32), 0, 255).astype(np.uint8)
    img = Image.fromarray(base)
    d = ImageDraw.Draw(img)

    # Candle burns down over five minutes, then is replaced
    burn = ((now - st["start"]) % 300.0) / 300.0
    top = 118 + int(burn * 30)
    d.rectangle([102, top, 138, 196], fill=(220, 200, 160))
    d.rectangle([132, top, 138, 196], fill=(185, 165, 125))
    for dx, ln in ((104, 18), (113, 9), (124, 26), (131, 14)):
        d.rounded_rectangle([dx, top - 2, dx + 5, top + ln], radius=2, fill=(235, 220, 185))
    d.ellipse([100, top - 4, 140, top + 5], fill=(240, 228, 200))
    # Brass dish
    d.polygon([(76, 196), (164, 196), (150, 208), (90, 208)], fill=(120, 80, 30))
    d.line([(76, 196), (164, 196)], fill=(200, 150, 70), width=2)

    # Wick and layered flame with sway
    sway = 3 * math.sin(now * 2.1) + 1.5 * math.sin(now * 5.7)
    fh = 34 * flick + random.uniform(-2, 2)
    wx, wy = 120, top - 3
    d.line([(wx, wy), (wx + sway * 0.2, wy - 6)], fill=(30, 20, 10), width=2)
    tip = (wx + sway, wy - fh)
    for w, h, col in ((11, 1.0, (255, 120, 20)), (8, 0.8, (255, 190, 60)), (4.5, 0.55, (255, 245, 200))):
        pts = []
        for k in range(17):
            a = math.pi * k / 16
            yy = wy - 4 - (fh * h - 4) * (1 - math.cos(a)) / 2
            ww = w * math.sin(a) ** 0.7 * (1 - (wy - yy) / (fh * h + 6)) ** 0.5
            pts.append((wx + sway * (wy - yy) / fh + ww, yy))
        for k in range(16, -1, -1):
            a = math.pi * k / 16
            yy = wy - 4 - (fh * h - 4) * (1 - math.cos(a)) / 2
            ww = w * math.sin(a) ** 0.7 * (1 - (wy - yy) / (fh * h + 6)) ** 0.5
            pts.append((wx + sway * (wy - yy) / fh - ww, yy))
        d.polygon(pts, fill=col)
    d.ellipse([wx - 3, wy - 9, wx + 3, wy - 2], fill=(70, 90, 200))

    # Smoke wisps curl off the tip
    if random.random() < 0.25:
        st["smoke"].append([tip[0], tip[1] - 4, 1.0, random.uniform(0, 6.28)])
    for s in st["smoke"]:
        s[1] -= 0.9
        s[0] += 0.5 * math.sin(now * 2 + s[3])
        s[2] -= 0.015
        v = int(70 * s[2])
        d.point((s[0], s[1]), fill=(v, v, v))
    st["smoke"] = [s for s in st["smoke"] if s[2] > 0]

    amber = (int(200 * flick), int(130 * flick), 40)
    text_center(d, 22, "IN DEATH", amber, 13)
    text_center(d, 212, "STILL I SERVE", (150, 95, 30), 10)
    return img
