"""core.vad: the end-of-speech decision and the Silero model (run: python -m pytest tests)."""

import pathlib
import wave

import numpy as np
import pytest

from core import vad


def windows(probs, step=0.25):
    """Feed a sequence of per-window probabilities; return the stop time (or None)."""
    eos = vad.EndOfSpeech(threshold=0.5, start_timeout=2.7, end_silence=0.7)
    for i, p in enumerate(probs):
        if eos.update(p, (i + 1) * step):
            return (i + 1) * step, eos.started
    return None, eos.started


def test_stops_shortly_after_speech_ends():
    # 1 s of speech, then silence: stops 0.75 s (three windows) after the last speech.
    stop, started = windows([0.9, 0.9, 0.9, 0.9] + [0.0] * 10)
    assert started and stop == 1.75


def test_pauses_shorter_than_end_silence_do_not_stop():
    stop, started = windows([0.9, 0.9, 0.0, 0.0, 0.9, 0.9, 0.0, 0.0, 0.0])
    assert started and stop == 2.25


def test_gives_up_if_nobody_speaks():
    stop, started = windows([0.0] * 20)
    assert not started and stop == 2.75


def test_threshold_is_respected():
    eos = vad.EndOfSpeech(threshold=0.8)
    assert not eos.update(0.6, 0.25)
    assert not eos.started
    eos.update(0.85, 0.5)
    assert eos.started


@pytest.fixture(scope="module")
def model():
    try:
        return vad.SileroVAD()
    except Exception as e:  # onnxruntime or the model file missing on this machine
        pytest.skip(f"Silero VAD not loadable here: {e}")


def test_silence_and_noise_are_not_speech(model):
    rng = np.random.default_rng(1)
    assert model.feed(np.zeros(16000, dtype=np.int16)) < 0.1
    model.reset()
    noise = (rng.normal(0, 300, 16000)).astype(np.int16)
    assert model.feed(noise) < 0.5


def test_feed_buffers_partial_chunks(model):
    model.reset()
    assert model.feed(np.zeros(100, dtype=np.int16)) == 0.0   # fewer than 512 samples
    assert model.feed(np.zeros(412, dtype=np.int16)) < 0.1     # now one full chunk


def _speech_16k() -> np.ndarray:
    """tests/fixtures/speech_22k.wav (a spoken sentence, 22.05 kHz) resampled to 16 kHz
    with plain interpolation — accurate enough for a VAD."""
    with wave.open(str(pathlib.Path(__file__).parent / "fixtures" / "speech_22k.wav")) as w:
        rate = w.getframerate()
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    n = int(len(pcm) * 16000 / rate)
    return np.interp(np.linspace(0, len(pcm) - 1, n), np.arange(len(pcm)), pcm).astype(np.int16)


def test_real_speech_is_speech(model):
    model.reset()
    speech = _speech_16k()
    # Feed it in the 0.25 s windows record() uses; most windows of a spoken sentence are speech.
    step = 4000
    probs = [model.feed(speech[i:i + step]) for i in range(0, len(speech), step)]
    assert max(probs) > 0.9
    assert sum(p >= 0.5 for p in probs) >= len(probs) // 2


def test_end_of_speech_on_real_speech(model):
    model.reset()
    speech = _speech_16k()
    eos = vad.EndOfSpeech(threshold=0.5, start_timeout=2.7, end_silence=0.7)
    step = 4000
    stop = None
    for i in range(0, len(speech) + 16000 * 2, step):   # the sentence, then two seconds of silence
        window = speech[i:i + step] if i < len(speech) else np.zeros(step, dtype=np.int16)
        if eos.update(model.feed(window), (i + step) / 16000):
            stop = (i + step) / 16000
            break
    assert eos.started
    assert stop is not None and len(speech) / 16000 < stop < len(speech) / 16000 + 1.5
