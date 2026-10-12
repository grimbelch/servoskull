"""A gang list's own special rules, and the rules printed inside them.

A gang list prints rules that belong to no rule table: Claiming Bounties, a
Gang Legacy, and the "NEW SUBTYPE: RATLING" blocks that introduce a Subtype
along with the rules it carries. All of it was written into rule_gangs and read
back by nothing -- not indexed for search, not reachable by any tool -- so
asking what Sneaking does was answered "the book does not contain it" while the
sentence sat in the database, correctly transcribed. The gap was never in the
reading; it was that nothing could see what had been read.

What is pinned here is reachability: that each of the three ways the question
arrives finds the rule.
"""

import json

import pytest

from games.necromunda import db as necro_db, gangbook, rules_tools, search


# ------------------------------------------------------------- pure logic ---

@pytest.mark.parametrize("printed,expected", [
    ("New Subtype: Ratling", "Ratling"),
    ("NEW SUBTYPE: OGRYN", "OGRYN"),
    ("new subtype:  Beastman ", "Beastman"),
])
def test_a_gang_list_subtype_block_is_recognised(printed, expected):
    found = gangbook._NEW_SUBTYPE.match(printed)
    assert found and found.group(1) == expected


@pytest.mark.parametrize("printed", [
    "Claiming Bounties", "Starting Skills", "Skill Access", "Gang Legacy",
    "Subtype Access",            # near miss: not a block that introduces one
])
def test_an_ordinary_gang_rule_is_not_mistaken_for_a_subtype(printed):
    assert gangbook._NEW_SUBTYPE.match(printed) is None


def test_a_gang_rule_counts_as_a_rule_and_not_as_background():
    """Hits are split into rules and lore; a gang rule is a rule, and read as
    lore it would be reported as the sort of thing that may be invented."""
    assert "gang_rule" in search._RULES_KINDS


def test_the_miss_no_longer_speaks_only_for_the_core_rulebook():
    """Four supplements are held. Telling the reader "the core rulebook does
    not cover it" invited exactly the answer-from-memory it exists to stop."""
    message = search.not_in_book("a weapon called 'renderizer'",
                                 {"title": "Necromunda Skirmish: Core Rulebook"})
    assert "does not contain" in message
    assert "memory" in message.lower()
    assert "supplement" in message.lower()
    assert "core rulebook does not cover" not in message.lower()


# -------------------------------------------------------- against the book ---

@pytest.fixture
def gang_rules_db():
    """The real database, skipped where it has not been built."""
    if not necro_db.db_path().exists():
        pytest.skip("Necromunda rules database is not built on this machine")
    conn = necro_db.connect(create=False)
    try:
        held = conn.execute(
            "SELECT COUNT(*) FROM rule_gangs WHERE special_rules_json NOT IN"
            " ('', '[]')").fetchone()[0]
        if not held:
            pytest.skip("no gang book with special rules is loaded")
    finally:
        conn.close()
    yield


def test_a_subtype_a_gang_list_introduces_is_found_by_the_subtype_lookup(gang_rules_db):
    """Ratling is printed in Gangs of the Underhive, not the core rulebook.
    Scoped to one book the lookup could never reach it."""
    answer = rules_tools.model_subtype("Ratling")
    assert "does not contain" not in answer
    assert "Sneaking" in answer
    assert "Underhive" in answer


def test_a_rule_printed_inside_a_subtype_block_is_found_by_name(gang_rules_db):
    """"What does Sneaking do" goes to the rule lookup, because the player has
    no way of knowing it was printed inside a Subtype block in a gang list."""
    answer = rules_tools.named_rule("Sneaking")
    assert "does not contain" not in answer
    assert "Long Range" in answer


def test_the_rule_is_found_without_being_told_which_gang(gang_rules_db):
    """The question names the rule and never the gang."""
    answer = rules_tools.gang_special_rules("", "Sneaking")
    assert "Venator" in answer
    assert "Long Range" in answer


def test_a_gang_lists_its_own_rules(gang_rules_db):
    answer = rules_tools.gang_special_rules("Venator")
    assert "Claiming Bounties" in answer
    assert "Gang Legacy" in answer


def test_an_unheld_gang_says_so_and_names_what_is_held(gang_rules_db):
    answer = rules_tools.gang_special_rules("Squat Prospectors Of Nowhere")
    assert "is held" in answer
    assert "Venator" in answer


def test_every_gang_rule_reached_the_search_index(gang_rules_db):
    """112 of them were in the database and none were searchable."""
    conn = necro_db.connect(create=False)
    try:
        stored = sum(
            len(json.loads(r[0] or "[]")) for r in
            conn.execute("SELECT special_rules_json FROM rule_gangs"))
        indexed = conn.execute(
            "SELECT COUNT(*) FROM rule_search WHERE kind = 'gang_rule'").fetchone()[0]
    finally:
        conn.close()
    assert stored and indexed == stored
