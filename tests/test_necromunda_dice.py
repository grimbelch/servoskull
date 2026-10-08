"""Necromunda Skirmish dice (run: python -m pytest tests).

These pin the things the 2026 rulebook states outright, and guard the two
mistakes the previous implementation made: calling an Injury result a "Flesh
Wound" (a term absent from this edition) and totalling a roll the rules say is
a choice.
"""

import random

import pytest

from games.necromunda import dice


def seeded(seed=11):
    return random.Random(seed)


# ── D66, D3 ───────────────────────────────────────────────────────────────────

def test_d66_is_two_dice_read_as_tens_and_units():
    """A D66 yields 11-66 with no 0, 7, 8 or 9 in either digit.

    Rolling randint(1, 66) instead would produce 17 or 20, which two D6 cannot.
    """
    values = dice.d66(2000, seeded())
    assert min(values) == 11 and max(values) == 66
    assert len(set(values)) == 36
    for value in values:
        assert value // 10 in range(1, 7)
        assert value % 10 in range(1, 7)


def test_d3_halves_a_d6_rounding_up():
    assert sorted(set(dice.d3(500, seeded()))) == [1, 2, 3]


# ── Injury ────────────────────────────────────────────────────────────────────

def test_injury_results_use_this_editions_names():
    """Injured, not Flesh Wound: the old term is nowhere in the 2026 rulebook."""
    assert set(dice.INJURY_FACES) == {
        dice.INJURED, dice.SERIOUS_INJURY, dice.OUT_OF_ACTION}
    assert "Flesh Wound" not in dice.INJURY_FACES
    faces = dice.injury(6, seeded())["faces"]
    assert all(f in dice.INJURY_FACES for f in faces)


def test_injury_rolls_one_die_per_point_of_lethality():
    for lethality in (1, 2, 3, 5):
        result = dice.injury(lethality, seeded())
        assert result["dice"] == lethality
        assert len(result["faces"]) == lethality


def test_injury_offers_a_choice_rather_than_a_tally():
    """The attacker applies ONE of the dice, so the roll reports the options.

    The previous implementation counted how many of each result came up, which
    answers a question the rule does not ask.
    """
    result = dice.injury(4, seeded())
    assert result["chooser"] == "attacker"
    severity = dice.INJURY_SEVERITY
    assert severity[result["most_severe"]] >= severity[result["least_severe"]]
    assert result["most_severe"] in result["faces"]
    assert result["least_severe"] in result["faces"]


def test_injury_lethality_below_one_still_rolls_a_die():
    assert dice.injury(0, seeded())["dice"] == 1


# ── Scatter, Firepower ────────────────────────────────────────────────────────

def test_scatter_has_two_hit_faces_and_four_arrows():
    """The rulebook gives this one exactly (page 32)."""
    assert len(dice.SCATTER_FACES) == 6
    assert sum(1 for f in dice.SCATTER_FACES if f == "Hit") == 2
    assert len([f for f in dice.SCATTER_FACES if f != "Hit"]) == 4


def test_scatter_gives_a_bearing_over_the_whole_circle():
    """A dice is read at the rotation it landed in, so direction is continuous.

    Snapping it to four compass points throws away most of the answer: the
    template could end up anywhere on the circle, not only north of the target.
    """
    result = dice.scatter(400, seeded())
    assert len(result["bearings"]) == 400
    assert all(0 <= b < 360 for b in result["bearings"])
    # Every quadrant should come up over that many rolls.
    quadrants = {b // 90 for b in result["bearings"]}
    assert quadrants == {0, 1, 2, 3}
    assert len(set(result["bearings"])) > 100


def test_a_hit_face_still_carries_a_bearing():
    """The Hit symbol incorporates its own small arrow (page 32)."""
    result = dice.scatter(30, seeded())
    assert len(result["bearings"]) == len(result["faces"])


@pytest.mark.parametrize("degrees,expected", [
    (0, "12 o'clock"), (90, "3 o'clock"), (180, "6 o'clock"),
    (270, "9 o'clock"), (359, "12 o'clock"), (31, "1 o'clock"),
])
def test_a_bearing_reads_as_a_clock_face(degrees, expected):
    assert dice.bearing_name(degrees) == expected


def test_firepower_reports_shots_and_ammo_checks():
    result = dice.firepower(8, seeded())
    assert len(result["faces"]) == 8
    assert result["shots"] >= 8  # every face yields at least one shot
    assert result["ammo_checks"] == sum(1 for f in result["faces"] if f == "ammo")


def test_firepower_ammo_face_also_scores_a_shot():
    ammo_faces = [shot for shot, ammo in dice.FIREPOWER_FACES if ammo]
    assert ammo_faces and all(shot >= 1 for shot in ammo_faces)
