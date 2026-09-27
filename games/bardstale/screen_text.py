"""
Read the text on the Bard's Tale screen exactly, so the model gets words and numbers
instead of squinting at 7-pixel Apple II characters.

The game draws all text on the Apple's 40x24 character grid (7x8 pixels a cell,
14x8 in MAME's 560-wide frame). Each cell's ink pattern is looked up in font.json,
a table of glyph bitmaps learned from known screens (both of the game's fonts: the
message box's and the bolder party roster's). A cell whose glyph isn't in the table
reads as "·"; the model still has the screenshot for those.

Layout (rows/cols of the text grid):
    row 14, cols 1-14     location label under the view ("Skara Brae", "The Guild")
    rows 3-14, cols 21-38 message box
    rows 17-23            party: "1) NAME", AC, Hits (max), Cond (current), SpPt, Class
"""

from __future__ import annotations

import json
import pathlib

import numpy as np
from PIL import Image

_FONT: dict[str, str] = json.loads((pathlib.Path(__file__).with_name("font.json")).read_text())
UNKNOWN = "·"


def _pixels(img: Image.Image) -> np.ndarray:
    a = np.asarray(img.convert("RGB"), dtype=np.int16)
    if a.shape[:2] != (192, 560):
        a = np.asarray(img.convert("RGB").resize((560, 192), Image.NEAREST), dtype=np.int16)
    return a


def _cells(img_or_pixels, dy: int = 0) -> list[list[str | None]]:
    """Glyph key (56-bit string) of every text cell, or None for an empty cell. `dy`
    shifts the grid down by that many pixel rows (for smoothly scrolling text)."""
    a = img_or_pixels if isinstance(img_or_pixels, np.ndarray) else _pixels(img_or_pixels)
    if dy:
        a = np.concatenate([a[dy:], np.zeros((dy, 560, 3), dtype=a.dtype)])
    bright = (a.min(axis=2) > 200).reshape(24, 8, 40, 14).transpose(0, 2, 1, 3)
    dark = (a.max(axis=2) < 60).reshape(24, 8, 40, 14).transpose(0, 2, 1, 3)
    # Ink is whatever differs from the cell's background (white box or black screen).
    white_bg = bright.sum(axis=(2, 3)) >= dark.sum(axis=(2, 3))
    ink = np.where(white_bg[:, :, None, None], ~bright, ~dark)
    bits = ink.reshape(24, 40, 8, 7, 2).any(axis=4).reshape(24, 40, 56)
    out = []
    for r in range(24):
        row = []
        for c in range(40):
            v = bits[r, c]
            row.append("".join("1" if b else "0" for b in v) if v.any() else None)
        out.append(row)
    return out


_MAX_DISTANCE = 4       # differing pixels tolerated (colour fringes from neighbouring cells)
_near_cache: dict[str, str] = {}


def _glyph(key: str | None) -> str:
    if key is None:
        return " "
    ch = _FONT.get(key)
    if ch is not None:
        return ch
    if key not in _near_cache:
        # Nearest known glyph by Hamming distance; unknown if none is close, or if the
        # two closest disagree and are equally close.
        v = int(key, 2)
        ranked = sorted((bin(v ^ int(k, 2)).count("1"), c) for k, c in _FONT.items())
        (d1, c1), (d2, c2) = ranked[0], ranked[1]
        _near_cache[key] = c1 if d1 <= _MAX_DISTANCE and (d1 < d2 or c1 == c2) else UNKNOWN
    return _near_cache[key]


def _line(cells, r: int, c0: int, c1: int) -> str:
    return "".join(_glyph(k) for k in cells[r][c0:c1]).rstrip()


def _message(a: np.ndarray, cells) -> list[str]:
    """Message box lines. Combat messages scroll up pixel by pixel, so when the
    grid-aligned read has unreadable cells, the best of the 8 row offsets wins."""
    lines = [_line(cells, r, 21, 39) for r in range(3, 15)]
    bad = sum(l.count(UNKNOWN) for l in lines)
    if bad:
        for dy in range(1, 8):
            c = _cells(a, dy)
            alt = [_line(c, r, 21, 39) for r in range(2, 15)]
            n = sum(l.count(UNKNOWN) for l in alt)
            if n < bad:
                lines, bad = alt, n
            if not bad:
                break
    return lines


def read(img: Image.Image) -> dict:
    """{"location": str, "message": [lines], "party": [lines]} for a 560x192 frame."""
    a = _pixels(img)
    cells = _cells(a)
    message = _message(a, cells)
    while message and not message[-1]:
        message.pop()
    while message and not message[0]:
        message.pop(0)
    party = [_line(cells, r, 0, 40) for r in range(17, 24)]
    return {
        "location": _line(cells, 14, 1, 15).strip(" " + UNKNOWN),
        "message": message,
        "party": [p for p in party if p.strip() and p.strip() != "S)"] or [],
    }


def describe(img: Image.Image) -> str:
    """The screen's text as a compact block for the model."""
    t = read(img)
    lines = [f"Location label: {t['location'] or '(none)'}", "Message box:"]
    lines += [f"  {m}" for m in t["message"]] or ["  (empty)"]
    if t["party"]:
        lines.append("Party (#) NAME, AC, Hits=max HP, Cond=current HP, SpPt, Class):")
        lines += [f"  {p}" for p in t["party"]]
    return "\n".join(lines)


def learn(img: Image.Image, row: int, col: int, text: str, save: bool = True) -> list[str]:
    """Development aid: teach the reader the glyphs of `text`, known to be drawn at
    (row, col) of `img`. Returns conflicts (a glyph already mapped to another
    character). With save, font.json is rewritten."""
    cells = _cells(img)
    conflicts = []
    for i, ch in enumerate(text):
        k = cells[row][col + i]
        if ch == " " or k is None:
            continue
        if _FONT.get(k, ch) != ch:
            conflicts.append(f"({row},{col + i}) {ch!r} vs {_FONT[k]!r}")
            continue
        _FONT[k] = ch
    _near_cache.clear()
    if save:
        pathlib.Path(__file__).with_name("font.json").write_text(json.dumps(_FONT, sort_keys=True))
    return conflicts
