"""Omega-7's eye styles and the display's style switching (run: python -m pytest tests)."""

import pytest
from PIL import Image

from personalities.omega7 import display as omega_display
from personalities.omega7 import eyes


@pytest.mark.parametrize("name", list(eyes.STYLES))
def test_every_style_renders_through_blinks_gaze_and_speech(name):
    mod = eyes.STYLES[name]
    bezel = mod.render_bezel()
    mask = Image.new("L", (240, 240), 255)
    for amp, angle, blink, lx, ly in ((0.15, 0, 0, 0, 0), (0.9, 120, 0, -18, 12), (0.3, 0, 0.5, 9, -6), (0.2, 0, 1.0, 0, 0)):
        img = mod.render_frame(bezel, mask, amp, angle, blink, lx, ly, (255, 40, 30))
        assert img.size == (240, 240) and img.mode == "RGB"
    assert 20 <= mod.APERTURE_R <= 110


def test_every_mood_has_its_own_eye():
    from core import mood
    assert set(omega_display.MOOD_EYES) == set(mood.MOODS)
    assert len(set(omega_display.MOOD_EYES.values())) == len(mood.MOODS)


def test_spoken_names_never_collide():
    owners = {}
    for name in eyes.STYLES:
        for phrase in eyes.spoken_names(name):
            assert owners.setdefault(phrase, name) == name, f"'{phrase}' names both {owners[phrase]} and {name}"


@pytest.fixture
def display(monkeypatch, tmp_path):
    from core import config, display
    monkeypatch.setattr(config, "data_path", lambda n: tmp_path / n)
    monkeypatch.setattr(display, "_display_module", omega_display)
    monkeypatch.setattr(display, "_eye_follows_mood", False)
    yield display
    omega_display.set_eye_style(eyes.DEFAULT)


def test_mood_eye_follows_the_disposition_and_is_remembered(display):
    display.set_mood("CONTEMPLATIVE")
    assert display.set_eye_style("mood")
    assert display.get_eye_style() == "mood"
    assert display.get_eye_style_shown() == "contemplative"
    display.set_mood("SUSPICIOUS")
    assert display.get_eye_style_shown() == "suspicious"

    assert display.set_eye_style("auspex")         # a chosen style stops following
    display.set_mood("FERVENT")
    assert display.get_eye_style_shown() == "auspex"

    display.set_eye_style("mood")
    display._eye_follows_mood = False               # as after a restart
    display._restore_eye_style()
    assert display.get_eye_style() == "mood" and display.get_eye_style_shown() == "fervent"


def test_unknown_style_is_refused_and_cycle_wraps(display):
    assert not display.set_eye_style("no_such_eye")
    styles = display.get_eye_styles()
    assert styles[-1] == "mood"
    display.set_eye_style(styles[-1])
    assert display.cycle_eye_style(1) == styles[0]
