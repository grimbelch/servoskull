"""
VL53L1X time-of-flight proximity sensor (I2C) — tells the camera and idle loops when someone is
physically close, replacing frame-difference motion as the vision trigger.

Why ToF over the old motion approach: a laser rangefinder fires only on genuine
physical approach (no false trips from auto-exposure or a changing scene) and it
works in a dark room, where frame differencing sees nothing. If the sensor or its
library is absent (non-Pi dev hosts, or a Pi without the sensor wired),
every entry point is a silent no-op and camera.py falls back to motion detection.
Mirrors the defensive pattern in eyes.py / display.py.

Enable with PROXIMITY_ENABLED=true in .env. Wiring lives in config.py.
"""

from __future__ import annotations
import threading
import time
import collections

from skull import config

_tof = None
_available = False
_lock = threading.Lock()  # I2C transactions aren't reentrant; serialize reads

_polling_thread: threading.Thread | None = None
_polling_active: bool = False
_last_cm: float | None = None
_last_poll_time: float = 0.0
_readings_buffer = collections.deque(maxlen=10)
_poll_lock = threading.Lock()


def _patch_vl53l1x():
    """Monkeypatch VL53L1X to catch I2C errors in ctypes callbacks."""
    try:
        import VL53L1X
        from ctypes import CFUNCTYPE, c_int, c_ubyte, POINTER, c_uint16
        from smbus2 import i2c_msg
    except ImportError:
        return

    _I2C_MULTI_FUNC = CFUNCTYPE(c_int, c_ubyte, c_uint16)
    _I2C_READ_FUNC = CFUNCTYPE(c_int, c_ubyte, c_uint16, POINTER(c_ubyte), c_ubyte)
    _I2C_WRITE_FUNC = CFUNCTYPE(c_int, c_ubyte, c_uint16, POINTER(c_ubyte), c_ubyte)

    def custom_configure(self):
        self._i2c_error = False

        def _i2c_read(address, reg, data_p, length):
            if self._i2c_error:
                return -1
            try:
                msg_w = i2c_msg.write(address, [reg >> 8, reg & 0xff])
                msg_r = i2c_msg.read(address, length)
                self._i2c.i2c_rdwr(msg_w, msg_r)
                for index in range(length):
                    data_p[index] = ord(msg_r.buf[index])
                return 0
            except Exception as e:
                self._i2c_error = True
                print(f"[proximity] I2C read error: {e}")
                return -1

        def _i2c_write(address, reg, data_p, length):
            if self._i2c_error:
                return -1
            try:
                data = [data_p[index] for index in range(length)]
                msg_w = i2c_msg.write(address, [reg >> 8, reg & 0xff] + data)
                self._i2c.i2c_rdwr(msg_w)
                return 0
            except Exception as e:
                self._i2c_error = True
                print(f"[proximity] I2C write error: {e}")
                return -1

        def _i2c_multi(address, reg):
            if self._i2c_error:
                return -1
            try:
                self._i2c.write_byte(address, reg)
                return 0
            except Exception as e:
                self._i2c_error = True
                print(f"[proximity] I2C multi-write error: {e}")
                return -1

        self._i2c_multi_func = _I2C_MULTI_FUNC(_i2c_multi)
        self._i2c_read_func = _I2C_READ_FUNC(_i2c_read)
        self._i2c_write_func = _I2C_WRITE_FUNC(_i2c_write)
        VL53L1X._TOF_LIBRARY.VL53L1_set_i2c(self._i2c_multi_func, self._i2c_read_func, self._i2c_write_func)

    VL53L1X.VL53L1X._configure_i2c_library_functions = custom_configure


def _raw_read_cm() -> float | None:
    """Read a single raw measurement from hardware."""
    global _available
    if not _available or _tof is None:
        return None

    if getattr(_tof, "_i2c_error", False):
        print("[proximity] VL53L1X flagged I2C error. Disabling proximity sensor.")
        _available = False
        try:
            with _lock:
                _tof.stop_ranging()
                _tof.close()
        except Exception:
            pass
        return None

    try:
        with _lock:
            mm = _tof.get_distance()
    except Exception as e:
        print(f"[proximity] Error reading sensor: {e}. Disabling sensor.")
        _available = False
        return None

    if getattr(_tof, "_i2c_error", False):
        return None

    if mm is None or mm <= 0:
        return None
    return mm / 10.0


def _continuous_poll_loop() -> None:
    """Background thread continuously polling the rangefinder sensor."""
    global _last_cm, _last_poll_time, _polling_active
    print("[proximity] Continuous rangefinder polling thread started.")
    while _polling_active and _available:
        try:
            cm = _raw_read_cm()
            with _poll_lock:
                _last_cm = cm
                _last_poll_time = time.time()
                if cm is not None:
                    _readings_buffer.append(cm)
        except Exception as e:
            print(f"[proximity] Error in continuous poll loop: {e}")
        time.sleep(config.PROXIMITY_POLL_INTERVAL)
    print("[proximity] Continuous rangefinder polling thread stopped.")


def start() -> bool:
    """Open the sensor and begin continuous ranging and background polling.

    Returns True on success, False (a silent no-op) if proximity is disabled, the
    library is missing, or no sensor answers on the bus.
    """
    global _tof, _available, _polling_thread, _polling_active
    if not config.PROXIMITY_ENABLED:
        return False
    if _available and _tof is not None and _polling_active:
        return True
    try:
        # Drive XSHUT pin HIGH to boot up the sensor
        try:
            import RPi.GPIO as GPIO
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)
            GPIO.setup(config.PROXIMITY_XSHUT_PIN, GPIO.OUT, initial=GPIO.HIGH)
            time.sleep(0.1)  # 100ms to allow VL53L1X to boot up and initialize I2C
            print(f"[proximity] Driven XSHUT (GPIO {config.PROXIMITY_XSHUT_PIN}) HIGH.")
        except Exception as ge:
            print(f"[proximity] GPIO setup warning (XSHUT pin {config.PROXIMITY_XSHUT_PIN}): {ge}")

        _patch_vl53l1x()
        import VL53L1X
        tof = VL53L1X.VL53L1X(
            i2c_bus=config.PROXIMITY_I2C_BUS,
            i2c_address=config.PROXIMITY_I2C_ADDR,
        )
        tof.open()
        if getattr(tof, "_i2c_error", False) or not tof._dev:
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
    if not _available and config.PROXIMITY_ENABLED:
        start()
    if not _available:
        return None
    with _poll_lock:
        return _last_cm


def read_cm() -> float | None:
    """Latest distance in centimetres, or None if unavailable/no valid target."""
    return get_latest_distance_cm()


def read_cm_average(samples: int = 3, sample_delay: float = 0.03) -> float | None:
    """Return average of recent distance readings from continuous polling or fresh samples."""
    if not available() and config.PROXIMITY_ENABLED:
        start()
    if not available():
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
    if not config.PROXIMITY_ENABLED:
        return None
    if not available():
        start()
    if not available():
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

    # Drive XSHUT low to put sensor back in shutdown/low-power state
    try:
        import RPi.GPIO as GPIO
        GPIO.setup(config.PROXIMITY_XSHUT_PIN, GPIO.OUT)
        GPIO.output(config.PROXIMITY_XSHUT_PIN, GPIO.LOW)
    except Exception:
        pass

    _tof = None
    _available = False


def get_distance_summary_short() -> str:
    """Return a short distance summary string for UI displays."""
    if not config.PROXIMITY_ENABLED:
        return "DISABLED"
    if not available():
        start()
    if not available():
        return "UNAVAILABLE"

    cm = get_latest_distance_cm()
    if cm is None or cm <= 0:
        return "OUT OF RANGE (> 8.0 m)"

    meters = cm / 100.0
    return f"{cm:.1f} cm ({meters:.2f} m)"


def get_distance_summary() -> str:
    """Return a human-readable distance measurement string."""
    if not available() and config.PROXIMITY_ENABLED:
        start()
    if not available():
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


# Auto-start continuous polling if proximity is enabled in config
if config.PROXIMITY_ENABLED:
    try:
        threading.Thread(target=start, daemon=True).start()
    except Exception as _e:
        print(f"[proximity] Auto-start error: {_e}")
