"""
Timer and reminder persistence for Omega-7.

Reminders are stored in reminders.json so they survive restarts.
All public functions are thread-safe.
"""

from __future__ import annotations
import json
import pathlib
import threading
import uuid
from datetime import datetime, timedelta

_FILE = pathlib.Path(__file__).parent.parent / "reminders.json"
_lock = threading.Lock()
_items: list[dict] = []


# ── Persistence ────────────────────────────────────────────────────────────────

def _load() -> None:
    global _items
    try:
        if _FILE.exists():
            with _FILE.open() as f:
                _items = json.load(f)
            print(f"[reminders] Loaded {len(_items)} pending reminder(s)")
    except Exception:
        _items = []


def _save() -> None:
    try:
        _FILE.parent.mkdir(parents=True, exist_ok=True)
        with _FILE.open("w") as f:
            json.dump(_items, f, indent=2)
    except Exception as e:
        print(f"[reminders] Save error: {e}")


_load()


# ── Public API ─────────────────────────────────────────────────────────────────

def add(message: str, delay_seconds: int, repeating: bool = False) -> str:
    """Schedule a reminder. Returns its short ID."""
    rid = str(uuid.uuid4())[:8]
    fire_at = (datetime.now() + timedelta(seconds=delay_seconds)).isoformat()
    with _lock:
        _items.append({"id": rid, "message": message, "fire_at": fire_at, "repeating": repeating})
        _save()
    print(f"[reminders] Set: [{rid}] in {delay_seconds}s — {message!r}")
    return rid


def acknowledge_all() -> int:
    """Remove all repeating reminders (user acknowledged by triggering wake word).
    Returns the number cleared."""
    with _lock:
        before = len(_items)
        _items[:] = [r for r in _items if not r.get("repeating", False)]
        removed = before - len(_items)
        if removed:
            _save()
        return removed


def cancel(reminder_id: str) -> bool:
    """Cancel by ID. Returns True if found."""
    with _lock:
        before = len(_items)
        _items[:] = [r for r in _items if r["id"] != reminder_id]
        if len(_items) < before:
            _save()
            return True
    return False


def list_all() -> list[dict]:
    with _lock:
        return list(_items)


def get_due() -> list[dict]:
    """Pop and return all reminders whose fire_at has passed."""
    now = datetime.now().isoformat()
    with _lock:
        due = [r for r in _items if r["fire_at"] <= now]
        if due:
            _items[:] = [r for r in _items if r["fire_at"] > now]
            _save()
        return due


def format_remaining(fire_at_iso: str) -> str:
    """Human-readable time remaining for display."""
    try:
        remaining = (datetime.fromisoformat(fire_at_iso) - datetime.now()).total_seconds()
    except Exception:
        return "unknown"
    if remaining <= 0:
        return "due now"
    if remaining < 60:
        return f"{int(remaining)}s"
    if remaining < 3600:
        m, s = divmod(int(remaining), 60)
        return f"{m}m {s}s" if s else f"{m}m"
    h, rem = divmod(int(remaining), 3600)
    m = rem // 60
    return f"{h}h {m}m" if m else f"{h}h"
