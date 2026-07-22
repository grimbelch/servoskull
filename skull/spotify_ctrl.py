"""
Spotify playback control via the Web API (Premium required).
Targets the Mac Spotify desktop app via Spotify Connect.
Authentication is lazy — only triggered on the first music command.
"""

from __future__ import annotations
import spotipy
from spotipy.oauth2 import SpotifyOAuth

from skull import config

import time
import requests

def retry_spotify_call(max_retries=3):
    def decorator(func):
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except (spotipy.SpotifyException, requests.exceptions.RequestException) as e:
                    if attempt == max_retries - 1:
                        print(f"[spotify] Failed after {max_retries} attempts: {e}")
                        raise
                    delay = 2 ** attempt
                    print(f"[spotify] Transient error ({e}), retrying in {delay}s...")
                    time.sleep(delay)
            return None
        return wrapper
    return decorator


_SCOPES = " ".join([
    "user-read-playback-state",
    "user-modify-playback-state",
    "user-read-currently-playing",
])

_sp: spotipy.Spotify | None = None


def _client() -> spotipy.Spotify:
    global _sp
    if _sp is None:
        _sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
            client_id=config.SPOTIFY_CLIENT_ID,
            client_secret=config.SPOTIFY_CLIENT_SECRET,
            redirect_uri=config.SPOTIFY_REDIRECT_URI,
            scope=_SCOPES,
            open_browser=True,
            cache_path=str(config.data_path(".spotify_cache")),
        ))
    return _sp


def _normalize_name(name: str) -> str:
    import re
    return re.sub(r"[^a-zA-Z0-9]", "", name).lower()


def _device_id(prefer_name: str = None) -> str | None:
    """Find a Spotify Connect device, optionally by name (partial, case-insensitive)."""
    devices = _client().devices().get("devices", [])
    print(f"[spotify] Available devices: {[d['name'] + ' (' + d['type'] + ')' for d in devices]}")
    if prefer_name:
        norm_prefer = _normalize_name(prefer_name)
        for d in devices:
            if norm_prefer in _normalize_name(d["name"]) and not d["is_restricted"]:
                print(f"[spotify] Routing to '{d['name']}'")
                return d["id"]
        print(f"[spotify] Device matching '{prefer_name}' not found — falling back to default")
    # Default: prefer Computer (desktop app), then any unrestricted device
    for d in devices:
        if d["type"] == "Computer" and not d["is_restricted"]:
            return d["id"]
    for d in devices:
        if not d["is_restricted"]:
            return d["id"]
    return None


def search_and_play(query: str, device_name: str = None) -> str:
    """Search Spotify and play the best match. Returns a human-readable result string."""
    sp = _client()

    results = sp.search(q=query, type="track,playlist", limit=5)
    # Filter out None entries (unavailable/region-locked items)
    playlists = [p for p in ((results.get("playlists") or {}).get("items") or []) if p]
    tracks    = [t for t in ((results.get("tracks")    or {}).get("items") or []) if t]

    # Pick what to play
    uri, label, use_context = None, "nothing", False
    if playlists and len(query.split()) <= 4:
        item = playlists[0]
        uri, label, use_context = item["uri"], item["name"], True
    elif tracks:
        item = tracks[0]
        uri   = item["uri"]
        label = f"{item['name']} by {item['artists'][0]['name']}"

    if uri is None:
        return "not-found"

    dev = _device_id(prefer_name=device_name)
    if dev is None:
        print("[spotify] No available device found. Is the Spotify app open?")
        return "no-device"

    def _play():
        if use_context:
            sp.start_playback(device_id=dev, context_uri=uri)
        else:
            sp.start_playback(device_id=dev, uris=[uri])

    try:
        _play()
        return label
    except spotipy.SpotifyException as e:
        if e.http_status == 404:
            # Device exists but isn't active — transfer playback to wake it then retry
            print(f"[spotify] Device inactive, waking {dev}...")
            try:
                sp.transfer_playback(device_id=dev, force_play=True)
                import time; time.sleep(1.5)
                _play()
                return label
            except Exception as e2:
                return f"playback-error: {e2}"
        return f"spotify-error {e.http_status}: {e.msg}"
    except Exception as e:
        return f"error: {e}"


_pre_duck_volume: int | None = None


@retry_spotify_call()
def duck(level: int = 20) -> None:
    """Lower the music volume while Omega-7 speaks, then restore() afterwards.

    Idempotent (a second call while already ducked is a no-op) and silent when
    nothing is playing. Only acts if Spotify has already been used this session —
    we never force the lazy OAuth flow just to duck, so wake/idle stay snappy and
    headless boots don't block on a browser auth prompt.
    """
    global _pre_duck_volume
    if _sp is None or _pre_duck_volume is not None:
        return
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


@retry_spotify_call()
def restore() -> None:
    """Restore the pre-duck music volume. Idempotent; no-op if not ducked."""
    global _pre_duck_volume
    if _sp is None or _pre_duck_volume is None:
        return
    vol = _pre_duck_volume
    _pre_duck_volume = None
    try:
        pb = _sp.current_playback()
        dev = (pb or {}).get("device") or {}
        _sp.volume(vol, device_id=dev.get("id"))
        print(f"[spotify] Restored volume → {vol}%")
    except Exception as e:
        print(f"[spotify] Restore failed: {e}")


def _active_device_id() -> str | None:
    """The id of whatever device is currently playing, for targeted control calls."""
    try:
        pb = _client().current_playback()
        return ((pb or {}).get("device") or {}).get("id")
    except Exception:
        return None


@retry_spotify_call()
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


@retry_spotify_call()
def resume() -> None:
    try:
        _client().start_playback(device_id=_active_device_id())
        print("[spotify] Resumed")
    except Exception as e:
        print(f"[spotify] Resume failed: {e}")


@retry_spotify_call()
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


@retry_spotify_call()
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

