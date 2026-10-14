"""Votive Candle – the skull's candle-lantern keeps its vigil, on a phosphor cogitator.

A wireframe wax candle with drips stands in a brass dish, drawn in green phosphor
under a pulsing green halo; the layered, swaying flame alone burns in its true
amber and gold, and smoke curls off the tip. The candle burns down over a
five-minute showing. "IN DEATH / STILL I SERVE".
"""

from __future__ import annotations

import math
import random

import numpy as np
from PIL import Image, ImageDraw

from ..classic._phosphor import GREEN, GREEN_DIM, GREEN_FAINT, GREEN_HI, GREEN_MID, Phosphor
from ._common import Session, text_center

NAME = "votive_candle"

_session = Session()
_ph = Phosphor(decay=0.45, bloom=0.5, flicker=0.02)

_YY, _XX = np.mgrid[0:240, 0:240].astype(np.float32)
_HALO = (np.clip(1.0 - np.hypot(_XX - 120, (_YY - 96) * 1.2) / 125.0, 0, 1) ** 2.2)[..., None] \
    * np.array([6, 60, 22], np.float32)


_votive_state = {"smoke": [], "start": None}


def render(bezel, mask, now):
    if _session.fresh(now) or _votive_state["start"] is None:
        _votive_state["start"] = now
        _votive_state["smoke"] = []
        _ph.reset()
    st = _votive_state
    flick = 0.78 + 0.12 * math.sin(now * 7.3) + 0.07 * math.sin(now * 13.1) + random.uniform(-0.05, 0.05)
    img = Image.fromarray((_HALO * flick).astype(np.uint8))
    d = ImageDraw.Draw(img)

    # Candle burns down over five minutes, then is replaced
    burn = ((now - st["start"]) % 300.0) / 300.0
    top = 118 + int(burn * 30)
    d.rectangle([102, top, 138, 196], fill=GREEN_FAINT, outline=GREEN)
    d.line([(132, top + 4), (132, 196)], fill=GREEN_DIM)
    for dx, ln in ((104, 18), (113, 9), (124, 26), (131, 14)):
        d.rounded_rectangle([dx, top - 2, dx + 5, top + ln], radius=2, fill=GREEN_FAINT, outline=GREEN_MID)
    d.ellipse([100, top - 4, 140, top + 5], fill=GREEN_FAINT, outline=GREEN_HI)
    # Brass dish
    d.polygon([(76, 196), (164, 196), (150, 208), (90, 208)], fill=GREEN_FAINT, outline=GREEN_MID)
    d.line([(76, 196), (164, 196)], fill=GREEN_HI, width=2)

    # Wick and layered flame with sway, in the flame's own colours
    sway = 3 * math.sin(now * 2.1) + 1.5 * math.sin(now * 5.7)
    fh = 34 * flick + random.uniform(-2, 2)
    wx, wy = 120, top - 3
    d.line([(wx, wy), (wx + sway * 0.2, wy - 6)], fill=GREEN_MID, width=2)
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
        d.point((s[0], s[1]), fill=(int(20 * s[2]), int(150 * s[2]), int(60 * s[2])))
    st["smoke"] = [s for s in st["smoke"] if s[2] > 0]

    text_center(d, 22, "IN DEATH", tuple(int(c * min(1.0, flick + 0.1)) for c in GREEN_HI), 13)
    text_center(d, 212, "STILL I SERVE", GREEN_MID, 10)
    return _ph.compose(img)
