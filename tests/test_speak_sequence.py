"""The sequence lock, and the deadlock that came of holding it too early.

"Play a holy hymn" hung the main thread for 190s and the watchdog restarted the
service. A reply's player thread starts the moment the streamer is built and then
waits for the model's first sentence; it held _speak_seq_lock across that wait.
Streaming is disabled for hymn requests, so no sentence ever arrived, while the
hymn tool — called from inside the same turn — waited for the lock the streamer
would only release once that turn finished (run on the Pi: python -m pytest tests).
"""
import threading
import time

import pytest

m = pytest.importorskip("core.main")  # needs sounddevice (run on the Pi)


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    """Keep the test off the speaker, the eyes and the microphone."""
    played = []
    monkeypatch.setattr(m.audio, "play_wav_bytes",
                        lambda wav, **kw: played.append(wav))
    for obj, name in ((m.eyes, "on"), (m.eyes, "off"), (m.eyes, "set_amplitude"),
                      (m.display, "on"), (m.display, "idle"), (m.display, "set_amplitude")):
        monkeypatch.setattr(obj, name, lambda *a, **k: None, raising=False)
    monkeypatch.setattr(m.cast_audio, "is_configured", lambda: False)
    # No real listener: the wake word never fires, and cancel returns at once.
    monkeypatch.setattr(m.wake_word, "wait_for_wake_word",
                        lambda cancel=None, threshold=None, on_detected=None: False)
    monkeypatch.setattr(m.watchdog, "beat", lambda: None)
    return played


def test_a_clip_plays(_quiet):
    assert m._speak_clips([b"RIFFone"], None) is False
    assert _quiet == [b"RIFFone"]


def test_an_empty_sequence_plays_nothing(_quiet):
    assert m._speak_clips([], None) is False
    assert m._speak_clips([None], None) is False
    assert _quiet == []


def test_every_clip_of_a_sequence_plays(_quiet):
    m._speak_clips([b"a", b"b", b"c"], None)
    assert _quiet == [b"a", b"b", b"c"]


def test_a_none_ends_the_sequence(_quiet):
    m._speak_clips([b"a", None, b"c"], None)
    assert _quiet == [b"a"]


def test_waiting_for_a_first_clip_does_not_hold_the_sequence_lock(_quiet):
    """The hymn deadlock, in miniature.

    One caller is a reply that will never produce a sentence; the other is a tool
    that speaks from inside the same turn. The second must not wait on the first.
    """
    release = threading.Event()

    def never_arrives():
        # A streamed reply whose first sentence is still being written.
        release.wait(timeout=10)
        return
        yield  # pragma: no cover - makes this a generator

    waiting = threading.Thread(target=lambda: m._speak_clips(never_arrives(), None),
                               daemon=True)
    waiting.start()
    time.sleep(0.2)  # let it reach the wait

    done = threading.Event()

    def tool_speaks():
        m._speak_clips([b"RIFFhymn"], None)
        done.set()

    threading.Thread(target=tool_speaks, daemon=True).start()
    assert done.wait(timeout=5), "the tool's speech is still waiting on the sequence lock"
    assert _quiet == [b"RIFFhymn"]
    release.set()
    waiting.join(timeout=5)


def test_two_real_sequences_still_take_turns(_quiet):
    """The lock must still do its job: one spoken sequence at a time, because the
    barge-in listeners share a single wake-word model."""
    order = []
    started = threading.Event()

    def slow_clips():
        order.append("first:start")
        started.set()
        time.sleep(0.4)
        yield b"first"
        order.append("first:done")

    t1 = threading.Thread(target=lambda: m._speak_clips(slow_clips(), None), daemon=True)
    t1.start()
    started.wait(timeout=2)
    time.sleep(0.5)  # it now holds the lock, mid-sequence

    t2 = threading.Thread(target=lambda: (order.append("second:start"),
                                          m._speak_clips([b"second"], None),
                                          order.append("second:done")), daemon=True)
    t2.start()
    t1.join(timeout=5)
    t2.join(timeout=5)
    assert order.index("first:done") < order.index("second:done")
