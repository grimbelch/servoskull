import io
import re
from skull.config import OPENAI_API_KEY

# Built lazily on first transcription so importing this module never fails just
# because the OpenAI key isn't set (e.g. on a host that only does TTS playback).
_client = None


def _get_client():
    global _client
    if _client is None:
        if not OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY is not set (required for Whisper speech-to-text).")
        from openai import OpenAI
        _client = OpenAI(api_key=OPENAI_API_KEY)
    return _client

# Whisper hallucinates these strings on silence or ambient noise
_HALLUCINATION_PATTERNS = [
    r"(www\.|https?://)\S+",          # URLs
    r"\.(com|org|net|io|co)\b",       # domain suffixes
    r"(youtube|facebook|twitter|instagram|tiktok|reddit)",
    r"(subscribe|like and|thanks? for watching|patreon)",
    r"(\w+\s*){1,3}(\.com|\.org)",    # "word word.com" patterns
]
_HALLUCINATION_RE = re.compile(
    "|".join(_HALLUCINATION_PATTERNS), re.IGNORECASE
)

# The domain `prompt` below biases Whisper toward these tokens; on silence/noise it
# regurgitates them verbatim. A transcript made of nothing but these words is that
# hallucination, not a real request — suppress it so the brain doesn't monologue on it.
_PROMPT_WORDS = {
    "omega", "omega-7", "omega7", "omnissiah",
    "adeptus", "mechanicus", "necromunda", "warhammer", "7",
}


def _is_hallucination(text: str) -> bool:
    if not text:
        return False
    if _HALLUCINATION_RE.search(text):
        return True
    # Repeated word spam (e.g. "the the the the")
    words = text.lower().split()
    if len(words) >= 4 and len(set(words)) <= 2:
        return True
    # Only the prompt's domain words echoed back (e.g. "Adeptus Mechanicus. Necromunda.")
    tokens = [t for t in re.sub(r"[^\w\s-]", " ", text.lower()).split() if t]
    if tokens and all(t in _PROMPT_WORDS for t in tokens):
        return True
    return False


def transcribe(wav_bytes: bytes) -> str:
    """Send WAV bytes to OpenAI Whisper and return the transcript, or '' on hallucination."""
    audio_file = io.BytesIO(wav_bytes)
    audio_file.name = "audio.wav"

    result = _get_client().audio.transcriptions.create(
        model="whisper-1",
        file=audio_file,
        language="en",
        prompt="Omega-7, Omnissiah, Adeptus Mechanicus, Necromunda, Warhammer",
    )
    text = result.text.strip()
    print(f"[skull] Whisper raw: {text!r}")

    if _is_hallucination(text):
        print(f"[skull] Whisper hallucination suppressed: {text!r}")
        return ""

    return text
