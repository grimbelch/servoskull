"""
Run the skull brain on your desktop (macOS or Windows) with a visual LED emulator.

Real:      microphone, speaker, Claude, Whisper STT, ElevenLabs/Piper TTS
Emulated:  GPIO eye LEDs, APA102 candle LEDs, wake word detection (button/Space)

The OS is auto-detected — the TUI uses the platform's curses backend
(stdlib on macOS, windows-curses on Windows) and TTS falls back to the
platform's system voice (`say` on macOS, SAPI on Windows).

Setup:
    macOS:    pip install -r requirements-mac.txt
    Windows:  pip install -r requirements-windows.txt

Usage:
    python run_emulator.py                  # Space bar triggers wake word
    python run_emulator.py --wake-word      # real mic + Space bar both work
"""

import argparse
import platform
import sys
import warnings
warnings.filterwarnings("ignore", message=".*LibreSSL.*")
warnings.filterwarnings("ignore", message=".*NotOpenSSL.*")

print(f"[emulator] Detected {platform.system()} ({sys.platform}) — starting Omega-7 emulator.")

if sys.platform == "win32":
    try:
        import curses  # noqa: F401  (windows-curses provides this on Windows)
    except ImportError:
        sys.exit(
            "[emulator] The 'curses' module is missing. On Windows, install it with:\n"
            "    pip install -r requirements-windows.txt\n"
            "(or: pip install windows-curses)"
        )

_args = argparse.ArgumentParser(description="Omega-7 emulator")
_args.add_argument("--wake-word", action="store_true", help="Use real mic for wake word (plus Space bar)")
_args = _args.parse_args()

# ── 1. Patch hardware modules BEFORE skull.main is imported ────────────────────
from emulator.patches import FakeEyes, FakeCandle, FakeWakeWord, HybridWakeWord, get_state, trigger_wake

sys.modules["skull.eyes"]        = FakeEyes()
sys.modules["skull.candle_leds"] = FakeCandle()

if _args.wake_word:
    import skull.wake_word as _real_ww  # import real module before replacing it
    sys.modules["skull.wake_word"] = HybridWakeWord(_real_ww)
    print("[emulator] Wake word: mic enabled — say your wake word or press Space")
else:
    sys.modules["skull.wake_word"] = FakeWakeWord()
    print("[emulator] Wake word: Space bar only (use --wake-word to enable mic)")

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

