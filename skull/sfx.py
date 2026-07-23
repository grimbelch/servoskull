"""
Omega-7 sound effects library.

All functions fail silently if the sounds/ directory hasn't been generated yet
(run generate_sounds.py once to populate it). This keeps the skull fully
functional even without the sound library present.
"""

from __future__ import annotations
import pathlib
import threading

SOUNDS_DIR = pathlib.Path(__file__).parent.parent / "sounds"

# Lazy cache: loaded on first play, not at import time, to keep startup fast.
_cache: dict[str, bytes] = {}


def _load(name: str) -> bytes | None:
    if name in _cache:
        return _cache[name]
    path = SOUNDS_DIR / f"{name}.wav"
    if not path.exists():
        return None
    try:
        data = path.read_bytes()
        _cache[name] = data
        return data
    except Exception:
        return None


def play(name: str, output_device=None) -> None:
    """Play a sound effect asynchronously in a background thread."""
    wav = _load(name)
    if wav is None:
        return
    from skull import audio as _audio

    kwargs: dict = {}
    if output_device is not None:
        if isinstance(output_device, str) or (isinstance(output_device, int) and output_device >= 0):
            kwargs["output_device"] = output_device
    threading.Thread(
        target=_audio.play_wav_bytes,
        args=(wav,),
        kwargs=kwargs,
        daemon=True,
    ).start()


def play_blocking(name: str, output_device=None) -> None:
    """Play a sound effect and block until it finishes."""
    wav = _load(name)
    if wav is None:
        return
    from skull import audio as _audio
    kwargs: dict = {}
    if output_device is not None:
        if isinstance(output_device, str) or (isinstance(output_device, int) and output_device >= 0):
            kwargs["output_device"] = output_device
    _audio.play_wav_bytes(wav, **kwargs)
