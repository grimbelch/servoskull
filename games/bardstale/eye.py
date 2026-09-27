"""
The eye's view of a Bard's Tale session (240x240, round GC9A01 panel).

    ┌──── keys just pressed (↑ ↑ ↱) ────┐
    │      the Apple II screen, whole    │
    └─── what Omega-7 is doing ──────────┘

The whole Apple screen is kept (view window, message box and party roster),
scaled to sit inside the circle, with a phosphor-green bezel ring.
"""

from __future__ import annotations

from PIL import Image, ImageDraw, ImageFont

SIZE = 240
_SCREEN_W, _SCREEN_H = 200, 137          # Apple II 280x192 aspect
_SCREEN_X, _SCREEN_Y = (SIZE - _SCREEN_W) // 2, 48
_GREEN = (60, 255, 110)
_DIM = (30, 120, 55)

_KEY_GLYPHS = {"I": "↑", "K": "↓", "J": "↰", "L": "↱", "RETURN": "↵", "SPACE": "SPC", "ESC": "ESC"}

_fonts: dict[int, ImageFont.ImageFont] = {}


def _font(size: int):
    if size not in _fonts:
        for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                     "/Library/Fonts/Arial Unicode.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf"):
            try:
                _fonts[size] = ImageFont.truetype(path, size)
                break
            except OSError:
                continue
        else:
            _fonts[size] = ImageFont.load_default()
    return _fonts[size]


def key_glyphs(keys: list[str]) -> str:
    return " ".join(_KEY_GLYPHS.get(k, k if len(k) <= 8 else k[:7] + "…") for k in keys[:8])


def _fit_text(d: ImageDraw.ImageDraw, text: str, max_w: int, size: int, min_size: int = 10):
    while size > min_size and d.textlength(text, font=_font(size)) > max_w:
        size -= 1
    font = _font(size)
    while text and d.textlength(text, font=font) > max_w:
        text = text[:-2] + "…"
    return text, font


def render(screen: Image.Image | None, doing: str, keys_text: str) -> Image.Image:
    """Compose one eye frame from the emulator screen (any size, 280x192 aspect)."""
    img = Image.new("RGB", (SIZE, SIZE), (0, 0, 0))
    d = ImageDraw.Draw(img)

    if screen is not None:
        img.paste(screen.resize((_SCREEN_W, _SCREEN_H), Image.BOX), (_SCREEN_X, _SCREEN_Y))
    else:
        text, font = _fit_text(d, "LOADING…", 160, 16)
        d.text((SIZE // 2, SIZE // 2), text, fill=_GREEN, font=font, anchor="mm")

    if keys_text:
        text, font = _fit_text(d, keys_text, 150, 17)
        d.text((SIZE // 2, 33), text, fill=_GREEN, font=font, anchor="mm")
    if doing:
        text, font = _fit_text(d, doing.upper(), 172, 15)
        d.text((SIZE // 2, 203), text, fill=_GREEN, font=font, anchor="mm")

    d.ellipse((1, 1, SIZE - 2, SIZE - 2), outline=_DIM, width=2)
    return img
