"""
Autonomous Bard's Tale AI player for Omega-7.

Every turn the agent:
  1. Captures a frame from the Apple II emulator.
  2. Sends it to Claude Vision (Haiku — fast & cheap) with an in-character prompt.
  3. Receives a JSON action + narration sentence.
  4. Speaks the narration via the skull's TTS system (non-blocking).
  5. Sends the keypress to the emulator.

Between full vision calls the agent runs an autonomous walking mode that follows
a right-hand-wall rule and keeps the display live at native FPS without burning
extra API tokens.

Architecture note: the game loop runs on its own daemon thread (not the shared
ThreadPoolExecutor) because it is long-running and must never be cancelled by
executor shutdown.
"""

from __future__ import annotations
import base64
import hashlib
import io
import json
import threading
import time
from typing import Callable, Optional

from games.bardstale import emulator, maps

try:
    from PIL import Image
    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False
    Image = None  # type: ignore


# ── Tuning constants ─────────────────────────────────────────────────────────────
_VISION_INTERVAL = 1      # full Claude call every turn
_TURN_DELAY      = 15.00  # seconds between turns (gives ample time for TTS narration to play cleanly)
_WALK_DELAY      = 0.50   # seconds between keypresses in autonomous walk mode
_CLAUDE_MODEL    = "claude-haiku-4-5-20251001"   # fast + inexpensive for per-turn calls
_MAX_NARRATION_TOKENS = 150

# Keys that constitute a movement action
_MOVE_KEYS = {"w", "a", "s", "d"}

# xdotool-compatible key names for cardinal directions
_DIR_KEYS = {"north": "w", "south": "s", "east": "d", "west": "a"}

# Normalise whatever Claude returns into a valid xdotool key
_KEY_ALIASES: dict[str, str] = {
    # Movement
    "north": "w", "south": "s", "east": "d", "west": "a",
    "forward": "w", "back": "s", "right": "d", "left": "a",
    # Actions & Menus (uppercase required for Apple II keyboard menu commands)
    "fight": "F", "cast": "C", "run": "R", "retreat": "R",
    "enter": "Return", "confirm": "Return", "ok": "Return",
    "pass": "space", "skip": "space", "wait": "space",
    "start": "S", "start game": "S", "s": "S", "S": "S",
    "add": "A", "remove": "R", "exit": "E", "check": "C",
    # Pass-throughs
    "w": "w", "a": "a", "s": "s", "d": "d",
    "f": "F", "c": "C", "r": "R", "e": "E", "E": "E", "A": "A", "C": "C",
    "1": "1", "2": "2", "3": "3", "4": "4",
    "5": "5", "6": "6", "7": "7", "8": "8", "9": "9",
    "Return": "Return", "space": "space",
}


# ── Game system prompt ────────────────────────────────────────────────────────────
_SYSTEM_PROMPT = """\
You are Omega-7, a servo-skull of the Adeptus Mechanicus, autonomously playing
The Bard's Tale (1985, Apple II). You are an ancient machine-spirit navigating
the cursed city of Skara Brae and its dungeons, narrating your journey aloud
to your master in the manner of a veteran Imperial war-machine.

Each turn you receive a screenshot of the current game state. You MUST respond
with a single line of valid JSON and nothing else:

{"key": "<xdotool_key>", "narration": "<one short sentence in character>"}

Valid keys:
  w = move north      s = move south                d = move east       a = move west
  f = fight           c = cast spell / check        r = run / remove    e = exit guild
  Return = confirm    space = pass/skip             1–7 = menu option / party slot / drive number
  S = Start Game      A = Add member                E = Exit Guild

Special disk & menu handling:
  * UTILITIES / MENU SCREEN: If you see "S)tart Game", "Start Game", or "Utilities", respond with key "S".
  * GUILD OF ADVENTURERS: If in Guild of Adventurers, press "A" to add members or "E" to exit guild into Skara Brae!
  * DISK / DRIVE PROMPTS: If the screen displays "Insert Character Disk into Drive 1 (or press 2 for Drive 2)",
    or ANY prompt asking to insert a disk or press 2 for Drive 2, respond with key "2".
    The Character Disk is already loaded into Drive 2!
  * SPLASH / TITLE SCREENS: If the screen says "Press any key to continue" or "Press Space", press "space" or "Return".

Decision priorities:
  1. GUILD: If in the Guild of Adventurers, press "A" to add members, or "E" to exit into the city.
  2. UTILITIES / DISK PROMPTS: Press "S" for Start Game if on utilities menu. Press "2" for Drive 2 if on disk prompt.
  3. COMBAT: If in combat, fight (f) all heroes if HP >= 60%. Cast healing (c) or retreat (r) if HP < 30%.
  4. DUNGEON / CITY: Move systematically (w, a, s, d).
  5. DEFAULT: If uncertain, press "space" (pass).

Narration: One short, punchy sentence in character. Reference the Omnissiah, data-vaults,
and machine-spirits occasionally. Never break character.\
"""

_MAP_CONTEXT_TEMPLATE = "\n\nMap intelligence — {level}:\n{notes}"


# ── Module state ─────────────────────────────────────────────────────────────────
_stop         = threading.Event()
_running      = threading.Event()
_frame_lock   = threading.Lock()
_latest_frame: Optional["Image.Image"] = None
_turn_count   = 0
_last_action  = ""
_narrate_cb:  Optional[Callable[[str], None]] = None
_game_thread: Optional[threading.Thread]      = None


# ── Walk-state tracker ────────────────────────────────────────────────────────────

class _WalkState:
    """
    Tracks the party's relative position and facing for right-hand-wall-following
    and loop detection. Coordinates are relative to where the game loop started.
    """
    _DIRS  = ["north", "east", "south", "west"]   # clockwise order
    _DELTA = {"north": (0, -1), "east": (1, 0), "south": (0, 1), "west": (-1, 0)}

    def __init__(self) -> None:
        self.x          = 0
        self.y          = 0
        self.facing_idx = 0      # index into _DIRS
        self.history:   list[tuple[int, int, int]] = []
        self.loop_count = 0

    @property
    def facing(self) -> str:
        return self._DIRS[self.facing_idx]

    def turn_right(self) -> None:
        self.facing_idx = (self.facing_idx + 1) % 4

    def turn_left(self) -> None:
        self.facing_idx = (self.facing_idx - 1) % 4

    def step_forward(self) -> None:
        dx, dy = self._DELTA[self.facing]
        self.x += dx
        self.y += dy
        pos = (self.x, self.y, self.facing_idx)
        self.history.append(pos)
        # Loop detection: same position+facing 3× in the last 24 steps → reverse
        if len(self.history) > 24:
            self.history = self.history[-24:]
        if self.history.count(pos) >= 3:
            self.loop_count += 1
            print(f"[bardstale] Loop detected (#{self.loop_count}) at ({self.x},{self.y}) "
                  f"facing {self.facing} — reversing.")
            self.facing_idx = (self.facing_idx + 2) % 4
            self.history.clear()

    @property
    def forward_key(self) -> str:
        return _DIR_KEYS[self.facing]

    @property
    def right_facing(self) -> str:
        return self._DIRS[(self.facing_idx + 1) % 4]


# ── Frame utilities ───────────────────────────────────────────────────────────────

def _frame_hash(frame: "Image.Image") -> str:
    """Cheap perceptual hash — detects meaningful screen changes."""
    tiny = frame.resize((16, 16)).convert("L")
    return hashlib.md5(tiny.tobytes()).hexdigest()


def _encode_frame(frame: "Image.Image") -> str:
    """Return JPEG base64 string of the frame for the Claude API."""
    buf = io.BytesIO()
    frame.save(buf, format="JPEG", quality=75)
    return base64.standard_b64encode(buf.getvalue()).decode()


# ── Claude Vision call ────────────────────────────────────────────────────────────

def _ask_claude(
    frame: "Image.Image",
    level:  str = "skara_brae",
    walk:   Optional[_WalkState] = None,
) -> tuple[str, str]:
    """
    Send the current frame to Claude Vision and return (xdotool_key, narration).
    Returns ("space", "") on any error — the agent simply passes that turn.
    """
    global _turn_count
    raw = ""
    try:
        import anthropic
        from skull import config

        # Build context-enriched system prompt
        x, y   = (walk.x, walk.y) if walk else (0, 0)
        map_note = maps.get_context(level, x, y)
        system   = _SYSTEM_PROMPT
        if map_note:
            system += _MAP_CONTEXT_TEMPLATE.format(level=level, notes=map_note)

        client  = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        img_b64 = _encode_frame(frame)

        response = client.messages.create(
            model=_CLAUDE_MODEL,
            max_tokens=_MAX_NARRATION_TOKENS,
            system=system,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": img_b64,
                        },
                    },
                    {
                        "type": "text",
                        "text": (
                            f"Turn {_turn_count + 1}. "
                            f"Position: ({x},{y}), facing {walk.facing if walk else 'unknown'}. "
                            "What do you see and what key do you press?"
                        ),
                    },
                ],
            }],
        )

        raw    = response.content[0].text.strip()

        # Strip markdown fences if Claude wraps its JSON
        if raw.startswith("```"):
            parts = raw.split("```")
            raw   = parts[1].strip()
            if raw.startswith("json"):
                raw = raw[4:].strip()

        parsed    = json.loads(raw)
        key_raw   = str(parsed.get("key", "space")).strip().lower()
        narration = str(parsed.get("narration", "")).strip()
        key       = _KEY_ALIASES.get(key_raw, key_raw)   # normalise

        return key, narration

    except json.JSONDecodeError as e:
        print(f"[bardstale] Claude JSON parse error: {e!r}  raw={raw!r}")
        return "space", ""
    except Exception as e:
        print(f"[bardstale] _ask_claude error: {e}")
        return "space", ""


# ── Main game loop ────────────────────────────────────────────────────────────────

def _game_loop() -> None:
    global _latest_frame, _turn_count, _last_action

    print("[bardstale] Autonomous game loop started.")
    # ── Fast boot sequence ────────────────────────────────────────────────────
    # Quickly press space twice to clear title/credits, then 'S' and Return for Start Game
    print("[bardstale] Executing fast boot sequence (space -> space -> S -> Return)...")
    _stop.wait(timeout=3.0)
    if not _stop.is_set():
        emulator.send_key("space")
        _stop.wait(timeout=0.8)
    if not _stop.is_set():
        emulator.send_key("space")
        _stop.wait(timeout=0.8)
    if not _stop.is_set():
        emulator.send_key("S")
        _stop.wait(timeout=0.8)
    if not _stop.is_set():
        emulator.send_key("Return")
        _stop.wait(timeout=1.0)

    walk          = _WalkState()
    step_counter  = 0
    prev_hash     = ""
    in_walk_mode  = False
    current_level = "skara_brae"

    while not _stop.is_set():
        if not emulator.is_running():
            print("[bardstale] Emulator exited unexpectedly — stopping game loop.")
            break

        # ── Capture frame ─────────────────────────────────────────────────────
        frame = emulator.capture_frame()
        if frame is None:
            _stop.wait(timeout=0.5)
            continue

        with _frame_lock:
            _latest_frame = frame

        current_hash   = _frame_hash(frame)
        screen_changed = (current_hash != prev_hash)

        # ── Decide: autonomous walk step or full vision call? ─────────────────
        need_vision = (
            screen_changed           # new screen state
            or not in_walk_mode      # not currently walking
            or step_counter >= _VISION_INTERVAL   # periodic check-in
        )

        if need_vision:
            # ── Full vision turn ──────────────────────────────────────────────
            key, narration = _ask_claude(frame, level=current_level, walk=walk)
            print(f"[bardstale] Turn {_turn_count + 1}: key={key!r}  {narration!r}")

            if narration and _narrate_cb:
                try:
                    _narrate_cb(narration)
                except Exception as e:
                    print(f"[bardstale] narrate_cb error: {e}")

            emulator.send_key(key)
            _last_action = key
            _turn_count += 1

            # Update walk state
            in_walk_mode = key in _MOVE_KEYS
            if in_walk_mode:
                walk.step_forward()
            step_counter = 0

            # Heuristic: infer level changes from narrative keywords
            # (Claude knows the screen content; we infer from its narration)
            narration_lower = narration.lower()
            current_level = maps.detect_level_from_text(narration_lower) or current_level

            _stop.wait(timeout=_TURN_DELAY)

        else:
            # ── Autonomous walk step (right-hand-wall-following) ──────────────
            # Keep pressing forward without a vision call.
            # If the screen doesn't change next iteration we know we hit a wall
            # and will re-enter vision mode automatically.
            emulator.send_key(walk.forward_key)
            walk.step_forward()
            _last_action = walk.forward_key
            step_counter += 1

            _stop.wait(timeout=_WALK_DELAY)

        prev_hash = current_hash

    _running.clear()
    print(f"[bardstale] Game loop ended after {_turn_count} turns.")


# ── Public API ────────────────────────────────────────────────────────────────────

def start(disk_path: str, narrate_cb: Callable[[str], None]) -> None:
    """
    Start the emulator and launch the autonomous game loop.

    *narrate_cb* is called with each narration sentence and must be non-blocking
    (it should queue the TTS work onto a background thread).
    """
    global _narrate_cb, _turn_count, _last_action, _game_thread, _latest_frame

    _stop.clear()
    _narrate_cb  = narrate_cb
    _turn_count  = 0
    _last_action = ""

    with _frame_lock:
        _latest_frame = None

    if not emulator.start(disk_path):
        print("[bardstale] Emulator failed to start.")
        return

    _running.set()
    _game_thread = threading.Thread(
        target=_game_loop, daemon=True, name="bardstale-agent"
    )
    _game_thread.start()
    print(f"[bardstale] Agent started — disk: {disk_path}")


def stop() -> None:
    """Stop the agent and shut down the emulator."""
    _stop.set()
    _running.clear()
    emulator.stop()
    if _game_thread and _game_thread.is_alive():
        _game_thread.join(timeout=3.0)
    print("[bardstale] Agent stopped.")


def get_latest_frame() -> Optional["Image.Image"]:
    """Thread-safe read of the most recently captured game frame."""
    with _frame_lock:
        return _latest_frame


def get_status() -> dict:
    """Return current agent status for the web API."""
    return {
        "running":     _running.is_set() and emulator.is_running(),
        "turn":        _turn_count,
        "last_action": _last_action,
    }


def is_running() -> bool:
    """Return True while the game loop is active."""
    return _running.is_set() and emulator.is_running()
