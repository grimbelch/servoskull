"""
VL53L1X time-of-flight proximity sensor (I2C) — tells the camera, web interface,
and idle loops when someone is physically close.

Enable with PROXIMITY_ENABLED=true in .env. Wiring lives in config.py.
"""

from __future__ import annotations
import threading
import time
import collections
import json

from core import config

_tof = None
_available = False
_lock = threading.Lock()  # I2C transactions serialization

_polling_thread: threading.Thread | None = None
_polling_active: bool = False
_last_cm: float | None = None
_last_poll_time: float = 0.0
_readings_buffer = collections.deque(maxlen=10)
_poll_lock = threading.Lock()


def _raw_read_cm() -> float | None:
    """Read a single raw measurement from hardware in cm."""
    global _available
    if not _available or _tof is None:
        return None

    try:
        with _lock:
            mm = _tof.get_distance()
    except Exception as e:
        print(f"[proximity] Error reading sensor: {e}.")
        return None

    if mm is None or mm <= 0:
        return None
    return mm / 10.0


_stop_event = threading.Event()


def _continuous_poll_loop() -> None:
    """Background thread continuously polling the rangefinder sensor."""
    global _last_cm, _last_poll_time, _polling_active
    print("[proximity] Continuous rangefinder polling thread started.")
    while _polling_active and _available and not _stop_event.is_set():
        try:
            cm = _raw_read_cm()
            with _poll_lock:
                now_time = time.time()
                if cm is not None and cm > 0:
                    _last_cm = cm
                    _last_poll_time = now_time
                    _readings_buffer.append(cm)
                elif now_time - _last_poll_time > 2.0:
                    _last_cm = None
                    _readings_buffer.clear()
            try:
                from core import db
                db.kv_set("telemetry_proximity", {
                    "enabled": config.PROXIMITY_ENABLED,
                    "available": _available,
                    "distance_cm": round(_last_cm, 1) if _last_cm is not None else None,
                    "timestamp": time.time()
                })
            except Exception:
                pass
        except Exception as e:
            print(f"[proximity] Error in continuous poll loop: {e}")
        if _stop_event.wait(config.PROXIMITY_POLL_INTERVAL):
            break
    print("[proximity] Continuous rangefinder polling thread stopped.")


def start() -> bool:
    """Open the sensor and begin continuous ranging and background polling.

    Returns True on success, False (a silent no-op) if proximity is disabled, the
    library is missing, or no sensor answers on the bus.
    """
    global _tof, _available, _polling_thread, _polling_active
    if not config.PROXIMITY_ENABLED:
        return False

    with _lock:
        if _available and _tof is not None and _polling_active:
            return True
        try:
            try:
                import VL53L1X
            except ImportError:
                import vl53l1x as VL53L1X
            tof = VL53L1X.VL53L1X(
                i2c_bus=config.PROXIMITY_I2C_BUS,
                i2c_address=config.PROXIMITY_I2C_ADDR,
            )
            tof.open()
            if not getattr(tof, "_dev", True):
                raise RuntimeError("Sensor not responding on I2C bus")
            tof.start_ranging(config.PROXIMITY_RANGE_MODE)
            _tof = tof
            _available = True

            # Start continuous background polling thread
            if not _polling_active:
                _polling_active = True
                _polling_thread = threading.Thread(target=_continuous_poll_loop, daemon=True)
                _polling_thread.start()

            print(
                f"[proximity] VL53L1X ranging on i2c-{config.PROXIMITY_I2C_BUS} "
                f"@ 0x{config.PROXIMITY_I2C_ADDR:02x} "
                f"(mode {config.PROXIMITY_RANGE_MODE}, poll interval {config.PROXIMITY_POLL_INTERVAL}s)"
            )
            return True
        except Exception as e:
            print(f"[proximity] Sensor unavailable ({e})")
            _available = False
            _polling_active = False
            return False


def available() -> bool:
    """True once start() has successfully opened a sensor."""
    return _available


def get_latest_distance_cm() -> float | None:
    """Return the latest distance in cm from constant background polling."""
    if not _available:
        return None
    with _poll_lock:
        return _last_cm


def read_cm() -> float | None:
    """Latest distance in centimetres, or None if unavailable/no valid target."""
    return get_latest_distance_cm()


def read_cm_average(samples: int = 3, sample_delay: float = 0.03) -> float | None:
    """Return average of recent distance readings from continuous polling or fresh samples."""
    if not _available:
        return None

    with _poll_lock:
        if len(_readings_buffer) >= samples:
            recent = list(_readings_buffer)[-samples:]
            return sum(recent) / len(recent)
        if _last_cm is not None:
            return _last_cm

    # Fallback if buffer empty
    readings = []
    for _ in range(samples):
        cm = _raw_read_cm()
        if cm is not None and cm > 0:
            readings.append(cm)
        time.sleep(sample_delay)
    if not readings:
        return None
    return sum(readings) / len(readings)


def is_target_within(max_feet: float = 5.0) -> bool | None:
    """Check if a target is detected by the rangefinder within max_feet (default 5.0 ft / 152.4 cm).

    Returns:
        True  — sensor is active and target is detected <= max_feet.
        False — sensor is active and target is > max_feet or out of range / no target (None).
        None  — sensor is disabled or unavailable on hardware.
    """
    if not config.PROXIMITY_ENABLED or not _available:
        return None

    max_cm = max_feet * 12.0 * 2.54  # 5 feet = 152.4 cm
    cm = get_latest_distance_cm()

    if cm is None or cm > max_cm:
        return False
    return True


def stop() -> None:
    """Stop ranging, stop background thread, and release the bus."""
    global _tof, _available, _polling_active
    _polling_active = False
    if _tof is None:
        return
    try:
        with _lock:
            _tof.stop_ranging()
            _tof.close()
    except Exception:
        pass

    _tof = None
    _available = False


def get_distance_summary_short() -> str:
    """Return a short distance summary string for UI displays."""
    if not config.PROXIMITY_ENABLED:
        return "DISABLED"
    if not _available:
        return "UNAVAILABLE"

    cm = get_latest_distance_cm()
    if cm is None or cm <= 0:
        return "OUT OF RANGE (> 4.0 m)"

    meters = cm / 100.0
    return f"{cm:.1f} cm ({meters:.2f} m)"


def get_distance_summary() -> str:
    """Return a human-readable distance measurement string."""
    if not config.PROXIMITY_ENABLED or not _available:
        return "Laser rangefinder sensor is disabled or unavailable."

    avg_cm = read_cm_average(samples=4)
    if not avg_cm:
        return "Target is out of range or no obstacle was detected by the rangefinder."

    inches = avg_cm / 2.54
    feet = inches / 12.0

    if feet >= 1.0:
        feet_int = int(feet)
        rem_inches = round(inches % 12)
        if rem_inches == 12:
            feet_int += 1
            rem_inches = 0
        return f"{avg_cm:.1f} cm ({feet_int} feet, {rem_inches} inches)"
    else:
        return f"{avg_cm:.1f} cm ({inches:.1f} inches)"
