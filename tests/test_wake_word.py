"""core.wake_word: a microphone that stops delivering audio is reopened, and does not
feed the watchdog (run on the Pi: python -m pytest tests)."""

import threading
import time

import numpy as np
import pytest

wake_word = pytest.importorskip("core.wake_word")  # needs openwakeword / sounddevice


class _FakeModel:
    def reset(self):
        pass

    def predict(self, audio):
        return {"omega7": 0.0}


class _FakeStream:
    """An InputStream that delivers `chunks` blocks of silence, then goes quiet."""

    def __init__(self, chunks, **kw):
        self.cb, self.chunks, self.active = kw["callback"], chunks, True

    def __enter__(self):
        def feed():
            for _ in range(self.chunks):
                self.cb(np.zeros((1280, 1), np.int16), 1280, None, None)
                time.sleep(0.02)
        threading.Thread(target=feed, daemon=True).start()
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def ww(monkeypatch):
    monkeypatch.setattr(wake_word, "_get_model", lambda: _FakeModel())
    monkeypatch.setattr(wake_word, "_native_rate", lambda dev: 16000)
    monkeypatch.setattr(wake_word, "MIC_STALL_SECS", 0.3)
    monkeypatch.setattr(wake_word.time, "sleep", lambda s: None)   # skip the reopen backoff
    beats = []
    monkeypatch.setattr(wake_word.watchdog, "beat", lambda: beats.append(time.monotonic()))
    return wake_word, beats


def test_a_stalled_stream_is_given_up_so_it_can_be_reopened(ww, monkeypatch):
    wake_word, beats = ww
    monkeypatch.setattr(wake_word.sd, "InputStream", lambda **kw: _FakeStream(5, **kw))
    t0 = time.monotonic()
    assert wake_word.wait_for_wake_word() is False      # returned instead of hanging
    assert time.monotonic() - t0 < 3.0
    assert len(beats) == 5                               # one beat per chunk, none while dead
    assert wake_word._ww_consecutive_failures == 1


def test_a_stopped_stream_is_given_up_at_once(ww, monkeypatch):
    wake_word, beats = ww

    def stopped(**kw):
        s = _FakeStream(0, **kw)
        s.active = False
        return s
    monkeypatch.setattr(wake_word.sd, "InputStream", stopped)
    t0 = time.monotonic()
    assert wake_word.wait_for_wake_word() is False
    assert time.monotonic() - t0 < 0.3 and beats == []


def test_cancel_still_returns_promptly(ww, monkeypatch):
    wake_word, _ = ww
    monkeypatch.setattr(wake_word.sd, "InputStream", lambda **kw: _FakeStream(1000, **kw))
    cancel = threading.Event()
    threading.Timer(0.2, cancel.set).start()
    assert wake_word.wait_for_wake_word(cancel=cancel) is False
    assert wake_word._ww_consecutive_failures == 0
