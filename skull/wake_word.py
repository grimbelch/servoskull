from __future__ import annotations
from math import gcd

import numpy as np
import pyaudio
from scipy.signal import resample_poly
from openwakeword.model import Model
from skull.config import WAKE_WORD_MODEL, MIC_DEVICE_INDEX

TARGET_RATE = 16000
CHUNK = 1280  # 80 ms at 16 kHz — minimum required by openwakeword
THRESHOLD = 0.5


def _native_rate(pa: pyaudio.PyAudio) -> int:
    if MIC_DEVICE_INDEX >= 0:
        info = pa.get_device_info_by_index(MIC_DEVICE_INDEX)
    else:
        info = pa.get_default_input_device_info()
    return int(info.get("defaultSampleRate", 44100))


def _to_target(audio: np.ndarray, native: int) -> np.ndarray:
    if native == TARGET_RATE:
        return audio
    g = gcd(TARGET_RATE, native)
    return resample_poly(audio, TARGET_RATE // g, native // g).astype(np.int16)


def wait_for_wake_word(on_detected=None, cancel=None) -> bool:
    """Block until the wake word is detected or cancel is set.

    Returns True if wake word was detected, False if cancelled.
    """
    oww = Model(wakeword_models=[WAKE_WORD_MODEL], inference_framework="onnx")

    pa = pyaudio.PyAudio()
    native = _native_rate(pa)
    # Scale chunk so each read is still ~80 ms of real time
    native_chunk = int(CHUNK * native / TARGET_RATE)

    kwargs = {}
    if MIC_DEVICE_INDEX >= 0:
        kwargs["input_device_index"] = MIC_DEVICE_INDEX

    stream = pa.open(
        rate=native,
        channels=1,
        format=pyaudio.paInt16,
        input=True,
        frames_per_buffer=native_chunk,
        **kwargs,
    )

    print(f"[skull] Listening for wake word ({WAKE_WORD_MODEL}) ...")
    try:
        while True:
            if cancel and cancel.is_set():
                return False
            raw = stream.read(native_chunk, exception_on_overflow=False)
            audio = _to_target(np.frombuffer(raw, dtype=np.int16), native)
            predictions = oww.predict(audio)
            score = max(predictions.values())
            if score >= THRESHOLD:
                print("[skull] Wake word detected!")
                oww.reset()
                if on_detected:
                    on_detected()
                return True
    finally:
        stream.stop_stream()
        stream.close()
        pa.terminate()
