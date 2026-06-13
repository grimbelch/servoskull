from __future__ import annotations
import io
import wave
import threading
from math import gcd

import numpy as np
import pyaudio
import sounddevice as sd
import scipy.io.wavfile as wavfile
from scipy.signal import resample_poly

SAMPLE_RATE = 16000
CHANNELS = 1
FORMAT = pyaudio.paInt16
CHUNK = 512
_SAMPLE_WIDTH = 2  # bytes per sample for paInt16


def _native_input_rate(pa: pyaudio.PyAudio, device_index: int) -> int:
    if device_index >= 0:
        info = pa.get_device_info_by_index(device_index)
    else:
        info = pa.get_default_input_device_info()
    return int(info.get("defaultSampleRate", 44100))


def record(seconds: float, device_index: int = -1, silence_threshold: int = 300, silence_duration: float = 1.5) -> bytes:
    """Record audio, stopping early on sustained silence. Returns raw PCM bytes at SAMPLE_RATE."""
    pa = pyaudio.PyAudio()
    native = _native_input_rate(pa, device_index)
    native_chunk = int(CHUNK * native / SAMPLE_RATE)

    kwargs = {}
    if device_index >= 0:
        kwargs["input_device_index"] = device_index

    try:
        stream = pa.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=native,
            input=True,
            frames_per_buffer=native_chunk,
            **kwargs,
        )

        frames = []
        silent_chunks = 0
        max_chunks = int(native / native_chunk * seconds)
        silence_chunks_needed = int(native / native_chunk * silence_duration)

        for _ in range(max_chunks):
            data = stream.read(native_chunk, exception_on_overflow=False)
            frames.append(data)
            rms = np.sqrt(np.mean(np.frombuffer(data, dtype=np.int16).astype(np.float32) ** 2))
            if rms < silence_threshold:
                silent_chunks += 1
            else:
                silent_chunks = 0
            if silent_chunks >= silence_chunks_needed and len(frames) > int(native / native_chunk):
                break

        stream.stop_stream()
        stream.close()
    finally:
        pa.terminate()

    pcm = b"".join(frames)
    if native != SAMPLE_RATE:
        g = gcd(SAMPLE_RATE, native)
        audio = resample_poly(
            np.frombuffer(pcm, dtype=np.int16), SAMPLE_RATE // g, native // g
        ).astype(np.int16)
        return audio.tobytes()
    return pcm


def pcm_to_wav_bytes(pcm: bytes) -> bytes:
    """Wrap raw PCM in a WAV container."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(_SAMPLE_WIDTH)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm)
    return buf.getvalue()


def play_wav_bytes(
    wav_bytes: bytes,
    amplitude_cb=None,
    stop_event: threading.Event = None,
    output_device: int = None,
) -> None:
    """Play WAV audio.

    amplitude_cb: called once with a callable that returns the current RMS amplitude.
    stop_event: if set mid-playback, audio stops immediately (barge-in interruption).
    """
    import time

    buf = io.BytesIO(wav_bytes)
    rate, data = wavfile.read(buf)

    if data.dtype != np.float32:
        data = data.astype(np.float32) / np.iinfo(data.dtype).max

    if data.ndim > 1:
        data = data.mean(axis=1)

    chunk_size = rate // 20  # 50ms chunks
    pos = 0
    _current_amp = [0.0]
    _lock = threading.Lock()

    def amp_fn():
        with _lock:
            return _current_amp[0]

    if amplitude_cb is not None:
        amplitude_cb(amp_fn)

    def callback(outdata, frames, time_info, status):
        nonlocal pos
        if stop_event and stop_event.is_set():
            outdata.fill(0)
            raise sd.CallbackStop()
        chunk = data[pos : pos + frames]
        if len(chunk) == 0:
            outdata.fill(0)
            raise sd.CallbackStop()
        if len(chunk) < frames:
            outdata[: len(chunk), 0] = chunk
            outdata[len(chunk) :] = 0
            raise sd.CallbackStop()
        outdata[:, 0] = chunk
        pos += frames
        rms = float(np.sqrt(np.mean(chunk ** 2)))
        with _lock:
            _current_amp[0] = rms

    sd_kwargs = {"samplerate": rate, "channels": 1, "callback": callback, "blocksize": chunk_size}
    if output_device is not None and output_device >= 0:
        sd_kwargs["device"] = output_device
    with sd.OutputStream(**sd_kwargs) as stream:
        while stream.active:
            time.sleep(0.05)


def cleanup() -> None:
    pass  # PyAudio instances are now created and destroyed per-call
