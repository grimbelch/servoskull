"""Unprompted speech, in one queue.

Warnings, reminders, printer events, hymn snippets, camera observations and the
morning greeting are produced on their own threads but must never talk over a
conversation or each other. Producers call announce(); the main loop drains the
queue at the top of each turn (main._deliver speaks each item, in priority order
then arrival order) and never in the middle of a reply. announce() also wakes the
main loop out of its wake-word wait, so an announcement is spoken now rather than
after the next command.

This module holds data and a heap only — no audio, no config — so it is
unit-tested in tests/test_announcements.py.
"""

from __future__ import annotations

import heapq
import threading
from dataclasses import dataclass, field
from typing import Callable

# Lower speaks first.
SAFETY = 0        # overheating, under-voltage
REMINDER = 10
NOTICE = 20       # printer events, the morning greeting
AMBIENT = 30      # hymn snippets
OBSERVATION = 40  # camera observations, idle remarks


@dataclass(order=True)
class Announcement:
    priority: int
    seq: int = 0
    text: str | None = field(default=None, compare=False)
    wav: bytes | None = field(default=None, compare=False)   # pre-rendered audio instead of text
    source: str = field(default="", compare=False)
    ping: str | None = field(default=None, compare=False)    # sfx played first ("wake_ping", "negative")
    duck_music: bool = field(default=True, compare=False)
    bypass_silent: bool = field(default=False, compare=False)  # speak even in silent mode
    skip_if_music: bool = field(default=False, compare=False)  # drop if Spotify is playing
    then: Callable[[], None] | None = field(default=None, compare=False)  # runs after delivery


_heap: list[Announcement] = []
_lock = threading.Lock()
_seq = 0
_wakeup: threading.Event | None = None


def announce(text: str | None = None, *, wav: bytes | None = None, priority: int = NOTICE,
             source: str = "", ping: str | None = None, duck_music: bool = True,
             bypass_silent: bool = False, skip_if_music: bool = False,
             then: Callable[[], None] | None = None) -> Announcement:
    """Queue something for the main loop to say and wake it if it is idle."""
    global _seq
    if text is None and wav is None:
        raise ValueError("an announcement needs text or wav")
    with _lock:
        _seq += 1
        ann = Announcement(priority=priority, seq=_seq, text=text, wav=wav, source=source, ping=ping,
                           duck_music=duck_music, bypass_silent=bypass_silent,
                           skip_if_music=skip_if_music, then=then)
        heapq.heappush(_heap, ann)
        wakeup = _wakeup
    if wakeup is not None:
        wakeup.set()
    return ann


def register_wakeup(event: threading.Event | None) -> None:
    """The main loop's wake-word-wait cancel event; announce() sets it. None to clear."""
    global _wakeup
    with _lock:
        _wakeup = event


def pending() -> bool:
    with _lock:
        return bool(_heap)


def drain() -> list[Announcement]:
    """Take everything queued, highest priority first, then in arrival order."""
    with _lock:
        items = sorted(_heap)
        _heap.clear()
    return items
