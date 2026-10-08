"""Weapon traits, skills and conditions (run: python -m pytest tests).

These three tables stood empty because the section extractor could not see
their entries: it looks for chapter headings at 12pt and above, and a trait or
skill is printed at the size of body text, told apart by its FACE. Nothing here
needs the source PDF.
"""

import pytest

from games.necromunda.extract import conditions, entries, layout, skills, traits


def line(text, size=10, bold=1.0, display=None):
    return {"text": text, "size": size, "bold": bold,
            "display": bold if display is None else display,
            "x0": 60.0, "x1": 200.0, "y": 100.0}


# ── recognising a named rule ──────────────────────────────────────────────────

def test_a_name_in_display_type_at_body_size_is_recognised():
    """The whole reason the tables were empty.

    `is_heading` wants 12pt and the word "Bold" in the font; a trait is 10pt
    and on two pages the scan reports its face as Franklin Gothic, which has
    no "Bold" in the name at all.
    """
    assert layout.is_named_entry(line("RAPID FIRE (X)", size=10))
    assert layout.is_named_entry(line("BLAZE (X+)", size=9))
    assert not layout.is_heading(line("RAPID FIRE (X)", size=10))


def test_a_condensed_face_counts_as_display_type():
    """Two pages of traits are reported as Franklin Gothic, not as bold."""
    franklin = line("GRAVITATION PULSE", size=10, bold=0.0, display=1.0)
    assert layout.is_named_entry(franklin)


def test_body_text_is_not_a_name():
    assert not layout.is_named_entry(line("A weapon with this trait", bold=0.0))
    assert not layout.is_named_entry(
        line("If the Wound roll is at least X", bold=0.1, display=0.1))


def test_a_long_qualifier_still_fits_the_name():
    """"5. RAIN OF BLOWS (FIGHTER OR WALKER ONLY)" is 41 characters.

    A 40-character limit dropped it, and that skill set came out one short.
    """
    assert layout.is_named_entry(line("5. RAIN OF BLOWS (FIGHTER OR WALKER ONLY)", size=9))


def test_the_printed_list_number_is_not_part_of_the_name():
    assert entries._clean_name("3. HEADBUTT (FIGHTER ONLY)") == "HEADBUTT (FIGHTER ONLY)"
    assert entries._clean_name("BACKSTAB") == "BACKSTAB"


# ── the sets ──────────────────────────────────────────────────────────────────

def test_this_editions_skill_sets():
    """Seven sets. Ferocity, Leadership and Driving belonged to the old game."""
    assert skills.SKILL_SETS == ("AGILITY", "BRAWN", "COMBAT", "CUNNING",
                                 "SAVANT", "SHOOTING", "INHERENT")
    for gone in ("FEROCITY", "LEADERSHIP", "DRIVING"):
        assert gone not in skills.SKILL_SETS


def test_markers_are_not_rules():
    """The spread after the statuses shows the card markers used to track them."""
    assert conditions._NOT_A_RULE.search("SUPPRESSED MARKER")
    assert conditions._NOT_A_RULE.search("INSANITY TABLE")
    assert not conditions._NOT_A_RULE.search("SUPPRESSED")
    assert not conditions._NOT_A_RULE.search("WEBBED")


def test_a_trait_needs_a_rule_not_just_a_qualifier():
    """Weapon accessories share the traits pages, headed only by a shout."""
    assert traits._HAS_PROSE.search("A weapon with this trait gains...")
    assert not traits._HAS_PROSE.search("(LAS WEAPONS ONLY)")


# ── looking one up ────────────────────────────────────────────────────────────

@pytest.fixture()
def named_db(tmp_path, monkeypatch):
    from core import config
    from games.necromunda import db as necro_db

    monkeypatch.setattr(config, "data_path", lambda name: tmp_path / name)
    necro_db._DB_PATH = None
    conn = necro_db.connect()
    with conn:
        book = conn.execute(
            "INSERT INTO rulebooks (slug, title, page_offset) VALUES"
            " ('t','Test Rulebook',1)").lastrowid
        conn.execute(
            "INSERT INTO rule_traits (rulebook_id, slug, name, takes_value,"
            " description, page) VALUES (?,?,?,?,?,?)",
            (book, "blaze-x", "BLAZE (X+)", 1, "The target catches fire.", 163))
        conn.execute(
            "INSERT INTO rule_skills (rulebook_id, slug, name, skill_set,"
            " description, page) VALUES (?,?,?,?,?,?)",
            (book, "backstab", "BACKSTAB (FIGHTER ONLY)", "Cunning",
             "Gains the Backstab trait.", 152))
        conn.execute(
            "INSERT INTO rule_conditions (rulebook_id, slug, name, kind,"
            " description, page) VALUES (?,?,?,?,?,?)",
            (book, "webbed", "WEBBED", "condition", "The model cannot act.", 49))
    conn.close()
    return tmp_path


def test_a_trait_is_found_despite_its_printed_value(named_db):
    """A weapon prints "Blaze (5+)"; the trait is printed "Blaze (X+)"."""
    from games.necromunda import rules_tools
    assert "catches fire" in rules_tools.named_rule("Blaze (5+)")
    assert "catches fire" in rules_tools.named_rule("blaze")


def test_a_named_rule_says_which_kind_it_is_and_cites_its_page(named_db):
    from games.necromunda import rules_tools
    out = rules_tools.named_rule("webbed")
    assert "condition" in out
    assert "p48" in out          # printed page, not the PDF index


def test_a_skill_reports_its_set(named_db):
    from games.necromunda import rules_tools
    assert "Cunning skill" in rules_tools.named_rule("backstab")


def test_listing_a_skill_set(named_db):
    from games.necromunda import rules_tools
    assert "BACKSTAB" in rules_tools.skills_in_set("cunning")
    assert "sets are" in rules_tools.skills_in_set("ferocity")  # the old game's


def test_an_unknown_name_says_so(named_db):
    from games.necromunda import rules_tools
    assert "No trait, skill or condition" in rules_tools.named_rule("flibbertigibbet")


def test_a_weapons_traits_are_explained_in_full(named_db):
    """A profile that names traits and explains none is half an answer."""
    from games.necromunda import rules_tools
    assert "catches fire" in rules_tools.weapon_traits("Blaze (5+), Unknown Trait")
