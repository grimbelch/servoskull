"""Setting a reminder, and not claiming to have set one.

set_reminder had never fired once in the unit's whole journal — untested rather
than broken, as it turned out: the path works end to end. What it had no guard
against was the model saying a timer was set without calling the tool, which is
the failure every other spoken action showed at some point (run: python -m pytest tests).
"""
import pytest

reminders = pytest.importorskip("core.reminders")


@pytest.fixture(autouse=True)
def _own_store(tmp_path, monkeypatch):
    """A database of this test's own.

    core.db resolves _DB_PATH at import and caches one connection per thread, so
    redirecting config afterwards would not move it — point both at tmp_path and
    drop the cached connection.
    """
    from core import db
    monkeypatch.setattr(db, "_DB_PATH", tmp_path / "state.db")
    if hasattr(db._local, "conn"):
        monkeypatch.delattr(db._local, "conn")
    db.init_db()
    yield
    if hasattr(db._local, "conn"):
        db._local.conn.close()
        del db._local.conn


def test_a_reminder_is_stored_and_listed():
    rid = reminders.add("check the printer", 60)
    assert rid
    items = reminders.list_all()
    assert [r["message"] for r in items] == ["check the printer"]
    assert items[0]["id"] == rid


def test_a_reminder_comes_due_and_then_is_gone():
    reminders.add("now please", -1)          # already past its time
    due = reminders.get_due()
    assert [r["message"] for r in due] == ["now please"]
    assert reminders.get_due() == []          # delivered once, not twice


def test_one_not_yet_due_is_not_delivered():
    reminders.add("later", 3600)
    assert reminders.get_due() == []
    assert len(reminders.list_all()) == 1


def test_a_reminder_can_be_cancelled():
    rid = reminders.add("never mind", 3600)
    assert reminders.cancel(rid) is True
    assert reminders.list_all() == []
    assert reminders.cancel(rid) is False


def test_cancelling_something_that_is_not_there_is_false():
    assert reminders.cancel("nope") is False


def test_the_remaining_time_is_described():
    reminders.add("soon", 90)
    text = reminders.format_remaining(reminders.list_all()[0]["fire_at"])
    assert any(ch.isdigit() for ch in text)


# ── the fabrication guard ─────────────────────────────────────────────────────

def test_asking_for_a_timer_is_recognised():
    brain = pytest.importorskip("core.brain")
    for said in ("remind me in ten minutes to check the printer",
                 "set a timer for 5 minutes", "wake me at seven",
                 "set an alarm for noon", "nudge me in an hour"):
        assert brain._REMINDER_REQUEST_RE.search(said), said


def test_asking_about_timers_is_not_asking_for_one():
    brain = pytest.importorskip("core.brain")
    # These have their own tools; the guard must not fire on them.
    for said in ("what reminders do I have", "cancel my reminder",
                 "list my timers", "tell me a joke"):
        assert not brain._REMINDER_REQUEST_RE.search(said), said
