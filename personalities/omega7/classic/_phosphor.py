"""Shared green-phosphor CRT look for the classic cogitator screensavers.

Draw each frame's content onto a black 240x240 RGB image (bright strokes on
black), then pass it through a Phosphor instance, which adds:
  - persistence: previous frames fade out instead of vanishing (afterglow trails)
  - bloom: a soft glow around bright strokes
  - scanlines, a curved-glass vignette and a faint flicker

Keep one Phosphor per screensaver and call reset() when a new showing starts.
"""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageFilter

from ..lore._common import CX, CY, H, W

# Palette — a P1-style green phosphor with amber/red reserved for warnings.
BG = (0, 10, 4)
GREEN_HI = (170, 255, 190)   # hottest strokes, text highlights
GREEN = (40, 230, 100)       # primary strokes
GREEN_MID = (20, 150, 60)    # secondary strokes, labels
GREEN_DIM = (8, 70, 28)      # grids, graticules, inactive elements
GREEN_FAINT = (4, 36, 14)    # background texture
AMBER = (255, 180, 40)       # cautions, scores, highlights
RED = (255, 64, 48)          # alarms only

_yy, _xx = np.mgrid[0:H, 0:W].astype(np.float32)
_r = np.sqrt((_xx - CX) ** 2 + (_yy - CY) ** 2) / 120.0
_VIGNETTE = np.clip(1.08 - 0.38 * _r ** 2.2, 0.35, 1.0)[..., None]
_SCAN = np.where((np.arange(H) % 2) == 0, 1.0, 0.80).astype(np.float32)[:, None, None]
_BG = np.array(BG, dtype=np.float32)


class Phosphor:
    def __init__(self, decay: float = 0.78, bloom: float = 0.55, scan: bool = True, flicker: float = 0.03):
        """decay: fraction of last frame's light kept (0 = no trails, 0.9 = long trails).
        bloom: glow strength. flicker: max random brightness wobble per frame."""
        self.decay = decay
        self.bloom = bloom
        self.scan = scan
        self.flicker = flicker
        self._rng = np.random.default_rng()
        self._buf = None

    def reset(self) -> None:
        self._buf = None

    def compose(self, frame: Image.Image) -> Image.Image:
        """Blend a freshly drawn frame into the phosphor and return the display image."""
        cur = np.asarray(frame, dtype=np.float32)
        if self._buf is None or self.decay <= 0:
            self._buf = cur.copy()
        else:
            np.multiply(self._buf, self.decay, out=self._buf)
            np.maximum(self._buf, cur, out=self._buf)

        out = self._buf.copy()
        if self.bloom > 0:
            small = Image.fromarray(np.clip(self._buf, 0, 255).astype(np.uint8)).resize((60, 60), Image.BOX)
            glow = small.filter(ImageFilter.GaussianBlur(1.6)).resize((W, H), Image.BILINEAR)
            out += np.asarray(glow, dtype=np.float32) * self.bloom
        if self.scan:
            out *= _SCAN
        out *= _VIGNETTE
        if self.flicker:
            out *= 1.0 - self.flicker * self._rng.random()
        out += _BG
        return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))


def blank() -> Image.Image:
    """A black canvas to draw a frame's content on before compose()."""
    return Image.new("RGB", (W, H), (0, 0, 0))
