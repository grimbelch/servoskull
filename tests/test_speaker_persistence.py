"""The carried-over identification, and the rule for clips too short to trust.

Two things used to make the owner a stranger. The first was a 0.8 s floor on voiced
speech: an ordinary short command ("Tell me a joke") carries about 0.7 s, so the most
common summons of all was discarded unjudged. The second was that the continuity
window lived only in memory, and the unit restarts often enough — a deploy, a
self-update, the watchdog — that the first short command after a restart was certain
to come back unknown. Measured against a real profile, the score is dependable from
0.7 s up and a lottery below it, so clips in the 0.5-0.7 s band may confirm an
identity and never disprove one (run on the Pi: python -m pytest tests).
"""
import json
import time

import pytest

sid = pytest.importorskip("core.speaker_id")  # needs scikit-learn (run on the Pi)


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path, monkeypatch):
    monkeypatch.setattr(sid, "_LAST_SPEAKER_PATH", tmp_path / "last_speaker.json")
    monkeypatch.setattr(sid, "_last_confident", None)
    monkeypatch.setattr(sid, "_last_confident_loaded", False)
    monkeypatch.setattr(sid, "_speaker_models", {"Sean": object()})
    yield


def test_the_band_that_may_confirm_but_not_disprove_sits_below_the_dependable_one():
    assert sid._MIN_SPEECH_FRAMES < sid._SHORT_SPEECH_FRAMES
    assert sid._MIN_SPEECH_FRAMES == 50   # 0.5 s: judged, but only ever confirming
    assert sid._SHORT_SPEECH_FRAMES == 70  # 0.7 s: scores are dependable from here


def test_an_identification_is_written_where_a_restart_will_find_it():
    sid._remember_confident("Sean")
    saved = json.loads(sid._LAST_SPEAKER_PATH.read_text())
    assert saved["name"] == "Sean"
    assert saved["at"] == pytest.approx(time.time(), abs=5)


def test_a_fresh_process_recovers_the_speaker_from_disk():
    sid._remember_confident("Sean")
    sid._last_confident = None          # as a restart leaves it
    sid._last_confident_loaded = False
    sid._load_last_confident()
    assert sid._last_confident[0] == "Sean"


def test_a_recovered_speaker_still_expires_on_the_continuity_window():
    sid._LAST_SPEAKER_PATH.write_text(json.dumps(
        {"name": "Sean", "at": time.time() - sid._CONTINUITY_SECS - 1}))
    sid._load_last_confident()
    assert sid._last_confident is None


def test_a_profile_that_no_longer_exists_is_not_carried_over():
    sid._LAST_SPEAKER_PATH.write_text(json.dumps({"name": "Justin", "at": time.time()}))
    sid._load_last_confident()
    assert sid._last_confident is None


def test_a_purge_clears_only_the_person_purged():
    sid._remember_confident("Sean")
    sid.forget_speaker("Justin")
    assert sid._last_confident[0] == "Sean"
    sid.forget_speaker("Sean")
    assert sid._last_confident is None
    assert not sid._LAST_SPEAKER_PATH.exists()


def test_a_purge_reads_the_stored_name_when_this_process_has_none():
    sid._remember_confident("Sean")
    sid._last_confident = None  # a restart, then a purge before anyone has spoken
    sid.forget_speaker("Sean")
    assert not sid._LAST_SPEAKER_PATH.exists()


def test_unreadable_state_is_survivable():
    sid._LAST_SPEAKER_PATH.write_text("{ not json")
    sid._load_last_confident()
    assert sid._last_confident is None
