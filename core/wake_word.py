from __future__ import annotations
import queue
import threading
import time
from math import gcd

import numpy as np
import sounddevice as sd
from scipy.signal import resample_poly
from openwakeword.model import Model
from core import watchdog
from core.config import WAKE_WORD_MODEL, MIC_DEVICE_INDEX, WAKE_WORD_THRESHOLD

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


import os

def _get_model() -> Model:
    global _model
    with _model_lock:
        if _model is None:
            m_path = os.path.abspath(WAKE_WORD_MODEL) if os.path.exists(WAKE_WORD_MODEL) else WAKE_WORD_MODEL
            _model = Model(wakeword_models=[m_path], inference_framework="onnx")
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


_ww_consecutive_failures = 0
_DEVICE_UNAVAILABLE_ERR = -9985  # PaErrorCode: paDeviceUnavailable

# A healthy stream delivers a chunk every 80 ms. If none arrives for this long
# (PipeWire restarted, USB mic dropped: PortAudio often just stops calling back
# without raising), the stream is treated as dead and reopened. The watchdog is
# only fed when audio actually arrives, so a mic that stays dead stops the
# pings and systemd restarts the service.
MIC_STALL_SECS = 3.0


class MicStalled(RuntimeError):
    """The input stream stopped delivering audio."""


def wait_for_wake_word(on_detected=None, cancel=None, threshold=None) -> bool:
    """Block until the wake word is detected or cancel is set.

    threshold overrides config.WAKE_WORD_THRESHOLD for this listener; the barge-in
    listener passes a lower one so the skull can be cut off mid-sentence.

    Returns True if wake word was detected, False if cancelled.
    """
    global _ww_consecutive_failures

    oww = _get_model()
    oww.reset()  # clear prediction buffer from any previous session before reuse
    native = _native_rate(MIC_DEVICE_INDEX)
    native_chunk = int(CHUNK * native / TARGET_RATE)
    dev = MIC_DEVICE_INDEX if MIC_DEVICE_INDEX >= 0 else None

    q: queue.Queue = queue.Queue()

    def _cb(indata, frames, time_info, status):
        q.put(indata.copy())

    print(f"[skull] Listening for wake word ({WAKE_WORD_MODEL}) at {native}Hz...")
    try:
        with sd.InputStream(samplerate=native, channels=1, dtype="int16",
                            blocksize=native_chunk, device=dev, callback=_cb) as stream:
            _ww_consecutive_failures = 0  # device opened successfully — reset counter
            last_audio = time.monotonic()
            while True:
                if cancel and cancel.is_set():
                    return False
                try:
                    raw = q.get(timeout=0.1)
                except queue.Empty:
                    silent_for = time.monotonic() - last_audio
                    if silent_for > MIC_STALL_SECS or not stream.active:
                        raise MicStalled(f"no audio from the microphone for {silent_for:.1f}s")
                    continue
                last_audio = time.monotonic()
                watchdog.beat()  # audio is arriving: the mic stream is alive
                audio = _to_target(raw.flatten(), native)
                rms = float(np.sqrt(np.mean(audio.astype(np.float32) ** 2)))
                predictions = oww.predict(audio)
                score = max(predictions.values()) if predictions else 0.0
                from core import config as _cfg
                # re-read per chunk so a live config edit takes effect without a restart
                thr = float(getattr(_cfg, "WAKE_WORD_THRESHOLD", 0.65)) if threshold is None else threshold
                if _cfg.AUDIO_DEBUG and (rms > 50 or score > 0.1):
                    print(f"[ww] rms={rms:.0f} score={score:.3f} (need >={thr:.2f})")
                if score >= thr:
                    mode = "idle" if threshold is None else "barge-in"
                    print(f"[skull] Wake word detected! (score={score:.3f} >= {thr:.2f}, {mode})")

                    oww.reset()
                    if on_detected:
                        on_detected()
                    return True

    except Exception as e:
        _ww_consecutive_failures += 1
        # Back off exponentially (capped at 30s) when the device is unavailable,
        # e.g. during the PipeWire startup race on boot. This prevents the tight
        # failure loop that causes a sound to play every ~3 seconds.
        backoff = min(5.0 * _ww_consecutive_failures, 30.0)
        print(f"[wake_word] Audio InputStream error: {e} (retry in {backoff:.0f}s, attempt {_ww_consecutive_failures})")
        time.sleep(backoff)
        return False

