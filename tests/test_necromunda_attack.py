"""Resolving a Necromunda attack step by step (run: python -m pytest tests).

The sequence is the one the core rulebook prints: a Hit roll, then Resolve Hits
as Wound, Save and Inflict Damage (p76-77). These pin the arithmetic and the
terseness of the report -- the skull is an arbiter calling numbers, not a
narrator.
"""

import random

import pytest

from games.necromunda import attack, dice


def seeded(seed=3):
    return random.Random(seed)


# ── the Strength vs Toughness table ───────────────────────────────────────────

@pytest.mark.parametrize("strength,toughness,needed", [
    (8, 4, 2),   # twice the Toughness or greater
    (9, 4, 2),
    (4, 3, 3),   # greater than
    (3, 3, 4),   # equal to
    (3, 4, 5),   # lower than
    (2, 4, 6),   # half the Toughness or lower
    (1, 4, 6),
])
def test_the_wound_table_is_the_printed_one(strength, toughness, needed):
    assert attack.wound_target(strength, toughness) == needed


def test_doubled_strength_beats_merely_greater():
    """S8 against T4 is both "twice or greater" and "greater"; the table means 2+.

    Checking "greater than" first would quietly cost every heavy weapon a point.
    """
    assert attack.wound_target(8, 4) == 2
    assert attack.wound_target(7, 4) == 3


# ── the sequence stops where the rules stop it ────────────────────────────────

def test_a_miss_ends_the_attack():
    result = attack.resolve(shots=1, ballistic_skill=6, strength=4, toughness=3,
                            save=5, rng=random.Random(2))
    if result["outcome"] == "missed":
        assert [s["name"] for s in result["steps"]] == ["hit"]


def test_an_attack_that_wounds_nothing_stops_at_the_wound_roll():
    # Strength 1 against Toughness 6 needs a 6; with a certain hit and a seed
    # that rolls low, the sequence must stop there.
    for seed in range(40):
        result = attack.resolve(shots=1, ballistic_skill=2, strength=1,
                                toughness=6, save=4, rng=random.Random(seed))
        names = [s["name"] for s in result["steps"]]
        if result["outcome"] == "no wounds":
            assert names == ["hit", "wound"]
            return
    pytest.fail("no seed produced a failed wound roll")


def test_a_saved_wound_does_no_damage():
    for seed in range(60):
        result = attack.resolve(shots=1, ballistic_skill=2, strength=8,
                                toughness=3, ap=0, save=2, rng=random.Random(seed))
        if result["outcome"] == "all saved":
            assert [s["name"] for s in result["steps"]] == ["hit", "wound", "save"]
            return
    pytest.fail("no seed produced a successful save")


def test_armour_piercing_is_applied_to_the_save_roll():
    """AP modifies the dice, so a -4 weapon beats a 4+ save every time."""
    result = attack.resolve(shots=4, ballistic_skill=2, strength=8, toughness=3,
                            ap=-4, save=4, lethality=1, rng=seeded())
    save_step = next(s for s in result["steps"] if s["name"] == "save")
    assert save_step["passed"] == 0


def test_a_target_with_no_save_skips_the_save_roll():
    result = attack.resolve(shots=2, ballistic_skill=2, strength=8, toughness=3,
                            save=None, lethality=1, rng=seeded())
    assert "save" not in [s["name"] for s in result["steps"]]


# ── injury ────────────────────────────────────────────────────────────────────

def test_injury_dice_are_only_rolled_at_zero_wounds():
    """A Wound is lost first; the Injury dice come when the last one goes."""
    tough = attack.resolve(shots=1, ballistic_skill=2, strength=8, toughness=3,
                           save=None, lethality=2, wounds=3, rng=seeded())
    assert "injury" not in [s["name"] for s in tough["steps"]]
    assert tough["wounds_left"] == 2

    frail = attack.resolve(shots=1, ballistic_skill=2, strength=8, toughness=3,
                           save=None, lethality=2, wounds=1, rng=seeded())
    assert "injury" in [s["name"] for s in frail["steps"]]


def test_the_number_of_injury_dice_is_the_weapons_lethality():
    for lethality in (1, 2, 3):
        result = attack.resolve(shots=1, ballistic_skill=2, strength=8,
                                toughness=3, save=None, lethality=lethality,
                                wounds=1, rng=seeded())
        step = next(s for s in result["steps"] if s["name"] == "injury")
        assert len(step["injury"]["faces"]) == lethality


def test_the_attack_reports_the_worst_injury_available():
    result = attack.resolve(shots=1, ballistic_skill=2, strength=8, toughness=3,
                            save=None, lethality=3, wounds=1, rng=seeded())
    step = next(s for s in result["steps"] if s["name"] == "injury")
    severity = dice.INJURY_SEVERITY
    assert result["outcome"] == step["injury"]["most_severe"]
    assert all(severity[f] <= severity[result["outcome"]]
               for f in step["injury"]["faces"])


# ── the report ────────────────────────────────────────────────────────────────

def test_the_report_is_one_short_line_per_step():
    """The whole point: an arbiter calls the numbers rather than narrating.

    What this replaced ran to two hundred words of prose for a single roll.
    """
    result = attack.resolve(shots=3, ballistic_skill=4, strength=4, toughness=3,
                            ap=-1, save=5, lethality=2, rng=seeded())
    lines = attack.narration(result).splitlines()
    assert len(lines) == len(result["steps"])
    for line in lines:
        assert len(line) < 110
    assert len(attack.narration(result)) < 400


def test_the_report_names_the_number_that_was_needed():
    """A ruling you cannot check is worth little."""
    result = attack.resolve(shots=2, ballistic_skill=4, strength=4, toughness=3,
                            ap=0, save=5, lethality=1, rng=seeded())
    text = attack.narration(result)
    assert "4+" in text and "3+" in text


# ── what the eye plays ────────────────────────────────────────────────────────

def test_each_rolled_step_becomes_a_roll_on_the_eye():
    result = attack.resolve(shots=3, ballistic_skill=4, strength=4, toughness=3,
                            ap=-1, save=5, lethality=2, wounds=1, rng=seeded())
    steps = attack.display_steps(result)
    assert steps
    for step in steps:
        assert step["kind"] in ("d6", "injury")
        assert step["faces"]
        assert step["hold"] > 0


def test_the_injury_step_shows_injury_symbols_not_pips():
    result = attack.resolve(shots=1, ballistic_skill=2, strength=8, toughness=3,
                            save=None, lethality=3, wounds=1, rng=seeded())
    last = attack.display_steps(result)[-1]
    assert last["kind"] == "injury"
    assert set(last["faces"]) <= {"cross", "starburst", "skull"}
    assert last["chosen"] >= 0


# ── the active game decides which dice are on the table ───────────────────────

def dice_tools(game):
    from core import brain
    names = [t["name"] for t in brain.get_active_tools_for_game(game)]
    return {n for n in names if "roll" in n or "attack" in n}


def test_necromunda_is_offered_only_necromundas_own_dice():
    """Another game's attack sequence is the wrong arithmetic for this one.

    A Necromunda attack was being rolled with roll_dice, the 40k hit/wound/save
    sequence, because that tool was offered whatever was being played.
    """
    tools = dice_tools("necromunda")
    assert "necromunda_attack" in tools
    assert "roll_necromunda_dice" in tools
    assert "roll_dice" not in tools        # the 40k sequence
    assert "roll_epic_dice" not in tools   # Epic's firefights


def test_other_games_are_not_offered_necromundas_dice():
    """The gate has to hold both ways: Injury dice are not a 40k concept."""
    for game in ("warhammer 40k", "netepic", "whfrp"):
        assert "roll_necromunda_dice" not in dice_tools(game)
        assert "necromunda_attack" not in dice_tools(game)


def test_each_game_keeps_its_own_attack_roller():
    assert "roll_dice" in dice_tools("warhammer 40k")
    assert "roll_epic_dice" in dice_tools("netepic")
    assert "whfrp_resolve_attack" in dice_tools("whfrp")


def test_a_plain_dice_roll_is_still_available_everywhere():
    """"Roll a d20" should work whatever is on the table."""
    for game in ("necromunda", "warhammer 40k", "whfrp"):
        assert "roll_standard_dice" in dice_tools(game)


# ── the wound table as a lookup ───────────────────────────────────────────────

@pytest.mark.parametrize("strength,toughness,need", [
    (8, 4, 2), (9, 4, 2), (5, 4, 3), (4, 4, 4), (3, 4, 5), (2, 4, 6),
    (2, 5, 6), (1, 2, 6), (3, 5, 5), (6, 3, 2),
])
def test_the_wound_table_is_a_lookup_not_a_judgement(strength, toughness, need):
    """"What do I need to wound T4 with S3?" is the commonest question asked.

    The doubled and halved cases are checked before the simple comparisons: a
    Strength of 8 against Toughness 4 is both "twice or greater" and
    "greater", and the table means the former.
    """
    assert attack.wound_target(strength, toughness) == need


def test_every_strength_and_toughness_pair_matches_the_printed_table():
    def printed(s, t):
        if s >= 2 * t:
            return 2
        if s > t:
            return 3
        if s == t:
            return 4
        if 2 * s > t:
            return 5
        return 6
    assert all(attack.wound_target(s, t) == printed(s, t)
               for s in range(1, 11) for t in range(1, 11))
