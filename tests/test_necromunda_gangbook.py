"""Loading a gang book that was read off the page rather than parsed.

A gang book is almost entirely datasheets and multi-column grids: a statline of
thirteen values, a Skill Access table of fighters against six Skill Sets, an
Equipment List where the same item costs a different amount to each gang. Every
one of those is a shape that came back interleaved or missing when the core
rulebook was read by column geometry, so this book is transcribed by eye and
this module only loads it. What is pinned here is the loading, not any parsing.
"""

import pytest

from games.necromunda import gangbook


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
