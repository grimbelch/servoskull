"""Noosphere Cog – a mood-lit Mechanicus cog for an iris, haloed by binharic cant.

Two counter-rotating rings of glyphs (binary outside, hex inside) circle the
eye and flicker as the data changes. The iris is a toothed cog with a glowing
core and a dark pupil; it follows the gaze, and it turns while the skull
cogitates, like the original cog eye. When the skull speaks, data packets
stream inward along the spokes and the cog swells.
"""

from __future__ import annotations

import random
import time

from PIL import Image, ImageDraw

from ..classic._phosphor import GREEN, GREEN_DIM, GREEN_FAINT, GREEN_HI, GREEN_MID
from ._common import CX, CY, Phosphor, arc_ring, composed_bezel, font, gear_points, polar, scale, shutter

NAME = "noosphere"
TITLE = "Noosphere Cog"
ALIASES = ("binharic", "cog iris", "data cog")
APERTURE_R = 80

_OUTER_N, _OUTER_R = 40, 104
_INNER_N, _INNER_R = 24, 88
_SPOKES = 8

_ph = Phosphor(decay=0.4, bloom=0.55, flicker=0.03)
_rng = random.Random()
_outer = [_rng.choice("01") for _ in range(_OUTER_N)]
_inner = [f"{_rng.randrange(256):02X}" for _ in range(_INNER_N)]
_hot: dict[tuple[str, int], float] = {}   # recently changed glyph -> time it changed
_last_mut = 0.0
_packets: list[list[float]] = []          # [spoke deg, radius]


def _static() -> Image.Image:
    img = Image.new("RGB", (240, 240), (0, 0, 0))
    d = ImageDraw.Draw(img)
    arc_ring(d, 116, 0, 360, GREEN_DIM)
    arc_ring(d, 96, 0, 360, GREEN_FAINT)
    arc_ring(d, APERTURE_R, 0, 360, GREEN_DIM)
    for i in range(_SPOKES):
        deg = i * 360 / _SPOKES + 22.5
        for r in range(30, APERTURE_R - 2, 6):
            x, y = polar(r, deg)
            d.point((x, y), fill=GREEN_FAINT)
    return img


_STATIC = _static()


def render_bezel() -> Image.Image:
    _ph.reset()
    return composed_bezel(_STATIC)


def _mutate(now: float, rate: float) -> None:
    global _last_mut
    if now - _last_mut < 0.08:
        return
    _last_mut = now
    for _ in range(max(1, int(rate))):
        i = _rng.randrange(_OUTER_N)
        _outer[i] = "1" if _outer[i] == "0" else "0"
        _hot[("o", i)] = now
    if _rng.random() < 0.5 * rate:
        j = _rng.randrange(_INNER_N)
        _inner[j] = f"{_rng.randrange(256):02X}"
        _hot[("i", j)] = now


_sprites: dict[str, Image.Image] = {}


def _sprite(text: str) -> Image.Image:
    """Glyph rendered once as a 1-bit mask (Pillow text drawing is slow on the Pi)."""
    m = _sprites.get(text)
    if m is None:
        f = font(9)
        w = int(ImageDraw.Draw(Image.new("1", (1, 1))).textlength(text, font=f)) + 1
        m = Image.new("1", (w, 12), 0)
        ImageDraw.Draw(m).text((0, 0), text, fill=1, font=f)
        _sprites[text] = m
    return m


def _glyph_ring(d, glyphs, radius, rot, kind, now, base) -> None:
    n = len(glyphs)
    for i, g in enumerate(glyphs):
        x, y = polar(radius, rot + i * 360 / n)
        age = now - _hot.get((kind, i), -9.0)
        colour = GREEN_HI if age < 0.25 else (GREEN if age < 0.8 else base)
        m = _sprite(g)
        d.bitmap((round(x - m.width / 2), round(y - 5)), m, fill=colour)


def render_frame(bezel, mask, amp: float, angle: float, blink: float, look_x: float, look_y: float,
                 mood_rgb: tuple) -> Image.Image:
    now = time.monotonic()
    _mutate(now, 1 + 6 * amp)

    img = _STATIC.copy()
    d = ImageDraw.Draw(img)
    _glyph_ring(d, _outer, _OUTER_R, now * 6 + angle, "o", now, GREEN_MID)
    _glyph_ring(d, _inner, _INNER_R, -now * 9 - angle * 1.5, "i", now, GREEN_DIM)

    # Speech sends data packets down the spokes into the cog.
    if amp > 0.25 and _rng.random() < amp * 1.2:
        _packets.append([_rng.randrange(_SPOKES) * 360 / _SPOKES + 22.5, APERTURE_R - 2])
    for p in _packets:
        p[1] -= 7
    _packets[:] = [p for p in _packets if p[1] > 30]
    for deg, r in _packets:
        x, y = polar(r, deg)
        d.rectangle([x - 1.5, y - 1.5, x + 1.5, y + 1.5], fill=GREEN_HI)

    cx, cy = CX + look_x * 1.3, CY + look_y * 1.3
    lum = 0.35 + 0.65 * amp
    r_root = 34 + 14 * amp
    rot = angle + now * 3
    d.ellipse([cx - r_root - 18, cy - r_root - 18, cx + r_root + 18, cy + r_root + 18],
              fill=scale(mood_rgb, 0.07 + 0.08 * lum))
    d.polygon(gear_points(10, r_root, r_root + 10, rot, cx, cy),
              fill=scale(mood_rgb, 0.35 * lum + 0.1), outline=scale(mood_rgb, 0.9))
    d.ellipse([cx - r_root + 5, cy - r_root + 5, cx + r_root - 5, cy + r_root - 5], fill=scale(mood_rgb, 0.12))
    core = r_root * 0.62
    d.ellipse([cx - core, cy - core, cx + core, cy + core], fill=scale(mood_rgb, 0.7 * lum + 0.2))
    pup = r_root * 0.28
    d.ellipse([cx - pup, cy - pup, cx + pup, cy + pup], fill=(0, 0, 0))
    for i in range(6):  # bolt ring between rim and core
        bx, by = polar(r_root - 1.5 - (r_root - core) / 2 + 1, rot + i * 60 + 30, cx, cy)
        d.ellipse([bx - 1.5, by - 1.5, bx + 1.5, by + 1.5], fill=scale(mood_rgb, 0.8))
    hx, hy = cx - pup * 0.9, cy - pup * 0.9
    d.ellipse([hx - 2, hy - 2, hx + 2, hy + 2], fill=scale((255, 255, 255), 0.4 + 0.5 * lum))

    out = _ph.compose(img)
    return shutter(out, blink, CX, cy, APERTURE_R)
