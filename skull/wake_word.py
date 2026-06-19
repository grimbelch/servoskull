from __future__ import annotations
import queue
import threading
from math import gcd

import numpy as np
import sounddevice as sd
from scipy.signal import resample_poly
from openwakeword.model import Model
from skull.config import WAKE_WORD_MODEL, MIC_DEVICE_INDEX, WAKE_WORD_THRESHOLD

TARGET_RATE = 16000
CHUNK = 1280  # 80 ms at 16 kHz — minimum required by openwakeword
THRESHOLD = WAKE_WORD_THRESHOLD

# Build the openWakeWord model ONCE and reuse it. Constructing a Model spins up
# onnxruntime inference sessions in native code; doing that on every call (this
# function runs once per loop and again as the barge-in listener) churns those
# sessions and segfaults / "free(): invalid pointer" the interpreter. Access is
# sequential in practice, but the lock guards the lazy init against a rare race.
_model = None
_model_lock = threading.Lock()


def _get_model() -> Model:
    global _model
    with _model_lock:
        if _model is None:
            _model = Model(wakeword_models=[WAKE_WORD_MODEL], inference_framework="onnx")
    return _model


def _native_rate(device_index: int) -> int:
    try:
        info = sd.query_devices(device_index if device_index >= 0 else None, kind="input")
        return int(info["default_samplerate"])
    except Exception:
        return 48000


def _to_target(audio: np.ndarray, native: int) -> np.ndarray:
    if native == TARGET_RATE:
        return audio
    g = gcd(TARGET_RATE, native)
    # float32 conversion before resample_poly avoids int16 numerical zeroing bug
    resampled = resample_poly(audio.astype(np.float32), TARGET_RATE // g, native // g)
    return resampled.astype(np.int16)


def wait_for_wake_word(on_detected=None, cancel=None) -> bool:
    """Block until the wake word is detected or cancel is set.

    Returns True if wake word was detected, False if cancelled.
    """
    oww = _get_model()
    oww.reset()  # clear prediction buffer from any previous session before reuse
    native = _native_rate(MIC_DEVICE_INDEX)
    native_chunk = int(CHUNK * native / TARGET_RATE)
    dev = MIC_DEVICE_INDEX if MIC_DEVICE_INDEX >= 0 else None

    q: queue.Queue = queue.Queue()

    def _cb(indata, frames, time_info, status):
        q.put(indata.copy())

    print(f"[skull] Listening for wake word ({WAKE_WORD_MODEL}) at {native}Hz...")
    with sd.InputStream(samplerate=native, channels=1, dtype="int16",
                        blocksize=native_chunk, device=dev, callback=_cb):
        while True:
            if cancel and cancel.is_set():
                return False
            try:
                raw = q.get(timeout=0.1)
            except queue.Empty:
                continue
            audio = _to_target(raw.flatten(), native)
            rms = float(np.sqrt(np.mean(audio.astype(np.float32) ** 2)))
            predictions = oww.predict(audio)
            score = max(predictions.values())
            from skull import config as _cfg
            if _cfg.AUDIO_DEBUG and (rms > 50 or score > 0.1):
                print(f"[ww] rms={rms:.0f} score={score:.3f} (need >={THRESHOLD})")
            if score >= THRESHOLD:
                print("[skull] Wake word detected!")
                oww.reset()
                if on_detected:
                    on_detected()
                return True
