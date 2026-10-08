"""Carrying a speaker across a turn too short to identify.

A barged-in command loses its front to the summons, so it often lands under
speaker_id's 0.8 s minimum and the owner silently becomes "Unknown voice"
mid-conversation. The carry-forward fills that gap without ever overriding a
real identification (run on the Pi: python -m pytest tests).
"""
import time

import pytest

m = pytest.importorskip("core.main")  # needs sounddevice (run on the Pi)


@pytest.fixture(autouse=True)
def _reset():
    m._last_identified = None
    yield
    m._last_identified = None


def test_a_positive_identification_passes_through_and_is_remembered():
    assert m._carry_speaker_forward("Sean") == "Sean"
    assert m._last_identified[0] == "Sean"


def test_an_unknown_turn_reuses_the_last_identified_speaker():
    m._carry_speaker_forward("Sean")
    assert m._carry_speaker_forward(None) == "Sean"


def test_a_different_speaker_always_wins_over_the_carry():
    m._carry_speaker_forward("Sean")
    assert m._carry_speaker_forward("Justin") == "Justin"
    assert m._carry_speaker_forward(None) == "Justin"


def test_the_carry_expires():
    m._carry_speaker_forward("Sean")
    m._last_identified = ("Sean", time.time() - m.SPEAKER_CARRY_SECS - 1)
    assert m._carry_speaker_forward(None) is None


def test_unknown_with_no_history_stays_unknown():
    assert m._carry_speaker_forward(None) is None
