"""Omnissiah's Fire – the FERVENT eye: wide open and blazing with zeal.

A glowing cog halo turns around an iris that burns like a small sun: rays of
uneven length flicker out from it, and embers rise and drift up out of the
eye. Speech fans the flames; cogitation spins the halo. The lids are thrown
fully open.
"""

from __future__ import annotations

import math
import random
import time

from PIL import Image, ImageDraw

from ..classic._phosphor import AMBER, GREEN_DIM, GREEN_FAINT, GREEN_MID
from ._common import CX, CY, Phosphor, arc_ring, composed_bezel, gear_points, lids, polar, scale

NAME = "fervent"
TITLE = "Omnissiah's Fire"
ALIASES = ("omnissiah's fire", "omnissiah fire", "fire", "flame", "zealous", "blazing")
MOOD = "FERVENT"
APERTURE_R = 92

_RAYS = 28
_ph = Phosphor(decay=0.55, bloom=0.75, flicker=0.05)
_rng = random.Random()
_embers: list[list[float]] = []   # [x, y, vx, vy, life]
_ray_len = [1.0] * _RAYS


def _static() -> Image.Image:
    img = Image.new("RGB", (240, 240), (0, 0, 0))
    d = ImageDraw.Draw(img)
    arc_ring(d, 117, 0, 360, GREEN_DIM)
    for i in range(24):
        a = i * 15
        d.line([polar(110, a), polar(116, a)], fill=GREEN_FAINT)
    arc_ring(d, APERTURE_R + 2, 0, 360, GREEN_DIM)
    return img


_STATIC = _static()


def render_bezel() -> Image.Image:
    _ph.reset()
    _embers.clear()
    return composed_bezel(_STATIC)


def render_frame(bezel, mask, amp: float, angle: float, blink: float, look_x: float, look_y: float,
                 mood_rgb: tuple) -> Image.Image:
    now = time.monotonic()
    img = _STATIC.copy()
    d = ImageDraw.Draw(img)
    heat = 0.45 + 0.55 * amp
    hot = tuple(min(255, int(c * 0.6 + a * 0.4)) for c, a in zip(mood_rgb, AMBER))

    # Turning cog halo.
    rot = now * 10 + angle * 2
    d.polygon(gear_points(18, 98, 106, rot), outline=scale(hot, 0.55 + 0.3 * heat))

    cx, cy = CX + look_x * 1.3, CY + look_y * 1.3
    r = 30 + 12 * amp

    # Sun rays: lengths flicker towards new random targets.
    for i in range(_RAYS):
        _ray_len[i] += (_rng.uniform(0.5, 1.0 + amp) - _ray_len[i]) * 0.35
        a = i * 360 / _RAYS + now * 6
        length = r + 8 + 34 * _ray_len[i] * heat
        d.line([polar(r + 2, a, cx, cy), polar(min(length, 88), a, cx, cy)], fill=scale(hot, 0.35 + 0.5 * _ray_len[i] * heat),
               width=2 if i % 2 else 1)

    for k, frac in ((0.25, 1.45), (0.55, 1.15), (0.95, 0.9)):
        rr = r * frac
        d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=scale(hot, k * heat + 0.05))
    core = r * 0.55
    d.ellipse([cx - core, cy - core, cx + core, cy + core], fill=tuple(min(255, int(c * 0.5 + 128)) for c in hot))
    pr = r * 0.32  # a dilated, eager pupil with a cog edge
    d.polygon(gear_points(8, pr, pr + 3, -rot * 2, cx, cy), fill=(0, 0, 0))

    # Embers rising out of the fire.
    for _ in range(1 + int(3 * amp)):
        if _rng.random() < 0.6:
            a = _rng.uniform(0, 2 * math.pi)
            _embers.append([cx + r * math.cos(a), cy + r * math.sin(a), _rng.uniform(-0.6, 0.6), _rng.uniform(-2.6, -1.0), 1.0])
    for e in _embers:
        e[0] += e[2] + 0.4 * math.sin(now * 3 + e[1] * 0.1)
        e[1] += e[3]
        e[4] -= 0.03
    _embers[:] = [e for e in _embers if e[4] > 0 and (e[0] - CX) ** 2 + (e[1] - CY) ** 2 < 90 ** 2]
    for x, y, _, _, life in _embers:
        d.rectangle([x - 1, y - 1, x + 1, y + 1], fill=scale(hot, life))

    out = _ph.compose(img)
    return lids(out, CX, CY, APERTURE_R, blink=blink, edge=GREEN_MID) if blink > 0 else out
