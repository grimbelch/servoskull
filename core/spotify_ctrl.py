"""
Spotify playback control via the Web API (Premium required).
Targets the Mac Spotify desktop app via Spotify Connect.
Authentication is lazy — only triggered on the first music command.
"""

from __future__ import annotations
import re
import threading
from typing import NamedTuple

import spotipy
from spotipy.oauth2 import SpotifyOAuth

from core import config

import time
import requests

# There is no retry wrapper here on purpose. spotipy already retries a failed
# request three times with its own backoff (requests_timeout=5, retries=3,
# backoff_factor=0.3 in 2.26), so a second layer would turn one transient blip into
# nine attempts and several seconds of sleep on the main loop. The functions below
# catch their own errors and report them; that is the whole policy.


class PlayResult(NamedTuple):
    """What came of a play request.

    It used to be a string: a track title when it worked, and one of "not-found",
    "no-device:<name>", "playback-error: ...", "spotify-error 404: ..." or
    "error: ..." when it did not, which the caller sorted out with startswith. A
    track whose name began with "error" would have been read as a failure.
    """
    ok: bool
    label: str = ""      # what is playing, when ok
    kind: str = ""        # not-found | no-device | spotify-error | playback-error | error
    detail: str = ""      # the device asked for, an HTTP status, a message


# Asking for a playlist is something the user says, not something the length of
# the query implies. "play Bohemian Rhapsody" is four words and wants the song.
_PLAYLIST_WORDS = re.compile(r"\b(?:playlist|mix|radio|station)\b", re.I)

_SCOPES = " ".join([
    "user-read-playback-state",
    "user-modify-playback-state",
])

_sp: spotipy.Spotify | None = None


def _client() -> spotipy.Spotify:
    global _sp
    if _sp is None:
        try:
            _sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
                client_id=config.SPOTIFY_CLIENT_ID,
                client_secret=config.SPOTIFY_CLIENT_SECRET,
                redirect_uri=config.SPOTIFY_REDIRECT_URI,
                scope=_SCOPES,
                open_browser=False,
                cache_path=str(config.data_path(".spotify_cache")),
            ))
        except (EOFError, OSError, Exception) as e:
            # Running headlessly — OAuth interactive flow is not available.
            # Raise as a SpotifyException so callers can handle it cleanly
            # without crashing the whole service process.
            print(f"[spotify] Auth init failed (headless environment?): {e}")
            raise spotipy.SpotifyException(0, -1, f"Spotify auth unavailable: {e}")
    return _sp


def _normalize_name(name: str) -> str:
    import re
    return re.sub(r"[^a-zA-Z0-9]", "", name).lower()
def _device_id(prefer_name: str = None) -> str | None:
    """Find a Spotify Connect device, optionally by name (partial, case-insensitive)."""
    devices = _client().devices().get("devices", [])
    print(f"[spotify] Available devices: {[d['name'] + ' (' + d['type'] + ')' for d in devices]}")

    # Canonicalize self-referential device requests (e.g. "own speaker", "Omega-7", "local")
    if prefer_name:
        p_lower = prefer_name.lower().strip()
        if any(alias in p_lower for alias in ("own speaker", "omega7", "omega-7", "servoskull", "this speaker", "local", "skull")):
            prefer_name = "omega"

    if prefer_name:
        norm_prefer = _normalize_name(prefer_name)
        for d in devices:
            if norm_prefer in _normalize_name(d["name"]) and not d["is_restricted"]:
                print(f"[spotify] Routing to requested device '{d['name']}'")
                return d["id"]
        print(f"[spotify] Requested device target '{prefer_name}' not found among active devices.")
        return None

    # Priority order when no specific device target given:
    # 1. Omega-7 / Raspotify local client
    for d in devices:
        if ("omega" in d["name"].lower() or "raspotify" in d["name"].lower()) and not d["is_restricted"]:
            print(f"[spotify] Default routing to Omega-7 client '{d['name']}'")
            return d["id"]

    # 2. Speaker device
    for d in devices:
        if d["type"].lower() == "speaker" and not d["is_restricted"]:
            return d["id"]

    print("[spotify] No active device found.")
    return None


def search_and_play(query: str, device_name: str | None = None) -> PlayResult:
    """Search Spotify and play the best match."""
    sp = _client()

    results = sp.search(q=query, type="track,playlist", limit=5)
    # Filter out None entries (unavailable/region-locked items)
    playlists = [p for p in ((results.get("playlists") or {}).get("items") or []) if p]
    tracks    = [t for t in ((results.get("tracks")    or {}).get("items") or []) if t]

    # A playlist only when one was asked for. The rule was a word count -- four or
    # fewer and it took the playlist -- so "play Bohemian Rhapsody" got a playlist
    # named after the song rather than the song.
    uri, label, use_context = None, "nothing", False
    wants_playlist = bool(_PLAYLIST_WORDS.search(query or ""))
    if wants_playlist and playlists:
        item = playlists[0]
        uri, label, use_context = item["uri"], item["name"], True
    elif tracks:
        item = tracks[0]
        uri = item["uri"]
        label = f"{item['name']} by {item['artists'][0]['name']}"
    elif playlists:
        # Nothing else on offer; a playlist beats telling them it was not found.
        item = playlists[0]
        uri, label, use_context = item["uri"], item["name"], True

    if uri is None:
        return PlayResult(False, kind="not-found")

    dev = _device_id(prefer_name=device_name)
    if dev is None:
        target = device_name if device_name else "Omega-7"
        print(f"[spotify] No available device found for target '{target}'.")
        return PlayResult(False, kind="no-device", detail=target)

    def _play():
        if use_context:
            sp.start_playback(device_id=dev, context_uri=uri)
        else:
            sp.start_playback(device_id=dev, uris=[uri])

    try:
        _play()
        return PlayResult(True, label=label)
    except spotipy.SpotifyException as e:
        if e.http_status == 404:
            # Device exists but isn't active — transfer playback to wake it then retry
            print(f"[spotify] Device inactive, waking {dev}...")
            try:
                sp.transfer_playback(device_id=dev, force_play=True)
                time.sleep(1.5)
                _play()
                return PlayResult(True, label=label)
            except Exception as e2:
                return PlayResult(False, kind="playback-error", detail=str(e2))
        return PlayResult(False, kind="spotify-error", detail=f"{e.http_status}: {e.msg}")
    except Exception as e:
        return PlayResult(False, kind="error", detail=str(e))


_pre_duck_volume: int | None = None
_duck_lock = threading.Lock()


def duck(level: int = 20) -> None:
    """Lower the music volume while Omega-7 speaks, then restore() afterwards.

    Idempotent (a second call while already ducked is a no-op) and silent when
    nothing is playing. Only acts if Spotify has already been used this session —
    we never force the lazy OAuth flow just to duck, so wake/idle stay snappy and
    headless boots don't block on a browser auth prompt.
    """
    if _sp is None:
        return
    with _duck_lock:
        if _pre_duck_volume is not None:
            return          # already ducked; a second caller must not overwrite it
        _duck_locked(level)


def _duck_locked(level: int) -> None:
    global _pre_duck_volume
    try:
        pb = _sp.current_playback()
        if not pb or not pb.get("is_playing"):
            return
        dev = pb.get("device") or {}
        if dev.get("supports_volume") is False:
            return  # e.g. a restricted Connect device that can't be volume-controlled
        cur = dev.get("volume_percent")
        if cur is None or cur <= level:
            return  # already at/below the duck level — nothing to restore later
        _pre_duck_volume = cur
        _sp.volume(level, device_id=dev.get("id"))
        print(f"[spotify] Ducked {cur}% → {level}% (Omega-7 speaking)")
    except Exception as e:
        print(f"[spotify] Duck failed: {e}")
        _pre_duck_volume = None


def restore() -> None:
    """Restore the pre-duck music volume. Idempotent; no-op if not ducked."""
    if _sp is None:
        return
    with _duck_lock:
        if _pre_duck_volume is None:
            return
        _restore_locked()


def _restore_locked() -> None:
    global _pre_duck_volume
    vol = _pre_duck_volume
    try:
        pb = _sp.current_playback()
        dev = (pb or {}).get("device") or {}
        _sp.volume(vol, device_id=dev.get("id"))
    except Exception as e:
        # Keep the remembered level: clearing it first meant one failed call left
        # the music at the duck level permanently, with every later restore a no-op.
        print(f"[spotify] Restore failed, still holding {vol}% to restore to: {e}")
        return
    _pre_duck_volume = None
    print(f"[spotify] Restored volume → {vol}%")


def _active_device_id() -> str | None:
    """The id of whatever device is currently playing, for targeted control calls."""
    try:
        pb = _client().current_playback()
        return ((pb or {}).get("device") or {}).get("id")
    except Exception:
        return None


def pause() -> None:
    try:
        _client().pause_playback(device_id=_active_device_id())
        print("[spotify] Paused")
    except spotipy.SpotifyException as e:
        # 403 commonly means "already paused" — not a real failure.
        if e.http_status == 403:
            print("[spotify] Pause: already paused")
        else:
            print(f"[spotify] Pause failed: {e.http_status} {e.msg}")
    except Exception as e:
        print(f"[spotify] Pause failed: {e}")


def resume() -> None:
    try:
        _client().start_playback(device_id=_active_device_id())
        print("[spotify] Resumed")
    except Exception as e:
        print(f"[spotify] Resume failed: {e}")


def transfer(device_name: str) -> str:
    try:
        sp = _client()
        dev_id = _device_id(prefer_name=device_name)
        if not dev_id:
            return f"Could not find Spotify device '{device_name}' to transfer to."
        sp.transfer_playback(device_id=dev_id, force_play=True)
        print(f"[spotify] Transferred playback to {device_name}")
        return f"Transferred playback to {device_name}."
    except Exception as e:
        print(f"[spotify] Transfer failed: {e}")
        return f"Failed to transfer playback: {e}"


def skip() -> None:
    try:
        _client().next_track(device_id=_active_device_id())
        print("[spotify] Skipped")
    except Exception as e:
        print(f"[spotify] Skip failed: {e}")


def is_configured() -> bool:
    return bool(config.SPOTIFY_CLIENT_ID and config.SPOTIFY_CLIENT_SECRET)


def get_currently_playing() -> str:
    """Get details on whatever track is currently playing on Spotify across any active device."""
    try:
        sp = _client()
        pb = sp.current_playback()
        if not pb or not pb.get("is_playing"):
            return "Nothing is currently playing on Spotify."
        item = pb.get("item") or {}
        if not item:
            return "Spotify is active, but track details could not be retrieved."
        track_name = item.get("name", "Unknown Track")
        artists = ", ".join([a.get("name", "") for a in item.get("artists", []) if a.get("name")])
        album = (item.get("album") or {}).get("name", "Unknown Album")
        dev_name = (pb.get("device") or {}).get("name", "Unknown Device")
        progress_ms = pb.get("progress_ms", 0)
        duration_ms = item.get("duration_ms", 0)
        
        mins_prog, secs_prog = divmod(progress_ms // 1000, 60)
        mins_dur, secs_dur = divmod(duration_ms // 1000, 60)
        time_str = f"{mins_prog}:{secs_prog:02d} / {mins_dur}:{secs_dur:02d}"

        return f"Currently playing '{track_name}' by {artists} (Album: {album}) [{time_str}] on device '{dev_name}'."
    except Exception as e:
        return f"Failed to check Spotify playback: {e}"


def is_playing() -> bool:
    if _sp is None:
        return False
    try:
        pb = _sp.current_playback()
        return bool(pb and pb.get("is_playing"))
    except Exception:
        return False


def set_volume(level: int) -> str:
    try:
        sp = _client()
        pb = sp.current_playback()
        dev_id = None
        if pb and pb.get("device"):
            dev_id = pb["device"].get("id")
        if not dev_id:
            dev_id = _device_id()
        if dev_id:
            sp.volume(level, device_id=dev_id)
            print(f"[spotify] Set volume to {level}%")
            return f"Set Spotify volume to {level}%."
        return "No active Spotify Connect device found to set volume."
    except (spotipy.SpotifyException, requests.exceptions.RequestException) as e:
        return f"Failed to set Spotify volume: {e}"


def adjust_volume(change: int) -> str:
    try:
        sp = _client()
        pb = sp.current_playback()
        dev_id = None
        curr_vol = 50
        if pb and pb.get("device"):
            dev_id = pb["device"].get("id")
            curr_vol = pb["device"].get("volume_percent") or 50
        if not dev_id:
            dev_id = _device_id()
        if dev_id:
            target = max(0, min(100, curr_vol + change))
            sp.volume(target, device_id=dev_id)
            print(f"[spotify] Adjusted volume from {curr_vol}% to {target}%")
            return f"Adjusted Spotify volume from {curr_vol}% to {target}%."
        return "No active Spotify Connect device found to adjust volume."
    except Exception as e:
        return f"Failed to adjust Spotify volume: {e}"

