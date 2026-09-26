"""Classic cogitator screensavers, upgraded with a shared phosphor CRT look.

Each submodule exposes NAME and render(bezel, mask, now). RENDERERS maps name ->
render function in display order; screensavers.py merges it into its registry.
"""

from __future__ import annotations

import importlib

_MODULES = [
    "pong", "asteroids", "battlezone", "game_of_life", "radar", "oscilloscope", "spectrum_bars",
    "canticle_rain", "data_stream", "glitch", "cogitator_terminal", "hud_status", "linguis_technis",
    "lexmechanic_ledger",
    "warp_core", "double_helix", "orbitals", "neural_net", "hex_grid", "noosphere_tether",
    "astronomican_pulse",
    "exterminatus_targeting", "bio_magos_sequencer", "golden_throne_ekg", "titan_manifold",
    "fabricator_matrix", "archeotech_vault", "magos_biologis",
]

RENDERERS = {}
for _mod_name in _MODULES:
    try:
        _mod = importlib.import_module(f"{__name__}.{_mod_name}")
        RENDERERS[_mod.NAME] = _mod.render
    except Exception as _e:  # one broken screensaver must not take down the rest
        print(f"[screensavers] Skipping classic screensaver {_mod_name}: {_e}")
