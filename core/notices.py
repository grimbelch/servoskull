"""
Things waiting for the owner: a finished print, a printer fault, announcements
dropped while silent mode was on. The right eye shows them (core/eye_watch.py)
until they are dealt with, which is one of:

  - acknowledged by voice (the acknowledge_reminders tool clears them all);
  - announced while someone was there to hear it: the rangefinder had seen
    movement within config.PRESENCE_WINDOW_SECS when the announcement finished;
  - made moot by the thing itself (a new print starts; the printer's errors clear).

A notice announced to an empty room stays, and is announced again when someone
next walks in (core/eye_watch.py watches for the arrival). Notices live in memory
only: a restart forgets them, as it forgets the printer's own state.

No hardware or audio here; presence is injected, so this is unit-tested in
tests/test_notices.py.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable

PRINT_DONE = "print_done"
PRINT_ERROR = "print_error"
MISSED = "missed"


@dataclass
class Notice:
    kind: str
    text: str
    at: float


_lock = threading.Lock()
_items: dict[str, Notice] = {}
_missed: list[str] = []
_clear_hooks: dict[str, list[Callable[[], None]]] = {}
_present: Callable[[], bool | None] = lambda: None


def set_presence(fn: Callable[[], bool | None]) -> None:
    """fn() -> True (someone is here), False (nobody), None (no sensor)."""
    global _present
    _present = fn


def on_clear(kind: str, fn: Callable[[], None]) -> None:
    """Run fn whenever a notice of `kind` is cleared, e.g. stop the printer's repeats."""
    _clear_hooks.setdefault(kind, []).append(fn)


def add(kind: str, text: str) -> None:
    """Hold a notice. Adding one already held refreshes its text only."""
    with _lock:
        old = _items.get(kind)
        _items[kind] = Notice(kind, text, old.at if old else time.time())
    if old is None:
        print(f"[notices] Holding {kind}: {text}")


def add_missed(text: str) -> None:
    """An announcement silent mode dropped. Held as one notice, counting them."""
    with _lock:
        _missed.append(text)
        n = len(_missed)
        _items[MISSED] = Notice(MISSED, f"{n} announcement(s) withheld in silent mode", time.time())


def clear(kind: str, why: str = "") -> bool:
    with _lock:
        gone = _items.pop(kind, None)
        if kind == MISSED:
            _missed.clear()
    if gone is None:
        return False
    print(f"[notices] Cleared {kind}{f' ({why})' if why else ''}.")
    for fn in _clear_hooks.get(kind, ()):
        try:
            fn()
        except Exception as e:
            print(f"[notices] Clear hook for {kind} failed: {e}")
    return True


def pending() -> list[Notice]:
    """Held notices, oldest first."""
    with _lock:
        return sorted(_items.values(), key=lambda n: n.at)


def has(kind: str) -> bool:
    with _lock:
        return kind in _items


def acknowledge_all() -> tuple[list[Notice], list[str]]:
    """Clear everything. Returns what was held and the texts silent mode withheld."""
    with _lock:
        held = sorted(_items.values(), key=lambda n: n.at)
        missed = list(_missed)
    for n in held:
        clear(n.kind, "acknowledged")
    return held, missed


def delivered(kind: str) -> bool:
    """An announcement of `kind` has just been spoken. Clears it if someone was
    there to hear it; returns True if it did."""
    if _present() is True:
        return clear(kind, "announced to someone present")
    return False
