"""
Silent-mode state and Sleep Schedule (Quiet Hours) for Omega-7. When enabled,
Omega-7 stops making unprompted periodic observations and remains silent during
configured sleep hours (default Midnight – 7:00 AM). Direct conversations and
on-demand requests are unaffected. Persists across restarts via quiet.json.
"""

from __future__ import annotations
from datetime import datetime
import json
import pathlib
import threading

from core import config

_FILE = config.data_path("quiet.json")
_lock = threading.Lock()

_state: dict = {
    "silent": False,
    "sleep_start_hour": 0,          # 00:00 (Midnight)
    "sleep_end_hour": 7,            # 07:00 (7:00 AM)
    "sleep_schedule_enabled": True,
}


def _load() -> None:
    global _state
    try:
        if _FILE.exists():
            with _FILE.open() as f:
                data = json.load(f)
                if isinstance(data, dict):
                    _state.update(data)
            print(f"[quiet] Restored: silent={_state.get('silent', False)}, "
                  f"sleep_schedule={_state.get('sleep_start_hour', 0):02d}:00–{_state.get('sleep_end_hour', 7):02d}:00")
    except Exception:
        pass


def _save() -> None:
    try:
        with _FILE.open("w") as f:
            json.dump(_state, f, indent=2)
    except Exception as e:
        print(f"[quiet] Save error: {e}")


_load()


def is_in_sleep_hours() -> bool:
    """Return True if current time falls within configured sleep schedule hours."""
    with _lock:
        if not _state.get("sleep_schedule_enabled", True):
            return False
        start = int(_state.get("sleep_start_hour", 0))
        end = int(_state.get("sleep_end_hour", 7))

    now_hour = datetime.now().hour
    if start == end:
        return False
    elif start < end:
        return start <= now_hour < end
    else:  # Overnight span (e.g. 23:00 to 07:00)
        return now_hour >= start or now_hour < end


def is_silent() -> bool:
    """Return True if manual silent mode is active OR current time is in sleep hours."""
    with _lock:
        manual_silent = bool(_state.get("silent", False))
    return manual_silent or is_in_sleep_hours()


def set_silent(enabled: bool) -> bool:
    """Enable or disable manual silent mode. Returns the new state."""
    with _lock:
        prev = bool(_state.get("silent", False))
        _state["silent"] = bool(enabled)
        if _state["silent"] != prev:
            _save()
            print(f"[quiet] Silent mode {'ON' if enabled else 'OFF'}")
    return bool(enabled)


def set_sleep_schedule(start_hour: int, end_hour: int, enabled: bool = True) -> tuple[int, int, str]:
    """Set quiet hours sleep schedule (hours 0–23). Returns (start_hour, end_hour, text_summary)."""
    start_hour = max(0, min(23, int(start_hour)))
    end_hour = max(0, min(23, int(end_hour)))

    with _lock:
        _state["sleep_start_hour"] = start_hour
        _state["sleep_end_hour"] = end_hour
        _state["sleep_schedule_enabled"] = bool(enabled)
        _save()

    def _fmt(h: int) -> str:
        if h == 0 or h == 24:
            return "Midnight"
        elif h == 12:
            return "12:00 PM (Noon)"
        elif h < 12:
            return f"{h}:00 AM"
        else:
            return f"{h - 12}:00 PM"

    summary = f"Sleep schedule set from {_fmt(start_hour)} to {_fmt(end_hour)}."
    print(f"[quiet] {summary}")
    return start_hour, end_hour, summary


def get_sleep_schedule() -> dict:
    """Return current sleep schedule configuration dictionary."""
    with _lock:
        return {
            "start_hour": int(_state.get("sleep_start_hour", 0)),
            "end_hour": int(_state.get("sleep_end_hour", 7)),
            "enabled": bool(_state.get("sleep_schedule_enabled", True)),
            "in_sleep_hours": is_in_sleep_hours(),
        }

