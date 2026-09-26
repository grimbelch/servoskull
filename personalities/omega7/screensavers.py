"""skull/screensavers.py – Cogitator Visual Emulation (Screensaver Animations).

Registry and dispatch for Omega-7's screensavers on the GC9A01 circular HUD.
The screensavers themselves live in two packages, each module exposing NAME and
render(bezel, mask, now):
  classic/ – green-phosphor cogitator screensavers (arcade, instruments,
             terminals, Mechanicus displays) sharing the phosphor CRT layer
  lore/    – larger simulation-driven Warhammer 40k scenes
"""

from PIL import Image

from .classic import RENDERERS as _CLASSIC_RENDERERS
from .lore import RENDERERS as _LORE_RENDERERS

# Rotation order: classic screensavers first, then lore. A module that failed to
# import is simply absent from its package's RENDERERS.
_RENDERERS = {**_CLASSIC_RENDERERS, **_LORE_RENDERERS}

# Master list of all available screensaver animations
SCREENSAVER_ANIMS = list(_RENDERERS)

_FALLBACK = "canticle_rain"
_reported_failures: set[str] = set()


def get_screensaver_names() -> list[str]:
    """Return authoritative list of screensaver animation names."""
    return list(SCREENSAVER_ANIMS)


def _report_once(anim_name: str, message: str) -> None:
    if anim_name not in _reported_failures:
        _reported_failures.add(anim_name)
        print(f"[screensavers] {message}")


def _render_fallback(bezel, mask, now: float) -> Image.Image:
    handler = _RENDERERS.get(_FALLBACK)
    if handler is not None:
        try:
            return handler(bezel, mask, now)
        except Exception as e:
            _report_once(_FALLBACK, f"Fallback '{_FALLBACK}' failed ({type(e).__name__}: {e}), showing blank frame.")
    return Image.new("RGB", (240, 240), (0, 0, 0))


def render_screensaver_frame(anim_name: str, bezel, mask, now: float) -> Image.Image:
    """Render a single frame for the requested screensaver animation name ($O(1)$ dispatch).

    Unknown or failing screensavers fall back to canticle rain; each failure is
    logged once so a broken screensaver doesn't silently disappear.
    """
    handler = _RENDERERS.get(anim_name)
    if handler is None:
        _report_once(anim_name, f"Unknown screensaver '{anim_name}', showing {_FALLBACK}.")
        return _render_fallback(bezel, mask, now)
    try:
        return handler(bezel, mask, now)
    except Exception as e:
        _report_once(anim_name, f"'{anim_name}' failed ({type(e).__name__}: {e}), showing {_FALLBACK}.")
        return _render_fallback(bezel, mask, now)
