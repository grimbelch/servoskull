import io
import sys
import wave
import subprocess
from skull import config

# ── ElevenLabs (cloud, quota-limited) ─────────────────────────────────────────

def _elevenlabs_client():
    from elevenlabs.client import ElevenLabs
    return ElevenLabs(api_key=config.ELEVENLABS_API_KEY)

_el_client = None

def _synthesize_elevenlabs(text: str) -> bytes:
    global _el_client
    if _el_client is None:
        _el_client = _elevenlabs_client()
    audio_iter = _el_client.text_to_speech.convert(
        voice_id=config.ELEVENLABS_VOICE_ID,
        text=text,
        model_id="eleven_turbo_v2",
        output_format="pcm_16000",
    )
    pcm = b"".join(audio_iter)
    return _pcm_to_wav(pcm, sample_rate=16000)


# ── Piper (local, free) ────────────────────────────────────────────────────────

_piper_voice = None

def _get_piper_voice():
    global _piper_voice
    if _piper_voice is None:
        from piper.voice import PiperVoice
        _piper_voice = PiperVoice.load(config.PIPER_MODEL_PATH)
    return _piper_voice

def _synthesize_piper(text: str) -> bytes:
    import wave as _wave
    voice = _get_piper_voice()
    buf = io.BytesIO()
    with _wave.open(buf, "wb") as wf:
        voice.synthesize_wav(text, wf)
    return buf.getvalue()


# ── Public API ─────────────────────────────────────────────────────────────────

# Once ElevenLabs reports its quota is gone, stop calling it for the rest of the
# session — every further phrase goes straight to the local Piper voice instead
# of paying the network round-trip just to get another quota error.
_elevenlabs_exhausted = False


def _is_quota_error(e: Exception) -> bool:
    msg = str(e).lower()
    return any(s in msg for s in ("quota", "payment", "unauthorized", "401", "402"))


def synthesize(text: str) -> bytes:
    """Convert text to WAV bytes using the configured TTS backend.

    When the backend is ElevenLabs but its quota is exhausted (or it otherwise
    fails), fall back to the local Piper model so the skull keeps talking — just
    in its local voice rather than going silent.
    """
    global _elevenlabs_exhausted
    if config.TTS_BACKEND.lower() == "elevenlabs" and not _elevenlabs_exhausted:
        try:
            return _synthesize_elevenlabs(text)
        except Exception as e:
            if _is_quota_error(e):
                print("[tts] ElevenLabs quota exhausted — falling back to local "
                      "Piper voice for the rest of this session.")
                _elevenlabs_exhausted = True
            else:
                print(f"[tts] ElevenLabs error ({e}) — falling back to local Piper voice.")
    return _synthesize_piper(text)


def synthesize_elevenlabs(text: str) -> bytes:
    """Synthesize specifically in the ElevenLabs voice, ignoring TTS_BACKEND.

    Used for the prerecorded canned phrases, which are always spoken in the
    ElevenLabs voice. Raises on failure (no Piper fallback) so the caller can avoid
    caching a fallback under an ElevenLabs key. This touches no global state, so it
    is safe to call concurrently (the canned phrases preload in a background thread
    while the boot phrase synthesizes on the main thread)."""
    return _synthesize_elevenlabs(text)


def synthesize_fallback(text: str) -> None:
    """Last-resort system TTS (ElevenLabs quota exhausted, Piper unavailable)."""
    if sys.platform == "darwin":
        subprocess.run(["say", "-r", "175", text], timeout=60)
    elif sys.platform == "win32":
        # Windows SAPI via PowerShell — no extra dependency. Text is piped in on
        # stdin so it needs no shell-quoting or escaping.
        script = (
            "Add-Type -AssemblyName System.Speech; "
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            "$s.Rate = 1; "
            "$s.Speak([Console]::In.ReadToEnd())"
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            input=text,
            text=True,
            timeout=60,
        )
    else:
        subprocess.run(["espeak", "-s", "150", text], timeout=60)


def _pcm_to_wav(pcm: bytes, sample_rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()
