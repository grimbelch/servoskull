"""core.announcements: the unprompted-speech queue (run: python -m pytest tests)."""

import threading

import pytest

from core import announcements as ann


@pytest.fixture(autouse=True)
def empty_queue():
    ann.drain()
    ann.register_wakeup(None)
    yield
    ann.drain()
    ann.register_wakeup(None)


def test_drain_orders_by_priority_then_arrival():
    ann.announce("hymn", priority=ann.AMBIENT, source="hymn")
    ann.announce("print done", priority=ann.NOTICE, source="printer")
    ann.announce("too hot", priority=ann.SAFETY, source="temperature")
    ann.announce("second print", priority=ann.NOTICE, source="printer")
    assert [a.text for a in ann.drain()] == ["too hot", "print done", "second print", "hymn"]
    assert ann.drain() == []
    assert not ann.pending()


def test_announce_wakes_the_main_loop():
    wake = threading.Event()
    ann.register_wakeup(wake)
    ann.announce("reminder", priority=ann.REMINDER)
    assert wake.is_set()
    assert ann.pending()


def test_announce_without_a_wakeup_just_queues():
    ann.announce("observation", priority=ann.OBSERVATION)
    assert ann.pending()


def test_announcement_keeps_its_delivery_options():
    calls = []
    a = ann.announce("nag", priority=ann.REMINDER, source="reminder", ping="wake_ping",
                     bypass_silent=True, duck_music=False, then=lambda: calls.append("then"))
    assert (a.source, a.ping, a.bypass_silent, a.duck_music) == ("reminder", "wake_ping", True, False)
    a.then()
    assert calls == ["then"]


def test_audio_only_announcements_and_validation():
    a = ann.announce(wav=b"RIFF", priority=ann.AMBIENT, skip_if_music=True)
    assert a.text is None and a.wav == b"RIFF" and a.skip_if_music
    with pytest.raises(ValueError):
        ann.announce()
