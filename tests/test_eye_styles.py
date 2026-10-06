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
    monkeypatch.setattr(display, "_eye_shuffles", False)
    monkeypatch.setattr(display, "_mood_name", "DUTIFUL")
    yield display
    omega_display.set_eye_style(eyes.DEFAULT)


def test_shuffle_picks_the_mood_eye_a_third_of_the_time_and_never_repeats():
    import random
    from core.display import pick_eye_style
    styles = list(eyes.STYLES)
    rng = random.Random(1)
    picks = [pick_eye_style(styles, "suspicious", "auspex", rng) for _ in range(6000)]
    assert 0.30 < picks.count("suspicious") / len(picks) < 0.37
    assert "auspex" not in picks                       # the eye already showing is never redrawn
    others = set(styles) - {"suspicious", "auspex"}
    assert set(picks) == others | {"suspicious"}       # every other design turns up
    assert pick_eye_style(["cog"], None, "cog", rng) == "cog"
    # already wearing the mood's eye: the shuffle still changes it
    assert all(pick_eye_style(styles, "suspicious", "suspicious", rng) != "suspicious" for _ in range(200))


def test_shuffle_redraws_on_mood_change_and_is_remembered(display):
    assert display.set_eye_style("shuffle")
    assert display.get_eye_style() == "shuffle"
    seen = {display.get_eye_style_shown()}
    for mood in ("SUSPICIOUS", "FERVENT", "MELANCHOLIC", "VIGILANT", "CONTEMPLATIVE", "DUTIFUL") * 3:
        before = display.get_eye_style_shown()
        display.set_mood(mood)
        assert display.get_eye_style_shown() != before   # each new mood brings a new design
        seen.add(display.get_eye_style_shown())
    assert len(seen) > 3

    before = display.get_eye_style_shown()
    display.set_mood("DUTIFUL")                          # same mood again: no redraw
    assert display.get_eye_style_shown() == before

    display._eye_shuffles = False                        # as after a restart
    display._restore_eye_style()
    assert display.get_eye_style() == "shuffle"


def test_a_chosen_style_stays_put(display):
    assert display.set_eye_style("auspex")
    display.set_mood("FERVENT")
    display._shuffle_eye("back from screensaver")
    assert display.get_eye_style() == display.get_eye_style_shown() == "auspex"


def test_unknown_style_is_refused_and_cycle_wraps(display):
    assert not display.set_eye_style("no_such_eye")
    styles = display.get_eye_styles()
    assert styles[-1] == "shuffle"
    display.set_eye_style(styles[-1])
    assert display.cycle_eye_style(1) == styles[0]
