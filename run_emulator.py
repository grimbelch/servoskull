"""
Run the skull brain on your desktop (macOS or Windows) with a visual LED emulator.

Real:      microphone, speaker, Claude, Whisper STT, ElevenLabs/Piper TTS
Emulated:  GPIO eye LEDs, wake word detection (button/Space)

The OS is auto-detected — the TUI uses the platform's curses backend
(stdlib on macOS, windows-curses on Windows) and TTS falls back to the
platform's system voice (`say` on macOS, SAPI on Windows).

Setup:
    macOS:    pip install -r requirements-mac.txt
    Windows:  pip install -r requirements-windows.txt

Usage:
    python run_emulator.py                        # Space bar triggers wake word
    python run_emulator.py --wake-word            # real mic + Space bar both work
    python run_emulator.py --list-devices         # print audio device list and exit
    python run_emulator.py --mic-device 1         # use device index 1 for this session
"""

import argparse
import os
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

_parser = argparse.ArgumentParser(description="Omega-7 emulator")
_parser.add_argument("--wake-word", action="store_true", help="Use real mic for wake word (plus Space bar)")
_parser.add_argument("--list-devices", action="store_true", help="Print audio device list and exit")
_parser.add_argument("--mic-device", type=int, default=None, metavar="N",
                     help="Override mic device index for this session (see --list-devices)")
_parser.add_argument("--test-mic", action="store_true",
                     help="Record 3 seconds and print audio levels, then exit")
_args = _parser.parse_args()

if _args.list_devices:
    import sounddevice as sd
    print(sd.query_devices())
    sys.exit(0)

if _args.test_mic:
    import sounddevice as sd
    import numpy as np
    dev = _args.mic_device  # None = system default
    dev_label = f"device {dev}" if dev is not None else "default input"
    print(f"Recording 3 seconds from {dev_label} — speak normally...")
    try:
        data = sd.rec(int(3 * 44100), samplerate=44100, channels=1,
                      device=dev, dtype="int16", blocking=True)
        sd.wait()
        rms = float(np.sqrt(np.mean(data.astype(np.float32) ** 2)))
        peak = int(np.max(np.abs(data)))
        print(f"RMS: {rms:.1f}   Peak: {peak}")
        if rms > 100:
            print("  Mic is working (RMS > 100)")
        else:
            print("  Mic appears silent — check System Settings → Privacy & Security → Microphone")
            print("  Make sure your terminal app (VSCode / Terminal) is listed and enabled there.")
    except Exception as e:
        print(f"  Error opening device: {e}")
        print("  Try a different --mic-device index (see --list-devices).")
    sys.exit(0)

if _args.mic_device is not None:
    # Set before skull.config is imported so int(os.getenv("MIC_DEVICE_INDEX")) picks it up.
    os.environ["MIC_DEVICE_INDEX"] = str(_args.mic_device)
    print(f"[emulator] Mic device overridden to index {_args.mic_device}")

# ── 1. Patch hardware modules BEFORE skull.main is imported ────────────────────
from emulator.patches import FakeEyes, FakeWakeWord, HybridWakeWord, get_state, trigger_wake, log_line

sys.modules["skull.eyes"] = FakeEyes()

if _args.wake_word:
    import skull.wake_word as _real_ww  # import real module before replacing it
    _hw = HybridWakeWord(_real_ww)
    sys.modules["skull.wake_word"] = _hw
    # `import skull.wake_word` above set skull.wake_word attribute on the package object.
    # Patching sys.modules alone doesn't update that attribute, so `from skull import wake_word`
    # in skull.main would silently get the real module instead of HybridWakeWord.
    import skull as _skull_pkg
    _skull_pkg.wake_word = _hw
    print("[emulator] Wake word: mic enabled — say your wake word or press Space")
else:
    sys.modules["skull.wake_word"] = FakeWakeWord()
    print("[emulator] Wake word: Space bar only (use --wake-word to enable mic)")

# ── 2. Now safe to import skull.main (its imports see the fakes) ───────────────
import skull.main as skull_main  # noqa: E402  (intentionally after patches)

# ── 3. Wrap brain.respond to capture the conversation for the GUI ──────────────
import skull.brain as _brain

# ── 3b. Redirect print() → GUI log panel so curses display stays clean ─────────
class _GUIStdout:
    """Route skull thread print() calls into the emulator log panel."""
    def __init__(self):
        self._buf = ""
        self._lock = threading.Lock()
    def write(self, s: str) -> int:
        with self._lock:
            self._buf += s
            while "\n" in self._buf:
                line, self._buf = self._buf.split("\n", 1)
                if line.strip():
                    log_line(line)
        return len(s)
    def flush(self) -> None:
        pass

import threading
sys.stdout = _GUIStdout()

state = get_state()

# Wrap audio.record to update emulator status
import skull.audio as _skull_audio
_orig_audio_record = _skull_audio.record

def _patched_audio_record(*args, **kwargs):
    state.status = "RECORDING"
    try:
        return _orig_audio_record(*args, **kwargs)
    finally:
        state.status = "LISTENING"

_skull_audio.record = _patched_audio_record

# Wrap brain.respond to update emulator status and capture conversation
_orig_respond = _brain.respond

def _patched_respond(text: str):
    state.last_heard = text
    state.status = "THINKING"
    try:
        spoken, cmds = _orig_respond(text)
    finally:
        state.status = "SPEAKING"
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

