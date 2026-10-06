"""
Timer and reminder persistence for Omega-7.

Reminders are stored in SQLite so they survive restarts.
All public functions are thread-safe.
"""

from __future__ import annotations
import uuid
from datetime import datetime, timedelta

from core import announcements, db

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


def announce_due(rem: dict) -> announcements.Announcement:
    """Queue a due reminder to be spoken; it nags every 10 s until acknowledged.

    Reminders speak even in silent mode and during sleep hours: get_due() has
    already removed them from the database, so dropping one would lose it for good,
    and a reminder the owner set for 06:30 is meant to be heard at 06:30.
    """
    print(f"[skull] Reminder due: {rem['message']}")
    return announcements.announce(rem["message"], priority=announcements.REMINDER, source="reminder",
                                  ping="wake_ping", bypass_silent=True,
                                  then=lambda m=rem["message"]: add(m, 10, repeating=True))


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
