"""Voice activity detection: is this bit of audio someone talking?

Silero VAD v5 (models/silero_vad.onnx, MIT, © Silero Team,
https://github.com/snakers4/silero-vad) on onnxruntime, which the wake word
already needs. It scores 32 ms of 16 kHz audio in well under a millisecond on
a Pi 5 and, unlike an RMS threshold, ignores fans, music and keyboard noise.

audio.record() feeds it each analysis window and asks EndOfSpeech when the
command is over: after speech has been heard, a short pause ends it; before any
speech, a longer wait gives the speaker time to start.
"""

from __future__ import annotations

import pathlib
import threading

import numpy as np

SAMPLE_RATE = 16000
CHUNK = 512    # samples per model call (32 ms)
CONTEXT = 64   # tail of the previous chunk the v5 model wants in front of each call

_MODEL_PATH = pathlib.Path(__file__).resolve().parent.parent / "models" / "silero_vad.onnx"


class SileroVAD:
    def __init__(self, path: pathlib.Path = _MODEL_PATH):
        import onnxruntime as ort
        opts = ort.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        opts.log_severity_level = 3
        self._session = ort.InferenceSession(str(path), sess_options=opts, providers=["CPUExecutionProvider"])
        self._sr = np.array(SAMPLE_RATE, dtype=np.int64)
        self._lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        """Forget the previous utterance (the model is stateful)."""
        with self._lock:
            self._state = np.zeros((2, 1, 128), dtype=np.float32)
            self._context = np.zeros(CONTEXT, dtype=np.float32)
            self._pending = np.zeros(0, dtype=np.float32)

    def feed(self, samples_16k) -> float:
        """Score new 16 kHz mono audio (int16 or float in [-1, 1]); returns the highest
        speech probability among the complete 32 ms chunks it contained (0.0 if
        fewer than 512 new samples have accumulated)."""
        x = np.asarray(samples_16k)
        if x.dtype != np.float32:
            x = x.astype(np.float32) / 32768.0 if x.dtype == np.int16 else x.astype(np.float32)
        best = 0.0
        with self._lock:
            buf = np.concatenate([self._pending, x]) if len(self._pending) else x
            n = len(buf) // CHUNK
            for i in range(n):
                chunk = buf[i * CHUNK:(i + 1) * CHUNK]
                # Without the context the model scores real speech near zero.
                x_in = np.concatenate([self._context, chunk]).reshape(1, CONTEXT + CHUNK)
                out, self._state = self._session.run(None, {"input": x_in, "state": self._state, "sr": self._sr})
                self._context = chunk[-CONTEXT:]
                best = max(best, float(out[0][0]))
            self._pending = buf[n * CHUNK:]
        return best


class EndOfSpeech:
    """Turns per-window speech probabilities into a stop decision.

    update(prob, t) is called once per analysis window with the window's speech
    probability and the seconds elapsed since recording began. Before speech has
    been heard it stops at start_timeout (nobody spoke); after speech it stops
    once end_silence seconds have passed without speech. Pure, so it is tested in
    tests/test_vad.py.
    """

    def __init__(self, threshold: float = 0.5, start_timeout: float = 2.7, end_silence: float = 0.7):
        self.threshold = threshold
        self.start_timeout = start_timeout
        self.end_silence = end_silence
        self.started = False
        self._last_speech = 0.0

    def update(self, prob: float, t: float) -> bool:
        if prob >= self.threshold:
            self.started = True
            self._last_speech = t
        if not self.started:
            return t >= self.start_timeout
        return (t - self._last_speech) >= self.end_silence


_loaded: SileroVAD | None = None
_load_lock = threading.Lock()
_load_failed = False


def load() -> SileroVAD | None:
    """The shared detector, or None (with one log line) if it can't be loaded."""
    global _loaded, _load_failed
    with _load_lock:
        if _loaded is None and not _load_failed:
            try:
                _loaded = SileroVAD()
                print(f"[vad] Silero VAD loaded from {_MODEL_PATH.name}.")
            except Exception as e:
                _load_failed = True
                print(f"[vad] Silero VAD unavailable ({e}) — recording ends on RMS silence instead.")
        return _loaded
