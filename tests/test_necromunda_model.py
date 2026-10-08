"""The data model the fresh reading of the book called for.

Reading all 114 rules pages turned up three things the schema could not hold:
Territories (a campaign holding with typed Boons), actions (which have a cost
and a status), and the restriction printed on a skill's name. These pin the
parsing of each; none needs the source PDF.
"""

import pytest

from games.necromunda.extract import entries, equipment, territories


# ── cost and restriction are different brackets ───────────────────────────────

@pytest.mark.parametrize("printed,name,cost", [
    ("COUP DE GRACE (SINGLE)", "COUP DE GRACE", "single"),
    ("CHARGE (DOUBLE)", "CHARGE", "double"),
    ("MAINTAIN CONTROL (FREE)", "MAINTAIN CONTROL", "free"),
])
def test_an_actions_cost_is_read_off_its_name(printed, name, cost):
    assert entries.split_cost(printed) == (name, cost)


@pytest.mark.parametrize("printed,name,who", [
    ("CATFALL (FIGHTER OR WALKER ONLY)", "CATFALL", "Fighter or Walker only"),
    ("CLAMBER (FIGHTER ONLY)", "CLAMBER", "Fighter only"),
    ("TRAIN (ANY MODEL)", "TRAIN", "Any Model"),
])
def test_a_restriction_is_read_off_its_name(printed, name, who):
    """Left inside the name, "which skills can a Vehicle take?" cannot be asked."""
    assert entries.split_qualifier(printed) == (name, who)


@pytest.mark.parametrize("printed", ["BLAZE (X+)", 'BLAST (3"/5")', "RAPID FIRE (X)",
                                     "TRANSPORT (X)"])
def test_a_bracketed_value_is_not_a_restriction(printed):
    """A trait's value lives in the same brackets as a restriction would."""
    assert entries.split_qualifier(printed) == (printed, "")
    assert entries.split_cost(printed) == (printed, "")


# ── equipment variants ────────────────────────────────────────────────────────

def test_one_item_with_two_prices_becomes_two_rows():
    """Carapace armour prints Light and Heavy under a single name.

    Read as one price the second is thrown away and the first one's label is
    left stuck on the item's name.
    """
    tree = [{"title": "ARMOUR CARAPACE ARMOUR LIGHT: 100 CREDITS – TP 1"
                      " HEAVY: 140 CREDITS – TP 3",
             "body": "Overlapping plates.", "page": 159}]
    rows = equipment.extract(None, tree)
    assert len(rows) == 2
    assert {r["variant"] for r in rows} == {"Light", "Heavy"}
    assert all(r["base_name"] == "CARAPACE ARMOUR" for r in rows)
    assert sorted(r["creds"] for r in rows) == [100, 140]
    assert sorted(r["trading_post"] for r in rows) == [1, 3]


def test_a_single_priced_item_is_unchanged():
    tree = [{"title": "DROP RIG 10 CREDITS - TP 0", "body": "x", "page": 160}]
    rows = equipment.extract(None, tree)
    assert len(rows) == 1 and rows[0]["variant"] == "" and rows[0]["name"] == "DROP RIG"


def test_an_items_restriction_becomes_a_column():
    tree = [{"title": "HOTSHOT LAS PACK (LAS WEAPONS ONLY) 25 CREDITS - TP 1",
             "body": "x", "page": 162}]
    row = equipment.extract(None, tree)[0]
    assert row["name"] == "HOTSHOT LAS PACK"
    assert "Las Weapons" in row["usable_by"]


# ── territory boons are typed ─────────────────────────────────────────────────

def test_the_boon_types_are_the_ones_the_campaign_rules_name():
    """A gang may take the Recruit Boon INSTEAD of the Income Boon.

    The rules act on the type, so the type has to survive extraction.
    """
    assert territories.BOON_TYPES == ("Income", "Recruit", "Equipment",
                                      "Reputation", "Special")


def test_a_boon_line_is_split_into_type_and_text():
    match = territories._BOON.match(
        "Income: The gang earns 15 credits from this Territory.")
    assert match and match.group(1) == "Income"
    assert match.group(2).startswith("The gang earns 15")


def test_the_cards_boilerplate_is_not_mistaken_for_a_boon():
    assert territories._BOILERPLATE.match("This Territory grants the following Boons:")
    assert territories._BOILERPLATE.match("This Territory has the following battlefield effect:")
    assert not territories._BOILERPLATE.match("Income: The gang earns 15 credits.")


def test_cards_are_split_by_where_their_rules_start_not_their_names():
    """A card's name is centred over it while its rules are flush left.

    The widest blank channel therefore runs between the two centred names and
    sits right of the right-hand card's own text -- which put "Old Ruins" in
    one column and its rules in the other.
    """
    lines = [{"x0": 63.0, "text": "Income: the gang earns 20 credits from this"},
             {"x0": 63.0, "text": "Territory when collecting income each cycle"},
             {"x0": 63.0, "text": "Toxic Vats: during a battle where this one is"},
             {"x0": 296.0, "text": "Income: the gang earns 20 credits from this"},
             {"x0": 296.0, "text": "Territory when collecting income each cycle"},
             {"x0": 296.0, "text": "Scattered Debris: during a battle where this"},
             {"x0": 125.0, "text": "SYNTH STILL"},
             {"x0": 363.0, "text": "OLD RUINS"}]
    split = territories.card_split(lines)
    assert split is not None
    assert 125.0 < split < 296.0     # both names fall on the correct side
    assert 63.0 < split < 363.0
