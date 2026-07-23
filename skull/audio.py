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
    """Record audio via a single InputStream, stopping early on sustained silence.

    Returns (pcm_bytes, sample_rate) at the device's native rate.

    Uses ONE explicitly-managed InputStream, started once and closed exactly once
    from this thread. The previous sd.rec()/sd.stop() approach let the silence
    monitor and the timeout-recovery path BOTH call sd.stop() on the shared global
    stream, racing PortAudio's (non-thread-safe) Pa_CloseStream and aborting the
    process with "double free" / a futex error. Here the audio callback only
    appends samples — it issues no PortAudio control calls — and stop/close happen
    once, in finally.
    """
    native = _native_input_rate(device_index)
    dev = device_index if device_index >= 0 else None
    max_frames = int(native * seconds)

    ANALYSIS_SECS = 0.25
    analysis_frames = int(native * ANALYSIS_SECS)
    lead_in_secs = 1.5
    silence_chunks_needed = max(1, round(silence_duration / ANALYSIS_SECS))

    print(f"[audio] recording: device={dev}, rate={native}Hz")

    chunks: list = []
    chunks_lock = threading.Lock()
    captured = [0]

    def _cb(indata, frames, time_info, status):
        with chunks_lock:
            chunks.append(indata.copy())
            captured[0] += frames

    def _collected() -> np.ndarray:
        with chunks_lock:
            if not chunks:
                return np.zeros(0, dtype=np.int16)
            return np.concatenate(chunks)[:, 0]

    stream = sd.InputStream(samplerate=native, channels=1, dtype="int16",
                            device=dev, callback=_cb)
    t_start = time.monotonic()
    hard_deadline = t_start + seconds + 5.0  # wall-clock safety net; never hangs
    silent_chunks = 0
    stream.start()
    try:
        while True:
            time.sleep(ANALYSIS_SECS)
            now = time.monotonic()
            if captured[0] >= max_frames:
                break
            if now >= hard_deadline:
                print("[audio] Recording timed out — stopping")
                break
            if now - t_start < lead_in_secs:
                continue
            data = _collected()
            if len(data) < analysis_frames:
                continue
            window = data[-analysis_frames:]
            rms = float(np.sqrt(np.mean(window.astype(np.float32) ** 2)))
            from skull import config as _cfg
            if _cfg.AUDIO_DEBUG:
                print(f"[audio] rms={rms:.1f} (threshold={silence_threshold})")
            if rms < silence_threshold:
                silent_chunks += 1
                if silent_chunks >= silence_chunks_needed:
                    break
            else:
                silent_chunks = 0
    finally:
        # Stop and close exactly once, from this thread only.
        try:
            stream.stop()
        finally:
            stream.close()

    data = _collected()
    frames = min(len(data), max_frames)
    total_secs = frames / native if native else 0.0
    print(f"[audio] done: {frames} frames ({total_secs:.1f}s)")

    pcm_arr = data[:frames].copy()
    if not pcm_arr.any():
        return b"", native
    return pcm_arr.tobytes(), native


def max_window_rms(pcm: bytes, sample_rate: int, window_secs: float = 0.25) -> float:
    """Peak RMS across non-overlapping windows — a proxy for whether speech occurred.

    A recording where the wake word fired but nothing was said is just ambient floor:
    no window ever rises above it. Real speech pushes at least one window well past the
    silence threshold. Lets the caller tell 'nothing was said' apart from 'said something',
    rather than trusting Whisper, which (biased by its domain prompt) hallucinates 40k
    lore words on silence.
    """
    if not pcm:
        return 0.0
    data = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    win = max(1, int(sample_rate * window_secs))
    peak = 0.0
    for start in range(0, len(data), win):
        seg = data[start:start + win]
        if seg.size == 0:
            continue
        rms = float(np.sqrt(np.mean(seg ** 2)))
        if rms > peak:
            peak = rms
    return peak


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
    try:
        from skull import web
        web.publish_web_audio(wav_bytes)
    except Exception:
        pass

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
    if output_device is not None:
        if isinstance(output_device, str):
            os.environ["PULSE_SINK"] = output_device
        elif isinstance(output_device, int) and output_device >= 0:
            os.environ.pop("PULSE_SINK", None)
            sd_kwargs["device"] = output_device
    else:
        os.environ.pop("PULSE_SINK", None)

    duration = len(data) / rate + 5.0  # audio duration + 5s safety margin
    deadline = time.monotonic() + duration
    with sd.OutputStream(**sd_kwargs) as stream:
        while stream.active and time.monotonic() < deadline:
            time.sleep(0.05)


def get_pulseaudio_sinks() -> dict[str, str]:
    """Returns a dict mapping sink type ('internal' or 'bluetooth') to PulseAudio sink name."""
    sinks = {}
    try:
        out = subprocess.run(["pactl", "list", "short", "sinks"], capture_output=True, text=True, timeout=5).stdout
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 2:
                name = parts[1]
                name_lower = name.lower()
                if "bluez" in name_lower or "bt" in name_lower:
                    sinks["bluetooth"] = name
                elif "usb" in name_lower or "alsa" in name_lower:
                    sinks["internal"] = name
    except Exception as e:
        print(f"[audio] Error listing PulseAudio sinks: {e}")
    return sinks


def get_internal_speaker_sink() -> str | int | None:
    """Find Omega-7's internal hardware speaker sink or card index."""
    sinks = get_pulseaudio_sinks()
    if "internal" in sinks:
        return sinks["internal"]
    return find_local_hardware_output_device()


def find_local_hardware_output_device() -> int | None:
    """Locate the hardware card index for Omega-7's internal/USB speaker."""
    try:
        import sounddevice as sd
        devices = sd.query_devices()
        for idx, d in enumerate(devices):
            if d["max_output_channels"] > 0:
                name_lower = d["name"].lower()
                if any(hw in name_lower for hw in ("usb", "hw:", "bcm2835", "headphone", "analog")) and "default" not in name_lower and "pipewire" not in name_lower:
                    return idx
        for idx, d in enumerate(devices):
            if d["max_output_channels"] > 0 and "default" not in d["name"].lower() and "pipewire" not in d["name"].lower():
                return idx
    except Exception as e:
        print(f"[audio] Error finding local hardware output device: {e}")
    return None


def set_voice_target(target: str) -> str:
    """Switch TTS vocal output between internal speaker and Bluetooth speaker."""
    from skull import config
    t_lower = target.lower().strip()
    sinks = get_pulseaudio_sinks()
    if any(k in t_lower for k in ("bluetooth", "bt", "external", "remote", "other")):
        bt_sink = sinks.get("bluetooth")
        config.VOICE_OUTPUT_DEVICE = bt_sink  # String sink name or None (PulseAudio default)
        print(f"[audio] Voice output target → Bluetooth ({bt_sink or 'system default'})")
        return "Voice output switched to the Bluetooth speaker."
    else:
        int_sink = get_internal_speaker_sink()
        config.VOICE_OUTPUT_DEVICE = int_sink
        print(f"[audio] Voice output target → Internal speaker ({int_sink})")
        return "Voice output returned to Omega-7's internal speaker."


def cleanup() -> None:
    pass
