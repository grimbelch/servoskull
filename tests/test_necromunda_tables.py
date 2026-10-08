"""Random tables and equipment (run: python -m pytest tests).

A table stored as prose is a wall of text and "I rolled 54" cannot be answered.
Rows keep their span parsed, so resolving a roll is an index lookup.
"""

import pytest

from games.necromunda.extract import equipment, randtables


# ── reading a roll off the page ───────────────────────────────────────────────

@pytest.mark.parametrize("label,span", [
    ("11", (11, 11)),
    ("54", (54, 54)),
    ("21-26", (21, 26)),      # the spans the Lasting Injury table prints
    ("63-65", (63, 65)),
    ("6+", (6, 999)),         # an open top end
    ("31–46", (31, 46)),  # printed with an en dash
])
def test_a_printed_roll_becomes_a_span(label, span):
    assert randtables._parse_roll(label) == span


@pytest.mark.parametrize("text", ["Lesson Learnt:", "D66", "", "by 1."])
def test_prose_is_not_a_roll(text):
    assert randtables._parse_roll(text) is None


# ── reading a price off a heading ─────────────────────────────────────────────

@pytest.mark.parametrize("title,name,creds,tp", [
    ("BIO-BOOSTER 25 CREDITS - TP 0", "BIO-BOOSTER", 25, 0),
    ("SERVO-HARNESS - PARTIAL 100 CREDITS - TP 2", "SERVO-HARNESS - PARTIAL", 100, 2),
    ("MESH ARMOUR 40 CREDITS – TP 0", "MESH ARMOUR", 40, 0),
])
def test_an_item_is_read_from_its_heading(title, name, creds, tp):
    """The name and the price are printed on two lines and joined back up.

    Before they were joined, the price alone became the heading: 23 sections
    across the book were titled "25 CREDITS - TP 0" and the item's own name
    appeared nowhere.
    """
    tree = [{"title": title, "body": "What it does.", "page": 160}]
    item = equipment.extract(None, tree)[0]
    assert item["name"] == name
    assert item["creds"] == creds
    assert item["trading_post"] == tp


def test_a_category_heading_is_not_part_of_the_item_name():
    tree = [{"title": "PERSONAL EQUIPMENT", "body": "", "page": 160},
            {"title": "DROP RIG 10 CREDITS - TP 0", "body": "x", "page": 160}]
    items = equipment.extract(None, tree)
    assert len(items) == 1
    assert items[0]["name"] == "DROP RIG"
    assert items[0]["category"] == "personal"


def test_a_section_with_no_price_is_not_equipment():
    tree = [{"title": "MOVEMENT", "body": "A model moves.", "page": 69}]
    assert equipment.extract(None, tree) == []


# ── resolving a roll ──────────────────────────────────────────────────────────

@pytest.fixture()
def table_db(tmp_path, monkeypatch):
    from core import config
    from games.necromunda import db as necro_db

    monkeypatch.setattr(config, "data_path", lambda name: tmp_path / name)
    necro_db._DB_PATH = None
    conn = necro_db.connect()
    with conn:
        book = conn.execute(
            "INSERT INTO rulebooks (slug, title, page_offset) VALUES"
            " ('t','Test Rulebook',1)").lastrowid
        table = conn.execute(
            "INSERT INTO rule_tables (rulebook_id, slug, title, dice, page)"
            " VALUES (?,?,?,?,?)",
            (book, "lasting-injury", "LASTING INJURY TABLE", "D66", 79)).lastrowid
        for ordinal, (label, lo, hi, result) in enumerate([
                ("11", 11, 11, "Lesson Learnt"),
                ("21-26", 21, 26, "Out Cold"),
                ("54", 54, 54, "Spinal Injury"),
                ("66", 66, 66, "Memorable Death")]):
            conn.execute(
                "INSERT INTO rule_table_rows (table_id, ordinal, roll_min,"
                " roll_max, roll_label, result) VALUES (?,?,?,?,?,?)",
                (table, ordinal, lo, hi, label, result))
    conn.close()
    return tmp_path


def test_a_roll_inside_a_span_finds_its_row(table_db):
    """23 is not printed; it falls inside 21-26 and must still resolve."""
    from games.necromunda import rules_tools
    assert "Out Cold" in rules_tools.table_result("lasting injury", 23)
    assert "Out Cold" in rules_tools.table_result("lasting injury", 26)
    assert "Spinal Injury" in rules_tools.table_result("lasting injury", 54)


def test_a_roll_the_table_cannot_produce_is_refused(table_db):
    from games.necromunda import rules_tools
    out = rules_tools.table_result("lasting injury", 99)
    assert "not on the" in out


def test_the_whole_table_can_be_listed(table_db):
    from games.necromunda import rules_tools
    out = rules_tools.table_result("lasting injury", None)
    for expected in ("Lesson Learnt", "Out Cold", "Spinal Injury", "Memorable Death"):
        assert expected in out


def test_rolling_the_table_uses_its_own_dice(table_db):
    """A D66 table must be rolled on two D6, never 1-66 flat."""
    from games.necromunda import rules_tools
    for _ in range(25):
        out = rules_tools.roll_on_table("lasting injury")
        assert "D66" in out or "not on the" in out


def test_an_unknown_table_lists_what_there_is(table_db):
    from games.necromunda import rules_tools
    assert "LASTING INJURY TABLE" in rules_tools.table_result("flibberty", 3)


def test_a_cited_table_names_the_printed_page(table_db):
    from games.necromunda import rules_tools
    assert "p78" in rules_tools.table_result("lasting injury", 54)


# ── a partly recovered table ──────────────────────────────────────────────────

def test_a_table_that_misses_results_its_dice_can_roll_is_flagged():
    """A partial table is the dangerous kind.

    Asked for a roll that went missing it answers "not on the table" with as
    much confidence as a real answer, so the gap has to be recorded.
    """
    table = {"dice": "D6", "rows": [
        {"roll_label": "1", "roll_min": 1, "roll_max": 1, "result": "a"},
        {"roll_label": "2", "roll_min": 2, "roll_max": 2, "result": "b"},
        {"roll_label": "3", "roll_min": 3, "roll_max": 3, "result": "c"},
        {"roll_label": "5", "roll_min": 5, "roll_max": 5, "result": "e"}]}
    assert randtables._missing_results(table) == [4, 6]


def test_a_complete_table_is_not_flagged():
    table = {"dice": "D6", "rows": [
        {"roll_label": "1-3", "roll_min": 1, "roll_max": 3, "result": "a"},
        {"roll_label": "4-6", "roll_min": 4, "roll_max": 6, "result": "b"}]}
    assert randtables._missing_results(table) == []


def test_a_d66_table_is_not_expected_to_cover_every_number():
    """D66 tables are legitimately sparse and span ranges."""
    table = {"dice": "D66", "rows": [
        {"roll_label": "11", "roll_min": 11, "roll_max": 11, "result": "a"},
        {"roll_label": "21-26", "roll_min": 21, "roll_max": 26, "result": "b"}]}
    assert randtables._missing_results(table) == []


# ── a printed diagram is not part of the rule ─────────────────────────────────

@pytest.mark.parametrize("line", [
    '~-+--+-+---+--+-+-+-+--+--+-1 ! 6"',
    'l------l----+-- 1------1----+-- f---j-------f-- 6 "',
    '___,___.. +---------t _.. _ --+',
    '9" I', '12" 12"', '-+ -+ --', 'I I', '7-r-',
])
def test_a_deployment_diagram_is_recognised_as_debris(line):
    """The scenario pages print a map beside each result.

    Its rules and hatching come through the text layer. One run was appended to
    a result; another, "9\" I", passed for a heading and titled a table with
    itself, which split the Deployment table's last two results off and then
    blocked them from merging back -- so the table answered "not on the table"
    for a roll of 4 or 6.
    """
    assert randtables._is_rubble(line)


@pytest.mark.parametrize("line", [
    "Sniping Range: The winner of a roll-off chooses a battlefield edge",
    "DEPLOYMENT TABLE",
    "Ambush: The defender's deployment zone is anywhere on the battlefield",
    "Status",
    "Dash",
])
def test_words_are_not_debris(line):
    assert not randtables._is_rubble(line)


def test_results_are_ordered_by_their_roll():
    """The Deployment table is printed two cards to a row across a spread.

    Read in band order its results arrive 1, 2, 3, 5, 4, 6.
    """
    tables = randtables._merge_fragments([{
        "title": "DEPLOYMENT TABLE", "dice": "D6", "columns": ["Deployment", "Zone"],
        "heading": "", "page": 145, "result_x": 107.0,
        "rows": [{"roll_label": str(n), "roll_min": n, "roll_max": n,
                  "result": f"result {n}"} for n in (1, 2, 3, 5, 4, 6)],
    }])
    assert [r["roll_label"] for r in tables[0]["rows"]] == ["1", "2", "3", "4", "5", "6"]
    assert tables[0]["missing"] == []
