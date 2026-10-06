"""Mechanicus Cog – the original eye: a gunmetal cog bezel around a glowing mood-tinted iris.

Archived here unchanged from the first ocular so it can be brought back with
"switch your eye to the cog". The cog turns while the skull is cogitating.
"""

from __future__ import annotations

import math

from PIL import Image, ImageDraw

NAME = "cog"
TITLE = "Mechanicus Cog"
ALIASES = ("classic", "original", "old", "gear")
APERTURE_R = 73  # the cog's central aperture; overlay modes draw inside it

W = H = 240
_CX = _CY = 120

def _scale(rgb, k: float):
    k = max(0.0, min(1.0, k))
    return (int(rgb[0] * k), int(rgb[1] * k), int(rgb[2] * k))

def _gear_polygon(n_teeth: int, r_root: float, r_tip: float,
                  tooth_frac: float = 0.52, tip_frac: float = 0.34,
                  gap_steps: int = 5):
    period = 2 * math.pi / n_teeth
    half_base = period * tooth_frac / 2
    half_tip = period * tip_frac / 2
    polar = []
    for i in range(n_teeth):
        a = i * period
        polar.append((a - half_base, r_root))
        polar.append((a - half_tip, r_tip))
        polar.append((a + half_tip, r_tip))
        polar.append((a + half_base, r_root))
        gap_start, gap_end = a + half_base, a + period - half_base
        for s in range(1, gap_steps):
            polar.append((gap_start + (gap_end - gap_start) * s / gap_steps, r_root))
    return [(_CX + r * math.cos(ang), _CY + r * math.sin(ang)) for ang, r in polar]

def render_bezel() -> Image.Image:
    GEAR = (60, 62, 70)
    EDGE = (120, 124, 138)
    DARK = (24, 25, 30)
    RIM = (150, 44, 24)

    bg = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(bg)

    d.polygon(_gear_polygon(11, r_root=96, r_tip=117), fill=GEAR, outline=EDGE, width=3)

    for deg in range(0, 360, 30):
        a = math.radians(deg)
        bx, by = _CX + 86 * math.cos(a), _CY + 86 * math.sin(a)
        d.ellipse([bx - 3, by - 3, bx + 3, by + 3], fill=DARK)

    d.ellipse([_CX - 80, _CY - 80, _CX + 80, _CY + 80], outline=EDGE, width=2)
    d.ellipse([_CX - 78, _CY - 78, _CX + 78, _CY + 78], fill=DARK)
    d.ellipse([_CX - 75, _CY - 75, _CX + 75, _CY + 75], outline=RIM, width=3)
    return bg

def render_frame(bezel: Image.Image, mask: Image.Image, amp: float, angle: float, blink: float, look_x: float, look_y: float, mood_rgb: tuple) -> Image.Image:
    img = bezel.rotate(angle, resample=Image.BICUBIC) if angle else bezel.copy()
    base = mood_rgb
    intensity = 0.25 + 0.75 * amp
    iris_r = 30 + 30 * amp

    cx = _CX + look_x
    cy = _CY + look_y

    iris = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(iris)

    def disc(r, colour):
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=colour)

    disc(iris_r * 2.0, _scale(base, intensity * 0.12))
    disc(iris_r * 1.45, _scale(base, intensity * 0.32))
    disc(iris_r, _scale(base, intensity))
    disc(iris_r * 0.55, _scale(base, min(1.0, intensity * 1.4)))
    disc(iris_r * 0.26, (8, 0, 0))

    if blink > 0.0:
        open_h = max(1, int(round(H * (1.0 - blink))))
        squashed = iris.resize((W, open_h), resample=Image.BILINEAR)
        iris = Image.new("RGB", (W, H), (0, 0, 0))
        iris.paste(squashed, (0, (H - open_h) // 2))

    img.paste(iris, (0, 0), mask)
    return img
