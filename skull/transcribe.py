import io
import re
from openai import OpenAI
from skull.config import OPENAI_API_KEY

_client = OpenAI(api_key=OPENAI_API_KEY)

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


def _is_hallucination(text: str) -> bool:
    if not text:
        return False
    if _HALLUCINATION_RE.search(text):
        return True
    # Repeated word spam (e.g. "the the the the")
    words = text.lower().split()
    if len(words) >= 4 and len(set(words)) <= 2:
        return True
    return False


def transcribe(wav_bytes: bytes) -> str:
    """Send WAV bytes to OpenAI Whisper and return the transcript, or '' on hallucination."""
    audio_file = io.BytesIO(wav_bytes)
    audio_file.name = "audio.wav"

    result = _client.audio.transcriptions.create(
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
