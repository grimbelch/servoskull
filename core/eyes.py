"""
Controls the 2 individually addressable eye LEDs (RGBW pixels, see EYE_WIRING.md).

On the Pi 5 the RP1 southbridge owns the GPIO pins, so rpi_ws281x (which drives
the Pi 4's PWM/DMA registers) cannot reach them. The signal is clocked out by
RP1's PIO block instead, through Adafruit's /dev/pio0 writer. Only that writer
is used: Blinka, which its examples pair it with, depends on RPi.GPIO and
rpi_ws281x, and installing those over the rpi-lgpio shim breaks every other GPIO
user on a Pi 5. The handful of bytes is packed here instead.

The pixels fitted are RGBW (SK6812-type, four bytes each, GRBW).

The third eye lens housing is dedicated to the camera mount, so 2 addressable
RGB LEDs (Left Eye = Index 0, Right Eye = Index 1) are driven in series via a
single GPIO data line (default GPIO 18) stepped up from 3.3V to 5.0V with a
logic level shifter.

While idle, the two eye LEDs independently "breathe" with subtle phase-shifted
sine waves in Warhammer Crimson Red (or custom configured RGB color). During
speech/attention, the brightness scales with speech amplitude.
"""

from __future__ import annotations
import math
import time
import threading
import atexit
from types import SimpleNamespace

_speaking_lock = threading.Lock()

_ws281x_available = False
_gpio = None              # what neopixel_write wants: any object with .id = BCM pin
_buf = bytearray()        # the frame, already in the pixels' byte order
_pin: int = 18
_count: int = 2
_order: str = "GRBW"       # colour byte order; a fourth letter means an RGBW pixel

# Global state
_stop = threading.Event()
_anim_thread: threading.Thread | None = None
_speaking = False         # True while speech/attention drives the eyes directly
_brightness = 255.0      # Current master brightness scale (0.0 to 255.0)

# Colors (R, G, B)
_active_color = (255, 0, 0) # Default grimdark crimson red

# Idle breathing parameters: each eye fades between IDLE_MIN and IDLE_MAX
# (percentages of active color intensity). Offset phases keep Left and Right
# eyes drifting independently for a living, cybernetic gaze.
IDLE_MIN = 0.15           # 15% baseline glow at sine trough
IDLE_MAX = 0.60           # 60% max glow at sine peak
_BREATH = [(3.2, 0.0), (4.5, 1.8)]  # (period_s, phase_rad) for [Left, Right]

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
    global _gpio, _buf, _pin, _count, _order, _anim_thread

    _pin = int(pin)
    _count = int(count)
    _order = parse_order(order)

    if not _ws281x_available:
        print("[eyes] Pi 5 NeoPixel driver unavailable (non-Pi host or missing lib); eye animations running in mock mode.")
        _stop.clear()
        _anim_thread = threading.Thread(target=_breathe_loop, daemon=True)
        _anim_thread.start()
        return

    try:
        _buf = bytearray(len(_order) * _count)
        _gpio = SimpleNamespace(id=_pin)
        neopixel_write(_gpio, bytes(_buf))

        _stop.clear()
        _anim_thread = threading.Thread(target=_breathe_loop, daemon=True)
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


def pixel_bytes(rgb: tuple[int, int, int], order: str) -> bytes:
    """One pixel's bytes on the wire. The white channel stays dark: the eyes
    are coloured, never white."""
    channel = dict(zip("RGB", rgb), W=0)
    return bytes(channel[c] for c in order)


def _breathe_loop() -> None:
    """Animate independent idle breathing for Left and Right eye LEDs."""
    t0 = time.monotonic()
    while not _stop.is_set():
        if not _speaking:
            now = time.monotonic() - t0
            for i in range(_count):
                period, phase = _BREATH[i % len(_BREATH)]
                frac = 0.5 + 0.5 * math.sin(2 * math.pi * now / period + phase)
                intensity = IDLE_MIN + (IDLE_MAX - IDLE_MIN) * frac
                _set_pixel(i, intensity)
            _show()
        if _stop.wait(1 / 50): # ~50 FPS refresh
            break


def _set_pixel(index: int, factor: float) -> None:
    """Set pixel color scaled by a factor (0.0 to 1.0) and master brightness."""
    if index >= _count:
        return
    r = int(max(0, min(255, _active_color[0] * factor * (_brightness / 255.0))))
    g = int(max(0, min(255, _active_color[1] * factor * (_brightness / 255.0))))
    b = int(max(0, min(255, _active_color[2] * factor * (_brightness / 255.0))))
    
    if _gpio is not None:
        n = len(_order)
        _buf[index * n:(index + 1) * n] = pixel_bytes((r, g, b), _order)


def _show() -> None:
    """Flush pixel changes to the physical strip."""
    if _gpio is not None:
        try:
            neopixel_write(_gpio, bytes(_buf))
        except Exception:
            pass


def set_color(r: int, g: int, b: int) -> None:
    """Set active RGB color tuple for the eye LEDs (0–255 each)."""
    global _active_color
    _active_color = (max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b)))


def set_brightness(pct: float) -> None:
    """Set master brightness percentage (0–100)."""
    global _brightness
    pct = max(0.0, min(100.0, pct))
    _brightness = (pct / 100.0) * 255.0
    if _speaking:
        for i in range(_count):
            _set_pixel(i, 1.0)
        _show()


def on() -> None:
    """Steady full-intensity gaze (e.g. while attending or executing commands)."""
    global _speaking
    _speaking = True
    set_brightness(100.0)


def off() -> None:
    """Return to the idle breathing glow."""
    global _speaking
    _speaking = False


def set_amplitude(amp: float) -> None:
    """Map a normalized speech amplitude (0–1) to eye brightness."""
    global _speaking
    _speaking = True
    # Baseline lift so eyes remain lit during speech, scaling sharply with volume
    pct = 20.0 + 80.0 * min(1.0, amp * 5.0)
    set_brightness(pct)


def cleanup() -> None:
    """Extinguish LEDs and release hardware resources."""
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


