"""Auspex Lens – the eye as a green-phosphor auspex with a mood-lit targeting reticle.

A cog-toothed bezel carries a degree ring and faint range rings. A sweep arm
circles slowly, waking contact blips as it passes; while the skull cogitates
it races. The iris is a targeting reticle in the mood colour that tracks the
gaze, opening and brightening with speech. Readouts on the rim give the
bearing of the gaze and a vox-amplitude bar.
"""

from __future__ import annotations

import math
import random
import time

from PIL import Image, ImageDraw

from ..classic._phosphor import GREEN, GREEN_DIM, GREEN_FAINT, GREEN_HI, GREEN_MID
from ._common import CX, CY, Phosphor, arc_ring, composed_bezel, font, gear_points, polar, scale, shutter

NAME = "auspex"
TITLE = "Auspex Lens"
ALIASES = ("radar", "scanner", "reticle", "targeting")
APERTURE_R = 86

_ph = Phosphor(decay=0.45, bloom=0.55, flicker=0.025)
_rng = random.Random()
_contacts: list[tuple[float, float]] = []   # (bearing deg, range px)
_next_reshuffle = 0.0
_SWEEP_DEG_PER_S = 50.0


def _static() -> Image.Image:
    img = Image.new("RGB", (240, 240), (0, 0, 0))
    d = ImageDraw.Draw(img)
    d.polygon(gear_points(30, 112, 118), outline=GREEN_MID)
    arc_ring(d, 108, 0, 360, GREEN_DIM)
    for deg in range(0, 360, 5):
        inner = 99 if deg % 30 == 0 else 104
        d.line([polar(inner, deg), polar(108, deg)], fill=GREEN_MID if deg % 30 == 0 else GREEN_DIM)
    for r in (34, 60):
        for deg in range(0, 360, 6):
            arc_ring(d, r, deg, deg + 2, GREEN_FAINT)
    arc_ring(d, APERTURE_R, 0, 360, GREEN_DIM)
    for deg in (0, 90, 180, 270):  # range-ring crosshair spokes, outside the iris
        d.line([polar(64, deg), polar(APERTURE_R - 2, deg)], fill=GREEN_FAINT)
    f = font(9)
    for deg, label in ((-90, "000"), (0, "090"), (90, "180"), (180, "270")):
        x, y = polar(93, deg)
        w = d.textlength(label, font=f)
        d.text((x - w / 2, y - 5), label, fill=GREEN_DIM, font=f)
    return img


_STATIC = _static()


def render_bezel() -> Image.Image:
    _ph.reset()
    return composed_bezel(_STATIC)


def _reshuffle(now: float) -> None:
    global _next_reshuffle
    _contacts[:] = [(_rng.uniform(0, 360), _rng.uniform(40, 84)) for _ in range(_rng.randint(2, 5))]
    _next_reshuffle = now + _rng.uniform(20.0, 45.0)


def render_frame(bezel, mask, amp: float, angle: float, blink: float, look_x: float, look_y: float,
                 mood_rgb: tuple) -> Image.Image:
    now = time.monotonic()
    if now >= _next_reshuffle:
        _reshuffle(now)

    img = _STATIC.copy()
    d = ImageDraw.Draw(img)

    # Sweep arm with a fading wedge behind it; thinking (angle) spins it hard.
    sweep = (now * _SWEEP_DEG_PER_S + angle * 3.0) % 360
    for k in range(14, 0, -1):
        d.line([(CX, CY), polar(106, sweep - k * 2.2)], fill=scale(GREEN, 0.45 * (1 - k / 15)))
    d.line([(CX, CY), polar(106, sweep)], fill=GREEN, width=2)

    for bearing, rng in _contacts:
        since = (sweep - bearing) % 360
        glow = max(0.0, 1.0 - since / 200.0)
        if glow > 0.05:
            x, y = polar(rng, bearing)
            d.ellipse([x - 2, y - 2, x + 2, y + 2], fill=scale(GREEN_HI, glow))
            if glow > 0.7:
                d.rectangle([x - 5, y - 5, x + 5, y + 5], outline=scale(GREEN, glow))

    # Targeting reticle (the iris) in the mood colour, following the gaze.
    cx, cy = CX + look_x * 1.4, CY + look_y * 1.4
    lum = 0.35 + 0.65 * amp
    r = 24 + 22 * amp

    def disc(rad, colour):
        d.ellipse([cx - rad, cy - rad, cx + rad, cy + rad], fill=colour)

    disc(r * 1.25, scale(mood_rgb, 0.10 * lum + 0.04))
    disc(r, scale(mood_rgb, 0.30 * lum))
    disc(r * 0.62, scale(mood_rgb, 0.75 * lum + 0.15))
    disc(r * 0.30, (0, 0, 0))
    hx, hy = cx - r * 0.12, cy - r * 0.12
    d.ellipse([hx - 2, hy - 2, hx + 2, hy + 2], fill=scale((255, 255, 255), 0.5 + 0.5 * lum))

    ring = r + 12
    spin = angle * 1.5 + now * 8
    for q in range(4):  # broken outer ring: four arcs with gaps on the diagonals
        a0 = spin + q * 90 + 12
        arc_ring(d, ring, a0, a0 + 66, scale(mood_rgb, 0.85), width=2, cx=cx, cy=cy)
    for deg in (0, 90, 180, 270):
        d.line([polar(ring + 4, deg, cx, cy), polar(ring + 16, deg, cx, cy)], fill=scale(mood_rgb, 0.9), width=2)
        d.line([polar(r * 0.36, deg, cx, cy), polar(r * 0.55, deg, cx, cy)], fill=scale(mood_rgb, 0.25))
    for deg in (45, 135, 225, 315):  # corner brackets
        p0 = polar(ring + 7, deg - 8, cx, cy)
        p1 = polar(ring + 10, deg, cx, cy)
        p2 = polar(ring + 7, deg + 8, cx, cy)
        d.line([p0, p1, p2], fill=scale(mood_rgb, 0.6))

    # Rim readouts: gaze bearing on top, vox amplitude bar below.
    f = font(9)
    bearing = (math.degrees(math.atan2(look_x, -look_y)) % 360) if abs(look_x) + abs(look_y) > 1 else 0
    label = f"BRG {bearing:03.0f}"
    d.text((CX - d.textlength(label, font=f) / 2, CY - 79), label, fill=GREEN_MID, font=f)
    bars = round(amp * 8)
    for i in range(8):
        x = CX - 28 + i * 7
        d.rectangle([x, CY + 74, x + 4, CY + 79], fill=GREEN if i < bars else GREEN_FAINT)

    out = _ph.compose(img)
    return shutter(out, blink, CX, cy, APERTURE_R)
