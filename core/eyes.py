"""
Drives the 2 individually addressable eye LEDs (RGBW pixels, see EYE_WIRING.md).

On the Pi 5 the RP1 southbridge owns the GPIO pins, so rpi_ws281x (which drives
the Pi 4's PWM/DMA registers) cannot reach them. The signal is clocked out by
RP1's PIO block instead, through Adafruit's /dev/pio0 writer. Only that writer
is used: Blinka, which its examples pair it with, depends on RPi.GPIO and
rpi_ws281x, and installing those over the rpi-lgpio shim breaks every other GPIO
user on a Pi 5. The handful of bytes is packed here instead.

The pixels fitted are RGBW (SK6812-type, four bytes each, GRBW). Left Eye =
index 0, Right Eye = index 1; the third lens housing holds the camera.

What they show is decided by core/eye_states.py, from the state held here:
main.py reports activity (wake(), think(), on()/set_amplitude() while speaking,
off()), core/eye_watch.py the status of the world (set_status(), blip()). A
50 FPS loop resolves each frame and sends it.
"""

from __future__ import annotations
import dataclasses
import time
import threading
import atexit
from types import SimpleNamespace

from core import eye_states as es

_ws281x_available = False
_gpio = None              # what neopixel_write wants: any object with .id = BCM pin
_buf = bytearray()        # the frame, already in the pixels' byte order
_pin: int = 18
_count: int = 2
_order: str = "GRBW"       # colour byte order; a fourth letter means an RGBW pixel

_stop = threading.Event()
_anim_thread: threading.Thread | None = None
_lock = threading.Lock()

# What the next frame is resolved from (see eye_states.Frame).
_mood_rgb = (255, 40, 30)
_wake_at = -1e9
_activity = ""
_activity_since = 0.0
_amplitude = 1.0
_confirm_until = 0.0
_health: es.Light | None = None
_links: list[es.Light] = []
_tasks: list[es.Light] = []
_blips: list[es.Blip] = []
_scale = 1.0
_calm = False
_started_at = 0.0
_fade_out_at: float | None = None

BOOT_FADE_SECS = 2.0
SHUTDOWN_FADE_SECS = 0.4

try:
    from adafruit_raspberry_pi5_neopixel_write import neopixel_write
    _ws281x_available = True
except (ImportError, RuntimeError, NotImplementedError):
    _ws281x_available = False


def setup(pin: int = 18, count: int = 2, order: str = "GRBW") -> None:
    """Initialize the eye LED chain on the given GPIO (BCM) pin.

    `order` is the pixels' colour byte order: "GRBW" for the RGBW pixels fitted,
    "GRB" for plain WS2812B.
    """
    global _gpio, _buf, _pin, _count, _order, _anim_thread, _started_at

    _pin = int(pin)
    _count = int(count)
    _order = parse_order(order)
    _started_at = time.monotonic()

    if not _ws281x_available:
        print("[eyes] Pi 5 NeoPixel driver unavailable (non-Pi host or missing lib); eye LEDs in mock mode.")
        return

    try:
        _buf = bytearray(len(_order) * _count)
        _gpio = SimpleNamespace(id=_pin)
        neopixel_write(_gpio, bytes(_buf))

        _stop.clear()
        _anim_thread = threading.Thread(target=_frame_loop, daemon=True)
        _anim_thread.start()
        print(f"[eyes] Initialized {_count} {_order} eye LEDs on GPIO {_pin}.")
    except Exception as e:
        _gpio = None
        print(f"[eyes] LED init warning ({e}); eye LED animation disabled.")


def parse_order(order: str) -> str:
    """Normalise a colour byte order ("grbw" -> "GRBW"); anything that is not
    a permutation of RGB or RGBW falls back to GRBW, the pixels fitted."""
    order = order.strip().upper()
    if sorted(order) not in (["B", "G", "R"], ["B", "G", "R", "W"]):
        print(f"[eyes] Ignoring colour order {order!r}; using GRBW.")
        return "GRBW"
    return order


def pixel_bytes(rgbw: tuple[int, ...], order: str) -> bytes:
    """One pixel's bytes on the wire. A 3-tuple leaves the white channel dark."""
    channel = dict(zip("RGBW", (*rgbw, 0)[:4]))
    return bytes(channel[c] for c in order)


def frame(now: float | None = None) -> es.Frame:
    """The state the next frame is resolved from."""
    now = time.monotonic() if now is None else now
    with _lock:
        _blips[:] = [b for b in _blips if now < b.until]
        if _fade_out_at is not None:
            fade = max(0.0, 1.0 - (now - _fade_out_at) / SHUTDOWN_FADE_SECS)
        else:
            fade = min(1.0, (now - _started_at) / BOOT_FADE_SECS)
        return es.Frame(
            now=now, mood_rgb=_mood_rgb, wake_at=_wake_at, activity=_activity,
            activity_since=_activity_since, amplitude=_amplitude,
            confirming=now < _confirm_until, health=_health, blips=list(_blips),
            links=list(_links), tasks=list(_tasks), scale=_scale, calm=_calm, fade=fade)


def _frame_loop() -> None:
    while not _stop.is_set():
        left, right = es.resolve(frame())
        n = len(_order)
        for i in range(_count):
            _buf[i * n:(i + 1) * n] = pixel_bytes(left if i == 0 else right, _order)
        try:
            neopixel_write(_gpio, bytes(_buf))
        except Exception:
            pass
        if _stop.wait(1 / 50):
            break


# ── Activity (main.py) ─────────────────────────────────────────────────────────

def _set_activity(name: str) -> None:
    global _activity, _activity_since
    with _lock:
        if _activity != name:
            _activity, _activity_since = name, time.monotonic()


def wake() -> None:
    """The wake word: a white flash, like an eye opening, then the status lights
    while he listens."""
    global _wake_at
    with _lock:
        _wake_at = time.monotonic()
    _set_activity("")


def think(active: bool = True) -> None:
    """Waiting on Claude or running tools: a slow left-right ping-pong."""
    _set_activity("thinking" if active else "")


def on() -> None:
    """About to speak: full brightness until the voice's amplitude arrives."""
    global _amplitude
    _amplitude = 1.0
    _set_activity("speaking")


def set_amplitude(amp: float) -> None:
    """Follow a normalized speech amplitude (0-1) while speaking."""
    global _amplitude
    _amplitude = 0.2 + 0.8 * min(1.0, amp * 5.0)
    _set_activity("speaking")


def off() -> None:
    """Done talking: back to the status lights."""
    _set_activity("")


def set_mood_colour(rgb: tuple[int, int, int]) -> None:
    """The colour activity is drawn in: the display's iris colour for the mood."""
    global _mood_rgb
    _mood_rgb = tuple(max(0, min(255, int(c))) for c in rgb[:3])


def set_confirming(until: float | None) -> None:
    """Waiting for a spoken yes/no until time.time() reaches `until` (None: not)."""
    global _confirm_until
    _confirm_until = 0.0 if until is None else time.monotonic() + max(0.0, until - time.time())


# ── Status (core/eye_watch.py) ─────────────────────────────────────────────────

def set_status(links: list[es.Light], tasks: list[es.Light], health: es.Light | None,
               scale: float = 1.0, calm: bool = False) -> None:
    """Replace the status layers: left-eye links (best first), right-eye tasks,
    a machine-health override, and the room's brightness modifiers."""
    global _links, _tasks, _health, _scale, _calm
    with _lock:
        _links, _tasks, _health = list(links), list(tasks), health
        _scale, _calm = scale, calm


def blip(light: es.Light, eyes: str = "both", secs: float = 1.0) -> None:
    """Show `light` on `eyes` for `secs`, over the status lights."""
    now = time.monotonic()
    with _lock:
        _blips.append(es.Blip(dataclasses.replace(light, since=now), eyes, now + secs))


def cleanup() -> None:
    """Fade the LEDs out and release them."""
    global _fade_out_at
    if _anim_thread is not None and _anim_thread.is_alive():
        with _lock:
            _fade_out_at = time.monotonic()
        time.sleep(SHUTDOWN_FADE_SECS)
    _stop.set()
    if _anim_thread is not None and _anim_thread.is_alive():
        try:
            _anim_thread.join(timeout=0.5)
        except Exception:
            pass
    if _gpio is not None:
        try:
            neopixel_write(_gpio, bytes(len(_buf)))
        except Exception:
            pass

atexit.register(cleanup)
