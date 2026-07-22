"""
Controls the self-flickering candle LEDs atop the skull via a single GPIO.

The EDGELEC 2V flicker LEDs generate their flame effect on an internal IC — the
Pi doesn't animate them. A GPIO drives a 2N2222 low-side transistor switch that
simply gates the candles on/off, so the skull lights its candles when it wakes and
snuffs them when it powers down.

Mirrors eyes.py: if the hardware/libs are absent (non-Pi dev host) or
CANDLE_ENABLED is false, every entry point is a silent no-op.
"""

from __future__ import annotations

from skull import config

_gpio_available = False
_pin: int | None = None

try:
    import RPi.GPIO as GPIO
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    _gpio_available = True
except (ImportError, RuntimeError):
    pass


def setup(pin: int) -> None:
    """Claim the candle GPIO as an output, initially off. No-op if disabled/absent."""
    global _pin
    if not (config.CANDLE_ENABLED and _gpio_available):
        return
    _pin = pin
    GPIO.setup(pin, GPIO.OUT, initial=GPIO.LOW)


def on() -> None:
    """Light the candles (drives the transistor gate high)."""
    if _pin is not None:
        GPIO.output(_pin, GPIO.HIGH)


def off() -> None:
    """Snuff the candles."""
    if _pin is not None:
        GPIO.output(_pin, GPIO.LOW)


def cleanup() -> None:
    """Snuff the candles on shutdown. Safe to call when never set up."""
    off()
