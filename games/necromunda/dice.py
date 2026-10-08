"""Necromunda Skirmish dice.

The 2026 core rulebook lists the dice the game uses (page 32, "NECROMUNDA
DICE"): D6, D66, D3, Firepower, Scatter and Injury. It spells out how to roll
D66 and D3, and it gives the Scatter dice's faces exactly -- a Hit symbol on two
faces and an arrow on each of the other four.

It does NOT print the faces of the Firepower or Injury dice. Those are moulded on
the physical dice and appear only as an illustration, so they cannot be read out
of the source text. They are declared here as data, with their provenance
stated, rather than buried inside a simulation function -- if a count is ever
shown to be wrong, one table changes and every caller follows.

Both distributions below are corroborated by independent community sources and
by photographs of the dice themselves, but neither is confirmed by an official
Games Workshop face table:

* Injury dice, 2 Injured / 3 Serious Injury / 1 Out of Action. Goonhammer's
  Hammer of Math quotes 33% / 50% / 17%, and a second account states the split
  directly as 2/6, 3/6 and 1/6.
* Firepower dice, one face of three bullet holes, two of two, two of one, and
  one carrying a single bullet hole together with the ammo symbol.

The symbols are recorded alongside the results because they are what the eye
display draws: a cross with a droplet for Injured, a splintered starburst for
Serious Injury, a skull for Out of Action, jagged bullet holes for shots, and a
crosshair for the Scatter dice's Hit face.

What the book does state, and what the previous implementation got wrong, is the
injury MECHANIC: the attacker rolls a number of Injury dice equal to the
weapon's Lethality and then selects ONE of them to apply (page 77, "3. INFLICT
DAMAGE"). It is a choice among dice, not a tally of all of them.
"""
from __future__ import annotations

import random

# Injury results, in increasing severity. "Injured" replaces the previous
# edition's "Flesh Wound", which does not appear anywhere in this rulebook.
INJURED = "Injured"
SERIOUS_INJURY = "Serious Injury"
OUT_OF_ACTION = "Out of Action"

INJURY_SEVERITY = {INJURED: 0, SERIOUS_INJURY: 1, OUT_OF_ACTION: 2}

# One entry per face of the die. See the module docstring for provenance.
INJURY_FACES: tuple[str, ...] = (
    INJURED, INJURED,
    SERIOUS_INJURY, SERIOUS_INJURY, SERIOUS_INJURY,
    OUT_OF_ACTION,
)

# Shots generated per face, and whether the face also carries the ammo symbol.
# The ammo face shows a bullet hole too, so it still scores a shot.
FIREPOWER_FACES: tuple[tuple[int, bool], ...] = (
    (1, True),    # ammo symbol: a shot, and an Out of Ammo check
    (1, False),
    (1, False),
    (2, False),
    (2, False),
    (3, False),
)

# The book gives these exactly: two Hit faces, four arrows (page 32).
#
# The arrows are not compass points. A dice lands in whatever rotation it lands
# in and the arrow is read as it lies on the table, so the direction it gives is
# continuous over the full circle -- which is why ``scatter`` rolls a bearing in
# degrees rather than picking one of four headings. The Hit face carries a small
# arrow of its own, so it has a bearing too, for the rules that ask for one.
SCATTER_FACES: tuple[str, ...] = ("Hit", "Hit", "Arrow", "Arrow", "Arrow", "Arrow")

# The symbol moulded on each face, for drawing it rather than spelling it out.
INJURY_SYMBOLS: dict[str, str] = {
    INJURED: "cross",          # a medical cross with a droplet
    SERIOUS_INJURY: "starburst",  # a splintered impact burst
    OUT_OF_ACTION: "skull",
}


def face_symbol(kind: str, face) -> str:
    """The symbol to draw for one rolled face.

    ``kind`` is "injury", "firepower" or "scatter"; ``face`` is an element of
    that dice's result. Shot counts come back as "holes1".."holes3" so the eye
    can draw the bullet holes the die actually shows instead of a numeral.
    """
    if kind == "injury":
        return INJURY_SYMBOLS.get(face, "skull")
    if kind == "firepower":
        return "ammo" if face == "ammo" else f"holes{face}"
    if kind == "scatter":
        return "crosshair" if face == "Hit" else "arrow"
    if kind == "bearing":
        return "arrow"
    return "pip"


def _roll(faces, rng: random.Random | None = None):
    return (rng or random).choice(faces)


def d6(count: int = 1, rng: random.Random | None = None) -> list[int]:
    r = rng or random
    return [r.randint(1, 6) for _ in range(max(1, count))]


def d3(count: int = 1, rng: random.Random | None = None) -> list[int]:
    """A D3 is a D6 halved, rounding fractions up (page 32)."""
    return [(value + 1) // 2 for value in d6(count, rng)]


def d66(count: int = 1, rng: random.Random | None = None) -> list[int]:
    """Two D6 read as tens then units, giving 11-66 (page 32).

    This is not a 66-sided die: 17 or 20 can never come up, which is exactly why
    treating "D66" as ``randint(1, 66)`` would be wrong.
    """
    r = rng or random
    return [r.randint(1, 6) * 10 + r.randint(1, 6) for _ in range(max(1, count))]


def firepower(count: int = 1, rng: random.Random | None = None) -> dict:
    """Roll Firepower dice for a Rapid Fire (X) attack."""
    rolls = [_roll(FIREPOWER_FACES, rng) for _ in range(max(1, count))]
    shots = sum(shot for shot, _ in rolls)
    ammo_checks = sum(1 for _, ammo in rolls if ammo)
    return {
        "faces": [("ammo" if ammo else str(shot)) for shot, ammo in rolls],
        "shots": shots,
        "ammo_checks": ammo_checks,
    }


def _bearing(rng: random.Random | None = None) -> int:
    """A heading in degrees clockwise from 12 o'clock."""
    return (rng or random).randrange(360)


def scatter(count: int = 1, rng: random.Random | None = None) -> dict:
    """Roll Scatter dice, each giving a face and the bearing it points in."""
    rolls = [_roll(SCATTER_FACES, rng) for _ in range(max(1, count))]
    bearings = [_bearing(rng) for _ in rolls]
    return {
        "faces": rolls,
        "bearings": bearings,
        "hits": sum(1 for f in rolls if f == "Hit"),
    }


def bearing_name(degrees: float) -> str:
    """A spoken compass reading for a bearing, for the dice roll's text."""
    points = ("12", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11")
    hour = points[int((degrees % 360) / 30 + 0.5) % 12]
    return f"{hour} o'clock"


def injury(lethality: int = 1, rng: random.Random | None = None) -> dict:
    """Roll Injury dice for a wound that took a model to zero Wounds.

    ``lethality`` is the weapon's L characteristic and sets how many dice are
    rolled. The attacker then picks ONE result to apply, so every face rolled is
    returned along with the most and least severe available -- the choice
    belongs to the player, not to this function.
    """
    count = max(1, lethality)
    faces = [_roll(INJURY_FACES, rng) for _ in range(count)]
    ranked = sorted(faces, key=lambda f: INJURY_SEVERITY[f])
    return {
        "faces": faces,
        "dice": count,
        "most_severe": ranked[-1],
        "least_severe": ranked[0],
        "chooser": "attacker",
    }
