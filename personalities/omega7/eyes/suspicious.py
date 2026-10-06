"""Narrowed Augur – the SUSPICIOUS eye: squinting, sidelong, its feed not quite clean.

The lids narrow to a lopsided slit, lower on one side, like a sceptical squint.
Behind them a small iris with a vertical slit pupil throws long sidelong
glances. Warp static speckles the dark, rows of the image tear sideways now
and then, and an anomaly reading creeps up and down on the rim.
"""

from __future__ import annotations

import random
import time

import numpy as np
from PIL import Image, ImageDraw

from ..classic._phosphor import AMBER, GREEN_DIM, GREEN_FAINT, GREEN_MID
from ._common import CX, CY, Phosphor, arc_ring, composed_bezel, font, lids, scale

NAME = "suspicious"
TITLE = "Narrowed Augur"
ALIASES = ("narrowed", "squint", "squinting", "sceptic", "skeptic")
MOOD = "SUSPICIOUS"
APERTURE_R = 88

_ph = Phosphor(decay=0.35, bloom=0.5, flicker=0.06)
_rng = random.Random()
_np_rng = np.random.default_rng()
_state = {"anomaly": 0.31, "tear_until": 0.0, "tear_rows": (0, 0), "tear_dx": 0}


def _static() -> Image.Image:
    img = Image.new("RGB", (240, 240), (0, 0, 0))
    d = ImageDraw.Draw(img)
    arc_ring(d, 114, 0, 360, GREEN_DIM)
    for i in range(0, 360, 20):  # broken, uneven rim segments
        arc_ring(d, 108, i + 2, i + 14 - (i % 60) // 10, GREEN_FAINT, width=3)
    arc_ring(d, APERTURE_R + 2, 0, 360, GREEN_DIM)
    return img


_STATIC = _static()


def render_bezel() -> Image.Image:
    _ph.reset()
    return composed_bezel(_STATIC)


def render_frame(bezel, mask, amp: float, angle: float, blink: float, look_x: float, look_y: float,
                 mood_rgb: tuple) -> Image.Image:
    now = time.monotonic()
    st = _state
    img = _STATIC.copy()
    d = ImageDraw.Draw(img)

    # Warp static in the dark of the eye.
    n = 60
    xs = _np_rng.integers(CX - 80, CX + 80, n)
    ys = _np_rng.integers(CY - 40, CY + 40, n)
    for x, y in zip(xs.tolist(), ys.tolist()):
        d.point((x, y), fill=GREEN_FAINT)

    # Sidelong glances: the gaze swings wider sideways and hardly up or down.
    cx, cy = CX + look_x * 2.4, CY + look_y * 0.5
    lum = 0.4 + 0.6 * amp
    r = 26 + 8 * amp
    d.ellipse([cx - r - 8, cy - r - 8, cx + r + 8, cy + r + 8], fill=scale(mood_rgb, 0.08 + 0.05 * lum))
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=scale(mood_rgb, 0.45 * lum + 0.1))
    d.ellipse([cx - r * 0.7, cy - r * 0.7, cx + r * 0.7, cy + r * 0.7], fill=scale(mood_rgb, 0.8 * lum + 0.15))
    sw = 3 + 3 * amp  # vertical slit pupil
    d.ellipse([cx - sw, cy - r * 0.85, cx + sw, cy + r * 0.85], fill=(0, 0, 0))

    # Anomaly reading drifts.
    st["anomaly"] = min(0.99, max(0.05, st["anomaly"] + _rng.uniform(-0.01, 0.012)))
    f = font(9)
    label = f"ANOMALY {st['anomaly']:.2f}"
    d.text((CX - d.textlength(label, font=f) / 2, CY + 46), label, fill=AMBER if st["anomaly"] > 0.6 else GREEN_MID, font=f)

    out = _ph.compose(img)

    # Image tearing: a band of rows shoved sideways for a moment.
    if now > st["tear_until"] and _rng.random() < 0.015 + 0.03 * amp:
        y0 = _rng.randint(CY - 30, CY + 20)
        st["tear_rows"], st["tear_dx"], st["tear_until"] = (y0, y0 + _rng.randint(2, 6)), _rng.choice((-6, -4, 4, 6)), now + 0.15
    if now < st["tear_until"]:
        a = np.asarray(out).copy()
        y0, y1 = st["tear_rows"]
        a[y0:y1] = np.roll(a[y0:y1], st["tear_dx"], axis=1)
        out = Image.fromarray(a)

    return lids(out, CX, CY, 86, top=0.36, bottom=0.42, slant=0.16, blink=blink, clip_r=APERTURE_R)
