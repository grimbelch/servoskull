"""ElevenLabs v3/v4 audio tags in core.tts (run: python -m pytest tests).

The persona writes delivery direction as "[whispers]". A tag-capable model must
receive it; anything else (older models, Piper, the transcript's own command
tokens) must never have it read aloud."""

import pytest

from core import config, tts


@pytest.fixture
def tagging(monkeypatch):
    monkeypatch.setattr(config, "ELEVENLABS_MODEL", "eleven_v4_turbo")
    monkeypatch.setattr(config, "ELEVENLABS_AUDIO_TAGS", True)


def test_tag_capable_models_are_recognised(tagging):
    assert tts.audio_tags_supported("eleven_v4_turbo")
    assert tts.audio_tags_supported("eleven_v4")
    assert tts.audio_tags_supported("eleven_v3_conversational")
    assert not tts.audio_tags_supported("eleven_flash_v2_5")
    assert not tts.audio_tags_supported("eleven_turbo_v2")
    assert not tts.audio_tags_supported("")


def test_tags_are_off_when_disabled_or_model_is_old(monkeypatch):
    monkeypatch.setattr(config, "ELEVENLABS_MODEL", "eleven_v4_turbo")
    monkeypatch.setattr(config, "ELEVENLABS_AUDIO_TAGS", False)
    assert not tts.audio_tags_supported()
    monkeypatch.setattr(config, "ELEVENLABS_AUDIO_TAGS", True)
    assert tts.audio_tags_supported()
    monkeypatch.setattr(config, "ELEVENLABS_MODEL", "eleven_flash_v2_5")
    assert not tts.audio_tags_supported()


def test_tags_survive_for_a_tag_capable_model():
    assert tts._preprocess_text(
        "[whispers] The Emperor hears you, Master.", keep_audio_tags=True
    ) == "[whispers] The Emperor hears you, Master."
    # Combinations and multi-word directions are allowed, and so are several tags.
    assert tts._preprocess_text(
        "[whispering, reverent] Praise him. [grimly] The heretic is logged.",
        keep_audio_tags=True,
    ) == "[whispering, reverent] Praise him. [grimly] The heretic is logged."


def test_tags_are_stripped_by_default():
    assert tts._preprocess_text("[whispers] The Emperor hears you.") == "The Emperor hears you."


def test_command_tokens_are_stripped_even_with_tags_kept():
    for command in ("[SPOTIFY: imperial march]", "[SPOTIFY_PAUSE]", "[SPOTIFY_TRANSFER: laptop]"):
        assert tts._preprocess_text(
            f"{command}\n[solemn] As you command.", keep_audio_tags=True
        ) == "[solemn] As you command."


def test_narration_and_markdown_still_go():
    # A long asterisked description is narration, not a delivery note.
    assert tts._preprocess_text(
        "*the lenses flare a baleful red* Compliance.", keep_audio_tags=True
    ) == "Compliance."
    # Brackets that are not tag-shaped (citations, upper case, colons) are not tags.
    assert tts._preprocess_text(
        "The rule is clear [1] and binding.", keep_audio_tags=True
    ) == "The rule is clear and binding."
    assert tts._preprocess_text(
        "**WEATHER:** [curious] Rain, Master.", keep_audio_tags=True
    ) == "[curious] Rain, Master."


def test_short_stage_directions_are_promoted_to_tags():
    assert tts._preprocess_text(
        "*sighs* Organic inefficiency again.", keep_audio_tags=True
    ) == "[sighs] Organic inefficiency again."
    # Without tag support the same line loses the direction entirely, as before.
    assert tts._preprocess_text("*sighs* Organic inefficiency again.") == "Organic inefficiency again."


def test_a_promoted_tag_does_not_leave_a_space_before_punctuation():
    assert tts._preprocess_text(
        "This unit obeys *quietly*, Master.", keep_audio_tags=True
    ) == "This unit obeys [quietly], Master."


def test_a_tag_alone_is_not_speech():
    # has_speech gates what gets sent for synthesis, so a sentence that is only a
    # direction is skipped rather than voiced.
    assert not tts.has_speech("[sighs]")
    assert not tts.has_speech("[SPOTIFY_SKIP]")
    assert tts.has_speech("[sighs] As you will.")


def test_elevenlabs_receives_the_tags(monkeypatch, tagging):
    sent = {}

    class _FakeTTS:
        def convert(self, **kwargs):
            sent.update(kwargs)
            return [b""]

    monkeypatch.setattr(tts, "_elevenlabs_client", lambda: type("C", (), {"text_to_speech": _FakeTTS()})())
    monkeypatch.setattr(config, "ELEVENLABS_VOICE_ID", "voice-1")
    tts._synthesize_elevenlabs("[ominously] The Omnissiah is watching.")
    assert sent["text"] == "[ominously] The Omnissiah is watching."
    assert sent["model_id"] == "eleven_v4_turbo"

    monkeypatch.setattr(config, "ELEVENLABS_MODEL", "eleven_flash_v2_5")
    tts._synthesize_elevenlabs("[ominously] The Omnissiah is watching.")
    assert sent["text"] == "The Omnissiah is watching."


def test_piper_never_speaks_a_tag(monkeypatch):
    spoken = {}

    class _Voice:
        def synthesize_wav(self, text, wf):
            spoken["text"] = text
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)

    monkeypatch.setattr(tts, "_get_piper_voice", lambda: _Voice())
    tts._synthesize_piper("[whispers] The Emperor protects.")
    assert spoken["text"] == "The Emperor protects."


# ── Voice settings (stability / similarity) ───────────────────────────────────

@pytest.fixture
def capture_convert(monkeypatch):
    """A fake ElevenLabs client that records the request kwargs."""
    sent = {}

    class _FakeTTS:
        def convert(self, **kwargs):
            sent.clear()
            sent.update(kwargs)
            return [b""]

    monkeypatch.setattr(tts, "_elevenlabs_client", lambda: type("C", (), {"text_to_speech": _FakeTTS()})())
    monkeypatch.setattr(config, "ELEVENLABS_VOICE_ID", "voice-1")
    monkeypatch.setattr(config, "ELEVENLABS_MODEL", "eleven_v4_turbo")
    return sent


def _settings_dict(settings):
    """The fake client receives either a VoiceSettings model or the plain dict."""
    return settings if isinstance(settings, dict) else settings.__dict__


def test_unset_voice_settings_are_not_sent(capture_convert, monkeypatch):
    # Sending nothing is not the same as sending the defaults: it leaves the voice's
    # own dashboard settings in force, which is where a tuned voice is tuned.
    monkeypatch.setattr(config, "ELEVENLABS_STABILITY", None)
    monkeypatch.setattr(config, "ELEVENLABS_SIMILARITY", None)
    tts._synthesize_elevenlabs("Compliance.")
    assert "voice_settings" not in capture_convert


def test_set_voice_settings_are_sent(capture_convert, monkeypatch):
    monkeypatch.setattr(config, "ELEVENLABS_STABILITY", 0.35)
    monkeypatch.setattr(config, "ELEVENLABS_SIMILARITY", 0.8)
    tts._synthesize_elevenlabs("Compliance.")
    sent = _settings_dict(capture_convert["voice_settings"])
    assert sent["stability"] == 0.35
    assert sent["similarity_boost"] == 0.8


def test_a_partial_override_leaves_the_other_to_the_voice(capture_convert, monkeypatch):
    monkeypatch.setattr(config, "ELEVENLABS_STABILITY", 0.2)
    monkeypatch.setattr(config, "ELEVENLABS_SIMILARITY", None)
    tts._synthesize_elevenlabs("Compliance.")
    sent = _settings_dict(capture_convert["voice_settings"])
    assert sent["stability"] == 0.2
    assert sent.get("similarity_boost") is None


def test_style_and_speed_are_never_sent(capture_convert, monkeypatch):
    # Eleven v4 dropped both; pacing comes from the script and the tags instead.
    monkeypatch.setattr(config, "ELEVENLABS_STABILITY", 0.5)
    monkeypatch.setattr(config, "ELEVENLABS_SIMILARITY", 0.5)
    tts._synthesize_elevenlabs("Compliance.")
    sent = _settings_dict(capture_convert["voice_settings"])
    assert sent.get("style") in (None, 0)
    assert sent.get("speed") in (None, 1.0)


@pytest.mark.parametrize("raw,expected", [
    ("", None), ("   ", None), ("0.35", 0.35), ("0", 0.0), ("1", 1.0),
    ("1.5", None), ("-0.1", None), ("creative", None),
])
def test_voice_setting_parsing(monkeypatch, raw, expected):
    monkeypatch.setitem(config.PERSONALITY, "elevenlabs_stability", raw)
    monkeypatch.setattr(config, "_cfg", lambda name, default="": default, raising=False)
    assert config._voice_setting("ELEVENLABS_STABILITY", "elevenlabs_stability") == expected
