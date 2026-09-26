"""Shared helpers for the lore screensavers (240x240 round GC9A01 eye panel).

Each lore screensaver is a module in this package exposing:
    NAME: str                                  – key used in SCREENSAVER_ANIMS
    render(bezel, mask, now: float) -> Image   – one 240x240 RGB frame

The panel is circular: only pixels within ~SAFE_R of the centre are visible,
so keep text and focal elements inside that radius.
"""

from __future__ import annotations

import math
from functools import lru_cache

from PIL import ImageFont

W = H = 240
CX = CY = 120
SAFE_R = 112  # radius that is comfortably visible on the round panel


@lru_cache(maxsize=16)
def font(size: int = 11):
    """Cached bitmap-free default font at the given pixel size."""
    try:
        return ImageFont.load_default(size=size)
    except Exception:
        return ImageFont.load_default()


def text_center(d, y: float, text: str, fill, size: int = 11) -> None:
    """Draw text horizontally centred on the panel at height y."""
    f = font(size)
    w = d.textlength(text, font=f)
    d.text((CX - w / 2, y), text, fill=fill, font=f)


def safe_half_width(y: float, margin: float = 6.0) -> float:
    """Half-width of the visible chord at height y (for fitting text/bars)."""
    dy = y - CY
    r = SAFE_R - margin
    return math.sqrt(max(0.0, r * r - dy * dy))


def in_view(x: float, y: float, r: float = SAFE_R) -> bool:
    return (x - CX) ** 2 + (y - CY) ** 2 <= r * r


def scale(color, k: float):
    k = max(0.0, min(1.0, k))
    return tuple(int(c * k) for c in color)


def lerp_color(a, b, t: float):
    t = max(0.0, min(1.0, t))
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def rotate_xyz(p, ax: float, ay: float, az: float = 0.0):
    """Rotate a 3D point about X, then Y, then Z (radians)."""
    x, y, z = p
    cx, sx = math.cos(ax), math.sin(ax)
    y, z = y * cx - z * sx, y * sx + z * cx
    cy, sy = math.cos(ay), math.sin(ay)
    x, z = x * cy + z * sy, -x * sy + z * cy
    if az:
        cz, sz = math.cos(az), math.sin(az)
        x, y = x * cz - y * sz, x * sz + y * cz
    return x, y, z


def project(p, fov: float = 180.0, cam_dist: float = 220.0):
    """Perspective-project a 3D point (camera on -Z looking +Z). Returns (sx, sy, depth) or None."""
    x, y, z = p
    zc = z + cam_dist
    if zc <= 1.0:
        return None
    f = fov / zc
    return CX + x * f, CY + y * f, zc


class Session:
    """Detects the start of a new showing so a screensaver can reset its story.

    The display calls render() every frame while a screensaver is active; a gap
    of more than `gap` seconds means it was off and is being shown afresh.
    """

    def __init__(self, gap: float = 2.0):
        self.gap = gap
        self.last = None
        self.start = 0.0

    def fresh(self, now: float) -> bool:
        is_new = self.last is None or now - self.last > self.gap or now < self.last
        if is_new:
            self.start = now
        self.last = now
        return is_new

    def t(self, now: float) -> float:
        """Seconds since this showing began."""
        return now - self.start
