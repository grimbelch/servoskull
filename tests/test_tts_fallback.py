"""ElevenLabs → Piper fallback rules in core.tts (run: python -m pytest tests)."""

import pytest

from core import config, tts


@pytest.fixture
def voices(monkeypatch):
    calls = {"eleven": 0, "piper": 0}
    eleven = {"error": None}

    def fake_eleven(text):
        calls["eleven"] += 1
        if eleven["error"]:
            raise eleven["error"]
        return b"eleven"

    def fake_piper(text):
        calls["piper"] += 1
        return b"piper"

    monkeypatch.setattr(tts, "_synthesize_elevenlabs", fake_eleven)
    monkeypatch.setattr(tts, "_synthesize_piper", fake_piper)
    monkeypatch.setattr(config, "TTS_BACKEND", "elevenlabs")
    monkeypatch.setattr(tts, "_elevenlabs_exhausted", False)
    monkeypatch.setattr(tts, "_elevenlabs_retry_at", 0.0)
    return calls, eleven


def test_elevenlabs_is_used_when_it_works(voices):
    calls, _ = voices
    assert tts.synthesize("Hello") == b"eleven"
    assert calls == {"eleven": 1, "piper": 0}


def test_network_error_rests_elevenlabs_for_the_cooldown(voices, monkeypatch):
    calls, eleven = voices
    eleven["error"] = ConnectionError("network unreachable")
    assert tts.synthesize("one") == b"piper"
    # The next sentences go straight to Piper without another slow attempt...
    eleven["error"] = None
    assert tts.synthesize("two") == b"piper"
    assert tts.synthesize("three") == b"piper"
    assert calls["eleven"] == 1
    # ...until the cooldown has passed.
    monkeypatch.setattr(tts, "_elevenlabs_retry_at", 0.0)
    assert tts.synthesize("four") == b"eleven"


def test_quota_error_disables_elevenlabs_for_the_session(voices, monkeypatch):
    calls, eleven = voices
    eleven["error"] = RuntimeError("402 payment required: quota exceeded")
    assert tts.synthesize("one") == b"piper"
    eleven["error"] = None
    monkeypatch.setattr(tts, "_elevenlabs_retry_at", 0.0)
    assert tts.synthesize("two") == b"piper"
    assert calls["eleven"] == 1


def test_piper_backend_never_calls_elevenlabs(voices, monkeypatch):
    calls, _ = voices
    monkeypatch.setattr(config, "TTS_BACKEND", "piper")
    assert tts.synthesize("Hello") == b"piper"
    assert calls["eleven"] == 0
