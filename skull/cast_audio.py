"""
Cast TTS audio to a Google Home / Nest speaker via pychromecast.
Falls back gracefully when not configured or no device is found.

Eye LED sync still works — amplitude is pre-computed from the WAV bytes
and replayed locally in sync with the remote cast playback.
"""

from __future__ import annotations
import http.server
import io
import os
import socket
import tempfile
import threading
import time

import numpy as np
import scipy.io.wavfile as wavfile

_DEVICE_NAME: str = os.environ.get("GOOGLE_HOME_DEVICE", "")
_cast = None          # cached pychromecast.Chromecast
_cast_lock = threading.Lock()


# ── Local audio amplitude helpers ──────────────────────────────────────────────

def amplitude_timeline(wav_bytes: bytes, chunk_ms: int = 40) -> list[float]:
    """Return per-chunk RMS amplitude list for eye-LED sync during remote playback."""
    buf = io.BytesIO(wav_bytes)
    rate, data = wavfile.read(buf)
    if data.dtype != np.float32:
        data = data.astype(np.float32) / np.iinfo(data.dtype).max
    if data.ndim > 1:
        data = data.mean(axis=1)
    size = int(rate * chunk_ms / 1000)
    return [float(np.sqrt(np.mean(data[i:i+size] ** 2)))
            for i in range(0, len(data), size) if i + size <= len(data)]


# ── Temp HTTP server to serve the WAV to the cast device ───────────────────────

class _AudioServer:
    def __init__(self, wav_bytes: bytes):
        self._dir = tempfile.mkdtemp()
        path = os.path.join(self._dir, "audio.wav")
        with open(path, "wb") as f:
            f.write(wav_bytes)

        with socket.socket() as s:
            s.bind(("", 0))
            self.port = s.getsockname()[1]

        self._server = http.server.HTTPServer(
            ("", self.port),
            lambda *a, **k: http.server.SimpleHTTPRequestHandler(
                *a, directory=self._dir, **k
            ),
        )
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def url(self) -> str:
        return f"http://{_local_ip()}:{self.port}/audio.wav"

    def stop(self) -> None:
        self._server.shutdown()


def _local_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    finally:
        s.close()


# ── Cast device discovery (cached) ─────────────────────────────────────────────

def _get_cast():
    global _cast
    with _cast_lock:
        if _cast is not None:
            return _cast
        try:
            import pychromecast
            chromecasts, browser = pychromecast.get_chromecasts()
            pychromecast.discovery.stop_discovery(browser)
            for cc in chromecasts:
                if cc.name == _DEVICE_NAME:
                    cc.wait()
                    _cast = cc
                    return _cast
            print(f"[cast] Device '{_DEVICE_NAME}' not found. "
                  f"Available: {[c.name for c in chromecasts]}")
        except Exception as e:
            print(f"[cast] Discovery error: {e}")
        return None


# ── Public API ─────────────────────────────────────────────────────────────────

def is_configured() -> bool:
    return bool(_DEVICE_NAME)


def play(wav_bytes: bytes, amplitude_fn_setter=None) -> None:
    """Cast wav_bytes to the Google Home and drive eye LEDs from pre-computed amplitude."""
    cast = _get_cast()
    if cast is None:
        return

    timeline = amplitude_timeline(wav_bytes)
    chunk_sec = 0.040

    server = _AudioServer(wav_bytes)
    url = server.url()

    # Eye LED thread — replays amplitude timeline in sync with remote playback
    def eye_loop():
        for amp in timeline:
            if amplitude_fn_setter:
                amplitude_fn_setter(lambda a=amp: a)
            time.sleep(chunk_sec)
        if amplitude_fn_setter:
            amplitude_fn_setter(lambda: 0.0)

    eye_thread = threading.Thread(target=eye_loop, daemon=True)

    try:
        mc = cast.media_controller
        mc.play_media(url, "audio/wav")
        mc.block_until_active(timeout=10)
        eye_thread.start()

        # Poll until playback finishes
        while mc.status.player_state in ("PLAYING", "BUFFERING", "UNKNOWN"):
            time.sleep(0.3)

    except Exception as e:
        print(f"[cast] Playback error: {e}")
    finally:
        eye_thread.join(timeout=1.0)
        server.stop()
