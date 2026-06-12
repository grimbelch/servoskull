import io
import wave
import threading
import numpy as np
import pyaudio
import sounddevice as sd
import scipy.io.wavfile as wavfile

SAMPLE_RATE = 16000
CHANNELS = 1
FORMAT = pyaudio.paInt16
CHUNK = 512

_pa = pyaudio.PyAudio()


def record(seconds: float, device_index: int = -1, silence_threshold: int = 300, silence_duration: float = 1.5) -> bytes:
    """Record audio, stopping early on sustained silence. Returns raw PCM bytes."""
    kwargs = {}
    if device_index >= 0:
        kwargs["input_device_index"] = device_index

    stream = _pa.open(
        format=FORMAT,
        channels=CHANNELS,
        rate=SAMPLE_RATE,
        input=True,
        frames_per_buffer=CHUNK,
        **kwargs,
    )

    frames = []
    silent_chunks = 0
    max_chunks = int(SAMPLE_RATE / CHUNK * seconds)
    silence_chunks_needed = int(SAMPLE_RATE / CHUNK * silence_duration)

    for _ in range(max_chunks):
        data = stream.read(CHUNK, exception_on_overflow=False)
        frames.append(data)
        rms = np.sqrt(np.mean(np.frombuffer(data, dtype=np.int16).astype(np.float32) ** 2))
        if rms < silence_threshold:
            silent_chunks += 1
        else:
            silent_chunks = 0
        # Stop early after silence_duration of quiet (but record at least 1 second)
        if silent_chunks >= silence_chunks_needed and len(frames) > int(SAMPLE_RATE / CHUNK):
            break

    stream.stop_stream()
    stream.close()

    return b"".join(frames)


def pcm_to_wav_bytes(pcm: bytes) -> bytes:
    """Wrap raw PCM in a WAV container."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(_pa.get_sample_size(FORMAT))
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm)
    return buf.getvalue()


def play_wav_bytes(
    wav_bytes: bytes,
    amplitude_cb=None,
    stop_event: threading.Event = None,
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

    with sd.OutputStream(samplerate=rate, channels=1, callback=callback, blocksize=chunk_size) as stream:
        while stream.active:
            time.sleep(0.05)


def cleanup() -> None:
    _pa.terminate()
