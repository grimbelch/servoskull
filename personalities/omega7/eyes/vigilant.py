"""Sentinel Augur – the VIGILANT eye: alert, slightly narrowed, always scanning.

A hazard-chevron band rings the eye. The iris is twelve armoured segments that
light in a running sequence around a tight, contracted pupil, while a scan line
sweeps up and down the eye. A tracking bracket jumps to wherever the gaze is
heading before the iris gets there, and a threat readout ticks over on the rim.
The lids sit a little lowered, like someone watching hard.
"""

from __future__ import annotations

import math
import random
import time

from PIL import Image, ImageDraw

from ..classic._phosphor import AMBER, GREEN, GREEN_DIM, GREEN_FAINT, GREEN_MID
from ._common import CX, CY, Phosphor, arc_ring, composed_bezel, font, lids, polar, scale

NAME = "vigilant"
TITLE = "Sentinel Augur"
ALIASES = ("sentinel", "sentry", "watchful")
MOOD = "VIGILANT"
APERTURE_R = 88

_ph = Phosphor(decay=0.4, bloom=0.55, flicker=0.03)
_rng = random.Random()
_threat = ["LOW", "LOW", "LOW", "MODERATE", "LOW", "UNKNOWN"]
_state = {"threat": "LOW", "next": 0.0}


def _static() -> Image.Image:
    img = Image.new("RGB", (240, 240), (0, 0, 0))
    d = ImageDraw.Draw(img)
    for i in range(36):  # hazard chevrons
        a = i * 10
        d.polygon([polar(106, a), polar(116, a + 4), polar(116, a + 7), polar(106, a + 3)],
                  fill=GREEN_DIM if i % 2 else GREEN_FAINT)
    arc_ring(d, 104, 0, 360, GREEN_MID)
    arc_ring(d, 118, 0, 360, GREEN_DIM)
    arc_ring(d, APERTURE_R + 2, 0, 360, GREEN_DIM)
    return img


_STATIC = _static()


def render_bezel() -> Image.Image:
    _ph.reset()
    return composed_bezel(_STATIC)


def render_frame(bezel, mask, amp: float, angle: float, blink: float, look_x: float, look_y: float,
                 mood_rgb: tuple) -> Image.Image:
    now = time.monotonic()
    if now >= _state["next"]:
        _state["threat"] = _rng.choice(_threat)
        _state["next"] = now + _rng.uniform(4.0, 9.0)

    img = _STATIC.copy()
    d = ImageDraw.Draw(img)
    lum = 0.4 + 0.6 * amp
    cx, cy = CX + look_x * 1.5, CY + look_y * 1.5

    # Scan line sweeping the eye vertically.
    sy = CY + 70 * math.sin(now * 1.6 + angle * 0.05)
    half = math.sqrt(max(0.0, 86 ** 2 - (sy - CY) ** 2))
    d.line([(CX - half, sy), (CX + half, sy)], fill=GREEN_MID)

    # Segmented iris: one bright segment chasing round (faster while thinking).
    r_out, r_in = 40 + 10 * amp, 20 + 4 * amp
    lead = (now * 8 + angle / 15) % 12
    d.ellipse([cx - r_out - 10, cy - r_out - 10, cx + r_out + 10, cy + r_out + 10], fill=scale(mood_rgb, 0.08 * lum + 0.03))
    for i in range(12):
        a0 = i * 30 - 90
        trail = (lead - i) % 12
        k = 1.0 if trail < 1 else max(0.25, 0.85 - trail * 0.12)
        d.polygon([polar(r_in, a0 + 2, cx, cy), polar(r_out, a0 + 3, cx, cy),
                   polar(r_out, a0 + 27, cx, cy), polar(r_in, a0 + 28, cx, cy)],
                  fill=scale(mood_rgb, k * (0.55 + 0.45 * lum)))
    pr = 7 + 3 * amp  # contracted pupil
    d.ellipse([cx - pr, cy - pr, cx + pr, cy + pr], fill=(0, 0, 0), outline=scale(mood_rgb, 0.9))

    # Tracking bracket leads the gaze.
    bx, by = CX + look_x * 2.6, CY + look_y * 2.6
    s = r_out + 16
    for sx, sy2 in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
        x, y = bx + sx * s, by + sy2 * s
        d.line([(x, y), (x - sx * 9, y)], fill=GREEN, width=2)
        d.line([(x, y), (x, y - sy2 * 9)], fill=GREEN, width=2)

    f = font(9)
    label = f"THREAT: {_state['threat']}"
    colour = AMBER if _state["threat"] != "LOW" else GREEN_MID
    d.text((CX - d.textlength(label, font=f) / 2, CY + 91), label, fill=colour, font=f)  # below the lids

    out = _ph.compose(img)
    return lids(out, CX + look_x * 0.3, CY + look_y * 0.3, 86, top=0.74, bottom=0.82, blink=blink,
                clip_r=APERTURE_R)
