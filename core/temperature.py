"""
Internal temperature monitoring for Omega-7.

On a Raspberry Pi this reads the SoC temperature and, when it climbs past a
threshold, queues a spoken warning that main.py drains and voices — the same
"background producer, main-loop speaks" pattern used by reminders and camera
observations. On non-Pi hosts there is no sensor, so
the monitor disables itself and the skull is unaffected.

Hysteresis + cooldown keep it from nagging:
  - warns the moment the temperature crosses the high threshold,
  - if it stays hot, re-warns at most once per cooldown,
  - once it cools below the clear threshold it re-arms for an immediate warning
    on the next spike.
"""

from __future__ import annotations
import threading
import time

from core import config

# Standard SoC thermal sensor on the Raspberry Pi (and most Linux SBCs).
_SENSOR = config.THERMAL_SENSOR_PATH

_lock = threading.Lock()
_pending: str | None = None   # warning text waiting for the main loop to speak
_armed = True                 # True when cooled below clear threshold (ready to warn)
_last_warn = 0.0              # monotonic timestamp of the last warning


def read_temp_c() -> float | None:
    """Current SoC temperature in °C, or None if no sensor is present (non-Pi)."""
    try:
        with open(_SENSOR) as f:
            return int(f.read().strip()) / 1000.0
    except Exception:
        # Fall back to vcgencmd if the sysfs node is missing but we're on a Pi.
        try:
            import subprocess
            out = subprocess.run(
                ["vcgencmd", "measure_temp"], capture_output=True, text=True, timeout=2
            ).stdout
            # Format: "temp=54.2'C"
            return float(out.split("=")[1].split("'")[0])
        except Exception:
            return None


def _phrase(temp: float) -> str:
    import random
    t = f"{temp:.0f}"
    return random.choice([
        f"Warning, my Lord. This unit's cogitator core has reached {t} degrees. "
        f"Thermal tolerance is exceeded — improve cooling, lest the machine spirit falter.",
        f"Alert. Core temperature is {t} degrees and rising beyond safe parameters. "
        f"This unit requires cooling, my Lord.",
        f"The Omnissiah's wrath burns within. This unit's core has reached {t} degrees. "
        f"Attend to my cooling before the heat claims this vessel.",
        f"Caution, master. Internal temperature stands at {t} degrees. "
        f"Prolonged operation at this heat risks thermal throttling of this unit's cogitator.",
    ])


def get_warning() -> str | None:
    """Pop the pending warning (if any) for the main loop to speak."""
    global _pending
    with _lock:
        w = _pending
        _pending = None
        return w


def has_pending() -> bool:
    with _lock:
        return _pending is not None


def _monitor() -> None:
    global _pending, _armed, _last_warn
    warn = config.TEMP_WARN_THRESHOLD
    clear = config.TEMP_CLEAR_THRESHOLD
    cooldown = config.TEMP_WARN_COOLDOWN
    interval = config.TEMP_CHECK_INTERVAL

    while True:
        time.sleep(interval)
        temp = read_temp_c()
        if temp is None:
            print("[temp] Sensor became unavailable — stopping monitor.")
            return
        if config.AUDIO_DEBUG:
            print(f"[temp] {temp:.1f}°C (warn≥{warn}, clear≤{clear}, armed={_armed})")
        now = time.monotonic()
        with _lock:
            if temp >= warn:
                if _armed or (now - _last_warn) >= cooldown:
                    _pending = _phrase(temp)
                    _armed = False
                    _last_warn = now
                    print(f"[temp] HIGH {temp:.1f}°C — queued spoken warning")
            elif temp <= clear:
                if not _armed:
                    print(f"[temp] Cooled to {temp:.1f}°C — re-armed")
                _armed = True


def start() -> None:
    """Launch the background monitor. No-op (with a log line) when no sensor exists."""
    if not config.TEMP_MONITOR_ENABLED:
        print("[temp] Temperature monitoring disabled (TEMP_MONITOR_ENABLED=false).")
        return
    if read_temp_c() is None:
        print("[temp] No SoC temperature sensor on this host — monitor disabled.")
        return
    threading.Thread(target=_monitor, daemon=True, name="temp-monitor").start()
    print(f"[temp] Monitoring core temperature (warn ≥ {config.TEMP_WARN_THRESHOLD}°C, "
          f"re-arm ≤ {config.TEMP_CLEAR_THRESHOLD}°C, every {config.TEMP_CHECK_INTERVAL}s).")


# ── Power supply (under-voltage) ─────────────────────────────────────────────────
# The Pi firmware reports supply trouble through `vcgencmd get_throttled`:
#   bit 0  = under-voltage right now      bit 16 = under-voltage has occurred since boot
#   bit 2  = currently throttled          bit 18 = throttling has occurred since boot
_UNDERVOLT_NOW = 0x1
_UNDERVOLT_SINCE_BOOT = 0x10000

_power_lock = threading.Lock()
_power_state = {
    "available": False,        # True once vcgencmd answered
    "under_voltage_now": False,
    "under_voltage_since_boot": False,
    "events": 0,               # under-voltage onsets seen by this process
    "last_event": None,        # epoch seconds of the most recent onset
    "min_volts": None,         # lowest 5 V reading seen during an event
    "volts": None,             # latest 5 V input reading (Pi 5 only)
}
_last_power_warn = 0.0


def _read_throttled() -> int | None:
    try:
        import subprocess
        out = subprocess.run(["vcgencmd", "get_throttled"], capture_output=True, text=True, timeout=2).stdout
        return int(out.strip().split("=")[1], 16)
    except Exception:
        return None


def _read_5v() -> float | None:
    """Pi 5 PMIC reading of the 5 V input, or None on other boards."""
    try:
        import subprocess
        out = subprocess.run(["vcgencmd", "pmic_read_adc", "EXT5V_V"], capture_output=True, text=True, timeout=2).stdout
        return float(out.strip().split("=")[1].rstrip("V"))
    except Exception:
        return None


def power_status() -> dict:
    """Snapshot of power-supply health for the web remote."""
    with _power_lock:
        return dict(_power_state)


def _power_phrase() -> str:
    import random
    return random.choice([
        "Warning, my Lord. This unit's power supply is failing — voltage has dropped below safe limits. "
        "Provide a stronger power source, lest my memory-coils be corrupted.",
        "Alert. Under-voltage detected in my power conduits. The machine spirit starves. "
        "This unit requires a proper power supply.",
        "Caution, master. My power feed is faltering. Sustained under-voltage risks a sudden "
        "shutdown and damage to my data-vaults.",
    ])


def _queue_warning(text: str) -> None:
    global _pending
    with _lock:
        _pending = f"{_pending} {text}" if _pending else text


def _power_monitor() -> None:
    global _last_power_warn
    from core import quiet
    was_low = False
    while True:
        flags = _read_throttled()
        if flags is not None:
            volts = _read_5v()
            low = bool(flags & _UNDERVOLT_NOW)
            with _power_lock:
                s = _power_state
                s["available"] = True
                s["under_voltage_now"] = low
                s["under_voltage_since_boot"] = bool(flags & _UNDERVOLT_SINCE_BOOT)
                s["volts"] = volts
                if low and volts is not None and (s["min_volts"] is None or volts < s["min_volts"]):
                    s["min_volts"] = volts
                if low and not was_low:
                    s["events"] += 1
                    s["last_event"] = time.time()
            if low and not was_low:
                v = f" (5V input {volts:.2f} V)" if volts is not None else ""
                print(f"[power] WARNING: under-voltage detected{v}, flags=0x{flags:x}. "
                      f"The power supply cannot keep up; brown-outs crash the Pi and corrupt files.")
                now = time.monotonic()
                if (now - _last_power_warn) >= config.POWER_WARN_COOLDOWN and not quiet.is_in_sleep_hours():
                    _queue_warning(_power_phrase())
                    _last_power_warn = now
            elif was_low and not low:
                print("[power] Supply voltage recovered.")
            was_low = low
        time.sleep(config.POWER_CHECK_INTERVAL)


def start_power_monitor() -> None:
    """Launch the under-voltage monitor. No-op off a Raspberry Pi."""
    if not config.POWER_MONITOR_ENABLED:
        return
    flags = _read_throttled()
    if flags is None:
        print("[power] vcgencmd unavailable — power monitor disabled.")
        return
    if flags & _UNDERVOLT_SINCE_BOOT:
        print(f"[power] Note: under-voltage has already occurred since boot (flags=0x{flags:x}).")
    threading.Thread(target=_power_monitor, daemon=True, name="power-monitor").start()
    print(f"[power] Monitoring power supply for under-voltage every {config.POWER_CHECK_INTERVAL:g}s.")
