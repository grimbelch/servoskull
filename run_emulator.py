"""
Run the skull brain on your Mac with a visual LED emulator.

Real on Mac:  microphone, speaker, Claude, Whisper STT, ElevenLabs TTS
Emulated:     GPIO eye LEDs, APA102 candle LEDs, wake word detection (button/Space)

Usage:
    python run_emulator.py
"""

import sys
import warnings
warnings.filterwarnings("ignore", message=".*LibreSSL.*")
warnings.filterwarnings("ignore", message=".*NotOpenSSL.*")

# ── 1. Patch hardware modules BEFORE skull.main is imported ────────────────────
from emulator.patches import FakeEyes, FakeCandle, FakeWakeWord, get_state, trigger_wake

sys.modules["skull.eyes"]        = FakeEyes()
sys.modules["skull.candle_leds"] = FakeCandle()
sys.modules["skull.wake_word"]   = FakeWakeWord()

# ── 2. Now safe to import skull.main (its imports see the fakes) ───────────────
import skull.main as skull_main  # noqa: E402  (intentionally after patches)

# ── 3. Wrap brain.respond to capture the conversation for the GUI ──────────────
import skull.brain as _brain

state = get_state()
_orig_respond = _brain.respond

def _patched_respond(text: str):
    state.last_heard = text
    spoken, cmds = _orig_respond(text)
    state.last_reply = spoken
    return spoken, cmds

_brain.respond = _patched_respond

# ── 4. Run skull loop in a background thread ───────────────────────────────────
import threading

skull_thread = threading.Thread(target=skull_main.main, daemon=True)
skull_thread.start()

# ── 5. GUI on the main thread (blocks until window is closed) ──────────────────
from emulator.gui import run_gui

run_gui(state, trigger_wake)

# ── 6. Clean shutdown — suppress PortAudio's macOS teardown noise ──────────────
import os
from skull import audio as _audio

_devnull = os.open(os.devnull, os.O_WRONLY)
_old_stderr = os.dup(2)
os.dup2(_devnull, 2)
try:
    _audio.cleanup()
finally:
    os.dup2(_old_stderr, 2)
    os.close(_devnull)
    os.close(_old_stderr)
