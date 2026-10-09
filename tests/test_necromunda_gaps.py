"""What Omega-7 does when the book does not have the answer.

The failure this guards against is not an empty answer, it is a confident
invented one. The core rulebook deliberately leaves out every gang's own
fighters, weapons and wargear (it says so on p154), and those are exactly the
things a player asks about -- so a miss has to say so loudly enough that the
model does not reach for its own memory instead.
"""

import pytest

from games.necromunda import search


@pytest.mark.parametrize("query,gang", [
    ("goliath forge born stats", "goliath"),
    ("what does an Escher Death Maiden cost", "escher"),
    ("Van Saar rad cleanser", "van saar"),
    ("Orlock road sergeant", "orlock"),
    ("palanite enforcer subjugator", "palanite enforcer"),
    ("corpse grinder cult skinner", "corpse grinder"),
    ("ironhead squat digger", "ironhead squat"),
])
def test_a_question_about_a_gang_is_recognised(query, gang):
    """The longest name wins, so "palanite enforcer" is not read as
    "enforcer": both are eight characters and tuple order would decide it."""
    assert search.names_a_gang(query) == gang


@pytest.mark.parametrize("query", [
    "what does Blaze do", "how does a Charge action work",
    "lasting injury table", "how do I wound",
])
def test_an_ordinary_rules_question_is_not_mistaken_for_a_gang_one(query):
    assert search.names_a_gang(query) == ""


def test_the_miss_tells_the_reader_not_to_invent_one():
    """Addressed to the model as much as to the player."""
    book = {"title": "Necromunda Skirmish: Core Rulebook"}
    message = search.not_in_book("a weapon called 'renderizer'", book)
    assert "does not contain" in message
    assert "memory" in message.lower()
    assert "supplement" in message.lower()


def test_every_gang_in_the_showcase_is_known():
    """The showcase names the gangs whose supplements exist; a question about
    any of them is the moment memory is most likely to be reached for."""
    for gang in ("goliath", "escher", "orlock", "van saar", "cawdor",
                 "delaque", "palanite", "corpse grinder", "ironhead",
                 "ash waste", "malstrain", "spyrer"):
        assert gang in search.GANGS
