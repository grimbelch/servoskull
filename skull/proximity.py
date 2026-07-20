"""
VL53L1X time-of-flight proximity sensor (I2C) — tells the camera when someone is
physically close, replacing frame-difference motion as the vision trigger.

Why ToF over the old motion approach: a laser rangefinder fires only on genuine
physical approach (no false trips from auto-exposure or a changing scene) and it
works in a dark room, where frame differencing sees nothing. If the sensor or its
library is absent (the Mac/Windows emulator, or a Pi without the sensor wired),
every entry point is a silent no-op and camera.py falls back to motion detection.
Mirrors the defensive pattern in eyes.py / display.py.

Enable with PROXIMITY_ENABLED=true in .env. Wiring lives in config.py.
"""

from __future__ import annotations
import threading

from skull import config

_tof = None
_available = False
_lock = threading.Lock()  # I2C transactions aren't reentrant; serialize reads


def start() -> bool:
    """Open the sensor and begin continuous ranging.

    Returns True on success, False (a silent no-op) if proximity is disabled, the
    library is missing, or no sensor answers on the bus — the caller then falls
    back to motion detection.
    """
    global _tof, _available
    if not config.PROXIMITY_ENABLED:
        return False
    try:
        # Drive XSHUT pin HIGH to boot up the sensor
        try:
            import RPi.GPIO as GPIO
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)
            GPIO.setup(config.PROXIMITY_XSHUT_PIN, GPIO.OUT, initial=GPIO.HIGH)
            import time
            time.sleep(0.1)  # 100ms to allow VL53L1X to boot up and initialize I2C
            print(f"[proximity] Driven XSHUT (GPIO {config.PROXIMITY_XSHUT_PIN}) HIGH.")
        except Exception as ge:
            print(f"[proximity] GPIO setup warning (XSHUT pin {config.PROXIMITY_XSHUT_PIN}): {ge}")

        import VL53L1X
        tof = VL53L1X.VL53L1X(
            i2c_bus=config.PROXIMITY_I2C_BUS,
            i2c_address=config.PROXIMITY_I2C_ADDR,
        )
        tof.open()
        tof.start_ranging(config.PROXIMITY_RANGE_MODE)
        _tof = tof
        _available = True
        print(
            f"[proximity] VL53L1X ranging on i2c-{config.PROXIMITY_I2C_BUS} "
            f"@ 0x{config.PROXIMITY_I2C_ADDR:02x} "
            f"(mode {config.PROXIMITY_RANGE_MODE}, trigger < {config.PROXIMITY_THRESHOLD_CM} cm)"
        )
        return True
    except Exception as e:
        print(f"[proximity] Sensor unavailable ({e}) — camera will use motion detection")
        _available = False
        return False


def available() -> bool:
    """True once start() has successfully opened a sensor."""
    return _available


def read_cm() -> float | None:
    """Latest distance in centimetres, or None if unavailable/no valid target.

    The VL53L1X reports 0 mm when it has no valid return (out of range, no target,
    or a failed measurement); we treat that as None rather than "0 cm away".
    """
    if not _available or _tof is None:
        return None
    try:
        with _lock:
            mm = _tof.get_distance()
    except Exception:
        return None
    if mm is None or mm <= 0:
        return None
    return mm / 10.0


def stop() -> None:
    """Stop ranging and release the bus. Safe to call when never started."""
    global _tof, _available
    if _tof is None:
        return
    try:
        with _lock:
            _tof.stop_ranging()
            _tof.close()
    except Exception:
        pass
    
    # Drive XSHUT low to put sensor back in shutdown/low-power state
    try:
        import RPi.GPIO as GPIO
        GPIO.setup(config.PROXIMITY_XSHUT_PIN, GPIO.OUT)
        GPIO.output(config.PROXIMITY_XSHUT_PIN, GPIO.LOW)
    except Exception:
        pass

    _tof = None
    _available = False
