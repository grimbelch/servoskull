"""Augmetic Cluster – a Skitarii-style optic: one great lens and a turret of lesser ones.

The primary lens holds the mood colour, with a focusing ring that tightens as
the skull speaks. Three secondary optics ride a turret ring of segmented armour
plates; each focuses and blinks on its own clock, and the turret slews round
while the skull cogitates. Gaze moves the primary lens fully and the turret a
little, for parallax.
"""

from __future__ import annotations

import math
import random
import time

from PIL import Image, ImageDraw

from ..classic._phosphor import AMBER, GREEN, GREEN_DIM, GREEN_FAINT, GREEN_HI, GREEN_MID
from ._common import CX, CY, Phosphor, arc_ring, composed_bezel, font, polar, scale, shutter

NAME = "augmetic"
TITLE = "Augmetic Cluster"
ALIASES = ("skitarii", "cluster", "multi lens", "multi optic")
APERTURE_R = 64

_TURRET_R = 90
_ph = Phosphor(decay=0.35, bloom=0.55, flicker=0.025)
_rng = random.Random()
# per secondary optic: [phase, focus period, next blink time, blink start or None]
_minis = [[_rng.uniform(0, 6.3), _rng.uniform(2.5, 5.0), 0.0, None] for _ in range(3)]
_MINI_BLINK = 0.18


def _static() -> Image.Image:
    img = Image.new("RGB", (240, 240), (0, 0, 0))
    d = ImageDraw.Draw(img)
    for i in range(12):  # segmented armour plates on the rim
        a0 = i * 30 + 2
        arc_ring(d, 114, a0, a0 + 26, GREEN_MID, width=3)
        x, y = polar(108, a0 + 13)
        d.ellipse([x - 1.5, y - 1.5, x + 1.5, y + 1.5], fill=GREEN_DIM)
    arc_ring(d, 103, 0, 360, GREEN_FAINT)
    arc_ring(d, APERTURE_R + 6, 0, 360, GREEN_DIM)
    arc_ring(d, APERTURE_R + 2, 0, 360, GREEN_MID, width=2)
    for deg in range(0, 360, 10):
        d.line([polar(APERTURE_R + 7, deg), polar(APERTURE_R + 11 if deg % 30 else APERTURE_R + 15, deg)],
               fill=GREEN_DIM)
    return img


_STATIC = _static()
_LENS_MASK = Image.new("L", (240, 240), 0)
ImageDraw.Draw(_LENS_MASK).ellipse([CX - APERTURE_R, CY - APERTURE_R, CX + APERTURE_R, CY + APERTURE_R], fill=255)


def render_bezel() -> Image.Image:
    _ph.reset()
    return composed_bezel(_STATIC)


def _mini(d, x: float, y: float, i: int, now: float, amp: float) -> None:
    m = _minis[i]
    if m[3] is None and now >= m[2]:
        m[3] = now
    shut = 0.0
    if m[3] is not None:
        p = (now - m[3]) / _MINI_BLINK
        if p >= 1:
            m[3], m[2] = None, now + _rng.uniform(3.0, 9.0)
        else:
            shut = math.sin(math.pi * p)
    r = 15
    d.ellipse([x - r - 3, y - r - 3, x + r + 3, y + r + 3], fill=(0, 0, 0), outline=GREEN_MID, width=2)
    focus = 0.5 + 0.5 * math.sin(now * 2 * math.pi / m[1] + m[0])
    ir = (5 + 4 * focus + 2 * amp) * (1 - shut)
    if ir > 0.6:
        d.ellipse([x - ir, y - ir, x + ir, y + ir], fill=scale(GREEN, 0.55 + 0.45 * focus), outline=GREEN_HI)
        d.ellipse([x - ir * 0.35, y - ir * 0.35, x + ir * 0.35, y + ir * 0.35], fill=(0, 0, 0))
    else:
        d.line([(x - r + 2, y), (x + r - 2, y)], fill=GREEN_HI)
    if i == 0 and focus > 0.8:  # rangefinder lock on one optic
        f = font(8)
        d.text((x - d.textlength("RNG", font=f) / 2, y - r - 14), "RNG", fill=AMBER, font=f)


def render_frame(bezel, mask, amp: float, angle: float, blink: float, look_x: float, look_y: float,
                 mood_rgb: tuple) -> Image.Image:
    now = time.monotonic()
    img = _STATIC.copy()
    d = ImageDraw.Draw(img)

    # Turret of secondary optics, slewing slowly (fast while cogitating).
    turret = 200 + 10 * math.sin(now * 0.25) + angle
    tx, ty = CX + look_x * 0.4, CY + look_y * 0.4
    for i, off in enumerate((0, 120, 240)):
        deg = turret + off
        x, y = polar(_TURRET_R, deg, tx, ty)
        d.line([polar(APERTURE_R + 16, deg, tx, ty), polar(_TURRET_R - 19, deg, tx, ty)], fill=GREEN_DIM, width=3)
        _mini(d, x, y, i, now, amp)

    # Primary lens, drawn on its own layer and clipped to the aperture.
    lens = Image.new("RGB", (240, 240), (0, 0, 0))
    d = ImageDraw.Draw(lens)
    cx, cy = CX + look_x * 1.2, CY + look_y * 1.2
    lum = 0.35 + 0.65 * amp
    r = 40 + 14 * amp
    for k, frac in ((0.10, 1.5), (0.22, 1.2), (0.45, 1.0)):
        rr = r * frac
        d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=scale(mood_rgb, k * lum + 0.03))
    core = r * 0.55
    d.ellipse([cx - core, cy - core, cx + core, cy + core], fill=scale(mood_rgb, 0.75 * lum + 0.2))
    pup = r * 0.24
    d.ellipse([cx - pup, cy - pup, cx + pup, cy + pup], fill=(0, 0, 0))
    focus_r = r * (0.95 - 0.2 * amp)  # focusing ring tightens with speech
    for q in range(3):
        a0 = now * -20 + angle * 2 + q * 120
        arc_ring(d, focus_r, a0, a0 + 80, scale(mood_rgb, 0.9), width=2, cx=cx, cy=cy)
    for deg in range(0, 360, 45):
        d.line([polar(r * 0.62, deg, cx, cy), polar(r * 0.72, deg, cx, cy)], fill=scale(mood_rgb, 0.35))
    hx, hy = cx - r * 0.3, cy - r * 0.32
    d.ellipse([hx - 3, hy - 2, hx + 3, hy + 2], fill=scale((255, 255, 255), 0.35 + 0.45 * lum))

    img.paste(lens, (0, 0), _LENS_MASK)

    out = _ph.compose(img)
    return shutter(out, blink, CX, cy, APERTURE_R)
