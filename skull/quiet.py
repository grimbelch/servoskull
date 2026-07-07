"""
Silent-mode state for Omega-7. When enabled, Omega-7 stops making unprompted
periodic (idle) observations; direct conversation and on-demand requests are
unaffected. Persists across restarts via quiet.json so a service restart mid-
silence doesn't make the skull start chattering again.
"""

from __future__ import annotations
import json
import pathlib
import threading

from skull import config

_FILE = config.data_path("quiet.json")
_lock = threading.Lock()

_state: dict = {"silent": False}


def _load() -> None:
    global _state
    try:
        if _FILE.exists():
            with _FILE.open() as f:
                _state = json.load(f)
            print(f"[quiet] Restored: silent={_state.get('silent', False)}")
    except Exception:
        pass


def _save() -> None:
    try:
        with _FILE.open("w") as f:
            json.dump(_state, f)
    except Exception as e:
        print(f"[quiet] Save error: {e}")


_load()


def is_silent() -> bool:
    with _lock:
        return bool(_state.get("silent", False))


def set_silent(enabled: bool) -> bool:
    """Enable or disable silent mode. Returns the new state."""
    with _lock:
        prev = bool(_state.get("silent", False))
        _state["silent"] = bool(enabled)
        if _state["silent"] != prev:
            _save()
            print(f"[quiet] Silent mode {'ON' if enabled else 'OFF'}")
    return bool(enabled)
