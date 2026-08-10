"""
Silent-mode state and Sleep Schedule (Quiet Hours) for Omega-7. When enabled,
Omega-7 stops making unprompted periodic observations and remains silent during
configured sleep hours (default Midnight – 7:00 AM). Direct conversations and
on-demand requests are unaffected. Persists across restarts via SQLite KV store.
"""

from __future__ import annotations
from datetime import datetime

from core import config
from core import db

_DEFAULT_STATE = {
    "silent": False,
    "sleep_start_hour": 0,          # 00:00 (Midnight)
    "sleep_end_hour": 7,            # 07:00 (7:00 AM)
    "sleep_schedule_enabled": True,
}

def _get_state() -> dict:
    state = dict(_DEFAULT_STATE)
    saved = db.kv_get("quiet_state", {})
    if isinstance(saved, dict):
        state.update(saved)
    return state

def _save_state(state: dict) -> None:
    db.kv_set("quiet_state", state)

def is_in_sleep_hours() -> bool:
    """Return True if current time falls within configured sleep schedule hours."""
    state = _get_state()
    if not state.get("sleep_schedule_enabled", True):
        return False
        
    start = int(state.get("sleep_start_hour", 0))
    end = int(state.get("sleep_end_hour", 7))

    now_hour = datetime.now().hour
    if start == end:
        return False
    elif start < end:
        return start <= now_hour < end
    else:  # Overnight span (e.g. 23:00 to 07:00)
        return now_hour >= start or now_hour < end


def is_silent() -> bool:
    """Return True if manual silent mode is active OR current time is in sleep hours."""
    state = _get_state()
    manual_silent = bool(state.get("silent", False))
    return manual_silent or is_in_sleep_hours()


def set_silent(enabled: bool) -> bool:
    """Enable or disable manual silent mode. Returns the new state."""
    state = _get_state()
    prev = bool(state.get("silent", False))
    state["silent"] = bool(enabled)
    
    if state["silent"] != prev:
        _save_state(state)
        print(f"[quiet] Silent mode {'ON' if enabled else 'OFF'}")
        
    return bool(enabled)


def set_sleep_schedule(start_hour: int, end_hour: int, enabled: bool = True) -> tuple[int, int, str]:
    """Set quiet hours sleep schedule (hours 0–23). Returns (start_hour, end_hour, text_summary)."""
    start_hour = max(0, min(23, int(start_hour)))
    end_hour = max(0, min(23, int(end_hour)))

    state = _get_state()
    state["sleep_start_hour"] = start_hour
    state["sleep_end_hour"] = end_hour
    state["sleep_schedule_enabled"] = bool(enabled)
    _save_state(state)

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
    state = _get_state()
    return {
        "start_hour": int(state.get("sleep_start_hour", 0)),
        "end_hour": int(state.get("sleep_end_hour", 7)),
        "enabled": bool(state.get("sleep_schedule_enabled", True)),
        "in_sleep_hours": is_in_sleep_hours(),
    }

