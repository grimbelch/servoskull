"""The explicit-mood-request path.

This matters more than it looks: shift_mood is described to the model as a tool
to use sparingly, so when the matcher misses, the model does not fall back to
calling it — it narrates a disposition change that never happened, and the eye
design and iris colour then contradict what it just said.
"""
import pytest

from core.brain import _mood_intent


@pytest.mark.parametrize("said, want", [
    # The one that failed on the device: heard as "mode", and "change to" is not
    # contiguous, so neither half of the old trigger list matched.
    ("Change mode to contemplative.", "CONTEMPLATIVE"),
    ("change mood to contemplative", "CONTEMPLATIVE"),
    ("switch to vigilant mode", "VIGILANT"),
    ("set your disposition to melancholic", "MELANCHOLIC"),
    ("go back to dutiful", "DUTIFUL"),
    ("be more fervent", "FERVENT"),
    ("change your temperament to suspicious", "SUSPICIOUS"),
    ("shift mode to melancholy", "MELANCHOLIC"),
    ("turn your mood to vigilant", "VIGILANT"),
])
def test_explicit_requests_are_recognised(said, want):
    assert _mood_intent(said) == want


@pytest.mark.parametrize("said", [
    "what mode are you in",            # a question, no mood named
    "tell me about the contemplative orders of Mars",   # mood word, no request
    "the enemy is vigilant",
    "",
])
def test_passing_mentions_do_not_shift_the_mood(said):
    assert _mood_intent(said) is None


def test_every_mood_is_reachable_by_name():
    from core import mood
    for m in mood.all_moods():
        assert _mood_intent(f"change mode to {m.lower()}") == m
