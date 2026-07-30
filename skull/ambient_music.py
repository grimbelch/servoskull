"""
Ambient Sacred Music module for Omega-7 Servo Skull.

Scans the sounds/Music/ directory for audio files (.ogg, .mp3, .wav, .flac, .m4a)
and occasionally plays a random ~15-second snippet during idle periods, separate from
text observations. Respects silent mode and quiet hours.
"""

from __future__ import annotations
import os
import pathlib
import random
import subprocess
import threading
import time

from skull import config

MUSIC_DIR = pathlib.Path(__file__).parent.parent / "sounds" / "Music"
MUSIC_DIR_ALT = pathlib.Path(__file__).parent.parent / "sounds" / "music"

SUPPORTED_EXTENSIONS = {".ogg", ".mp3", ".wav", ".flac", ".m4a", ".aac"}

_loop_thread: threading.Thread | None = None
_stop_event = threading.Event()
_is_playing_snippet = False
_snippet_lock = threading.Lock()


def get_music_files() -> list[pathlib.Path]:
    """Return a list of available music files in sounds/Music/."""
    files: list[pathlib.Path] = []
    dirs_to_check = [MUSIC_DIR, MUSIC_DIR_ALT]
    for d in dirs_to_check:
        if d.exists() and d.is_dir():
            for p in d.iterdir():
                if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS:
                    if p not in files:
                        files.append(p)
    return files


def get_file_duration(file_path: pathlib.Path) -> float:
    """Return track duration in seconds using ffprobe, or default to 180.0 if failed."""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(file_path),
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=5.0)
        if res.returncode == 0 and res.stdout.strip():
            return float(res.stdout.strip())
    except Exception as e:
        print(f"[ambient_music] ffprobe duration query error for {file_path.name}: {e}")
    return 180.0


def extract_random_snippet_wav(file_path: pathlib.Path, duration_sec: float = 15.0) -> bytes | None:
    """Extract a random duration_sec WAV snippet from the given audio file using ffmpeg."""
    total_dur = get_file_duration(file_path)
    max_start = max(0.0, total_dur - duration_sec)
    start_sec = random.uniform(0.0, max_start) if max_start > 0 else 0.0

    cmd = [
        "ffmpeg",
        "-ss",
        f"{start_sec:.2f}",
        "-i",
        str(file_path),
        "-t",
        f"{duration_sec:.2f}",
        "-ar",
        "44100",
        "-ac",
        "1",
        "-f",
        "wav",
        "-",
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, timeout=10.0)
        if res.returncode == 0 and res.stdout:
            return res.stdout
    except Exception as e:
        print(f"[ambient_music] ffmpeg snippet extraction error for {file_path.name}: {e}")
    return None


def play_random_snippet(specific_name: str | None = None, duration_sec: float = 15.0, force: bool = False) -> str | None:
    """Extract and play a snippet from a music file. Returns a descriptive string or None if unplayable."""
    global _is_playing_snippet
    from skull import quiet, audio, spotify_ctrl

    if not force and quiet.is_silent():
        print("[ambient_music] Silent mode / Quiet hours active — skipping ambient music snippet.")
        return None

    if spotify_ctrl.is_playing() and not force:
        print("[ambient_music] Spotify playback active — skipping ambient music snippet.")
        return None

    files = get_music_files()
    if not files:
        print("[ambient_music] No music files found in sounds/Music/")
        return None

    chosen_file = None
    if specific_name:
        for f in files:
            if specific_name.lower() in f.name.lower():
                chosen_file = f
                break

    if not chosen_file:
        chosen_file = random.choice(files)

    print(f"[ambient_music] Extracting {duration_sec}s snippet from '{chosen_file.name}'...")
    wav_bytes = extract_random_snippet_wav(chosen_file, duration_sec=duration_sec)
    if not wav_bytes:
        print(f"[ambient_music] Failed to extract WAV bytes from '{chosen_file.name}'")
        return None

    with _snippet_lock:
        _is_playing_snippet = True

    try:
        from skull import eyes, display
        display.on()
        eyes.on()
        print(f"[ambient_music] Playing sacred ambient music snippet: '{chosen_file.name}'")
        audio.play_wav_bytes(wav_bytes, output_device=config.VOICE_OUTPUT_DEVICE)
        return f"Played sacred music snippet from '{chosen_file.name}'."
    except Exception as e:
        print(f"[ambient_music] Error playing snippet: {e}")
        return None
    finally:
        with _snippet_lock:
            _is_playing_snippet = False
        try:
            from skull import eyes, display
            display.idle()
            eyes.off()
        except Exception:
            pass


def _ambient_music_loop() -> None:
    """Background daemon loop playing an ambient music snippet every 15 to 30 minutes while idle."""
    _IDLE_MIN, _IDLE_MAX = 15 * 60, 30 * 60  # seconds (15 to 30 mins)
    print(f"[ambient_music] Background ambient sacred music loop active (interval: {_IDLE_MIN/60:.0f}–{_IDLE_MAX/60:.0f}m)")

    while not _stop_event.is_set():
        interval = random.uniform(_IDLE_MIN, _IDLE_MAX)
        if _stop_event.wait(timeout=interval):
            break

        from skull import quiet, spotify_ctrl, main
        if quiet.is_silent():
            continue

        if spotify_ctrl.is_playing():
            continue

        if hasattr(main, "is_speech_active") and main.is_speech_active():
            continue

        play_random_snippet(duration_sec=15.0)


def start() -> None:
    """Start the ambient music background thread."""
    global _loop_thread
    if _loop_thread is None or not _loop_thread.is_alive():
        _stop_event.clear()
        _loop_thread = threading.Thread(target=_ambient_music_loop, daemon=True)
        _loop_thread.start()


def stop() -> None:
    """Stop the ambient music background thread."""
    _stop_event.set()
