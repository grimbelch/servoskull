"""Servitor Standard – the DUTIFUL eye: steady, orderly, wide open and attentive.

Everything runs like clockwork: a fine graticule, a seconds ring where one tick
lights per second, and a cog ring turning at an even rate around a calm,
precise iris. A duty-cycle arc fills around the iris and resets, with its
percentage on the rim. No squint, no slant: the machine spirit simply serves.
"""

from __future__ import annotations

import time

from PIL import Image, ImageDraw

from ..classic._phosphor import GREEN, GREEN_DIM, GREEN_FAINT, GREEN_HI, GREEN_MID
from ._common import CX, CY, Phosphor, arc_ring, composed_bezel, font, gear_points, lids, polar, scale

NAME = "dutiful"
TITLE = "Servitor Standard"
ALIASES = ("servitor", "standard", "clockwork")
MOOD = "DUTIFUL"
APERTURE_R = 90

_ph = Phosphor(decay=0.3, bloom=0.5, flicker=0.02)


def _static() -> Image.Image:
    img = Image.new("RGB", (240, 240), (0, 0, 0))
    grid = Image.new("RGB", (240, 240), (0, 0, 0))
    g = ImageDraw.Draw(grid)
    for v in range(CX - 84, CX + 85, 12):  # graticule, clipped to the aperture
        g.line([(v, CY - 84), (v, CY + 84)], fill=(2, 22, 8))
        g.line([(CX - 84, v), (CX + 84, v)], fill=(2, 22, 8))
    clip = Image.new("L", (240, 240), 0)
    ImageDraw.Draw(clip).ellipse([CX - 86, CY - 86, CX + 86, CY + 86], fill=255)
    img.paste(grid, (0, 0), clip)
    d = ImageDraw.Draw(img)
    arc_ring(d, 116, 0, 360, GREEN_DIM)
    for i in range(60):
        d.line([polar(106, i * 6 - 90), polar(112 if i % 5 else 116, i * 6 - 90)], fill=GREEN_FAINT if i % 5 else GREEN_DIM)
    arc_ring(d, 100, 0, 360, GREEN_DIM)
    arc_ring(d, APERTURE_R, 0, 360, GREEN_MID)
    return img


_STATIC = _static()


def render_bezel() -> Image.Image:
    _ph.reset()
    return composed_bezel(_STATIC)


def render_frame(bezel, mask, amp: float, angle: float, blink: float, look_x: float, look_y: float,
                 mood_rgb: tuple) -> Image.Image:
    now = time.monotonic()
    img = _STATIC.copy()
    d = ImageDraw.Draw(img)

    sec = int(now) % 60  # seconds ring
    d.line([polar(104, sec * 6 - 90), polar(116, sec * 6 - 90)], fill=GREEN_HI, width=2)

    cx, cy = CX + look_x * 1.4, CY + look_y * 1.4
    lum = 0.35 + 0.65 * amp
    r = 34 + 14 * amp
    rot = now * 12 + angle  # even, steady turning
    d.polygon(gear_points(16, r + 12, r + 18, rot, cx, cy), outline=GREEN, fill=(0, 0, 0))
    d.ellipse([cx - r - 6, cy - r - 6, cx + r + 6, cy + r + 6], fill=scale(mood_rgb, 0.1 * lum + 0.04))
    duty = (now % 8.0) / 8.0
    arc_ring(d, r + 7, -90, -90 + 360 * duty, scale(mood_rgb, 0.85), width=3, cx=cx, cy=cy)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=scale(mood_rgb, 0.35 * lum + 0.05))
    for k, frac in ((0.65, 0.72), (1.0, 0.45)):
        rr = r * frac
        d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=scale(mood_rgb, k * lum + 0.1 * (k < 1)))
    pr = r * 0.22
    d.ellipse([cx - pr, cy - pr, cx + pr, cy + pr], fill=(0, 0, 0))
    for deg in range(0, 360, 90):
        d.line([polar(r * 0.5, deg + 45, cx, cy), polar(r * 0.9, deg + 45, cx, cy)], fill=scale(mood_rgb, 0.3))

    f = font(9)
    label = f"DUTY {int(duty * 100):3d}%"
    d.text((CX - d.textlength(label, font=f) / 2, CY - 82), label, fill=GREEN_MID, font=f)

    out = _ph.compose(img)
    return lids(out, CX, CY, 88, blink=blink, clip_r=APERTURE_R) if blink > 0 else out
