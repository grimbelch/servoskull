"""Iris Diaphragm – a machined lens behind a nine-bladed iris, drawn on the phosphor.

The housing is a knurled ring with four small Mechanicus cogs set into it. In
the middle, nine overlapping blades leave a polygonal aperture over a mood-lit
lens. Speech opens the blades wide, a blink snaps them shut, and cogitation
twists them round. The lens drifts behind the aperture with the gaze, so the
pupil looks around while the blades stay put.
"""

from __future__ import annotations

import math

import numpy as np
from PIL import Image, ImageDraw

from ..classic._phosphor import GREEN, GREEN_DIM, GREEN_FAINT, GREEN_HI, GREEN_MID
from ._common import CX, CY, H, W, Phosphor, arc_ring, composed_bezel, gear_points, polar, scale

NAME = "aperture"
TITLE = "Iris Diaphragm"
ALIASES = ("iris", "diaphragm", "shutter")
APERTURE_R = 88

_BLADES = 9
_HOUSING_R = 92
_ph = Phosphor(decay=0.3, bloom=0.6, flicker=0.02)


def _static() -> Image.Image:
    img = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(img)
    arc_ring(d, 117, 0, 360, GREEN_MID, width=2)
    arc_ring(d, 101, 0, 360, GREEN_DIM)
    for deg in range(0, 360, 4):  # knurling
        d.line([polar(104, deg), polar(114, deg + 2)], fill=GREEN_FAINT)
    for deg in (45, 135, 225, 315):
        cx, cy = polar(108, deg)
        d.ellipse([cx - 9, cy - 9, cx + 9, cy + 9], fill=(0, 0, 0))
        d.polygon(gear_points(8, 5.5, 8, 0, cx, cy), outline=GREEN_MID)
        d.ellipse([cx - 2, cy - 2, cx + 2, cy + 2], outline=GREEN_DIM)
    for deg in (0, 90, 180, 270):  # index marks
        d.polygon([polar(100, deg - 2), polar(100, deg + 2), polar(95, deg)], fill=GREEN)
    arc_ring(d, _HOUSING_R, 0, 360, GREEN_MID, width=2)
    return img


_STATIC = _static()


def render_bezel() -> Image.Image:
    _ph.reset()
    return composed_bezel(_STATIC)


_LENS_R = 78
_PATCH = 2 * _LENS_R
_pr = np.sqrt(((np.mgrid[0:_PATCH, 0:_PATCH] - _LENS_R + 0.5) ** 2).sum(0)).astype(np.float32)
_GLOW = (np.clip(1.0 - _pr / _LENS_R, 0, 1) ** 1.3 * (0.82 + 0.18 * np.cos(_pr * 0.55))).astype(np.float32)


def _lens(cx: float, cy: float, mood_rgb, lum: float, pupil_r: float) -> Image.Image:
    """Mood-lit lens: soft radial glow with concentric refraction bands and a dark pupil.
    Computed on a patch around the lens only; the glow profile is precomputed."""
    k = _GLOW * (0.25 + 0.75 * lum)
    k = np.where(_pr < pupil_r, 0.0, k)
    k += np.clip(1.0 - np.abs(_pr - pupil_r - 1.5) / 2.0, 0, 1) * (0.9 * lum)  # hot pupil rim
    patch = np.clip(k[..., None] * np.array(mood_rgb, np.float32), 0, 255).astype(np.uint8)
    img = Image.new("RGB", (W, H), (0, 0, 0))
    img.paste(Image.fromarray(patch), (round(cx) - _LENS_R, round(cy) - _LENS_R))
    return img


def _blades(d: ImageDraw.ImageDraw, ax: float, ay: float, ap: float, twist: float) -> None:
    """Blades between the aperture polygon (radius ap) and the housing.

    Each blade edge runs from an aperture vertex out along the next polygon side,
    which gives the pinwheel look of a real diaphragm.
    """
    verts = [polar(ap, twist + i * 360 / _BLADES, ax, ay) for i in range(_BLADES)]
    # Fill everything outside the aperture, inside the housing, as blade metal.
    d.ellipse([CX - _HOUSING_R, CY - _HOUSING_R, CX + _HOUSING_R, CY + _HOUSING_R], fill=(2, 16, 6))
    if ap > 0.5:
        d.polygon(verts, fill=(0, 0, 0))
    for i in range(_BLADES):
        x0, y0 = verts[i]
        x1, y1 = verts[(i + 1) % _BLADES]
        dx, dy = x1 - x0, y1 - y0
        n = math.hypot(dx, dy) or 1.0
        ux, uy = dx / n, dy / n
        # extend the side past the next vertex to the housing, curving slightly outward
        pts = [(x0, y0)]
        for s in range(1, 7):
            t = s / 6
            reach = n + (_HOUSING_R * 1.4) * t
            bend = 10 * t * t
            pts.append((x0 + ux * reach - uy * bend, y0 + uy * reach + ux * bend))
        d.line(pts, fill=GREEN_MID, width=1)
        d.line([verts[i], verts[(i + 1) % _BLADES]], fill=GREEN_HI if ap > 2 else GREEN, width=2)


def render_frame(bezel, mask, amp: float, angle: float, blink: float, look_x: float, look_y: float,
                 mood_rgb: tuple) -> Image.Image:
    lum = 0.3 + 0.7 * amp
    ax, ay = CX + look_x * 0.35, CY + look_y * 0.35          # aperture drifts a little
    lx, ly = CX + look_x * 1.5, CY + look_y * 1.5            # lens drifts more behind it
    ap = (34 + 46 * amp) * (1.0 - blink)
    twist = angle * 2.0 + 30 * amp                           # opening or thinking turns the blades

    img = _lens(lx, ly, mood_rgb, lum, 9 + 9 * amp)
    hx, hy = lx - 16, ly - 18
    ImageDraw.Draw(img).ellipse([hx - 4, hy - 3, hx + 4, hy + 3], fill=scale((255, 255, 255), 0.35 + 0.4 * lum))

    blades = Image.new("RGB", (W, H), (0, 0, 0))
    bd = ImageDraw.Draw(blades)
    _blades(bd, ax, ay, ap, twist)
    cut = Image.new("L", (W, H), 0)
    cd = ImageDraw.Draw(cut)
    cd.ellipse([CX - _HOUSING_R, CY - _HOUSING_R, CX + _HOUSING_R, CY + _HOUSING_R], fill=255)
    if ap > 0.5:
        cd.polygon([polar(ap, twist + i * 360 / _BLADES, ax, ay) for i in range(_BLADES)], fill=0)
    img.paste(blades, (0, 0), cut)

    # blade edge highlights drawn over the lens rim too
    img.paste(_STATIC, (0, 0), _STATIC_MASK)
    return _ph.compose(img)


def _static_mask() -> Image.Image:
    m = Image.new("L", (W, H), 255)
    ImageDraw.Draw(m).ellipse([CX - _HOUSING_R + 1, CY - _HOUSING_R + 1, CX + _HOUSING_R - 1, CY + _HOUSING_R - 1], fill=0)
    return m


_STATIC_MASK = _static_mask()
