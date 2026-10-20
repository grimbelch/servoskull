"""
What the two optic LEDs show, as a pure function of time and state.

The round display already shows Omega-7's mood, so the LEDs carry what it does not:
the world around him. Each frame is resolved from layers, highest first:

    machine   both eyes   under-voltage, overheating (core/eye_watch.py)
    activity  both eyes   wake flash, thinking, speaking (core/main.py via eyes.py)
    confirm   both eyes   waiting for a spoken yes/no on update/reboot/shutdown
    blip      one or both a moment: speaker connected, speaker dropped
    status    per eye     left = links (speaker, cast, network)
                          right = tasks (print, reminders, missed messages)
    idle      both eyes   a faint ember, breathing slowly: alive, nothing to report

Several tasks waiting at once take turns on the right eye. Brightness modifiers
(sleep hours, silent mode, an empty room) scale the status layers; in sleep hours
nothing blinks. Everything here is data and arithmetic, so it is unit-tested in
tests/test_eye_states.py; core/eyes.py runs it at 50 FPS and sends the bytes.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

RGBW = tuple[int, int, int, int]

# ── Palette ────────────────────────────────────────────────────────────────────
EMBER = (70, 6, 0)            # idle: fixed, never the mood colour
BT_BLUE = (0, 50, 255)
CAST_VIOLET = (150, 0, 255)
AMBER = (255, 110, 0)
ORANGE = (255, 55, 0)
CYAN = (0, 200, 170)
GREEN = (0, 255, 40)
WHITE = (0, 0, 0)             # with white=True: the pixel's own white channel

# ── Patterns: level (0-1) as a function of seconds since the light began ──────
PATTERNS = ("steady", "breathe", "pulse", "blink", "double", "flicker", "fade")
_BLINKING = {"blink", "double", "flicker"}


def pattern_level(pattern: str, t: float, period: float = 0.0) -> float:
    """Brightness of `pattern` `t` seconds in. `period` overrides the default."""
    if pattern == "breathe":                      # slow, never fully dark
        p = period or 4.0
        return 0.35 + 0.65 * (0.5 - 0.5 * math.cos(2 * math.pi * t / p))
    if pattern == "pulse":                        # deeper; "come and look"
        p = period or 2.5
        return 0.12 + 0.88 * (0.5 - 0.5 * math.cos(2 * math.pi * t / p)) ** 2
    if pattern == "blink":
        p = period or 1.6
        return 1.0 if (t % p) < p / 2 else 0.0
    if pattern == "double":                       # two quick blinks, then a rest
        p = period or 2.0
        x = t % p
        return 1.0 if x < 0.15 or 0.3 <= x < 0.45 else 0.0
    if pattern == "flicker":                      # a bad connection
        step = int(t * 25)
        r = ((step * 2654435761) >> 7) % 1000 / 1000.0
        return 1.0 if r > 0.55 else 0.1 + 0.3 * r
    if pattern == "fade":                         # one-shot, over `period`
        p = period or 1.0
        return max(0.0, 1.0 - t / p)
    return 1.0


@dataclass(frozen=True)
class Light:
    colour: tuple[int, int, int]
    pattern: str = "steady"
    level: float = 1.0            # peak brightness, 0-1
    white: bool = False           # drive the white channel instead of the colour
    period: float = 0.0
    since: float = 0.0            # when it began; patterns run from here
    name: str = ""                # for logs and tests

    def at(self, now: float, calm: bool = False) -> tuple[float, float, float, float]:
        """(r, g, b, w) as floats 0-255 at `now`. `calm` holds blinkers steady."""
        if calm and self.pattern in _BLINKING:
            k = self.level * 0.6
        else:
            k = self.level * pattern_level(self.pattern, now - self.since, self.period)
        if self.white:
            return (0.0, 0.0, 0.0, 255.0 * k)
        r, g, b = self.colour
        return (r * k, g * k, b * k, 0.0)


@dataclass(frozen=True)
class Blip:
    light: Light
    eyes: str                     # "left", "right" or "both"
    until: float


@dataclass
class Frame:
    """Everything a frame depends on. Times are time.monotonic() seconds."""
    now: float
    mood_rgb: tuple[int, int, int] = (255, 40, 30)
    wake_at: float = -1e9         # last wake word
    activity: str = ""            # "", "thinking" or "speaking"
    activity_since: float = 0.0
    amplitude: float = 1.0        # speaking: 0-1 from the voice
    confirming: bool = False
    health: Light | None = None
    blips: list[Blip] = field(default_factory=list)
    links: list[Light] = field(default_factory=list)   # left eye, best first
    tasks: list[Light] = field(default_factory=list)   # right eye, take turns
    scale: float = 1.0            # brightness modifier for the status layers
    calm: bool = False            # sleep hours: nothing blinks
    fade: float = 1.0             # boot fade-in / shutdown fade-out, 0-1


# Idle: the ember breathes, each eye on its own period so they drift in and out
# of step, a living gaze rather than a pair of pilot lights.
IDLE_LEFT = Light(EMBER, "breathe", period=4.2, name="idle")
IDLE_RIGHT = Light(EMBER, "breathe", period=5.6, since=1.9, name="idle")

WAKE_FLASH_SECS = 0.5
TASK_TURN_SECS = 3.0
_PINGPONG_SECS = 1.6


def _rgbw(c: tuple[float, float, float, float], k: float = 1.0) -> RGBW:
    return tuple(int(max(0.0, min(255.0, v * k))) for v in c)  # type: ignore[return-value]


def _scaled(rgb: tuple[int, int, int], k: float) -> tuple[float, float, float, float]:
    return (rgb[0] * k, rgb[1] * k, rgb[2] * k, 0.0)


def resolve(f: Frame) -> tuple[RGBW, RGBW]:
    """The (left, right) colour for this frame."""
    now = f.now

    # Machine health beats everything, and never dims below half.
    if f.health is not None:
        c = f.health.at(now)
        k = f.fade * max(0.5, f.scale)
        return _rgbw(c, k), _rgbw(c, k)

    # Activity: he is talking to someone, so the room's modifiers don't apply.
    act_k = f.fade * max(0.6, f.scale) if f.calm else f.fade
    t_wake = now - f.wake_at
    if 0.0 <= t_wake < WAKE_FLASH_SECS:
        x = 1.0 - t_wake / WAKE_FLASH_SECS
        c = (*f.mood_rgb[:3], 255.0 * x * x)
        return _rgbw(c, act_k), _rgbw(c, act_k)
    if f.activity == "thinking":
        phase = 2 * math.pi * (now - f.activity_since) / _PINGPONG_SECS
        left = 0.08 + 0.72 * (0.5 + 0.5 * math.cos(phase))
        right = 0.08 + 0.72 * (0.5 - 0.5 * math.cos(phase))
        return (_rgbw(_scaled(f.mood_rgb, left), act_k),
                _rgbw(_scaled(f.mood_rgb, right), act_k))
    if f.activity == "speaking":
        c = _scaled(f.mood_rgb, max(0.2, min(1.0, f.amplitude)))
        return _rgbw(c, act_k), _rgbw(c, act_k)

    # Waiting for a spoken yes/no.
    if f.confirming:
        c = Light(AMBER, "blink", period=1.0).at(now)
        return _rgbw(c, act_k), _rgbw(c, act_k)

    k = f.fade * f.scale
    left = f.links[0].at(now, f.calm) if f.links else IDLE_LEFT.at(now)
    if f.tasks:
        turn = int(now / TASK_TURN_SECS) % len(f.tasks)
        right = f.tasks[turn].at(now, f.calm)
    else:
        right = IDLE_RIGHT.at(now)

    for b in f.blips:                 # latest blip wins its eye
        if now < b.until:
            c = b.light.at(now)
            if b.eyes in ("left", "both"):
                left = c
            if b.eyes in ("right", "both"):
                right = c

    return _rgbw(left, k), _rgbw(right, k)

