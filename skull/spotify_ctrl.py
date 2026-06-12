"""
Spotify playback control via the Web API (Premium required).
Targets the Mac Spotify desktop app via Spotify Connect.
Authentication is lazy — only triggered on the first music command.
"""

from __future__ import annotations
import os
import spotipy
from spotipy.oauth2 import SpotifyOAuth

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
            client_id=os.environ["SPOTIFY_CLIENT_ID"],
            client_secret=os.environ["SPOTIFY_CLIENT_SECRET"],
            redirect_uri=os.environ.get("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback"),
            scope=_SCOPES,
            open_browser=True,
            cache_path=".spotify_cache",
        ))
    return _sp


def _device_id() -> str | None:
    """Find the Mac Spotify desktop app, or any available device."""
    devices = _client().devices().get("devices", [])
    print(f"[spotify] Available devices: {[d['name'] + ' (' + d['type'] + ')' for d in devices]}")
    # Prefer an unrestricted Computer (desktop app)
    for d in devices:
        if d["type"] == "Computer" and not d["is_restricted"]:
            return d["id"]
    # Fall back to any unrestricted device
    for d in devices:
        if not d["is_restricted"]:
            return d["id"]
    return None


def search_and_play(query: str) -> str:
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

    dev = _device_id()

    def _play():
        if use_context:
            sp.start_playback(device_id=dev, context_uri=uri)
        else:
            sp.start_playback(device_id=dev, uris=[uri])

    try:
        _play()
        return label
    except spotipy.SpotifyException as e:
        if e.http_status == 404 and dev:
            # No active device — wake it up then retry
            print(f"[spotify] Waking device {dev}")
            sp.transfer_playback(device_id=dev, force_play=True)
            import time; time.sleep(1.5)
            try:
                _play()
                return label
            except Exception as e2:
                return f"playback-error: {e2}"
        return f"spotify-error {e.http_status}: {e.msg}"
    except Exception as e:
        return f"error: {e}"


def pause() -> None:
    try:
        _client().pause_playback()
    except Exception:
        pass


def resume() -> None:
    try:
        _client().start_playback()
    except Exception:
        pass


def skip() -> None:
    try:
        _client().next_track()
    except Exception:
        pass


def is_configured() -> bool:
    return bool(os.environ.get("SPOTIFY_CLIENT_ID") and os.environ.get("SPOTIFY_CLIENT_SECRET"))
