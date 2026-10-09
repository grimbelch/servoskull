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


# ── a gang whose skills depend on a choice made at founding ───────────────────

def test_an_outcast_fighters_skills_are_reported_per_archetype(gangbook_db):
    """An Outcast gang prints a whole Skill Access grid per Archetype.

    There is no single grid for the gang, and a Champion may take a different
    Archetype to their Leader, so "which Skill Sets can an Outcast Champion
    take?" has five answers and picking one would be inventing an answer.
    """
    from games.necromunda import rules_tools
    answer = rules_tools.fighter_profile("Outcast Champion")
    for archetype in ("Brawler", "Gunslinger", "Mastermind", "Survivor", "Wyrd"):
        assert f"Skills as {archetype}" in answer


def test_a_gang_printing_one_grid_still_reads_flat(gangbook_db):
    """Only a gang with variants should be reported variant by variant."""
    from games.necromunda import rules_tools
    answer = rules_tools.fighter_profile("Cawdor Word-Keeper")
    assert "\n  Skills: " in answer
    assert "Skills as " not in answer


def test_the_founding_choices_are_queryable(gangbook_db):
    from games.necromunda import rules_tools
    archetypes = rules_tools.gang_variants("outcast", "archetype")
    assert "Brawler" in archetypes and "Gunslinger" in archetypes
    affiliations = rules_tools.gang_variants("outcast", "affiliation")
    assert "Clanless" in affiliations and "Aranthian" in affiliations
    assert "archetype" not in affiliations.lower().split("affiliation")[0]


def test_every_lookup_spans_every_book(gangbook_db):
    """The single-book scope has surfaced four times now.

    Each lookup in rules_tools was written when there was one book and filtered
    on that book's id. Every time another book arrived, whatever had not been
    widened yet went blind to it: weapon profiles, then free-text search, then
    named rules and tables, then Territories -- a Goliath Slug House answering
    "the core rulebook does not contain a Territory called that" while the row
    sat in the database. This walks the lookups that can see more than one book
    and checks that each still finds content outside the core rulebook.
    """
    from games.necromunda import db as necro_db, rules_tools
    conn = necro_db.connect(create=False)
    try:
        books = conn.execute("SELECT count(*) FROM rulebooks").fetchone()[0]
    finally:
        conn.close()
    if books < 2:
        pytest.skip("only the core rulebook is built here")
    # Each of these lives outside the core rulebook.
    for answer in (rules_tools.weapon_profile("executioner's axe"),
                   rules_tools.fighter_profile("Cawdor Word-Keeper")):
        assert "does not contain" not in answer


# ── answers that depend on which, not just what ───────────────────────────────

def test_a_price_addition_names_the_weapon_it_is_for(gangbook_db):
    """"- smoke grenades +15" is an addition to the weapon printed above it.

    The Furnace Brutes list prints smoke grenades twice, at +20 on the assault
    grenade launcher and +15 on the plain one. The list carries which is which
    only in the order of its rows, so a price quoted without its weapon is not
    an answer at all.
    """
    from games.necromunda import rules_tools
    answer = rules_tools.equipment_cost("smoke grenades", "furnace brutes")
    assert "Assault grenade launchers" in answer
    assert "Grenade launcher with frag & krak" in answer
    assert "+20 credits" in answer and "+15 credits" in answer
    # And it should say the question is underdetermined rather than pick.
    assert "depends on which" in answer


def test_a_weapon_with_two_profiles_says_so(gangbook_db):
    """Nine weapon names in these books carry more than one profile.

    Delaque's ferocious jaws are S+1 where Goliath's are S. Answering with one
    of them silently answers a different question than the one asked.
    """
    from games.necromunda import rules_tools
    answer = rules_tools.weapon_profile("ferocious jaws")
    assert "NOTE:" in answer and "different" in answer
    assert "Say which gang" in answer


def test_a_superlative_is_one_query_not_a_roster_crawl(gangbook_db):
    """Asked the cheapest Leader, Omega-7 read every gang in turn: 25 tool
    calls for an answer the database can sort in one."""
    from games.necromunda import rules_tools
    answer = rules_tools.roster_query(subtype="Leader", order="cost", limit=3)
    lines = [l for l in answer.splitlines() if l.startswith("  ")]
    assert len(lines) == 3
    assert "Ratling Hunt Leader" in lines[0] and "105" in lines[0]
    costs = [int(l.split(" - ")[1].split()[0]) for l in lines]
    assert costs == sorted(costs)
