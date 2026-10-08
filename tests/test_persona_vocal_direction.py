"""The delivery-tag instructions follow the voice (run: python -m pytest tests).

Teaching the brain to write "[whispers]" is only worth prompt tokens when the model
behind the voice performs tags. On any other model core.tts strips them again before
synthesis, so the instructions would be pure cost — and the skull would spend its
replies writing stage direction nobody ever hears."""

import pathlib

import pytest

from core import config, persona

OMEGA7 = pathlib.Path(__file__).parent.parent / "personalities" / "omega7"


def _prompt() -> str:
    return persona.build_system_prompt({}, "Omega-7")


def test_the_block_is_omitted_on_a_model_that_cannot_perform_tags(monkeypatch):
    monkeypatch.setattr(config, "ELEVENLABS_MODEL", "eleven_turbo_v2")
    prompt = _prompt()
    assert "VOCAL DIRECTION" not in prompt
    assert "[whispers]" not in prompt


def test_the_block_is_included_on_a_tag_capable_model(monkeypatch):
    monkeypatch.setattr(config, "ELEVENLABS_MODEL", "eleven_v4_turbo")
    prompt = _prompt()
    assert "VOCAL DIRECTION" in prompt
    assert "[whispers]" in prompt


def test_disabling_tags_also_drops_the_block(monkeypatch):
    monkeypatch.setattr(config, "ELEVENLABS_MODEL", "eleven_v4_turbo")
    monkeypatch.setattr(config, "ELEVENLABS_AUDIO_TAGS", False)
    assert "VOCAL DIRECTION" not in _prompt()


@pytest.mark.parametrize("model", ["eleven_turbo_v2", "eleven_v4_turbo"])
def test_no_token_or_blank_run_is_left_behind(monkeypatch, model):
    monkeypatch.setattr(config, "ELEVENLABS_MODEL", model)
    prompt = _prompt()
    assert "{vocal_direction}" not in prompt
    assert "{skull_name}" not in prompt
    assert "{owner_section}" not in prompt
    # Dropping a block mid-template must not leave a gap where it was.
    assert "\n\n\n" not in prompt


def test_the_block_file_ships_with_the_personality():
    # The prompt silently loses its delivery vocabulary if this file goes missing,
    # which is the kind of thing only a test notices.
    block = (OMEGA7 / "vocal_direction.txt").read_text()
    assert "VOCAL DIRECTION" in block
    assert "[whispers]" in block


def test_a_personality_without_the_block_is_unaffected(monkeypatch):
    # jax has no {vocal_direction} token and no block file; its prompt must still
    # build, with or without a tag-capable model.
    monkeypatch.setattr(config, "ELEVENLABS_MODEL", "eleven_v4_turbo")
    prompt = persona.build_system_prompt({}, "Jax")
    assert prompt.strip()
    assert "{vocal_direction}" not in prompt
