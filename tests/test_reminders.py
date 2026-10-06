"""core.reminders: due reminders are announced even in silent mode (run: python -m pytest tests)."""

import pytest

from core import announcements, reminders


@pytest.fixture(autouse=True)
def empty_queue():
    announcements.drain()
    yield
    announcements.drain()


def test_due_reminder_speaks_through_silent_mode_and_nags(monkeypatch):
    added = []
    monkeypatch.setattr(reminders, "add", lambda m, s, repeating=False: added.append((m, s, repeating)))
    reminders.announce_due({"id": "abc", "message": "leave for work", "fire_at": "", "repeating": False})
    [ann] = announcements.drain()
    assert ann.text == "leave for work"
    assert ann.priority == announcements.REMINDER
    assert ann.bypass_silent        # sleep hours / "be quiet" must not swallow it
    ann.then()                      # delivered: re-armed to nag until acknowledged
    assert added == [("leave for work", 10, True)]
