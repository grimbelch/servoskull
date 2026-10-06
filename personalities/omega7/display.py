"""Omega-7's ocular: the active eye style, the boot glyph overlay and mood colours.

The eye itself is drawn by one of the styles in eyes/ (eyes.STYLES); core
display picks the style at boot and on "switch your eye to ..." through
set_eye_style(), then rebuilds the bezel and aperture mask.
"""

import math

from PIL import Image, ImageDraw

from . import eyes

W = H = 240
_CX = _CY = 120

EYE_STYLES = list(eyes.STYLES)
DEFAULT_EYE_STYLE = eyes.DEFAULT
_style = eyes.STYLES.get(eyes.DEFAULT) or next(iter(eyes.STYLES.values()))


def get_eye_style() -> str:
    return _style.NAME


def set_eye_style(name: str) -> bool:
    """Make `name` the active eye style; False if there is no such style."""
    global _style
    mod = eyes.STYLES.get(name)
    if mod is None:
        return False
    _style = mod
    return True


def eye_style_title(name: str) -> str:
    return eyes.STYLES[name].TITLE


def eye_style_phrases(name: str) -> tuple[str, ...]:
    return eyes.spoken_names(name)


def aperture_radius() -> int:
    return _style.APERTURE_R


def render_bezel() -> Image.Image:
    return _style.render_bezel()


def render_frame(bezel: Image.Image, mask: Image.Image, amp: float, angle: float, blink: float, look_x: float, look_y: float, mood_rgb: tuple) -> Image.Image:
    return _style.render_frame(bezel, mask, amp, angle, blink, look_x, look_y, mood_rgb)

def render_overlay(bezel: Image.Image, mask: Image.Image, now: float, start_time: float, duration: float, mood_rgb: tuple) -> Image.Image:
    age = max(0.0, now - start_time)
    overlay = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(overlay)

    # ── Adeptus Mechanicus Skull-Cog (Scaled to Full-Screen 240x240) ──
    scale = min(1.0, age / 1.0)
    scale = scale * scale * (3.0 - 2.0 * scale)

    if scale > 0.01:
        gear_angle = (age * 90.0) % 360
        r_outer = 110.0 * scale
        r_inner = 85.0 * scale
        num_teeth = 12

        points = []
        for i in range(num_teeth):
            t_start = i * (360.0 / num_teeth)
            cycle_deg = 360.0 / num_teeth
            a1 = gear_angle + t_start
            a2 = gear_angle + t_start + cycle_deg * 0.4
            a3 = gear_angle + t_start + cycle_deg * 0.5
            a4 = gear_angle + t_start + cycle_deg * 0.9

            points.append((_CX + r_outer * math.cos(math.radians(a1)), _CY + r_outer * math.sin(math.radians(a1))))
            points.append((_CX + r_outer * math.cos(math.radians(a2)), _CY + r_outer * math.sin(math.radians(a2))))
            points.append((_CX + r_inner * math.cos(math.radians(a3)), _CY + r_inner * math.sin(math.radians(a3))))
            points.append((_CX + r_inner * math.cos(math.radians(a4)), _CY + r_inner * math.sin(math.radians(a4))))

        d.polygon(points, fill=(235, 230, 215))

        r_center = 68.0 * scale
        d.ellipse([_CX - r_center, _CY - r_center, _CX + r_center, _CY + r_center], fill=(0, 0, 0))

        # Left cranium (bone)
        d.pieslice([_CX - 27 * scale, _CY - 34 * scale, _CX + 27 * scale, _CY + 20 * scale], 90, 270, fill=(235, 230, 215))
        # Right cranium (machine)
        d.pieslice([_CX - 27 * scale, _CY - 34 * scale, _CX + 27 * scale, _CY + 20 * scale], 270, 90, fill=(80, 85, 95))

        # Left jaw
        d.polygon([
            (_CX - 15 * scale, _CY + 20 * scale),
            (_CX, _CY + 20 * scale),
            (_CX, _CY + 37 * scale),
            (_CX - 12 * scale, _CY + 37 * scale)
        ], fill=(235, 230, 215))
        # Right jaw
        d.polygon([
            (_CX, _CY + 20 * scale),
            (_CX + 15 * scale, _CY + 20 * scale),
            (_CX + 12 * scale, _CY + 37 * scale),
            (_CX, _CY + 37 * scale)
        ], fill=(80, 85, 95))

        # Cheekbones
        d.ellipse([_CX - 31 * scale, _CY - 3 * scale, _CX - 17 * scale, _CY + 10 * scale], fill=(235, 230, 215))
        d.ellipse([_CX + 17 * scale, _CY - 3 * scale, _CX + 31 * scale, _CY + 10 * scale], fill=(80, 85, 95))

        # Left eye
        d.ellipse([_CX - 15 * scale, _CY - 7 * scale, _CX - 5 * scale, _CY + 3 * scale], fill=(0, 0, 0))
        # Right eye (glowing green/mood)
        d.ellipse([_CX + 5 * scale, _CY - 7 * scale, _CX + 15 * scale, _CY + 3 * scale], fill=mood_rgb)

        # Nose
        d.polygon([
            (_CX - 3 * scale, _CY + 14 * scale),
            (_CX, _CY + 7 * scale),
            (_CX + 3 * scale, _CY + 14 * scale)
        ], fill=(0, 0, 0))

        # Teeth slits
        for offset in (-8, -3):
            d.line([(_CX + offset * scale, _CY + 20 * scale), (_CX + offset * scale, _CY + 34 * scale)], fill=(0, 0, 0), width=1)
        for offset in (3, 8):
            d.line([(_CX + offset * scale, _CY + 20 * scale), (_CX + offset * scale, _CY + 34 * scale)], fill=(0, 0, 0), width=1)
        d.line([(_CX, _CY + 20 * scale), (_CX, _CY + 37 * scale)], fill=(0, 0, 0), width=1)

    return overlay

MOOD_COLOURS = {
    "VIGILANT": (255, 40, 30),
    "DUTIFUL": (255, 70, 25),
    "FERVENT": (255, 120, 20),
    "SUSPICIOUS": (255, 200, 30),
    "CONTEMPLATIVE": (60, 140, 255),
    "MELANCHOLIC": (90, 90, 200),
}
