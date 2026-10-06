"""Shared helpers for the phosphor eye styles (240x240 round GC9A01 panel).

The phosphor eyes draw their content as bright strokes on black, pass it through
a classic.Phosphor (afterglow, bloom, scanlines, vignette) to match the green
cogitator screensavers, and then close the shutter over the result so a blink –
only two frames at 15 fps – stays crisp instead of smearing into the afterglow.
"""

from __future__ import annotations

import math

import numpy as np
from PIL import Image, ImageDraw

from ..classic._phosphor import BG, GREEN_HI, GREEN_MID, Phosphor
from ..lore._common import CX, CY, H, W, font, lerp_color, scale

__all__ = ["CX", "CY", "H", "W", "font", "lerp_color", "scale", "Phosphor",
           "polar", "gear_points", "arc_ring", "shutter", "composed_bezel"]

_yy, _xx = np.mgrid[0:H, 0:W].astype(np.float32)
_ROW = np.arange(H, dtype=np.float32)[:, None]


def polar(r: float, deg: float, cx: float = CX, cy: float = CY):
    a = math.radians(deg)
    return cx + r * math.cos(a), cy + r * math.sin(a)


def gear_points(n_teeth: int, r_root: float, r_tip: float, rot_deg: float = 0.0,
                cx: float = CX, cy: float = CY, tooth: float = 0.45):
    """Outline of a cog: n_teeth flat-topped teeth between r_root and r_tip."""
    pts = []
    step = 360.0 / n_teeth
    for i in range(n_teeth):
        a = rot_deg + i * step
        flank = step * tooth / 2
        top = flank * 0.7
        pts += [polar(r_root, a - flank, cx, cy), polar(r_tip, a - top, cx, cy),
                polar(r_tip, a + top, cx, cy), polar(r_root, a + flank, cx, cy)]
        for k in (1, 2):  # keep the root between teeth round
            pts.append(polar(r_root, a + flank + (step - 2 * flank) * k / 3, cx, cy))
    return pts


def arc_ring(d: ImageDraw.ImageDraw, r: float, start: float, end: float, fill, width: int = 1,
             cx: float = CX, cy: float = CY) -> None:
    d.arc([cx - r, cy - r, cx + r, cy + r], start, end, fill=fill, width=width)


def shutter(img: Image.Image, blink: float, cx: float, cy: float, r: float, edge=GREEN_MID) -> Image.Image:
    """Close a pair of shutter lids over the disc (cx, cy, r): blink 0 open .. 1 shut.

    The lids meet on the eye's centre line; their leading edges glow like a CRT
    raster collapsing, and when nearly shut only a bright line is left.
    """
    if blink <= 0.0:
        return img
    half = r * (1.0 - blink)
    a = np.asarray(img).copy()
    disc = (_xx - cx) ** 2 + (_yy - cy) ** 2 <= r * r
    lid = disc & (np.abs(_ROW - cy) > half)
    a[lid] = BG
    out = Image.fromarray(a)
    d = ImageDraw.Draw(out)
    for y in ((cy - half, cy + half) if half >= 1.5 else (cy,)):
        dy = y - cy
        w = math.sqrt(max(0.0, r * r - dy * dy))
        colour = GREEN_HI if half < 1.5 else edge
        d.line([(cx - w, y), (cx + w, y)], fill=colour, width=2 if half < 1.5 else 1)
    return out


def composed_bezel(static: Image.Image) -> Image.Image:
    """The static layer as it looks on the phosphor, for overlay modes to draw onto."""
    return Phosphor(decay=0.0, flicker=0.0).compose(static)
