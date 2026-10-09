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


# ── what to play ──────────────────────────────────────────────────────────────

class _Search(_FakeSpotify):
    def __init__(self, tracks=(), playlists=(), **kw):
        super().__init__(**kw)
        self._tracks = list(tracks)
        self._playlists = list(playlists)
        self.started = []

    def search(self, q, type, limit):
        return {"tracks": {"items": [{"uri": f"track:{t}", "name": t,
                                      "artists": [{"name": "Someone"}]} for t in self._tracks]},
                "playlists": {"items": [{"uri": f"list:{p}", "name": p} for p in self._playlists]}}

    def devices(self):
        return {"devices": [{"id": "o7", "name": "Omega-7", "type": "Speaker",
                             "is_restricted": False}]}

    def start_playback(self, device_id=None, uris=None, context_uri=None):
        self.started.append(context_uri or (uris or [None])[0])


def test_a_short_query_gets_the_track_not_a_playlist(monkeypatch):
    # The rule was a word count: four words or fewer took the playlist, so
    # "Bohemian Rhapsody" got a playlist named after the song.
    fake = _install(monkeypatch, _Search(tracks=["Bohemian Rhapsody"],
                                        playlists=["Bohemian Rhapsody Mix"]))
    res = sc.search_and_play("Bohemian Rhapsody")
    assert res.ok and "Bohemian Rhapsody by Someone" == res.label
    assert fake.started == ["track:Bohemian Rhapsody"]


def test_a_playlist_is_played_when_one_is_asked_for(monkeypatch):
    for query in ("some doom metal playlist", "a chill mix", "forge world radio"):
        fake = _install(monkeypatch, _Search(tracks=["A Song"], playlists=["The List"]))
        res = sc.search_and_play(query)
        assert res.ok and res.label == "The List", query
        assert fake.started == ["list:The List"], query


def test_a_playlist_is_better_than_nothing(monkeypatch):
    fake = _install(monkeypatch, _Search(tracks=[], playlists=["The List"]))
    assert sc.search_and_play("something obscure").ok
    assert fake.started == ["list:The List"]


def test_finding_nothing_says_so(monkeypatch):
    _install(monkeypatch, _Search())
    res = sc.search_and_play("zzzzz")
    assert res.ok is False and res.kind == "not-found"


def test_no_device_names_the_one_that_was_wanted(monkeypatch):
    class NoDevices(_Search):
        def devices(self):
            return {"devices": []}
    _install(monkeypatch, NoDevices(tracks=["A Song"]))
    res = sc.search_and_play("a song", device_name="Kitchen")
    assert res.ok is False and res.kind == "no-device" and res.detail == "Kitchen"


def test_a_track_called_error_is_not_mistaken_for_one(monkeypatch):
    # The old result was a string and failures were told apart with startswith.
    _install(monkeypatch, _Search(tracks=["Error of the Ancients"]))
    res = sc.search_and_play("error of the ancients")
    assert res.ok is True and res.label.startswith("Error of the Ancients")


def test_a_spotify_failure_is_reported_with_its_status(monkeypatch):
    class Boom(_Search):
        def start_playback(self, **kw):
            raise spotipy.SpotifyException(503, -1, "service unavailable")
    _install(monkeypatch, Boom(tracks=["A Song"]))
    res = sc.search_and_play("a song")
    assert res.ok is False and res.kind == "spotify-error" and "503" in res.detail


# ── ducking from two threads ──────────────────────────────────────────────────

def test_two_threads_ducking_at_once_keep_one_level(monkeypatch):
    import threading
    fake = _install(monkeypatch, _FakeSpotify(volume=70))
    barrier = threading.Barrier(2)

    def duck():
        barrier.wait()
        sc.duck(20)
    threads = [threading.Thread(target=duck) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sc._pre_duck_volume == 70        # not overwritten with the ducked 20
    assert fake.volume_calls == [20]        # and only ducked once
    sc.restore()
    assert fake.device["volume_percent"] == 70
