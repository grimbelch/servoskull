"""
Static map knowledge for The Bard's Tale (1985, Apple II) — Skara Brae.

All data is derived from freely published fan walkthroughs and maps
(no copyrighted game assets). The coordinate system used here tracks
*relative* displacement from the party's starting position; it is most
useful for loop-detection and for feeding contextual hints to Claude Vision.

For Claude's benefit we also provide rich textual descriptions of every
major area and key strategic notes that the model can embed into its narration.
"""

from __future__ import annotations


# ── Skara Brae overworld — key landmarks ────────────────────────────────────────
#
# The city uses a 22×22 tile grid. Coordinates are (col, row) with (0,0) at the
# north-west corner. The party starts at the Adventurers' Guild near (11,11).
# Directions: north = row−1, south = row+1, east = col+1, west = col−1.
#
# Source: multiple fan-site Bard's Tale maps (e.g. GameFAQs/Shay Addams guide).

SKARA_BRAE_LANDMARKS: dict[tuple[int, int], str] = {
    (11, 11): "Adventurers' Guild — inn, party management, stat training with gold.",
    (10, 11): "West entrance to the Adventurers' Guild courtyard.",
    (12, 11): "East side of the guild courtyard; path toward the tavern.",
    (11, 10): "Northern exit of the guild toward the market district.",
    (11, 12): "Southern exit toward the sewers entrance.",
    ( 5, 11): "The Scarlet Bard Tavern — purchase Spellbooks here.",
    ( 5, 10): "Garth's Equipment Shoppe — buy weapons, armour, and shields.",
    (16, 11): "Temple of the Mad God — beware traps; contains a Mangar Ward.",
    (18,  5): "Temple of Aule — healing and resurrection services.",
    (18, 18): "Temple of Probo — cheaper healing.",
    ( 3,  3): "Ogre Fortress — high-level enemies, do not enter early.",
    (19,  3): "Castle Harkyn — end-game location; requires all dungeon keys.",
    (11, 19): "Sewers entrance — level 1 of the underworld, easiest dungeon.",
    ( 3, 19): "Wine Cellar entrance — second dungeon, moderate difficulty.",
    (19, 19): "Catacombs entrance — hardest surface dungeon.",
}

SKARA_BRAE_OVERVIEW = """\
You are in Skara Brae, a cursed city. Key landmarks:
- Adventurers' Guild (centre of map): heal, rest, train stats with gold, manage party.
- The Scarlet Bard Tavern (west): buy spellbooks for mages.
- Garth's Equipment Shoppe (west): weapons and armour.
- Temple of Aule (north-east), Temple of Probo (south-east): resurrection and healing.
- Sewers entrance (south-centre): first dungeon. Wine Cellar (south-west): second dungeon.
- Castle Harkyn (far north-east): final boss — only attempt with all dungeon keys.
Priority: Keep party HP above 50%. Return to the Guild inn when any hero is low.
Spend excess gold on stat training at the Guild — it persists permanently.\
"""


# ── Wine Cellar (Dungeon Level 1) ────────────────────────────────────────────────
#
# A modest maze directly beneath Skara Brae. Monster encounters scale with depth.
# The Wine Cellar exits to the Sewers on its deepest floor.

WINE_CELLAR_OVERVIEW = """\
You are in the Wine Cellar, the first dungeon beneath Skara Brae.
- Enemies here are skeletons, hobbits, and kobolds — manageable for a new party.
- Stairs down lead to the Sewers. Stairs up return to Skara Brae.
- Conserve spell points; cast only when party HP drops below 40%.
- Chests may be trapped — the Rogue can disarm them.
- Collect all gold here; return to the surface to train when full.\
"""


# ── Sewers (Dungeon Level 2) ─────────────────────────────────────────────────────

SEWERS_OVERVIEW = """\
You are in the Sewers, the second dungeon level.
- Enemies are stronger: berserkers, conjurers, and undead are common.
- There are anti-magic zones on certain squares — spells will fizzle.
- Watch for spinner traps that silently rotate your compass heading.
- Stairs up lead to the Wine Cellar; stairs down lead to the Catacombs.
- Return to the surface inn if any hero reaches critical HP.\
"""


# ── Catacombs (Dungeon Level 3) ──────────────────────────────────────────────────

CATACOMBS_OVERVIEW = """\
You are in the Catacombs, the third and deepest dungeon.
- Extremely dangerous — teleport traps, darkness zones, and powerful undead.
- Carry plenty of healing items and conserve your highest-level spells.
- The Archmage Mangar's lair connects via a hidden passage on this level.
- Do not explore without a full-strength party and maximum gold already spent on training.\
"""


# ── Castle Harkyn ────────────────────────────────────────────────────────────────

CASTLE_OVERVIEW = """\
You are in Castle Harkyn, the final dungeon.
- Requires all three dungeon level keys to progress.
- Enemies are the strongest in the game: demon lords and dragon packs.
- Conserve everything; the final confrontation with Mangar is at the castle's apex.\
"""


# ── Generic combat context ────────────────────────────────────────────────────────

COMBAT_CONTEXT = """\
You are in combat. Decision tree:
1. If party HP >= 60%: Fight (f) with every able hero.
2. If party HP 30-60%: Have the Bard sing a healing song; others fight.
3. If party HP < 30%: Retreat (r) immediately; cast MAWT or HEAL if you have it.
4. Against undead: TURN spell from a Paladin is highly effective.
5. Against casters: Eliminate conjurers and sorcerers first — they cast the most damage.
6. After combat: check HP before moving on.\
"""


# ── Public API ────────────────────────────────────────────────────────────────────

_LEVEL_CONTEXTS: dict[str, str] = {
    "skara_brae":  SKARA_BRAE_OVERVIEW,
    "wine_cellar": WINE_CELLAR_OVERVIEW,
    "sewers":      SEWERS_OVERVIEW,
    "catacombs":   CATACOMBS_OVERVIEW,
    "castle":      CASTLE_OVERVIEW,
    "combat":      COMBAT_CONTEXT,
}


def get_context(level: str, x: int = 0, y: int = 0) -> str:
    """
    Return a map / strategy context string for the given level.

    *x* and *y* are relative coordinates tracked by the walk-state tracker.
    For now they are used to look up nearby Skara Brae landmarks when in the
    overworld; dungeon levels return a flat overview.
    """
    ctx = _LEVEL_CONTEXTS.get(level.lower(), SKARA_BRAE_OVERVIEW)

    # Add a nearby-landmark note if we are in the overworld and have a position
    if level == "skara_brae":
        nearby = []
        for (lx, ly), desc in SKARA_BRAE_LANDMARKS.items():
            dist = abs(lx - x) + abs(ly - y)  # Manhattan distance
            if dist <= 2:
                nearby.append(f"  • {desc}")
        if nearby:
            ctx += "\n\nNearby landmarks:\n" + "\n".join(nearby)

    return ctx


def detect_level_from_text(screen_text: str) -> str:
    """
    Heuristic: guess the current dungeon level from keywords that appear on-screen.
    Claude Vision reads the screen directly, so this is only a coarse fallback.
    """
    t = screen_text.lower()
    if "wine cellar" in t:
        return "wine_cellar"
    if "sewer" in t:
        return "sewers"
    if "catacomb" in t:
        return "catacombs"
    if "castle" in t or "harkyn" in t:
        return "castle"
    if any(w in t for w in ("attack", "cast", "fight", "round", "monster", "combat")):
        return "combat"
    return "skara_brae"
