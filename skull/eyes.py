"""
Controls the red eye LEDs via GPIO PWM.

While idle the three eyes "breathe" — each fades in and out independently around
a low baseline glow, so the skull always looks faintly alive but never in unison.
During speech/attention the brightness tracks the speech amplitude instead.
"""

import math
import time
import threading

_gpio_available = False
_pwm_left = None
_pwm_center = None
_pwm_right = None
_pwms: list = []          # [left, center, right] for per-eye writes

PWM_FREQ = 100            # Hz — above visible flicker threshold

# Idle breathing: each eye fades between IDLE_MIN and IDLE_MAX on its own slow
# sine. Non-harmonic periods + offset phases keep the three drifting in and out
# independently rather than pulsing together.
IDLE_MIN = 10.0           # baseline — eyes stay "somewhat on" at the trough
IDLE_MAX = 50.0
_BREATH = [(3.1, 0.0), (4.7, 1.7), (5.9, 3.4)]  # (period_s, phase_rad) per eye

_stop = threading.Event()
_anim_thread: threading.Thread | None = None
_speaking = False         # True while speech/attention is driving the eyes directly

try:
    import RPi.GPIO as GPIO
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    _gpio_available = True
except (ImportError, RuntimeError):
    pass


def setup(pin_left: int, pin_center: int, pin_right: int) -> None:
    global _pwm_left, _pwm_center, _pwm_right, _pwms, _anim_thread
    if not _gpio_available:
        return
    for pin in (pin_left, pin_center, pin_right):
        GPIO.setup(pin, GPIO.OUT, initial=GPIO.LOW)
    _pwm_left = GPIO.PWM(pin_left, PWM_FREQ)
    _pwm_center = GPIO.PWM(pin_center, PWM_FREQ)
    _pwm_right = GPIO.PWM(pin_right, PWM_FREQ)
    for pwm in (_pwm_left, _pwm_center, _pwm_right):
        pwm.start(0)
    _pwms = [_pwm_left, _pwm_center, _pwm_right]

    _stop.clear()
    _anim_thread = threading.Thread(target=_breathe_loop, daemon=True)
    _anim_thread.start()


def _breathe_loop() -> None:
    """Animate the independent idle breathing whenever the eyes aren't being
    driven by speech/attention."""
    t0 = time.monotonic()
    while not _stop.is_set():
        if not _speaking and _pwms:
            now = time.monotonic() - t0
            for pwm, (period, phase) in zip(_pwms, _BREATH):
                frac = 0.5 + 0.5 * math.sin(2 * math.pi * now / period + phase)
                try:
                    pwm.ChangeDutyCycle(IDLE_MIN + (IDLE_MAX - IDLE_MIN) * frac)
                except Exception:
                    pass
        time.sleep(1 / 50)


def set_brightness(pct: float) -> None:
    """Set all three eyes to the same brightness 0–100."""
    if not _gpio_available or _pwm_left is None:
        return
    pct = max(0.0, min(100.0, pct))
    _pwm_left.ChangeDutyCycle(pct)
    _pwm_center.ChangeDutyCycle(pct)
    _pwm_right.ChangeDutyCycle(pct)


def on() -> None:
    """Steady full-intensity gaze (e.g. while attending a command)."""
    global _speaking
    _speaking = True
    set_brightness(100)


def off() -> None:
    """Return to the idle breathing glow (the eyes are never fully dark while
    running; use cleanup() to extinguish them)."""
    global _speaking
    _speaking = False


def set_amplitude(amp: float) -> None:
    """Map a normalized amplitude (0–1) to eye brightness during speech."""
    global _speaking
    _speaking = True
    # Low-end lift so eyes never go fully dark while speaking,
    # then scale up sharply — red eyes should look intense.
    pct = 20.0 + 80.0 * min(1.0, amp * 5)
    set_brightness(pct)


def cleanup() -> None:
    _stop.set()
    if _anim_thread is not None:
        _anim_thread.join(timeout=1.0)
    if _gpio_available:
        set_brightness(0)
        for pwm in (_pwm_left, _pwm_center, _pwm_right):
            if pwm:
                pwm.stop()
        GPIO.cleanup()
