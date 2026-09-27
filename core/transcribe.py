"""Speech-to-text.

transcribe(wav) is the batch call: the whole recording goes to OpenAI and the
text comes back. StreamingTranscriber sends the audio while it is still being
recorded (OpenAI's realtime transcription session over a websocket), so the
transcript is usually ready the moment the speaker stops; anything that goes
wrong with it makes finish() return None and the caller falls back to the batch
call, so the streamed path can only ever be faster, never worse.
"""

from __future__ import annotations

import base64
import io
import json
import queue
import re
import threading
import time

from core import config

# Built lazily on first transcription so importing this module never fails just
# because the OpenAI key isn't set (e.g. on a host that only does TTS playback).
# The key is read from config each time (not copied at import) so one saved by
# the setup wizard takes effect without a restart.
_client = None
_client_key = None


def _get_client():
    global _client, _client_key
    key = config.OPENAI_API_KEY
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not set (required for Whisper speech-to-text).")
    if _client is None or _client_key != key:
        from openai import OpenAI
        _client = OpenAI(api_key=key, timeout=15.0)
        _client_key = key
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

# The domain `prompt` below biases the model toward these tokens; on silence/noise it
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


def _prompt() -> str:
    """Domain words that bias recognition toward the skull's vocabulary."""
    if config.get_personality_key() == "jax":
        return f"Jax, {config.SKULL_NAME}, Golden Retriever, dog, fetch, woof"
    return f"{config.SKULL_NAME}, Omnissiah, Adeptus Mechanicus, Necromunda, Warhammer"


def _postprocess(text: str, source: str) -> str:
    text = (text or "").strip()
    print(f"[skull] {source} raw: {text!r}")
    if _is_hallucination(text):
        print(f"[skull] {source} hallucination suppressed: {text!r}")
        return ""
    # Normalize common mishearings of assistant names (e.g. "Jez" -> "Jax")
    if config.get_personality_key() == "jax":
        text = re.sub(r"\b(jez|jacks|jags|chax)\b", "Jax", text, flags=re.IGNORECASE)
    return text


def transcribe(wav_bytes: bytes) -> str:
    """Send WAV bytes to OpenAI and return the transcript, or '' on hallucination."""
    audio_file = io.BytesIO(wav_bytes)
    audio_file.name = "audio.wav"
    result = _get_client().audio.transcriptions.create(
        model=config.STT_MODEL,
        file=audio_file,
        prompt=_prompt(),
    )
    return _postprocess(result.text, "Whisper")


# ── Streaming ─────────────────────────────────────────────────────────────────

# The GA realtime API: a transcription-type session, our own commit (no server VAD).
_REALTIME_URL = "wss://api.openai.com/v1/realtime?intent=transcription"
_STREAM_RATE = 24000  # the realtime API's pcm16 format
_ABORT = object()


def streaming_available() -> bool:
    return bool(config.STT_STREAMING and config.OPENAI_API_KEY)


class StreamingTranscriber:
    """One recording's worth of audio, transcribed as it arrives.

    start() opens the session on a background thread (call it early, e.g. while the
    wake acknowledgement plays). feed(pcm, rate) takes each new slice of the
    recording at the mic's native rate. finish(timeout) commits the audio and
    returns the transcript ('' for nothing said), or None if streaming failed for
    any reason — then transcribe() the recording instead. abort() discards it.
    """

    def __init__(self):
        self._q: queue.Queue = queue.Queue()
        self._result: str | None = None
        self._failed = False
        self._done = threading.Event()
        self._started_at = 0.0
        self._sent_bytes = 0

    def start(self) -> None:
        self._started_at = time.monotonic()
        threading.Thread(target=self._run, daemon=True, name="stt-stream").start()

    def feed(self, pcm: bytes, rate: int) -> None:
        if self._failed or not pcm:
            return
        from core import audio
        pcm24, _ = audio.resample_pcm(pcm, rate, _STREAM_RATE)
        self._sent_bytes += len(pcm24)
        self._q.put(pcm24)

    def finish(self, timeout: float = 4.0) -> str | None:
        self._q.put(None)
        self._done.wait(timeout)
        if self._failed or not self._done.is_set():
            if not self._done.is_set():
                print("[stt] Streamed transcript not back in time — abandoning it.")
                self._failed = True
                self._q.put(_ABORT)
            return None
        return _postprocess(self._result or "", "Streamed STT")

    def abort(self) -> None:
        self._failed = True
        self._q.put(_ABORT)

    # -- background ----------------------------------------------------------

    def _run(self) -> None:
        try:
            from websockets.sync.client import connect
            headers = {"Authorization": f"Bearer {config.OPENAI_API_KEY}"}
            with connect(_REALTIME_URL, additional_headers=headers, open_timeout=5.0, close_timeout=1.0) as conn:
                conn.send(json.dumps({
                    "type": "session.update",
                    "session": {
                        "type": "transcription",
                        "audio": {"input": {
                            "format": {"type": "audio/pcm", "rate": _STREAM_RATE},
                            "noise_reduction": {"type": "near_field"},
                            "transcription": {
                                "model": config.STT_STREAMING_MODEL,
                                "prompt": _prompt(),
                                "language": "en",
                            },
                            "turn_detection": None,  # we commit when our own VAD says the speaker stopped
                        }},
                    },
                }))
                print(f"[stt] Streaming session open ({time.monotonic() - self._started_at:.2f}s).")
                threading.Thread(target=self._receive, args=(conn,), daemon=True).start()
                while True:
                    item = self._q.get()
                    if item is _ABORT:
                        return
                    if item is None:
                        break
                    conn.send(json.dumps({"type": "input_audio_buffer.append",
                                          "audio": base64.b64encode(item).decode("ascii")}))
                if self._sent_bytes < _STREAM_RATE * 2 // 5:  # under 200 ms: nothing to transcribe
                    self._result = ""
                    return
                conn.send(json.dumps({"type": "input_audio_buffer.commit"}))
                self._done.wait(timeout=8.0)
        except Exception as e:
            print(f"[stt] Streaming failed ({type(e).__name__}: {e}).")
            self._failed = True
        finally:
            self._done.set()

    def _receive(self, conn) -> None:
        try:
            for raw in conn:
                ev = json.loads(raw)
                kind = ev.get("type", "")
                if kind == "conversation.item.input_audio_transcription.completed":
                    self._result = ev.get("transcript", "")
                    self._done.set()
                    return
                if kind == "error":
                    err = ev.get("error", {})
                    print(f"[stt] Streaming error: {err.get('message') or err}")
                    self._failed = True
                    self._done.set()
                    return
                if kind == "input_audio_buffer.committed":
                    print("[stt] Audio committed; awaiting transcript.")
        except Exception:
            pass  # the connection closes when _run() returns
