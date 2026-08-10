"""
Timer and reminder persistence for Omega-7.

Reminders are stored in SQLite so they survive restarts.
All public functions are thread-safe.
"""

from __future__ import annotations
import uuid
from datetime import datetime, timedelta

from core import db

# ── Public API ─────────────────────────────────────────────────────────────────

def add(message: str, delay_seconds: int, repeating: bool = False) -> str:
    """Schedule a reminder. Returns its short ID."""
    rid = str(uuid.uuid4())[:8]
    fire_at = (datetime.now() + timedelta(seconds=delay_seconds)).isoformat()
    db.add_reminder(rid, message, fire_at, repeating)
    print(f"[reminders] Set: [{rid}] in {delay_seconds}s — {message!r}")
    return rid


def acknowledge_all() -> int:
    """Remove all repeating reminders (user acknowledged by triggering wake word).
    Returns the number cleared."""
    removed = db.remove_repeating_reminders()
    return removed


def cancel(reminder_id: str) -> bool:
    """Cancel by ID. Returns True if found."""
    return db.remove_reminder(reminder_id)


def list_all() -> list[dict]:
    return db.get_all_reminders()


def get_due() -> list[dict]:
    """Pop and return all reminders whose fire_at has passed."""
    now = datetime.now().isoformat()
    return db.get_due_reminders(now)


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
