"""Necromunda rules extraction and lookup (run: python -m pytest tests).

The column tests use real word positions measured off the printed weapon tables.
They guard the defect that motivated extracting those tables by geometry at all:
in the PDF's text layer an unprinted cell leaves no token, so reading a row as a
flat sequence shifts every later value one column to the left. The autopistol
prints no AP, and a linear read duly reports its Lethality as its AP.

Nothing here needs the source PDF or the built database; the rulebook text is
copyrighted and stays off the repo.
"""


import pytest

from games.necromunda import rules_schema
from games.necromunda.extract import layout, sections, tables

# The printed weapon profile's header positions, as measured across the book.
ANCHORS = [182.3, 210.7, 239.1, 267.2, 295.9, 321.7, 465.5, 493.8]
NAMES = ["SR", "LR", "Str", "AP", "L", "Traits", "Creds", "TP"]

# Autopistol: 4" / 12" / Str 3 / AP not printed / L 1 / Light, Rapid Fire (1).
AUTOPISTOL = [
    (66.0, 92.0, "Autopistol"),
    (185.3, 199.0, '4"'), (211.2, 225.0, '12"'), (244.1, 248.8, "3"),
    (301.2, 305.7, "1"),
    (318.2, 340.0, "Light,"), (343.4, 366.0, "Rapid"), (369.6, 385.0, "Fire"),
    (387.6, 398.0, "(1)"),
    (468.2, 479.0, "10"), (499.2, 504.0, "0"),
]

# Heavy bolter: every cell printed, and a trait list that reaches past the
# midpoint between the Traits and Creds headers.
HEAVY_BOLTER = [
    (66.0, 89.6, "Heavy"), (93.1, 119.0, "bolter"),
    (182.6, 196.7, '18"'), (210.5, 224.8, '36"'), (244.1, 248.8, "5"),
    (270.7, 278.1, "-2"), (300.7, 305.2, "2"),
    (317.3, 342.9, "Ammo"), (346.6, 365.3, "(3+),"), (369.1, 394.1, "Heavy,"),
    (397.9, 420.1, "Rapid"), (424.3, 438.4, "Fire"), (442.1, 452.6, "(2)"),
    (465.1, 481.1, "100"), (498.7, 503.7, "3"),
]


def cells_for(row, anchors=ANCHORS):
    """Columns as the extractor asks for them: the two cost columns by left edge."""
    cells = layout.columns(row, anchors, None, tables._COST_COLUMNS)
    return dict(zip(NAMES, cells[1:]))


# ── column recovery ───────────────────────────────────────────────────────────

def test_an_unprinted_cell_stays_empty_instead_of_shifting_the_row():
    """The autopistol's AP is blank, so L must read 1 and AP must read nothing.

    This is the whole reason the tables are recovered from geometry. Read as a
    flat token sequence the row is "4\\" 12\\" 3 1 ...", and AP takes the 1.
    """
    cells = cells_for(AUTOPISTOL)
    assert cells["AP"] == ""
    assert cells["L"] == "1"
    assert cells["Str"] == "3"


def test_a_wide_trait_list_does_not_bleed_into_the_cost_column():
    """Traits is free text beside a narrow numeric column.

    "Rapid Fire (2)" reaches past the midpoint between the two headers, so
    assigning each word to its nearest header would file it under Creds and
    report the heavy bolter as costing "Fire (2) 100".
    """
    cells = cells_for(HEAVY_BOLTER)
    assert cells["Traits"] == "Ammo (3+), Heavy, Rapid Fire (2)"
    assert cells["Creds"] == "100"
    assert cells["TP"] == "3"


def test_every_printed_cell_of_a_full_row_is_recovered():
    cells = cells_for(HEAVY_BOLTER)
    assert cells["SR"] == '18"' and cells["LR"] == '36"'
    assert cells["Str"] == "5" and cells["AP"] == "-2" and cells["L"] == "2"
    assert layout.columns(HEAVY_BOLTER, ANCHORS)[0] == "Heavy bolter"


# The worked example in the weaponry chapter is centre aligned: each value's
# centre sits on its header's centre, and the trait text is centred as a block
# so its first word starts left of the Traits header. Measured off that page.
EXAMPLE_ANCHORS = [200.2, 234.3, 268.3, 302.2, 336.4, 404.0, 472.1, 506.1]
EXAMPLE_BOLTGUN = [
    (73.7, 101.9, "Boltgun"),
    (193.4, 206.8, '12"'), (227.0, 240.6, '24"'), (265.9, 270.5, "4"),
    (298.6, 305.4, "-1"), (333.8, 338.2, "2"),
    (378.2, 399.3, "Rapid"), (403.4, 416.6, "Fire"), (420.2, 430.0, "(1)"),
    (467.3, 476.9, "55"), (503.8, 508.1, "2"),
]


def test_a_centre_aligned_table_is_read_correctly_too():
    """The example profile's trait begins left of its own header's centre.

    Claiming each column by its left edge reads "Rapid" as the Lethality, which
    is how this row came out as L='2 Rapid'.
    """
    cells = cells_for(EXAMPLE_BOLTGUN, EXAMPLE_ANCHORS)
    assert cells["L"] == "2"
    assert cells["Traits"] == "Rapid Fire (1)"
    assert cells["Creds"] == "55" and cells["TP"] == "2"
    assert cells["Str"] == "4" and cells["AP"] == "-1"


def test_column_bounds_sit_left_of_their_anchors_and_stay_ordered():
    bounds = layout.column_bounds(ANCHORS)
    assert len(bounds) == len(ANCHORS)
    assert all(b < a for b, a in zip(bounds, ANCHORS))
    assert bounds == sorted(bounds)


# ── anchors ───────────────────────────────────────────────────────────────────

def test_anchor_set_is_unmoved_by_a_dropped_header_token():
    """One page's header is missing L, another's Str; the median absorbs it."""
    assert layout.anchor_set([[295.9, 295.9, 296.1, 295.8]]) == [295.9]
    assert layout.anchor_set([[], [10.0, 12.0, 11.0]]) == [11.0]


# ── name cleanup ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("Heavy stubber*", "Heavy stubber"),
    ("· Heavy bolter'", "Heavy bolter"),
    ('Heavy flamer"', "Heavy flamer"),
    ("Autogun", "Autogun"),
])
def test_footnote_markers_are_stripped_from_names(raw, expected):
    name, _ = tables.clean_name(raw)
    assert name == expected


def test_a_marked_name_records_that_it_was_marked():
    assert tables.clean_name("Heavy stubber*")[1] is True
    assert tables.clean_name("Autogun")[1] is False


# ── contamination flag ────────────────────────────────────────────────────────

def test_a_trait_cell_holding_prose_is_flagged():
    """A few profiles are printed inside body text, not in a table.

    Their widest cell then absorbs the surrounding sentences, and a reader has
    to be able to say so rather than quote it as the printed trait list.
    """
    assert tables.looks_contaminated(
        "Additional When performing a Coup de Grace Attack players have rolled")
    assert not tables.looks_contaminated("Ammo (3+), Heavy, Rapid Fire (2)")
    assert not tables.looks_contaminated("")


# ── section helpers ───────────────────────────────────────────────────────────

def test_a_table_row_is_not_mistaken_for_prose():
    assert sections._is_tabular('8" 24" 3 1 - 20 0')
    assert not sections._is_tabular(
        "Each player rolls a D6, whoever rolls the highest has Priority.")


def test_hyphenated_line_breaks_are_rejoined():
    joined = sections._join_prose(["the model is Seriously In-", "jured instead."])
    assert "Seriously Injured instead." in joined


def test_slugify_makes_a_path_safe_token():
    assert sections.slugify("AUTO/STUB WEAPONS") == "auto-stub-weapons"
    assert sections.slugify("BATTLEFIELD SET-UP & SCENARIOS") == "battlefield-set-up-scenarios"


# ── schema and lookup ─────────────────────────────────────────────────────────

@pytest.fixture()
def rules_db(tmp_path, monkeypatch):
    """A rules database holding one invented weapon, so no book text is needed."""
    from core import config
    from games.necromunda import db as necro_db

    monkeypatch.setattr(config, "data_path", lambda name: tmp_path / name)
    necro_db._DB_PATH = None
    conn = necro_db.connect()
    with conn:
        book = conn.execute(
            "INSERT INTO rulebooks (slug, title, edition, page_offset)"
            " VALUES (?,?,?,?)", ("test-book", "Test Rulebook", "2026", 1)).lastrowid
        conn.execute(
            "INSERT INTO rule_weapons (rulebook_id, slug, name, category, sr_text,"
            " lr_text, str_text, ap_text, lethality_text, creds_text, tp_text,"
            " strength, ap, lethality, creds, trading_post, traits, page)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (book, "test-pistol", "Test pistol", "TEST WEAPONS", '4"', '12"', "3",
             "", "1", "10", "0", 3, None, 1, 10, 0, "Light", 155))
    conn.close()
    return tmp_path


def test_schema_creates_every_content_table(rules_db):
    from games.necromunda import db as necro_db
    conn = necro_db.connect(create=False)
    try:
        present = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()
    for table in rules_schema.CONTENT_TABLES:
        assert table in present


def test_a_blank_cell_is_reported_as_not_printed(rules_db):
    """AP was blank in the book, so it must not be read back as 0."""
    from games.necromunda import rules_tools
    out = rules_tools.weapon_profile("test pistol")
    assert "AP: not printed" in out
    assert "Lethality: 1" in out
    # Cited by the page PRINTED on the page, not the PDF's index: the row is
    # stored at index 155 and the book's own folio there reads 154.
    assert "p154" in out


def test_lethality_lookup_drives_the_injury_roll(rules_db):
    from games.necromunda import rules_tools
    assert rules_tools.weapon_lethality("test pistol") == 1
    assert rules_tools.weapon_lethality("no such weapon") is None


def test_an_unknown_weapon_says_so_rather_than_guessing(rules_db):
    from games.necromunda import rules_tools
    out = rules_tools.weapon_profile("plasma trebuchet")
    assert "No weapon called" in out


def test_lookups_report_a_missing_library_instead_of_creating_one(tmp_path, monkeypatch):
    from core import config
    from games.necromunda import db as necro_db, rules_tools
    from games.necromunda.search import necromunda_rules

    monkeypatch.setattr(config, "data_path", lambda name: tmp_path / "absent.db")
    necro_db._DB_PATH = None
    assert "isn't installed" in necromunda_rules("anything")
    assert "isn't installed" in rules_tools.weapon_profile("boltgun")
    assert not (tmp_path / "absent.db").exists()


def test_search_query_terms_cannot_be_read_as_fts_syntax(rules_db):
    """A question is data, not a query language; quoting it must not error."""
    from games.necromunda.search import necromunda_rules
    for query in ('what about "AP" OR NOT', "NEAR(a b)", "trait*", "a AND"):
        assert isinstance(necromunda_rules(query), str)


def test_reset_rulebook_clears_only_the_named_book(rules_db):
    from games.necromunda import db as necro_db
    conn = necro_db.connect(create=False)
    try:
        with conn:
            rules_schema.reset_rulebook(conn, "test-book")
        assert conn.execute("SELECT COUNT(*) FROM rule_weapons").fetchone()[0] == 0
    finally:
        conn.close()


# ── wrapped trait lists ───────────────────────────────────────────────────────

@pytest.mark.parametrize("fragment", [
    "(3+)",                 # Force Blast's Knockback value, wrapped alone
    "Attack (1),",          # Headbutt's Additional Attack, split mid-trait
    "Melee",
    'Blast (3"/5")',
    "Heavy",
])
def test_a_wrapped_trait_list_continues(fragment):
    assert tables.is_trait_fragment(fragment)


@pytest.mark.parametrize("fragment", [
    "have one or more traits,",   # the body text under the worked example
    "a Fight action, each model",
    "CUNNING",                    # the next section's heading
    "5. Terrify (Double)",        # the next numbered entry
    "steps:",
    "",
])
def test_a_trait_list_ends_at_anything_that_is_not_one(fragment):
    """Accepting any following line swallowed whole columns of the page.

    A Wyrd power's traits ran on into the next power's rules, and a Combat
    skill's into five more skills.
    """
    assert not tables.is_trait_fragment(fragment)


# ── which rows count as profiles ──────────────────────────────────────────────

@pytest.mark.parametrize("label", [
    "Autogun", "Heavy stubber*", "Multi-melta\u2022", "Las cutter",
    "- warp round",          # special ammunition, printed in lower case
    "- photon flash grenades",
])
def test_weapon_names_are_recognised(label):
    assert tables._looks_like_a_name(tables.clean_name(label)[0])


@pytest.mark.parametrize("label", [
    "the weapon cannot be used at that range.",
    "This indicates how many credits it costs to purchase",
    "In the same way as a model, each weapon has its own",
])
def test_body_text_is_not_mistaken_for_a_weapon_name(label):
    assert not tables._looks_like_a_name(tables.clean_name(label)[0])


def test_a_name_is_tested_after_its_footnote_marker_is_stripped():
    """"Multi-melta" carries a printed footnote marker the OCR renders as a dot.

    Testing the raw label dropped the weapon from the book entirely.
    """
    assert tables._looks_like_a_name("Multi-melta\u2022") is False
    assert tables._looks_like_a_name(tables.clean_name("Multi-melta\u2022")[0]) is True


# ── page citations ────────────────────────────────────────────────────────────

def test_a_citation_names_the_printed_page_not_the_pdf_index():
    """The scan's front matter is not counted by the printed folios.

    Citing the index sends a reader to the wrong page of their own copy. The
    offset is measured at ingest from the contents list.
    """
    from games.necromunda.search import printed_page
    book = {"page_offset": 1}
    assert printed_page(78, book) == 77
    assert printed_page(155, book) == 154
    # A book whose scan matches its folios needs no adjustment.
    assert printed_page(78, {"page_offset": 0}) == 78
    # Never below the first page, whatever the offset says.
    assert printed_page(1, {"page_offset": 5}) == 1


def test_contents_entries_are_read_as_title_and_page():
    from games.necromunda.extract import ingest

    class FakePage:
        def __init__(self, text):
            self._text = text

        def get_text(self, _kind):
            return self._text

    class FakeDoc:
        page_count = 1

        def load_page(self, _n):
            return FakePage("CONTENTS\nRules Introduction\n31\n- First Principles\n32\n")

    assert ingest._contents_entries(FakeDoc()) == [
        ("Rules Introduction", 31), ("First Principles", 32)]


# ── orphaned rows ─────────────────────────────────────────────────────────────

def test_dropping_a_stale_table_takes_the_whole_set(tmp_path, monkeypatch):
    """A parent dropped alone leaves its children pointing at nothing.

    The tables are dropped with foreign keys off, because the teardown has to
    survive tables that are already gone -- so no cascade runs. Adding a column
    to `rulebooks` dropped it on its own and orphaned 297 sections and 82
    weapons, which went on answering queries and doubled every lookup.
    """
    from core import config
    from games.necromunda import db as necro_db

    monkeypatch.setattr(config, "data_path", lambda name: tmp_path / name)
    necro_db._DB_PATH = None
    conn = necro_db.connect()
    with conn:
        book = conn.execute(
            "INSERT INTO rulebooks (slug, title) VALUES ('x','X')").lastrowid
        conn.execute("INSERT INTO rule_sections (rulebook_id, level, ordinal,"
                     " doc_order, title) VALUES (?,1,0,0,'T')", (book,))
    # Make `rulebooks` look like an older shape, then reopen.
    conn.execute("ALTER TABLE rulebooks RENAME TO rulebooks_old")
    conn.execute("CREATE TABLE rulebooks (id INTEGER PRIMARY KEY, slug TEXT)")
    conn.execute("INSERT INTO rulebooks (id, slug) SELECT id, slug FROM rulebooks_old")
    conn.execute("DROP TABLE rulebooks_old")
    conn.commit()
    conn.close()

    conn = necro_db.connect()
    try:
        assert conn.execute("SELECT COUNT(*) FROM rule_sections").fetchone()[0] == 0
    finally:
        conn.close()


def test_rows_left_by_a_deleted_rulebook_are_purged_on_open(rules_db, monkeypatch):
    from games.necromunda import db as necro_db, rules_schema

    conn = necro_db.connect(create=False)
    # Foreign keys are on, so an orphan cannot be inserted -- which is why the
    # only way they ever appeared was a parent table dropped with enforcement
    # off. Reproduce that state the same way.
    conn.execute("PRAGMA foreign_keys = OFF")
    with conn:
        conn.execute("INSERT INTO rule_sections (rulebook_id, level, ordinal,"
                     " doc_order, title, body_md) VALUES (99,3,0,0,'GHOST','x')")
        conn.execute("INSERT INTO rule_weapons (rulebook_id, slug, name)"
                     " VALUES (99,'ghost','Ghost gun')")
    assert rules_schema.purge_orphans(conn) >= 2
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM rule_sections WHERE title='GHOST'"
                        ).fetchone()[0] == 0
    conn.close()


def test_a_lookup_never_quotes_another_rulebooks_rows(rules_db):
    """Scoping is what stops a stray row being quoted in the first place."""
    from games.necromunda import db as necro_db, rules_tools

    conn = necro_db.connect(create=False)
    conn.execute("PRAGMA foreign_keys = OFF")
    with conn:
        conn.execute(
            "INSERT INTO rule_weapons (rulebook_id, slug, name, creds_text, page)"
            " VALUES (99,'test-pistol','Test pistol','999',1)")
    conn.close()

    out = rules_tools.weapon_profile("test pistol")
    assert "999" not in out            # the other book's copy is not quoted
    assert out.count("Test pistol") == 1


# ── headings the size floor was hiding ────────────────────────────────────────

def heading_line(text, size, bold=1.0):
    return {"text": text, "size": size, "bold": bold, "display": bold,
            "x0": 60.0, "x1": 300.0, "y": 100.0}


def test_a_step_heading_at_eleven_point_is_a_heading():
    """The book sets the steps of one sequence at both 11pt and 12pt.

    On the Close Combat page "1. DETERMINE WHO CAN FIGHT" is 12pt while
    "2. CHOOSE WEAPONS" is 11pt. A 12pt floor dropped half the steps and buried
    their rules inside whichever section came before them.
    """
    assert layout.is_heading(heading_line("1. DETERMINE WHO CAN FIGHT", 12))
    assert layout.is_heading(heading_line("2. CHOOSE WEAPONS", 11))
    assert layout.is_heading(heading_line("3. DETERMINE ATTACK DICE", 11))


def test_body_text_is_still_not_a_heading_at_that_size():
    """Body is 11pt too, so the floor alone cannot be what separates them."""
    assert not layout.is_heading(heading_line(
        "Each model selects which weapon they will use", 11, bold=0.0))
    assert not layout.is_heading(heading_line("Hand Weapons: If a Fighter", 11,
                                              bold=0.31))


def test_a_heading_split_over_two_lines_is_read_as_one():
    """A heading too long for its column is printed over two or three lines.

    Read separately they become sections called "LINE OF SIGHT &" and "SOLID
    TERRAIN FEATURES", filing the rule under the second half of its own name.
    """
    class FakePage:
        rect = type("R", (), {"width": 568.0, "height": 780.0})()

        def get_text(self, kind):
            if kind == "words":
                return []
            return {"blocks": [{"lines": [
                {"bbox": (60, y, 300, y + 12), "spans": [
                    {"text": t, "size": s, "font": "Arial-BoldMT"}]}
                for t, s, y in (("CORE RULES - MOVEMENT", 16, 55),
                                ("LINE OF SIGHT &", 11, 100),
                                ("SOLID TERRAIN FEATURES", 11, 112),
                                ("A model can see through a gap.", 11, 130))
            ]}]}

    found = sections.page_sections(FakePage(), 36)
    titles = [s["title"] for s in found]
    assert "LINE OF SIGHT & SOLID TERRAIN FEATURES" in titles
    assert "SOLID TERRAIN FEATURES" not in titles
