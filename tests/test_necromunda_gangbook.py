"""Loading a gang book that was read off the page rather than parsed.

A gang book is almost entirely datasheets and multi-column grids: a statline of
thirteen values, a Skill Access table of fighters against six Skill Sets, an
Equipment List where the same item costs a different amount to each gang. Every
one of those is a shape that came back interleaved or missing when the core
rulebook was read by column geometry, so this book is transcribed by eye and
this module only loads it. What is pinned here is the loading, not any parsing.
"""

import pytest

from games.necromunda import db as necro_db, gangbook


@pytest.fixture
def gangbook_db():
    """The real database, skipped where it has not been built."""
    if not necro_db.db_path().exists():
        pytest.skip("Necromunda rules database is not built on this machine")
    conn = necro_db.connect(create=False)
    try:
        if conn is None or not conn.execute(
                "SELECT count(*) FROM rule_gangs").fetchone()[0]:
            pytest.skip("no gang book is loaded")
    finally:
        if conn is not None:
            conn.close()
    yield


@pytest.mark.parametrize("printed,model_type,subtypes", [
    ("Fighter (Leader, Pious)", "Fighter", "Leader, Pious"),
    ("Fighter (Ganger, Pious, Specialist)", "Fighter", "Ganger, Pious, Specialist"),
    ("Fighter (Beast, Brute, Flying, Wyrd)", "Fighter", "Beast, Brute, Flying, Wyrd"),
    ("Fighter (Champion, Loner)", "Fighter", "Champion, Loner"),
])
def test_a_printed_type_splits_into_model_type_and_subtypes(printed, model_type, subtypes):
    """A datasheet prints "Fighter (Leader, Pious)" in one cell.

    Left whole, "which of my Fighters are Pious?" cannot be asked, and the
    Cawdor gang rules turn on exactly that count.
    """
    assert gangbook.split_type(printed) == (model_type, subtypes)


def test_a_type_with_no_brackets_is_left_alone():
    assert gangbook.split_type("Vehicle") == ("Vehicle", "")
    assert gangbook.split_type("") == ("", "")


def test_the_transcription_is_looked_for_beside_the_book_not_in_the_repo():
    """It is the book's own text, so it lives outside version control."""
    where = gangbook.books_dir("/x/necromunda/rules/manuals/core.pdf")
    assert where.name == gangbook.GANGS_DIRNAME
    assert "manuals" not in where.parts


def test_a_missing_transcription_is_not_an_error():
    """Without it the gang tables are empty and the lookup says the gang is
    not installed -- which is the right answer, and better than a guess."""
    assert gangbook.available("/nowhere/at/all/manuals/core.pdf") == []


# ── more than one book ────────────────────────────────────────────────────────

def test_a_lookup_spans_every_book_and_prefers_the_core_one(gangbook_db):
    """A gang's own weapons and wargear are in its supplement.

    Every lookup was written when there was one book and scoped itself to that
    book's id, so the whole gang book was invisible to them: an Executioner's
    axe came back as "the core rulebook does not contain a weapon called that"
    while the row sat in the database. Where a name is in both books the core
    rulebook still wins, because that is the general rule and the gang book
    only ever adds to it.
    """
    from games.necromunda import rules_tools
    gang_only = rules_tools.weapon_profile("executioner's axe")
    assert "does not contain" not in gang_only
    assert "Gangs of the Underhive" in gang_only

    shared = rules_tools.weapon_profile("boltgun")
    assert "Core Rulebook" in shared


def test_a_gang_fighter_is_found_and_an_absent_gang_is_refused(gangbook_db):
    from games.necromunda import rules_tools
    found = rules_tools.fighter_profile("Cawdor Word-Keeper")
    assert "115 credits" in found
    missing = rules_tools.fighter_profile("Sky Cutter Pilot")
    assert "memory" in missing.lower()
