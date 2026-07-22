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

from skull import config

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
