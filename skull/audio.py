from __future__ import annotations
import io
import time
import wave
import threading

import numpy as np
import sounddevice as sd
import scipy.io.wavfile as wavfile

CHANNELS = 1
_SAMPLE_WIDTH = 2  # bytes per sample for int16


def _native_input_rate(device_index: int) -> int:
    try:
        if device_index >= 0:
            info = sd.query_devices(device_index)
        else:
            info = sd.query_devices(kind="input")
        return int(info["default_samplerate"])
    except Exception:
        return 44100


def record(seconds: float, device_index: int = -1, silence_threshold: int = 300, silence_duration: float = 1.5) -> tuple:
    """Record audio as a single continuous sd.rec() call, aborting early on sustained silence.

    Returns (pcm_bytes, sample_rate) at the device's native rate.
    Single call avoids the gap/choppiness of repeated sd.rec() calls.
    InputStream callbacks were unreliable on macOS, so we use sd.rec() + sd.stop().
    """
    native = _native_input_rate(device_index)
    dev = device_index if device_index >= 0 else None
    max_frames = int(native * seconds)

    ANALYSIS_SECS = 0.25
    analysis_frames = int(native * ANALYSIS_SECS)
    lead_in_secs = 1.5
    silence_chunks_needed = max(1, round(silence_duration / ANALYSIS_SECS))

    print(f"[audio] recording: device={dev}, rate={native}Hz")

    buf = sd.rec(max_frames, samplerate=native, channels=1, device=dev, dtype="int16")
    t_start = time.monotonic()
    stop_at_frame = [max_frames]

    def _monitor():
        time.sleep(lead_in_secs)
        silent_chunks = 0
        chunk_num = 0
        max_rms = 0.0

        while True:
            time.sleep(ANALYSIS_SECS)
            elapsed = time.monotonic() - t_start
            write_pos = min(int(elapsed * native), max_frames)
            read_end = write_pos
            read_start = max(0, read_end - analysis_frames)
            if read_end <= read_start:
                continue

            chunk = buf[read_start:read_end, 0]
            rms = float(np.sqrt(np.mean(chunk.astype(np.float32) ** 2)))
            max_rms = max(max_rms, rms)
            chunk_num += 1
            print(f"[audio] chunk {chunk_num}: rms={rms:.1f} (threshold={silence_threshold})")

            if rms < silence_threshold:
                silent_chunks += 1
            else:
                silent_chunks = 0

            if silent_chunks >= silence_chunks_needed:
                stop_at_frame[0] = write_pos
                sd.stop()
                return

            if write_pos >= max_frames:
                return

    monitor = threading.Thread(target=_monitor, daemon=True)
    monitor.start()

    # sd.wait() has no timeout — wrap it in a thread so we can enforce one.
    # Without this, a CoreAudio hang (macOS mic permission/init race) blocks forever.
    _sd_wait_done = threading.Event()

    def _run_sd_wait():
        sd.wait()
        _sd_wait_done.set()

    threading.Thread(target=_run_sd_wait, daemon=True).start()
    if not _sd_wait_done.wait(timeout=seconds + 5.0):
        print("[audio] Recording timed out — forcing stop")
        try:
            sd.stop()
        except Exception:
            pass
        _sd_wait_done.wait(timeout=1.0)

    monitor.join(timeout=1.0)

    frames = min(stop_at_frame[0], max_frames)
    total_secs = frames / native
    print(f"[audio] done: {frames} frames ({total_secs:.1f}s)")

    pcm_arr = buf[:frames, 0].copy()
    if not pcm_arr.any():
        return b"", native
    return pcm_arr.tobytes(), native


def pcm_to_wav_bytes(pcm: bytes, sample_rate: int) -> bytes:
    """Wrap raw PCM in a WAV container at the given sample rate."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(_SAMPLE_WIDTH)
        wf.setframerate(sample_rate)
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
    duration = len(data) / rate + 5.0  # audio duration + 5s safety margin
    deadline = time.monotonic() + duration
    with sd.OutputStream(**sd_kwargs) as stream:
        while stream.active and time.monotonic() < deadline:
            time.sleep(0.05)


def cleanup() -> None:
    pass
