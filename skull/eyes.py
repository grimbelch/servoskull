"""
Controls the red eye LEDs via GPIO PWM.
Brightness tracks speech amplitude during playback.
"""

import time
import threading

_gpio_available = False
_pwm_left = None
_pwm_right = None

PWM_FREQ = 100  # Hz — above visible flicker threshold

try:
    import RPi.GPIO as GPIO
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    _gpio_available = True
except (ImportError, RuntimeError):
    pass


def setup(pin_left: int, pin_right: int) -> None:
    global _pwm_left, _pwm_right
    if not _gpio_available:
        return
    GPIO.setup(pin_left, GPIO.OUT, initial=GPIO.LOW)
    GPIO.setup(pin_right, GPIO.OUT, initial=GPIO.LOW)
    _pwm_left = GPIO.PWM(pin_left, PWM_FREQ)
    _pwm_right = GPIO.PWM(pin_right, PWM_FREQ)
    _pwm_left.start(0)
    _pwm_right.start(0)


def set_brightness(pct: float) -> None:
    """Set eye brightness 0–100."""
    if not _gpio_available or _pwm_left is None:
        return
    pct = max(0.0, min(100.0, pct))
    _pwm_left.ChangeDutyCycle(pct)
    _pwm_right.ChangeDutyCycle(pct)


def on() -> None:
    set_brightness(100)


def off() -> None:
    set_brightness(0)


def set_amplitude(amp: float) -> None:
    """Map a normalized amplitude (0–1) to eye brightness."""
    # Low-end lift so eyes never go fully dark while speaking,
    # then scale up sharply — red eyes should look intense.
    pct = 20.0 + 80.0 * min(1.0, amp * 5)
    set_brightness(pct)


def cleanup() -> None:
    if _gpio_available:
        set_brightness(0)
        if _pwm_left:
            _pwm_left.stop()
        if _pwm_right:
            _pwm_right.stop()
        GPIO.cleanup()
