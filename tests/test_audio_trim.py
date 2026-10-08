"""Dropping the head of a barged-in capture before the voice is scored.

A barged-in command is recorded while the reply is still playing, so the front of
the capture holds whatever the echo canceller could not subtract of the skull's own
voice. The recogniser averages over every frame it is given, so that residue dragged
a clean 2.6 s of the owner's voice down to an LLR of 0.69 against a 0.94 threshold
(run on the Pi: python -m pytest tests).
"""
import pytest

audio = pytest.importorskip("core.audio")  # needs sounddevice (run on the Pi)

RATE = 48000
_BYTES_PER_SEC = RATE * audio.CHANNELS * 2  # int16


@pytest.fixture
def one_second():
    return b"\x01\x02" * (RATE * audio.CHANNELS)


def test_the_requested_head_is_removed(one_second):
    trimmed = audio.drop_leading(one_second, RATE, 0.3)
    assert len(one_second) - len(trimmed) == int(0.3 * RATE) * audio.CHANNELS * 2


def test_trimming_nothing_leaves_the_audio_alone(one_second):
    assert audio.drop_leading(one_second, RATE, 0.0) == one_second


def test_a_capture_shorter_than_the_trim_is_left_alone(one_second):
    # Better to score a contaminated clip than to hand the recogniser nothing.
    assert audio.drop_leading(one_second, RATE, 2.0) == one_second
    assert audio.drop_leading(one_second, RATE, 1.0) == one_second


def test_a_negative_trim_is_not_an_invitation_to_slice_from_the_end(one_second):
    assert audio.drop_leading(one_second, RATE, -0.5) == one_second


def test_the_trim_lands_on_a_sample_boundary(one_second):
    for secs in (0.1, 0.3, 0.33333, 0.7):
        trimmed = audio.drop_leading(one_second, RATE, secs)
        assert len(trimmed) % (audio.CHANNELS * 2) == 0
