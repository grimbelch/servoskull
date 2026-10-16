"""The Cult Mechanicus cog-skull as phosphor light, for the boot animation and screensavers.

`cog_skull.png` is a greyscale luminance map of the emblem: the half-machine,
half-bone skull in a toothed cog, the left of the cog pale and the right dark.
It was made from a painting of the emblem by flattening it to grey, adding back
its local detail and edges, cutting it out of its white ground, and outlining the
gear so the dark half still reads on a black screen. Black is empty, so it
composites by brightness (`ImageChops.lighter`) without an alpha channel.

`tinted(size, colour)` gives it at any size in any phosphor colour; EYE and
EYE_R place the bionic lens (left half, the round grille) for whatever is lit
there.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageChops

_PATH = Path(__file__).with_name("cog_skull.png")

# The bionic lens: its centre as a fraction of the emblem's size from the
# emblem's centre, and the radius of its bezel as a fraction of that size.
EYE = (-0.127, 0.044)
EYE_R = 0.072


@lru_cache(maxsize=8)
def luminance(size: int) -> Image.Image:
    """The emblem's greyscale luminance at `size` x `size` pixels."""
    return Image.open(_PATH).convert("L").resize((size, size), Image.LANCZOS)


@lru_cache(maxsize=64)
def tinted(size: int, colour: tuple, gain: float = 1.0) -> Image.Image:
    """The emblem lit in `colour`, its luminance multiplied by `gain` and clipped."""
    lum = luminance(size)
    bands = [lum.point([min(255, int(v * gain * c / 255)) for v in range(256)]) for c in colour]
    return Image.merge("RGB", bands)


def draw(img: Image.Image, cx: float, cy: float, size: int, colour: tuple,
         gain: float = 1.0, reveal: float = 1.0, beam: tuple | None = None) -> None:
    """Light the emblem onto `img`, centred on (cx, cy), by brightness.

    `reveal` paints only the top fraction of its rows, as a raster still being
    struck; `beam` is the colour of the scan line at the front of that sweep.
    """
    x0, y0 = round(cx - size / 2), round(cy - size / 2)
    rows = size if reveal >= 1.0 else int(size * max(0.0, reveal))
    if rows > 0:
        _lighten(img, tinted(size, colour, gain).crop((0, 0, size, rows)), x0, y0)
    if beam is not None and rows < size and reveal > 0.0:
        _lighten(img, tinted(size, beam, 3.0).crop((0, rows, size, min(size, rows + 2))), x0, y0 + rows)


def _lighten(img: Image.Image, tile: Image.Image, x: int, y: int) -> None:
    box = (x, y, x + tile.width, y + tile.height)
    img.paste(ImageChops.lighter(img.crop(box), tile), box)


def eye_centre(cx: float, cy: float, size: int) -> tuple[float, float]:
    """Where the bionic lens sits on an emblem of `size` centred on (cx, cy)."""
    return cx + EYE[0] * size, cy + EYE[1] * size
