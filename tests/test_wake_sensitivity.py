"""Resolving a spoken sensitivity request to a wake-word threshold.

Sensitivity is the inverse of the threshold, so "listen harder" must lower the
number. The arithmetic sits in config because two callers reach it — the spoken
intent and the model's tool — and the model's version used to be the only one,
which is how "increase your wake word sensitivity" came to be acknowledged in
character twice without the threshold ever moving (run: python -m pytest tests).
"""
import pytest

from core import config


@pytest.fixture(autouse=True)
def _restore(monkeypatch):
    # Never write the real .env from a test.
    writes = {}
    monkeypatch.setattr(config, "_update_env_var", lambda k, v: writes.__setitem__(k, v))
    monkeypatch.setattr(config, "WAKE_WORD_THRESHOLD", 0.65)
    return writes


def test_more_sensitive_lowers_the_threshold(_restore):
    config.adjust_wake_word_sensitivity(direction="more")
    assert config.WAKE_WORD_THRESHOLD == 0.55
    assert _restore["WAKE_WORD_THRESHOLD"] == "0.55"


def test_less_sensitive_raises_it(_restore):
    config.adjust_wake_word_sensitivity(direction="less")
    assert config.WAKE_WORD_THRESHOLD == 0.75


def test_steps_accumulate_from_wherever_it_is():
    for _ in range(3):
        config.adjust_wake_word_sensitivity(direction="more")
    assert config.WAKE_WORD_THRESHOLD == pytest.approx(0.35)


def test_it_will_not_step_below_the_noise_floor():
    for _ in range(10):
        config.adjust_wake_word_sensitivity(direction="more")
    assert config.WAKE_WORD_THRESHOLD == config.WAKE_THRESHOLD_FLOOR


def test_it_will_not_step_past_the_ceiling():
    for _ in range(10):
        config.adjust_wake_word_sensitivity(direction="less")
    assert config.WAKE_WORD_THRESHOLD == config.WAKE_THRESHOLD_CEILING


def test_an_explicit_threshold_is_clamped_not_rejected():
    config.adjust_wake_word_sensitivity(threshold=0.01)
    assert config.WAKE_WORD_THRESHOLD == config.WAKE_THRESHOLD_FLOOR
    config.adjust_wake_word_sensitivity(threshold=9.0)
    assert config.WAKE_WORD_THRESHOLD == config.WAKE_THRESHOLD_CEILING


def test_a_named_level_is_absolute_and_clear_of_the_floor():
    config.adjust_wake_word_sensitivity(level="high")
    high = config.WAKE_WORD_THRESHOLD
    assert high < config.WAKE_THRESHOLD_DEFAULT
    # At the floor itself the room's own noise wakes the skull, so "high" stays above it.
    assert high > config.WAKE_THRESHOLD_FLOOR
    config.adjust_wake_word_sensitivity(level="default")
    assert config.WAKE_WORD_THRESHOLD == config.WAKE_THRESHOLD_DEFAULT


def test_the_spoken_line_states_the_number_that_was_written():
    line = config.adjust_wake_word_sensitivity(direction="more")
    assert "0.55" in line
    assert "more sensitive" in line


def test_an_empty_request_reports_without_changing_anything(_restore):
    line = config.adjust_wake_word_sensitivity()
    assert config.WAKE_WORD_THRESHOLD == 0.65
    assert "0.65" in line and _restore == {}


# ── microphone sensitivity ────────────────────────────────────────────────────

@pytest.fixture
def mic(monkeypatch):
    writes = {}
    monkeypatch.setattr(config, "_update_env_var", lambda k, v: writes.__setitem__(k, v))
    monkeypatch.setattr(config, "SILENCE_THRESHOLD", config.SILENCE_THRESHOLD_DEFAULT)
    return writes


def test_a_more_sensitive_microphone_lowers_the_silence_floor(mic):
    config.adjust_mic_sensitivity(direction="more")
    assert config.SILENCE_THRESHOLD == config.SILENCE_THRESHOLD_DEFAULT - config.MIC_SENSITIVITY_STEP
    assert mic["SILENCE_THRESHOLD"] == str(config.SILENCE_THRESHOLD)


def test_the_microphone_floor_and_ceiling_hold(mic):
    for _ in range(20):
        config.adjust_mic_sensitivity(direction="more")
    assert config.SILENCE_THRESHOLD == config.SILENCE_THRESHOLD_FLOOR
    for _ in range(40):
        config.adjust_mic_sensitivity(direction="less")
    assert config.SILENCE_THRESHOLD == config.SILENCE_THRESHOLD_CEILING


def test_the_microphone_threshold_is_a_whole_number(mic):
    config.adjust_mic_sensitivity(threshold=137.6)
    assert config.SILENCE_THRESHOLD == 138
    assert isinstance(config.SILENCE_THRESHOLD, int)


def test_named_microphone_levels_stay_inside_the_bounds(mic):
    for level in ("high", "medium", "low"):
        config.adjust_mic_sensitivity(level=level)
        assert config.SILENCE_THRESHOLD_FLOOR <= config.SILENCE_THRESHOLD <= config.SILENCE_THRESHOLD_CEILING


def test_the_microphone_line_states_what_was_written(mic):
    line = config.adjust_mic_sensitivity(direction="less")
    assert str(config.SILENCE_THRESHOLD) in line and "less sensitive" in line
