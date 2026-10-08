import io
import re
import sys
import time
import wave
import subprocess
from core import config

# ── ElevenLabs (cloud, quota-limited) ─────────────────────────────────────────

# Eleven v3/v4 read bracketed "audio tags" as performance direction rather than as
# words: "[whispers] The Emperor hears you." is spoken in a whisper, and the
# direction carries forward until the next tag. They are not a fixed vocabulary —
# any short lowercase direction works, and combinations like "[whispering,
# reverent]" are allowed — so rather than keep an allowlist of tags we recognise
# their *shape*. Every other bracketed token (the [SPOTIFY: …] command family,
# citation markers, stray brackets) is still stripped so it is never spoken.
# The directions the skull is told to use live in personalities/*/persona.txt.
_AUDIO_TAG = re.compile(r"\[([a-z][a-z \-,']{0,38})\]")
# Older models (flash/turbo/multilingual) have no notion of tags and would read the
# bracket contents aloud, so for those they are stripped like any other bracket.
_AUDIO_TAG_MODELS = ("eleven_v3", "eleven_v4")
# A stage direction the brain writes as "*sighs*" means the same thing as the tag,
# so a short one is promoted rather than dropped; "*the lenses dim*" is narration
# about the skull, not a delivery note, and is too long to qualify.
_STAGE_DIRECTION = re.compile(r"\*([a-z][a-z \-,']{0,24})\*")


def audio_tags_supported(model_id: str | None = None) -> bool:
    """True if the ElevenLabs model in play performs audio tags (and they're enabled)."""
    model = (model_id if model_id is not None else config.ELEVENLABS_MODEL) or ""
    return bool(config.ELEVENLABS_AUDIO_TAGS) and model.lower().startswith(_AUDIO_TAG_MODELS)


def _preprocess_text(text: str, keep_audio_tags: bool = False) -> str:
    """Preprocess text for TTS: strip stage directions/actions, Markdown formatting, and brackets so descriptions and symbols aren't spoken aloud.

    With `keep_audio_tags` (ElevenLabs v3/v4 only) tag-shaped brackets survive as
    performance direction and short asterisked stage directions are promoted into
    them; everything else is stripped exactly as it was before."""
    if not text:
        return ""
    # Strip leading markdown category prefixes like "**WEATHER:**" or "**SUMMARY:**"
    text = re.sub(r"^\s*\*{0,2}[A-Z\s]{2,15}:\*{0,2}\s*", "", text)
    tags: list[str] = []
    if keep_audio_tags:
        text = _STAGE_DIRECTION.sub(lambda m: f"[{m.group(1)}]", text)
        # Park the tags out of reach of the strippers below, which remove every
        # asterisk, underscore and bracket in the text.
        def _park(m):
            tags.append(m.group(1))
            return f"\x00{len(tags) - 1}\x00"
        text = _AUDIO_TAG.sub(_park, text)
    # Strip stage directions / action descriptions enclosed in asterisks (*wags tail*, *yawns*, etc.)
    text = re.sub(r"\*[^*]+\*", "", text)
    # Strip stage directions / action descriptions enclosed in underscores (_soft bark_, etc.)
    text = re.sub(r"_[^_]+_", "", text)
    # Strip bracketed tokens and tags like [SPOTIFY: ...], [laughs], etc.
    text = re.sub(r"\[[^\]]*\]", "", text)
    # Strip markdown headers (#)
    text = re.sub(r"#+\s*", "", text)
    # Strip markdown strikethrough (~) and backticks (`)
    text = re.sub(r"[~`]+", "", text)
    # Strip any remaining stray asterisks and underscores
    text = re.sub(r"[*_]+", "", text)
    # Normalize multiple spaces and whitespace
    text = re.sub(r"\s+", " ", text).strip()
    if tags:
        text = re.sub(r"\x00(\d+)\x00", lambda m: f"[{tags[int(m.group(1))]}]", text)
        # A promoted direction can be left hugging the punctuation it replaced.
        text = re.sub(r"\s+([,.!?;:])", r"\1", text)
        text = re.sub(r"\s+", " ", text).strip()
    return text

_eleven_client = None
_eleven_client_key = None

def has_speech(text: str) -> bool:
    """True if anything would be spoken after preprocessing (a bare "[SPOTIFY: …]"
    tag or "*nods*" leaves nothing and shouldn't be sent for synthesis)."""
    return bool(_preprocess_text(text))


def _elevenlabs_client():
    """One shared client (its HTTP connection is reused, saving a TLS handshake per
    phrase); rebuilt if the API key changes. The client is safe to share across threads."""
    global _eleven_client, _eleven_client_key
    if _eleven_client is None or _eleven_client_key != config.ELEVENLABS_API_KEY:
        from elevenlabs.client import ElevenLabs
        # A sentence takes ElevenLabs a second or two; a longer wait means the
        # network is gone, and the reply is waiting on this.
        _eleven_client = ElevenLabs(api_key=config.ELEVENLABS_API_KEY, timeout=10)
        _eleven_client_key = config.ELEVENLABS_API_KEY
    return _eleven_client

def _voice_settings():
    """The stability/similarity overrides, or None to use the voice's own settings.

    Only the keys that are actually set are sent: a partial override leaves the rest
    to the voice. Style and speed are deliberately absent — Eleven v4 dropped both,
    and delivery is shaped by the audio tags instead."""
    stability, similarity = config.ELEVENLABS_STABILITY, config.ELEVENLABS_SIMILARITY
    if stability is None and similarity is None:
        return None
    settings = {}
    if stability is not None:
        settings["stability"] = stability
    if similarity is not None:
        settings["similarity_boost"] = similarity
    try:
        from elevenlabs import VoiceSettings
        return VoiceSettings(**settings)
    except Exception:
        # An SDK without the model still accepts the plain request body.
        return settings


def _synthesize_elevenlabs(text: str) -> bytes:
    text = _preprocess_text(text, keep_audio_tags=audio_tags_supported())
    client = _elevenlabs_client()
    voice_id = config.ELEVENLABS_VOICE_ID if config.ELEVENLABS_VOICE_ID else "21m00Tcm4TlvDq8ikWAM"
    settings = _voice_settings()
    audio_iter = client.text_to_speech.convert(
        voice_id=voice_id,
        text=text,
        model_id=config.ELEVENLABS_MODEL,
        output_format="pcm_16000",
        **({"voice_settings": settings} if settings is not None else {}),
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
    text = _preprocess_text(text)
    voice = _get_piper_voice()
    buf = io.BytesIO()
    with _wave.open(buf, "wb") as wf:
        voice.synthesize_wav(text, wf)
    return buf.getvalue()


def synthesize_piper(text: str) -> bytes:
    """Synthesize text specifically using the local Piper model."""
    return _synthesize_piper(text)


# ── Public API ─────────────────────────────────────────────────────────────────

# Once ElevenLabs reports its quota is gone, stop calling it for the rest of the
# session — every further phrase goes straight to the local Piper voice instead
# of paying the network round-trip just to get another quota error.
_elevenlabs_exhausted = False
# Any other failure (network down, 5xx) rests ElevenLabs for a while: without
# this, every sentence of every reply waited out the full request timeout
# before Piper spoke it.
ELEVENLABS_COOLDOWN = 60.0
_elevenlabs_retry_at = 0.0


def _is_quota_error(e: Exception) -> bool:
    msg = str(e).lower()
    return any(s in msg for s in ("quota", "payment", "unauthorized", "401", "402"))


def synthesize(text: str) -> bytes:
    """Convert text to WAV bytes using the configured TTS backend.

    When the backend is ElevenLabs but its quota is exhausted (or it otherwise
    fails), fall back to the local Piper model so the skull keeps talking — just
    in its local voice rather than going silent.
    """
    global _elevenlabs_exhausted, _elevenlabs_retry_at
    if (config.TTS_BACKEND.lower() == "elevenlabs" and not _elevenlabs_exhausted
            and time.monotonic() >= _elevenlabs_retry_at):
        try:
            return _synthesize_elevenlabs(text)
        except Exception as e:
            if _is_quota_error(e):
                print("[tts] ElevenLabs quota exhausted — falling back to local "
                      "Piper voice for the rest of this session.")
                _elevenlabs_exhausted = True
            else:
                _elevenlabs_retry_at = time.monotonic() + ELEVENLABS_COOLDOWN
                print(f"[tts] ElevenLabs error ({e}) — using the local Piper voice for the "
                      f"next {ELEVENLABS_COOLDOWN:.0f}s.")
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
