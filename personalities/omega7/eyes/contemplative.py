"""Engram Orrery – the CONTEMPLATIVE eye: deep, slow and turned inward.

The iris is a still pool that sends slow ripples outward, ringed by memory
engrams on three tilted orbits, like a small orrery of remembered things.
Faint stars twinkle in the dark around it. The gaze drifts upward, as if
recalling, and the upper lid rests slightly lowered. Cogitation speeds the orbits.
"""

from __future__ import annotations

import math
import random
import time

from PIL import Image, ImageDraw

from ..classic._phosphor import GREEN, GREEN_DIM, GREEN_FAINT, GREEN_HI, GREEN_MID
from ._common import CX, CY, Phosphor, arc_ring, composed_bezel, lids, scale

NAME = "contemplative"
TITLE = "Engram Orrery"
ALIASES = ("engram", "orrery", "thoughtful", "pensive")
MOOD = "CONTEMPLATIVE"
APERTURE_R = 90

_ph = Phosphor(decay=0.6, bloom=0.6, flicker=0.015)
_rng = random.Random(40)
_STARS = [(CX + _rng.uniform(-84, 84), CY + _rng.uniform(-84, 84), _rng.uniform(0, 6.3), _rng.uniform(0.4, 1.4))
          for _ in range(40)]
_STARS = [s for s in _STARS if (s[0] - CX) ** 2 + (s[1] - CY) ** 2 < 84 ** 2]
# (semi-major, semi-minor, tilt deg, period s, motes)
_ORBITS = [(62, 22, -20, 14.0, 3), (74, 30, 35, 21.0, 2), (52, 40, 80, 11.0, 2)]


def _static() -> Image.Image:
    img = Image.new("RGB", (240, 240), (0, 0, 0))
    d = ImageDraw.Draw(img)
    arc_ring(d, 116, 0, 360, GREEN_DIM)
    for i in range(0, 360, 3):
        d.point(polar_pt(110, i), fill=GREEN_FAINT)
    arc_ring(d, APERTURE_R + 2, 0, 360, GREEN_FAINT)
    return img


def polar_pt(r, deg, cx=CX, cy=CY):
    a = math.radians(deg)
    return cx + r * math.cos(a), cy + r * math.sin(a)


_STATIC = _static()


def render_bezel() -> Image.Image:
    _ph.reset()
    return composed_bezel(_STATIC)


def _ellipse_pt(cx, cy, a, b, tilt, t):
    x, y = a * math.cos(t), b * math.sin(t)
    ct, st = math.cos(math.radians(tilt)), math.sin(math.radians(tilt))
    return cx + x * ct - y * st, cy + x * st + y * ct


def render_frame(bezel, mask, amp: float, angle: float, blink: float, look_x: float, look_y: float,
                 mood_rgb: tuple) -> Image.Image:
    now = time.monotonic()
    img = _STATIC.copy()
    d = ImageDraw.Draw(img)

    for x, y, ph, sp in _STARS:
        k = 0.5 + 0.5 * math.sin(now * sp + ph)
        d.point((x, y), fill=scale(GREEN, 0.15 + 0.6 * k))

    # Gaze drifts upward, as if recalling.
    cx, cy = CX + look_x * 1.0, CY + look_y * 0.8 - 10
    lum = 0.35 + 0.65 * amp
    r = 30 + 12 * amp

    speed = 1.0 + (2.5 if angle else 0.0)
    for a, b, tilt, period, motes in _ORBITS:
        pts = [_ellipse_pt(cx, cy, a, b, tilt, t * 2 * math.pi / 48) for t in range(49)]
        d.line(pts, fill=GREEN_FAINT)
        for m in range(motes):
            t = now * speed * 2 * math.pi / period + m * 2 * math.pi / motes + angle * 0.02
            x, y = _ellipse_pt(cx, cy, a, b, tilt, t)
            behind = math.sin(t) < 0 and tilt < 60  # motes pass behind the pool
            if behind and (x - cx) ** 2 + (y - cy) ** 2 < (r + 4) ** 2:
                continue
            d.ellipse([x - 2, y - 2, x + 2, y + 2], fill=GREEN_HI if not behind else GREEN_MID)

    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=scale(mood_rgb, 0.3 * lum + 0.06))
    for i in range(3):  # slow ripples spreading out from the pupil
        ph = ((now / 3.2) + i / 3) % 1.0
        rr = r * (0.3 + 0.7 * ph)
        arc_ring(d, rr, 0, 360, scale(mood_rgb, (0.9 * lum + 0.2) * (1 - ph)), cx=cx, cy=cy)
    pr = r * 0.3
    d.ellipse([cx - pr, cy - pr, cx + pr, cy + pr], fill=(0, 0, 0), outline=scale(mood_rgb, 0.7))
    hx, hy = cx - pr * 0.4, cy - pr * 0.5
    d.ellipse([hx - 1.5, hy - 1.5, hx + 1.5, hy + 1.5], fill=scale((255, 255, 255), 0.5 + 0.4 * lum))

    out = _ph.compose(img)
    return lids(out, CX, CY - 4, 88, top=0.82, bottom=1.0, blink=blink, edge=GREEN_DIM, clip_r=APERTURE_R)
