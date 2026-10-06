"""Lamenting Lens – the MELANCHOLIC eye: heavy-lidded, downcast and dim.

The upper lid hangs low and droops at its ends, the gaze sinks downward, and
the iris burns dimmer than in any other mood behind a cracked lens. Slow
phosphor tears gather at the lower lid and fall, leaving long trails, while a
sparse grey rain of old data drifts down behind.
"""

from __future__ import annotations

import random
import time

from PIL import Image, ImageDraw

from ..classic._phosphor import GREEN_DIM, GREEN_FAINT, GREEN_MID
from ._common import CX, CY, Phosphor, arc_ring, composed_bezel, lids, scale

NAME = "melancholic"
TITLE = "Lamenting Lens"
ALIASES = ("lamenting", "lament", "mournful", "sorrowful", "sad")
MOOD = "MELANCHOLIC"
APERTURE_R = 90

_ph = Phosphor(decay=0.82, bloom=0.45, flicker=0.02)
_rng = random.Random()
_tears: list[list[float]] = []    # [x, y, speed]
_rain: list[list[float]] = []     # [x, y, speed]
_next_tear = [0.0]
# A fixed crack across the lens (relative to the iris centre).
_CRACK = [(-30, -26), (-14, -12), (-17, -2), (-2, 8), (6, 6), (24, 22)]
_CRACK_BRANCH = [(-14, -12), (-4, -20), (2, -30)]


def _static() -> Image.Image:
    img = Image.new("RGB", (240, 240), (0, 0, 0))
    d = ImageDraw.Draw(img)
    arc_ring(d, 116, 0, 360, GREEN_FAINT)
    arc_ring(d, 108, 200, 340, GREEN_DIM)   # the rim is worn away below
    arc_ring(d, 108, 20, 160, GREEN_FAINT)
    arc_ring(d, APERTURE_R + 2, 0, 360, GREEN_FAINT)
    return img


_STATIC = _static()


def render_bezel() -> Image.Image:
    _ph.reset()
    _tears.clear()
    return composed_bezel(_STATIC)


def render_frame(bezel, mask, amp: float, angle: float, blink: float, look_x: float, look_y: float,
                 mood_rgb: tuple) -> Image.Image:
    now = time.monotonic()
    img = _STATIC.copy()
    d = ImageDraw.Draw(img)
    grey = tuple(int(c * 0.5 + sum(mood_rgb) / 6) for c in mood_rgb)   # desaturated mood colour

    # Sparse grey data rain.
    if _rng.random() < 0.25:
        _rain.append([_rng.uniform(CX - 80, CX + 80), CY - 85, _rng.uniform(0.6, 1.4)])
    for p in _rain:
        p[1] += p[2]
    _rain[:] = [p for p in _rain if p[1] < CY + 85]
    for x, y, _ in _rain:
        d.line([(x, y), (x, y + 4)], fill=GREEN_FAINT)

    cx, cy = CX + look_x * 0.9, CY + look_y * 0.6 + 12   # downcast
    lum = 0.4 + 0.5 * amp   # dimmer than any other mood
    r = 30 + 10 * amp
    d.ellipse([cx - r - 6, cy - r - 6, cx + r + 6, cy + r + 6], fill=scale(grey, 0.06 + 0.04 * lum))
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=scale(grey, 0.4 * lum + 0.06))
    d.ellipse([cx - r * 0.62, cy - r * 0.62, cx + r * 0.62, cy + r * 0.62], fill=scale(grey, 0.8 * lum + 0.08))
    pr = r * 0.34
    d.ellipse([cx - pr, cy - pr, cx + pr, cy + pr], fill=(0, 0, 0))
    d.line([(cx + x, cy + y) for x, y in _CRACK], fill=GREEN_DIM, width=1)
    d.line([(cx + x, cy + y) for x, y in _CRACK_BRANCH], fill=GREEN_DIM, width=1)

    # Tears gather under the eye and fall slowly; the phosphor keeps their trails.
    if now >= _next_tear[0]:
        _tears.append([cx + _rng.uniform(-r * 0.8, r * 0.8), cy + r * 0.9, 0.3])
        _next_tear[0] = now + _rng.uniform(1.5, 4.0)
    for t in _tears:
        t[2] = min(2.2, t[2] * 1.06 + 0.02)
        t[1] += t[2]
    _tears[:] = [t for t in _tears if (t[0] - CX) ** 2 + (t[1] - CY) ** 2 < 86 ** 2]
    for x, y, _ in _tears:
        d.ellipse([x - 2, y - 3, x + 2, y + 2], fill=scale(grey, 0.9))

    out = _ph.compose(img)
    return lids(out, CX, CY + 6, 88, top=0.55, bottom=0.95, droop=0.22, blink=blink, edge=GREEN_MID,
                clip_r=APERTURE_R)
