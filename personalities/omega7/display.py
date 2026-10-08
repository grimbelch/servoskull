"""Omega-7's ocular: the active eye style, the startup animation and mood colours.

The eye itself is drawn by one of the styles in eyes/ (eyes.STYLES); core
display picks the style at boot and on "switch your eye to ..." through
set_eye_style(), then rebuilds the bezel and aperture mask.

The startup animation shown before the eye takes over lives in boot_glyph.
"""

from __future__ import annotations

from PIL import Image

from . import boot_glyph, eyes

W = H = 240
_CX = _CY = 120

EYE_STYLES = list(eyes.STYLES)
DEFAULT_EYE_STYLE = eyes.DEFAULT
_style = eyes.STYLES.get(eyes.DEFAULT) or next(iter(eyes.STYLES.values()))


# Mood -> the eye drawn for it (each mood eye names its MOOD), used when the eye
# is set to follow the disposition.
MOOD_EYES = {mod.MOOD: name for name, mod in eyes.STYLES.items() if hasattr(mod, "MOOD")}


def eye_style_for_mood(mood: str) -> str | None:
    return MOOD_EYES.get((mood or "").upper())


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
    """The startup animation (core/display.start_omnissiah_glyph)."""
    return boot_glyph.render(now, start_time, duration, mood_rgb)


MOOD_COLOURS = {
    "VIGILANT": (255, 40, 30),
    "DUTIFUL": (255, 70, 25),
    "FERVENT": (255, 120, 20),
    "SUSPICIOUS": (255, 200, 30),
    "CONTEMPLATIVE": (60, 140, 255),
    "MELANCHOLIC": (90, 90, 200),
}
