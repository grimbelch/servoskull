"""core.wake_word: what fires a wake, and a microphone that stops delivering audio.

The firing tests exist because a merge once left the return inside the near-miss
branch that was added beside it. A score over the threshold then logged "Wake word
detected!" and carried on listening, while a score in the capture band fired the
wake instead — so the skull answered on the decay tail of the summons, seconds late
and only after several tries, and would have gone deaf outright had WAKE_CAPTURE been
switched off (run on the Pi: python -m pytest tests).
"""

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


class _ScriptedModel:
    """Returns each score in turn, so one utterance's rise and decay can be played."""

    def __init__(self, scores):
        self.scores, self.resets = list(scores), 0

    def reset(self):
        self.resets += 1

    def predict(self, audio):
        return {"omega7": self.scores.pop(0) if self.scores else 0.0}


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


# ── What fires a wake ────────────────────────────────────────────────────────────

@pytest.fixture
def scripted(monkeypatch):
    """Play a scripted run of scores through the detector and report what happened."""
    monkeypatch.setattr(wake_word, "_native_rate", lambda dev: 16000)
    monkeypatch.setattr(wake_word.time, "sleep", lambda s: None)
    monkeypatch.setattr(wake_word.watchdog, "beat", lambda: None)
    # A run where nothing fires ends by stalling once the scripted chunks run out;
    # keep that short, and leave the reopen counter as the other tests found it.
    monkeypatch.setattr(wake_word, "MIC_STALL_SECS", 0.3)
    monkeypatch.setattr(wake_word, "_ww_consecutive_failures", 0)

    def run(scores, threshold=None, capture=True, floor=0.25, idle_threshold=0.65):
        from core import config as cfg
        monkeypatch.setattr(cfg, "WAKE_CAPTURE", capture, raising=False)
        monkeypatch.setattr(cfg, "WAKE_CAPTURE_FLOOR", floor, raising=False)
        monkeypatch.setattr(cfg, "WAKE_WORD_THRESHOLD", idle_threshold, raising=False)
        monkeypatch.setattr(cfg, "AUDIO_DEBUG", False, raising=False)
        model = _ScriptedModel(scores)
        monkeypatch.setattr(wake_word, "_get_model", lambda: model)
        saved = []
        monkeypatch.setattr(wake_word, "_save_trigger_clip",
                            lambda chunks, score, mode="idle", fired=True: saved.append((score, fired)))
        monkeypatch.setattr(wake_word.sd, "InputStream",
                            lambda **kw: _FakeStream(len(scores), **kw))
        woke = []
        got = wake_word.wait_for_wake_word(on_detected=lambda: woke.append(True),
                                           threshold=threshold)
        return {"returned": got, "on_detected": len(woke), "saved": saved}

    return run


def test_a_score_over_the_threshold_fires_the_wake(scripted):
    out = scripted([0.9])
    assert out["returned"] is True
    assert out["on_detected"] == 1


def test_it_fires_on_the_first_frame_over_the_threshold_not_the_decay(scripted):
    # The logged failure: four frames at 0.80-0.97 passed without firing, and the
    # 0.274 tail two seconds later is what finally woke it.
    out = scripted([0.817, 0.932, 0.968, 0.801, 0.274], threshold=0.40)
    assert out["returned"] is True
    assert [score for score, fired in out["saved"] if fired] == [0.817]
    assert 0.274 not in [score for score, _ in out["saved"]]


def test_a_near_miss_is_captured_but_never_fires_the_wake(scripted):
    out = scripted([0.30, 0.27], threshold=0.40)
    assert out["returned"] is False          # the stream ran out; nothing fired
    assert out["on_detected"] == 0
    assert out["saved"] == [(0.30, False), (0.27, False)]


def test_a_score_under_the_capture_floor_leaves_no_trace(scripted):
    out = scripted([0.1, 0.2], threshold=0.40)
    assert out["returned"] is False and out["saved"] == []


def test_the_wake_still_fires_with_capture_switched_off(scripted):
    # WAKE_CAPTURE defaults to false, so a detection path that depends on it
    # would leave a stock unit unable to hear its own name.
    out = scripted([0.9], capture=False)
    assert out["returned"] is True
    assert out["on_detected"] == 1 and out["saved"] == []


def test_the_barge_in_threshold_is_the_one_that_applies(scripted):
    # 0.5 clears the barge-in threshold while falling well short of the idle one.
    assert scripted([0.5], threshold=0.40)["returned"] is True
    assert scripted([0.5], threshold=None, idle_threshold=0.65)["returned"] is False


def test_the_model_is_reset_before_the_listener_hands_back(scripted, monkeypatch):
    # A stale prediction buffer would re-fire on the previous summons.
    from core import config as cfg
    monkeypatch.setattr(cfg, "WAKE_CAPTURE", False, raising=False)
    monkeypatch.setattr(cfg, "AUDIO_DEBUG", False, raising=False)
    monkeypatch.setattr(wake_word, "_native_rate", lambda dev: 16000)
    monkeypatch.setattr(wake_word.watchdog, "beat", lambda: None)
    model = _ScriptedModel([0.9])
    monkeypatch.setattr(wake_word, "_get_model", lambda: model)
    monkeypatch.setattr(wake_word.sd, "InputStream", lambda **kw: _FakeStream(1, **kw))
    assert wake_word.wait_for_wake_word(threshold=0.40) is True
    assert model.resets == 2  # once on entry, once before returning
