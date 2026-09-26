"""Lore screensavers: larger, simulation-driven Warhammer 40k animations.

Each submodule exposes NAME and render(bezel, mask, now). RENDERERS maps name ->
render function in display order; screensavers.py merges it into its registry.
"""

from __future__ import annotations

import importlib

_MODULES = [
    "auspex_engagement", "titan_duel", "drop_pod_assault", "space_hulk_auspex",
    "gothic_broadside", "warp_translation", "galactic_orrery", "forge_world_orbital",
    "plasma_reactor", "mechadendrite_assembly", "cogitator_boot", "administratum_cogitation",
    "tyranid_swarm", "necron_awakening", "chaos_corruption", "inquisitorial_dossier",
]

RENDERERS = {}
for _mod_name in _MODULES:
    try:
        _mod = importlib.import_module(f"{__name__}.{_mod_name}")
        RENDERERS[_mod.NAME] = _mod.render
    except Exception as _e:  # one broken screensaver must not take down the rest
        print(f"[screensavers] Skipping lore screensaver {_mod_name}: {_e}")
