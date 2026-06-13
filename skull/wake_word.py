import numpy as np
import pyaudio
from openwakeword.model import Model
from skull.config import WAKE_WORD_MODEL, MIC_DEVICE_INDEX

SAMPLE_RATE = 16000
CHUNK = 1280  # 80 ms at 16 kHz — minimum required by openwakeword
THRESHOLD = 0.5


def wait_for_wake_word(on_detected=None, cancel=None) -> bool:
    """Block until the wake word is detected or cancel is set.

    Returns True if wake word was detected, False if cancelled.
    """
    oww = Model(wakeword_models=[WAKE_WORD_MODEL], inference_framework="onnx")

    pa = pyaudio.PyAudio()
    kwargs = {}
    if MIC_DEVICE_INDEX >= 0:
        kwargs["input_device_index"] = MIC_DEVICE_INDEX

    stream = pa.open(
        rate=SAMPLE_RATE,
        channels=1,
        format=pyaudio.paInt16,
        input=True,
        frames_per_buffer=CHUNK,
        **kwargs,
    )

    print(f"[skull] Listening for wake word ({WAKE_WORD_MODEL}) ...")
    try:
        while True:
            if cancel and cancel.is_set():
                return False
            raw = stream.read(CHUNK, exception_on_overflow=False)
            audio = np.frombuffer(raw, dtype=np.int16)
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
