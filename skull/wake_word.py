import struct
import pyaudio
from skull.config import PORCUPINE_ACCESS_KEY, WAKE_WORD, MIC_DEVICE_INDEX

try:
    import pvporcupine
except Exception as e:
    raise RuntimeError(
        "pvporcupine failed to load. On Mac use the emulator (run_emulator.py) instead."
    ) from e

CHUNK = 512


def wait_for_wake_word(on_detected=None, cancel: "threading.Event | None" = None) -> bool:
    """Block until the wake word is detected or cancel is set.

    Returns True if wake word was detected, False if cancelled.
    """
    import threading  # noqa: F401 — used only for the type hint above

    porcupine = pvporcupine.create(
        access_key=PORCUPINE_ACCESS_KEY,
        keywords=[WAKE_WORD],
    )

    pa = pyaudio.PyAudio()
    kwargs = {}
    if MIC_DEVICE_INDEX >= 0:
        kwargs["input_device_index"] = MIC_DEVICE_INDEX

    stream = pa.open(
        rate=porcupine.sample_rate,
        channels=1,
        format=pyaudio.paInt16,
        input=True,
        frames_per_buffer=porcupine.frame_length,
        **kwargs,
    )

    print(f'[skull] Listening for wake word: "{WAKE_WORD}" ...')
    try:
        while True:
            if cancel and cancel.is_set():
                return False
            raw = stream.read(porcupine.frame_length, exception_on_overflow=False)
            pcm = struct.unpack_from("h" * porcupine.frame_length, raw)
            result = porcupine.process(pcm)
            if result >= 0:
                print("[skull] Wake word detected!")
                if on_detected:
                    on_detected()
                return True
    finally:
        stream.stop_stream()
        stream.close()
        pa.terminate()
        porcupine.delete()
