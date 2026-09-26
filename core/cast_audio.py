"""
Cast TTS audio to a Google Home / Nest speaker via pychromecast.
Falls back gracefully when not configured or no device is found.

Eye LED sync still works — amplitude is pre-computed from the WAV bytes
and replayed locally in sync with the remote cast playback.
"""

from __future__ import annotations
import http.server
import io
import socket
import threading
import time

import numpy as np
import scipy.io.wavfile as wavfile

from core import config

_DEVICE_NAME: str = config.GOOGLE_HOME_DEVICE
_cast = None          # cached pychromecast.Chromecast
_browser = None       # kept alive so zeroconf stays running for the cast connection
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
    """Serves the WAV straight from memory — nothing is written to the SD card."""

    def __init__(self, wav_bytes: bytes):
        class _Handler(http.server.BaseHTTPRequestHandler):
            timeout = 10  # never let a stalled client wedge shutdown()

            def do_HEAD(self):
                self._send(body=False)

            def do_GET(self):
                self._send(body=True)

            def _send(self, body: bool):
                if self.path.split("?", 1)[0] != "/audio.wav":
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "audio/wav")
                self.send_header("Content-Length", str(len(wav_bytes)))
                self.end_headers()
                if body:
                    self.wfile.write(wav_bytes)

        # Bind port 0 directly so the OS picks a free port (no probe-then-rebind race).
        self._server = http.server.HTTPServer(("", 0), _Handler)
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def url(self) -> str:
        return f"http://{_local_ip()}:{self.port}/audio.wav"

    def stop(self) -> None:
        try:
            self._server.shutdown()
        finally:
            self._server.server_close()  # release the listening socket


def _local_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    finally:
        s.close()


# ── Cast device discovery (cached) ─────────────────────────────────────────────

def _get_cast():
    global _cast, _browser
    with _cast_lock:
        if _cast is not None:
            return _cast
        try:
            import pychromecast
            chromecasts, browser = pychromecast.get_chromecasts()
            for cc in chromecasts:
                if cc.name == _DEVICE_NAME:
                    cc.wait()
                    _cast = cc
                    _browser = browser  # keep alive — zeroconf must stay running
                    return _cast
            print(f"[cast] Device '{_DEVICE_NAME}' not found. "
                  f"Available: {[c.name for c in chromecasts]}")
            pychromecast.discovery.stop_discovery(browser)  # safe to stop, no device in use
        except Exception as e:
            print(f"[cast] Discovery error: {e}")
        return None


# ── Public API ─────────────────────────────────────────────────────────────────

def is_configured() -> bool:
    if not _DEVICE_NAME:
        return False
    # Casting is opt-in on macOS (dev host) and opt-out on Linux/Pi; see config.
    if not config.CAST_ENABLED:
        return False
    # Casting is impossible without pychromecast (not in the Pi requirements). Report
    # "not configured" so callers fall back to local playback instead of silently
    # dropping the audio when the library is absent.
    try:
        import pychromecast  # noqa: F401
    except ImportError:
        return False
    return True


def play(wav_bytes: bytes, amplitude_fn_setter=None, stop_event: threading.Event = None) -> None:
    """Cast wav_bytes to the Google Home and drive eye LEDs from pre-computed amplitude.

    stop_event: if set mid-playback, the cast device is stopped immediately so
    barge-in interruptions work the same as local playback.
    """
    cast = _get_cast()
    if cast is None:
        return

    timeline = amplitude_timeline(wav_bytes)
    chunk_sec = 0.040
    duration = len(timeline) * chunk_sec

    server = _AudioServer(wav_bytes)
    url = server.url()

    # Eye LED thread — replays amplitude timeline in sync with remote playback
    def eye_loop():
        for amp in timeline:
            if stop_event and stop_event.is_set():
                break
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

        # Poll until playback finishes — or until barge-in sets stop_event. The
        # caller holds the speech lock, so a device stuck in UNKNOWN/BUFFERING must
        # not spin forever: give up once the clip should long since have ended.
        deadline = time.monotonic() + duration + 10.0
        while mc.status.player_state in ("PLAYING", "BUFFERING", "UNKNOWN"):
            stopping = stop_event and stop_event.is_set()
            if not stopping and time.monotonic() >= deadline:
                print(f"[cast] Playback still '{mc.status.player_state}' after {duration + 10.0:.1f}s — abandoning")
                stopping = True
            if stopping:
                try:
                    mc.stop()  # halt remote playback on the Google Home
                except Exception as e:
                    print(f"[cast] Stop error: {e}")
                break
            time.sleep(0.1)

    except Exception as e:
        print(f"[cast] Playback error: {e}")
    finally:
        if eye_thread.is_alive():  # never started if play_media() raised
            eye_thread.join(timeout=1.0)
        server.stop()
