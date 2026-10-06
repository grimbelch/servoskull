"""Eye styles for Omega-7's round ocular panel.

Each submodule is one complete eye design exposing:
    NAME: str               – key stored in eye_style_<persona>.json and the config
    TITLE: str              – the name the skull speaks when switching
    ALIASES: tuple[str]     – extra spoken names ("classic", "radar" …)
    APERTURE_R: int         – radius of the central disc overlay modes draw into
    render_bezel() -> Image – static backdrop, rebuilt when the style changes
    render_frame(bezel, mask, amp, angle, blink, look_x, look_y, mood_rgb) -> Image

amp is speech amplitude (0..1), angle the cogitation spin in degrees (advances
only while thinking), blink 0 open .. 1 shut, look_x/look_y the idle gaze offset
in pixels (about ±18), and mood_rgb the disposition tint.
"""

from __future__ import annotations

import importlib

_MODULES = ["auspex", "aperture", "noosphere", "augmetic", "cog"]

DEFAULT = "cog"

STYLES = {}
for _mod_name in _MODULES:
    try:
        _mod = importlib.import_module(f"{__name__}.{_mod_name}")
        STYLES[_mod.NAME] = _mod
    except Exception as _e:  # one broken eye must not leave the skull blind
        print(f"[eyes] Skipping eye style {_mod_name}: {_e}")


def spoken_names(name: str) -> tuple[str, ...]:
    """Every phrase that names this style aloud: its key, title and aliases."""
    mod = STYLES[name]
    names = {name.replace("_", " "), mod.TITLE.lower(), *(a.lower() for a in getattr(mod, "ALIASES", ()))}
    return tuple(sorted(names, key=len, reverse=True))
