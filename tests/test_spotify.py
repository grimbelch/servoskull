"""Ducking the music, restoring it, and choosing a Connect device.

restore() used to clear the remembered volume before the call that used it, so one
failed request left the music at the duck level for good, with every later restore
a no-op. The retry wrapper that used to sit over these functions never fired —
each catches its own exceptions — and spotipy already retries, so there is none
now; a transient failure must make exactly one attempt and not sleep
(run on the Pi: python -m pytest tests).
"""
import time

import pytest

sc = pytest.importorskip("core.spotify_ctrl")  # needs spotipy (run on the Pi)
import spotipy  # noqa: E402  (only reached when the skip above passes)


class _FakeSpotify:
    """A Connect session: one device, a volume, and optional failure injection."""

    def __init__(self, volume=70, playing=True, fail_volume=False):
        self.device = {"id": "dev1", "volume_percent": volume, "supports_volume": True}
        self.playing = playing
        self.fail_volume = fail_volume
        self.volume_calls = []

    def current_playback(self):
        return {"is_playing": self.playing, "device": self.device}

    def volume(self, level, device_id=None):
        self.volume_calls.append(level)
        if self.fail_volume:
            raise spotipy.SpotifyException(500, -1, "transient")
        self.device["volume_percent"] = level


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setattr(sc, "_sp", None)
    monkeypatch.setattr(sc, "_pre_duck_volume", None)
    yield


def _install(monkeypatch, fake):
    monkeypatch.setattr(sc, "_sp", fake)
    monkeypatch.setattr(sc, "_client", lambda: fake)
    return fake


# ── ducking ───────────────────────────────────────────────────────────────────

def test_ducking_remembers_the_level_it_came_from(monkeypatch):
    fake = _install(monkeypatch, _FakeSpotify(volume=70))
    sc.duck(20)
    assert fake.device["volume_percent"] == 20
    assert sc._pre_duck_volume == 70


def test_ducking_twice_does_not_lose_the_original(monkeypatch):
    fake = _install(monkeypatch, _FakeSpotify(volume=70))
    sc.duck(20)
    sc.duck(20)
    assert sc._pre_duck_volume == 70
    assert fake.volume_calls == [20]


def test_nothing_is_ducked_when_nothing_plays(monkeypatch):
    fake = _install(monkeypatch, _FakeSpotify(playing=False))
    sc.duck(20)
    assert fake.volume_calls == [] and sc._pre_duck_volume is None


def test_ducking_never_forces_the_oauth_flow(monkeypatch):
    # _sp is None until Spotify has actually been used, and duck must not wake it:
    # a headless boot would block on a browser prompt.
    called = []
    monkeypatch.setattr(sc, "_client", lambda: called.append(1))
    sc.duck(20)
    assert called == []


def test_a_device_that_cannot_be_volume_controlled_is_left_alone(monkeypatch):
    fake = _install(monkeypatch, _FakeSpotify(volume=70))
    fake.device["supports_volume"] = False
    sc.duck(20)
    assert fake.volume_calls == [] and sc._pre_duck_volume is None


# ── restoring ─────────────────────────────────────────────────────────────────

def test_restoring_puts_the_level_back(monkeypatch):
    fake = _install(monkeypatch, _FakeSpotify(volume=70))
    sc.duck(20)
    sc.restore()
    assert fake.device["volume_percent"] == 70
    assert sc._pre_duck_volume is None


def test_a_failed_restore_keeps_the_level_for_the_next_attempt(monkeypatch):
    fake = _install(monkeypatch, _FakeSpotify(volume=70))
    sc.duck(20)
    fake.fail_volume = True
    sc.restore()
    # The music is still ducked, so the level it came from must survive.
    assert sc._pre_duck_volume == 70
    fake.fail_volume = False
    sc.restore()
    assert fake.device["volume_percent"] == 70
    assert sc._pre_duck_volume is None


def test_restoring_without_ducking_is_a_no_op(monkeypatch):
    fake = _install(monkeypatch, _FakeSpotify(volume=70))
    sc.restore()
    assert fake.volume_calls == []


# ── no second retry layer ─────────────────────────────────────────────────────

def test_a_transient_failure_makes_one_attempt_and_does_not_sleep(monkeypatch):
    fake = _install(monkeypatch, _FakeSpotify(volume=70, fail_volume=True))
    t0 = time.monotonic()
    sc.duck(20)
    assert fake.volume_calls == [20]              # one attempt, not three
    assert time.monotonic() - t0 < 0.5            # and no exponential backoff
    assert sc._pre_duck_volume is None            # nothing left half-ducked


def test_the_retry_wrapper_is_gone():
    assert not hasattr(sc, "retry_spotify_call")


# ── choosing a device ─────────────────────────────────────────────────────────

def test_names_compare_without_punctuation_or_case():
    assert sc._normalize_name("Omega-7") == sc._normalize_name("omega 7") == "omega7"


def test_the_skulls_own_client_wins_when_no_device_is_named(monkeypatch):
    class Devs(_FakeSpotify):
        def devices(self):
            return {"devices": [
                {"id": "tv", "name": "Living Room TV", "type": "TV", "is_restricted": False},
                {"id": "o7", "name": "Omega-7", "type": "Speaker", "is_restricted": False},
            ]}
    _install(monkeypatch, Devs())
    assert sc._device_id() == "o7"


def test_a_named_device_is_honoured_and_aliases_resolve_to_the_skull(monkeypatch):
    class Devs(_FakeSpotify):
        def devices(self):
            return {"devices": [
                {"id": "o7", "name": "Omega-7", "type": "Speaker", "is_restricted": False},
                {"id": "kit", "name": "Kitchen Nest", "type": "Speaker", "is_restricted": False},
            ]}
    _install(monkeypatch, Devs())
    assert sc._device_id("kitchen") == "kit"
    assert sc._device_id("your own speaker") == "o7"
    assert sc._device_id("a speaker that is not here") is None


def test_a_restricted_device_is_never_chosen(monkeypatch):
    class Devs(_FakeSpotify):
        def devices(self):
            return {"devices": [
                {"id": "o7", "name": "Omega-7", "type": "Speaker", "is_restricted": True},
            ]}
    _install(monkeypatch, Devs())
    assert sc._device_id() is None
