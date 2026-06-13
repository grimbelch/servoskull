"""
Drop-in replacements for skull.eyes, skull.candle_leds, and skull.wake_word.
Inject into sys.modules before importing skull.main.
"""

import threading


class EmulatorState:
    eye_brightness: float = 0.0   # 0–100
    candle_state: str = "off"     # idle | listen | think | off
    last_heard: str = ""
    last_reply: str = ""


_state = EmulatorState()
_wake_event = threading.Event()


def get_state() -> EmulatorState:
    return _state


def trigger_wake() -> None:
    _wake_event.set()


# ── Fake skull.eyes ────────────────────────────────────────────────────────────

class FakeEyes:
    def setup(self, pin_left, pin_center, pin_right):
        pass

    def set_brightness(self, pct: float):
        _state.eye_brightness = max(0.0, min(100.0, pct))

    def on(self):
        _state.eye_brightness = 100.0

    def off(self):
        _state.eye_brightness = 0.0

    def set_amplitude(self, amp: float):
        _state.eye_brightness = 20.0 + 80.0 * min(1.0, amp * 5)

    def cleanup(self):
        _state.eye_brightness = 0.0


# ── Fake skull.candle_leds ─────────────────────────────────────────────────────

class FakeCandle:
    def idle(self):
        _state.candle_state = "idle"

    def listen(self):
        _state.candle_state = "listen"

    def think(self):
        _state.candle_state = "think"

    def off(self):
        _state.candle_state = "off"

    def cleanup(self):
        _state.candle_state = "off"


# ── Fake skull.wake_word ───────────────────────────────────────────────────────

class FakeWakeWord:
    def wait_for_wake_word(self, on_detected=None, cancel=None):
        print('[emulator] Waiting — press Space or click "Trigger Wake Word"')
        while True:
            triggered = _wake_event.wait(timeout=0.1)
            if triggered:
                _wake_event.clear()
                if on_detected:
                    on_detected()
                return True
            if cancel and cancel.is_set():
                return False


class HybridWakeWord:
    """Wake word triggered by either the real OpenWakeWord mic model or the Space bar."""

    def __init__(self, real_module):
        self._real = real_module

    def wait_for_wake_word(self, on_detected=None, cancel=None):
        _trigger = threading.Event()
        _real_cancel = threading.Event()

        def _real_listener():
            try:
                if self._real.wait_for_wake_word(cancel=_real_cancel):
                    _trigger.set()
            except Exception as e:
                print(f"[emulator] Wake word mic error: {e}")

        t = threading.Thread(target=_real_listener, daemon=True)
        t.start()

        while True:
            # Space bar trigger
            if _wake_event.wait(timeout=0.05):
                _wake_event.clear()
                _real_cancel.set()
                if on_detected:
                    on_detected()
                return True
            # Real mic trigger
            if _trigger.is_set():
                _real_cancel.set()
                if on_detected:
                    on_detected()
                return True
            # External cancel (barge-in shutdown)
            if cancel and cancel.is_set():
                _real_cancel.set()
                return False
