"""
Drives a GC9A01 1.28" round IPS panel (240x240, 4-wire SPI) as Omega-7's
"machine-spirit" eye. A background thread renders a glowing iris whose size and
brightness track speech amplitude (the same signal that pulses the eye LEDs),
with a slow idle "breathing" pulse when silent. Mood tints the iris colour.

Self-contained driver (spidev + RPi.GPIO + Pillow) so it carries no dependency
on luma/Adafruit supporting GC9A01. Mirrors eyes.py: if the hardware or libs are
absent (e.g. non-Pi dev hosts), every entry point is a silent no-op.

Enable with DISPLAY_ENABLED=true in .env. Wiring lives in config.py.
"""

from __future__ import annotations
import json
import math
import random
import threading

_state_lock = threading.Lock()
import time

from core import config
from core import dice_faces
from core import dice3d
import importlib

_persona_key = config.get_personality_key() if hasattr(config, "get_personality_key") else config.SKULL_NAME.lower().replace("-", "")
_screensavers = None
try:
    _screensavers = importlib.import_module(f"personalities.{_persona_key}.screensavers")
except Exception as e:
    print(f"[display] Could not load personality screensavers module: {e}")

_display_module = None
try:
    _display_module = importlib.import_module(f"personalities.{_persona_key}.display")
except Exception as e:
    print(f"[display] Could not load personality display module: {e}")

_available = False
_spi = None
_GPIO = None
_render_thread: threading.Thread | None = None
_stop = threading.Event()

# Shared render state (plain float/tuple assignment is atomic enough for our needs).
_target_amp = 0.0          # 0..1, set from the speech-amplitude loop
_speaking = False          # True while audio is playing
_thinking = False          # True while the brain is cogitating; spins the cog
_mood_rgb = (255, 40, 30)  # base iris colour; default Imperial red
_rolling_die = False
_die_start_time = 0.0
_die_result = "0"
_die_kind = "d6"        # injury | firepower | scatter | d6 | num
_die_faces: tuple = ()  # symbol per dice, from dice.face_symbol()
_die_detail: tuple = () # per-dice extra: arrow direction, pip value, numeral
_die_chosen = -1        # dice to ring as the one that matters, or -1
_die_steps: list = []   # a whole attack, one roll per step; [] for a single roll
_die_step = 0           # which step of that sequence is on screen
_scanning_auspex = False
_scanning_noosphere = False
_searching_web = False
_web_search_until = 0.0
_looking_up_rules = False
_rules_lookup_until = 0.0
_fetching_news = False
_news_fetch_until = 0.0
_retrieving_image = False
_image_retrieval_until = 0.0
_targeting = False
_visualizing_music = False

_showing_alignment = False
_alignment_until = 0.0

def start_alignment_display(duration: float = 60.0):
    global _showing_alignment, _alignment_until
    _alignment_until = time.monotonic() + duration
    _showing_alignment = True
    _poke()

def stop_alignment_display():
    global _showing_alignment, _alignment_until
    _showing_alignment = False
    _alignment_until = 0.0

def is_alignment_active() -> bool:
    global _showing_alignment, _alignment_until
    if _showing_alignment and time.monotonic() >= _alignment_until:
        _showing_alignment = False
    return _showing_alignment and (time.monotonic() < _alignment_until)

_showing_omnissiah_glyph = False
_omnissiah_start_time = 0.0
_omnissiah_duration = 0.0

_showing_custom_image = False
_custom_image = None
_custom_image_expiry = 0.0
_custom_image_seq = 0      # bumped per new custom image, so an unchanged one isn't re-sent

# Autonomous game display — set while a games.bardstale agent is running
_showing_game = False

_showing_update_progress = False
_update_progress_percent = 0.0
_update_stage_text = ""

_last_activity_time = 0.0
_active_idle_anim = None
_custom_idle_expiry = 0.0
_requested_idle_anim = None

# Screensaver pool delegated to screensavers module
_screensaver_anims = _screensavers.SCREENSAVER_ANIMS if _screensavers else []



_SPIN_DEG_PER_SEC = 80.0   # cog rotation speed while thinking

_BLINK_DUR = 0.14          # seconds for one close-and-open blink
_BLINK_GAP = (2.5, 6.0)    # random idle interval (s) between blinks

W = H = 240
_CX = _CY = 120
_EYE_R = 73   # radius of the cog's central aperture; the iris lives inside this

# GC9A01 command set (subset).
_SWRESET = 0x01
_SLPIN = 0x10
_SLPOUT = 0x11
_DISPON = 0x29
_CASET = 0x2A
_RASET = 0x2B
_RAMWR = 0x2C
_MADCTL = 0x36
_COLMOD = 0x3A

# MADCTL orientation bits keyed by DISPLAY_ROTATION.
_MADCTL_BY_ROT = {0: 0x08, 90: 0x68, 180: 0xC8, 270: 0xA8}


def get_screensaver_names() -> list[str]:
    """Return the authoritative list of available screensaver animation names."""
    return _screensavers.get_screensaver_names() if _screensavers else []


# ── Eye styles ────────────────────────────────────────────────────────────────
# A personality's display module may offer several eye designs (EYE_STYLES).
# The pseudo-style "shuffle" draws a new design each time the eye comes back from
# a screensaver (or sleep) and whenever the disposition changes: the eye drawn for
# the current mood (eye_style_for_mood) a third of the time, otherwise any other.
# The choice is kept in eye_style_<persona>.json so it survives a restart; with
# none saved, the personality config's "eye_style" (else the module default) is
# used. Bumping _eye_style_gen makes the render loop rebuild bezel and mask.

SHUFFLE_EYE_STYLE = "shuffle"
MOOD_EYE_CHANCE = 1 / 3
_SHUFFLE_PHRASES = ("shuffle", "shuffled", "random", "randomise", "randomize", "mood", "match your mood",
                    "match my mood", "surprise me")

_eye_style_gen = 0
_eye_shuffles = False
_mood_name = "DUTIFUL"


def pick_eye_style(styles: list[str], mood_style: str | None, current: str | None, rng=random) -> str:
    """The next shuffled eye: the mood's own eye with MOOD_EYE_CHANCE, otherwise a
    random other design. Never the one already showing (when there is a choice), so
    every shuffle visibly changes the eye."""
    if mood_style in styles and mood_style != current and rng.random() < MOOD_EYE_CHANCE:
        return mood_style
    others = [s for s in styles if s not in (mood_style, current)] or [s for s in styles if s != mood_style] or styles
    return rng.choice(others)


def _eye_style_file():
    return config.data_path(f"eye_style_{_persona_key}.json")


def _designs() -> list[str]:
    return list(getattr(_display_module, 'EYE_STYLES', []))


def get_eye_styles() -> list[str]:
    """Names of the eye styles this personality offers ([] if only one design),
    plus "shuffle" when there is more than one."""
    styles = _designs()
    return styles + [SHUFFLE_EYE_STYLE] if len(styles) > 1 else styles


def get_eye_style() -> str | None:
    """The chosen style ("shuffle" while shuffling)."""
    return SHUFFLE_EYE_STYLE if _eye_shuffles else get_eye_style_shown()


def get_eye_style_shown() -> str | None:
    """The design actually on the eye."""
    if _display_module and hasattr(_display_module, 'get_eye_style'):
        return _display_module.get_eye_style()
    return None


def eye_style_title(name: str) -> str:
    if name == SHUFFLE_EYE_STYLE:
        return "Shuffled Ocular"
    if _display_module and hasattr(_display_module, 'eye_style_title'):
        return _display_module.eye_style_title(name)
    return name.replace("_", " ").title()


def eye_style_phrases() -> tuple[tuple[str, tuple[str, ...]], ...]:
    """(name, spoken phrases) for each eye style, for the voice-command matcher."""
    if not (_display_module and hasattr(_display_module, 'eye_style_phrases')):
        return ()
    return tuple((n, _SHUFFLE_PHRASES if n == SHUFFLE_EYE_STYLE else _display_module.eye_style_phrases(n))
                 for n in get_eye_styles())


def _show_eye_style(name: str) -> bool:
    """Make the display module draw design `name`; bump the generation if it changed."""
    global _eye_style_gen
    if not (_display_module and hasattr(_display_module, 'set_eye_style')):
        return False
    if name == get_eye_style_shown():
        return True
    if not _display_module.set_eye_style(name):
        return False
    _eye_style_gen += 1
    _poke()
    return True


def _shuffle_eye(reason: str) -> None:
    """Draw a new design for the shuffled eye."""
    if not _eye_shuffles:
        return
    mood_style = None
    if hasattr(_display_module, 'eye_style_for_mood'):
        mood_style = _display_module.eye_style_for_mood(_mood_name)
    name = pick_eye_style(_designs(), mood_style, get_eye_style_shown())
    if _show_eye_style(name):
        print(f"[display] Eye shuffled ({reason}): {name}")


def set_eye_style(name: str, save: bool = True) -> bool:
    """Switch the eye to design `name`, or "shuffle" (saved for the next boot);
    False if unknown."""
    global _eye_shuffles
    if name == SHUFFLE_EYE_STYLE:
        if SHUFFLE_EYE_STYLE not in get_eye_styles():
            return False
        _eye_shuffles = True
        _shuffle_eye("chosen")
    else:
        if not _show_eye_style(name):
            return False
        _eye_shuffles = False
        print(f"[display] Eye style: {name}")
    if save:
        try:
            config.atomic_write(_eye_style_file(), json.dumps({"style": name}))
        except Exception as e:
            print(f"[display] Could not save eye style ({e})")
    return True


def cycle_eye_style(step: int = 1) -> str | None:
    """Switch to the next (or previous, step=-1) eye style; returns its name. While
    shuffling, "next eye" just draws a new design and keeps shuffling."""
    styles = get_eye_styles()
    if not styles:
        return None
    if _eye_shuffles:
        _shuffle_eye("next eye")
        return get_eye_style_shown()
    current = get_eye_style()
    i = styles.index(current) if current in styles else -step
    name = styles[(i + step) % len(styles)]
    return name if set_eye_style(name) else None


def _restore_eye_style() -> None:
    styles = get_eye_styles()
    if not styles:
        return
    name = None
    try:
        name = json.loads(_eye_style_file().read_text()).get("style")
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"[display] Ignoring unreadable eye style file ({e})")
    if name not in styles:
        name = config.PERSONALITY.get("eye_style")
    if name in styles:
        set_eye_style(name, save=False)


# Mood -> base iris colour. Names match core/mood.py dispositions; unknown moods
# fall back to Imperial red.
_MOOD_COLOURS = getattr(_display_module, 'MOOD_COLOURS', {
    "VIGILANT": (255, 40, 30),
    "DUTIFUL": (255, 70, 25),
    "FERVENT": (255, 120, 20),
    "SUSPICIOUS": (255, 200, 30),
    "CONTEMPLATIVE": (60, 140, 255),
    "MELANCHOLIC": (90, 90, 200),
})

try:
    from PIL import Image, ImageDraw, ImageFont
    import numpy as np
except ImportError:
    pass

def _get_font(size: int, bold: bool = True):
    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf" if bold else "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        "/Library/Fonts/Arial Bold.ttf" if bold else "/Library/Fonts/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    for path in font_paths:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    try:
        return ImageFont.load_default(size=size)
    except Exception:
        return ImageFont.load_default()

try:
    import spidev
    import RPi.GPIO as GPIO
    _GPIO = GPIO
except (ImportError, RuntimeError):
    pass


# ── low-level panel I/O ──────────────────────────────────────────────────────────

def _cmd(c: int) -> None:
    _GPIO.output(config.DISPLAY_DC_PIN, 0)
    _spi.writebytes([c])


def _data(values) -> None:
    _GPIO.output(config.DISPLAY_DC_PIN, 1)
    if isinstance(values, int):
        values = [values]
    _spi.writebytes(values)


def _hard_reset() -> None:
    pin = config.DISPLAY_RST_PIN
    if pin < 0:
        return
    _GPIO.output(pin, 1)
    time.sleep(0.05)
    _GPIO.output(pin, 0)
    time.sleep(0.05)
    _GPIO.output(pin, 1)
    time.sleep(0.12)


def _init_panel() -> None:
    """GC9A01 power-on sequence (vendor inialisation, condensed)."""
    _hard_reset()
    # Inter-register enable + vendor init block.
    _cmd(0xEF)
    _cmd(0xEB); _data(0x14)
    _cmd(0xFE)
    _cmd(0xEF)
    _cmd(0xEB); _data(0x14)
    _cmd(0x84); _data(0x40)
    _cmd(0x85); _data(0xFF)
    _cmd(0x86); _data(0xFF)
    _cmd(0x87); _data(0xFF)
    _cmd(0x88); _data(0x0A)
    _cmd(0x89); _data(0x21)
    _cmd(0x8A); _data(0x00)
    _cmd(0x8B); _data(0x80)
    _cmd(0x8C); _data(0x01)
    _cmd(0x8D); _data(0x01)
    _cmd(0x8E); _data(0xFF)
    _cmd(0x8F); _data(0xFF)
    _cmd(0xB6); _data([0x00, 0x20])
    _cmd(_MADCTL); _data(_MADCTL_BY_ROT.get(config.DISPLAY_ROTATION, 0x08))
    _cmd(_COLMOD); _data(0x05)  # 16 bits/pixel (RGB565)
    _cmd(0x90); _data([0x08, 0x08, 0x08, 0x08])
    _cmd(0xBD); _data(0x06)
    _cmd(0xBC); _data(0x00)
    _cmd(0xFF); _data([0x60, 0x01, 0x04])
    _cmd(0xC3); _data(0x13)
    _cmd(0xC4); _data(0x13)
    _cmd(0xC9); _data(0x22)
    _cmd(0xBE); _data(0x11)
    _cmd(0xE1); _data([0x10, 0x0E])
    _cmd(0xDF); _data([0x21, 0x0C, 0x02])
    _cmd(0xF0); _data([0x45, 0x09, 0x08, 0x08, 0x26, 0x2A])
    _cmd(0xF1); _data([0x43, 0x70, 0x72, 0x36, 0x37, 0x6F])
    _cmd(0xF2); _data([0x45, 0x09, 0x08, 0x08, 0x26, 0x2A])
    _cmd(0xF3); _data([0x43, 0x70, 0x72, 0x36, 0x37, 0x6F])
    _cmd(0xED); _data([0x1B, 0x0B])
    _cmd(0xAE); _data(0x77)
    _cmd(0xCD); _data(0x63)
    _cmd(0x70); _data([0x07, 0x07, 0x04, 0x0E, 0x0F, 0x09, 0x07, 0x08, 0x03])
    _cmd(0xE8); _data(0x34)
    _cmd(0x62); _data([0x18, 0x0D, 0x71, 0xED, 0x70, 0x70,
                       0x18, 0x0F, 0x71, 0xEF, 0x70, 0x70])
    _cmd(0x63); _data([0x18, 0x11, 0x71, 0xF1, 0x70, 0x70,
                       0x18, 0x13, 0x71, 0xF3, 0x70, 0x70])
    _cmd(0x64); _data([0x28, 0x29, 0xF1, 0x01, 0xF1, 0x00, 0x07])
    _cmd(0x66); _data([0x3C, 0x00, 0xCD, 0x67, 0x45, 0x45, 0x10, 0x00, 0x00, 0x00])
    _cmd(0x67); _data([0x00, 0x3C, 0x00, 0x00, 0x00, 0x01, 0x54, 0x10, 0x32, 0x98])
    _cmd(0x74); _data([0x10, 0x85, 0x80, 0x00, 0x00, 0x4E, 0x00])
    _cmd(0x98); _data([0x3E, 0x07])
    _cmd(0x35)
    _cmd(0x21)
    _cmd(_SLPOUT)
    time.sleep(0.12)
    _cmd(_DISPON)
    time.sleep(0.02)


def _set_window(x0: int, y0: int, x1: int, y1: int) -> None:
    _cmd(_CASET); _data([x0 >> 8, x0 & 0xFF, x1 >> 8, x1 & 0xFF])
    _cmd(_RASET); _data([y0 >> 8, y0 & 0xFF, y1 >> 8, y1 & 0xFF])
    _cmd(_RAMWR)


_current_frame_image = None
_current_frame_seq = 0          # bumped on every blit
_frame_jpeg_cache = (-1, None)  # (seq, jpeg bytes) — one encode shared by all web viewers
_frame_lock = threading.Lock()   # guards the in-memory frame (shared with the web mirror)
_spi_lock = threading.Lock()     # serialises panel I/O; held for the SPI transfer only
_last_blit_key = None            # key of the static frame last sent to the panel, else None
_writebytes2_ok = True           # cleared if spidev's buffer API is missing or fails


def _push_frame(buf: bytes) -> None:
    """Send one full-screen RGB565 frame; the caller holds _spi_lock."""
    global _writebytes2_ok
    _set_window(0, 0, W - 1, H - 1)
    _GPIO.output(config.DISPLAY_DC_PIN, 1)
    if _writebytes2_ok:
        try:
            _spi.writebytes2(buf)  # buffer API: spidev chunks to bufsiz internally
            return
        except Exception as e:
            _writebytes2_ok = False
            print(f"[display] spidev writebytes2 unavailable ({e}); using chunked writes.")
            _set_window(0, 0, W - 1, H - 1)
            _GPIO.output(config.DISPLAY_DC_PIN, 1)
    # spidev caps a single transfer at its bufsiz (commonly 4096 bytes); chunk.
    step = 4096
    for i in range(0, len(buf), step):
        _spi.writebytes(buf[i:i + step])


def _blit(img, key=None) -> None:
    """Push a 240x240 PIL RGB image to the panel as big-endian RGB565.

    The latest frame is kept in memory for the web remote's ocular mirror. It is
    deliberately never written to disk: at 30 fps that was millions of SD-card
    rewrites a day and a corruption risk on power loss.

    `key` identifies a static screen's content (see _blit_static); animated
    frames pass none.
    """
    global _current_frame_image, _current_frame_seq, _last_blit_key
    _last_blit_key = None  # set once this frame is actually on the panel

    with _frame_lock:
        _current_frame_image = img.copy()
        _current_frame_seq += 1

    if not _available or _spi is None:
        _last_blit_key = key
        return

    if config.DISPLAY_FINE_ROTATION != 0.0:
        # PIL rotate is counter-clockwise. Pass -angle to rotate clockwise.
        img = img.rotate(-config.DISPLAY_FINE_ROTATION, resample=Image.BICUBIC)
    if img.mode != "RGB":
        img = to_rgb(img)
    arr = np.asarray(img, dtype=np.uint16)
    r = (arr[..., 0] & 0xF8) << 8
    g = (arr[..., 1] & 0xFC) << 3
    b = (arr[..., 2] & 0xF8) >> 3
    rgb565 = (r | g | b).astype(">u2")  # big-endian: MSB first on the wire
    with _spi_lock:
        _push_frame(rgb565.tobytes())
    _last_blit_key = key


def _blit_static(key, make) -> None:
    """Blit a static screen only if it isn't already on the panel: `make()` builds
    the image, and both it and the 115 KB SPI transfer are skipped when `key`
    matches the last frame sent."""
    key = (key, config.DISPLAY_FINE_ROTATION)
    if key != _last_blit_key:
        _blit(make(), key)


# ── panel power saving ────────────────────────────────────────────────────────────
# During sleep hours an idle panel is blanked and put into GC9A01 sleep with the
# backlight off, and the render thread blocks on _wake_event instead of rendering.
# Every entry point that gives the eye something to show calls _poke(), which wakes
# the thread at once (and, when asleep, the panel).

_wake_event = threading.Event()  # set by _poke()/cleanup() to cut a render wait short
_PRESENCE_DELTA_CM = 15.0        # rangefinder change that counts as someone moving nearby
_panel_asleep = False
_panel_slept_at = 0.0


def _poke(activity: bool = True) -> None:
    """Note display activity and wake the render thread (and panel) immediately."""
    global _last_activity_time
    if activity:
        _last_activity_time = time.monotonic()
    _wake_event.set()


def _panel_sleep() -> None:
    """Blank the panel, switch the backlight off and send SLPIN."""
    global _panel_asleep, _panel_slept_at
    _blit_static("blank", lambda: Image.new("RGB", (W, H), (0, 0, 0)))
    if _available and _spi is not None:
        with _spi_lock:
            if config.DISPLAY_BL_PIN >= 0:
                _GPIO.output(config.DISPLAY_BL_PIN, 0)
            _cmd(_SLPIN)
    _panel_asleep = True
    _panel_slept_at = time.monotonic()
    print("[display] Quiet hours and idle — panel asleep, rendering paused.")


def _panel_wake(reason: str) -> None:
    """SLPOUT, wait for the panel to come out of sleep, then backlight on."""
    global _panel_asleep
    if _available and _spi is not None:
        with _spi_lock:
            # Datasheet: 120 ms after SLPIN before SLPOUT, and 120 ms after SLPOUT
            # before the next command.
            time.sleep(max(0.0, _panel_slept_at + 0.12 - time.monotonic()))
            _cmd(_SLPOUT)
            time.sleep(0.12)
            _cmd(_DISPON)
            if config.DISPLAY_BL_PIN >= 0:
                _GPIO.output(config.DISPLAY_BL_PIN, 1)
    _panel_asleep = False
    print(f"[display] Panel awake ({reason}).")


_sleep_hours_cache = (-1e9, False)  # (checked_at, value) — quiet state lives in SQLite


def _in_sleep_hours(now: float) -> bool:
    global _sleep_hours_cache
    checked_at, value = _sleep_hours_cache
    if now - checked_at >= 5.0:
        try:
            from core import quiet
            value = quiet.is_in_sleep_hours()
        except Exception:
            value = False
        _sleep_hours_cache = (now, value)
    return value


def _read_distance():
    """(available, latest rangefinder distance in cm or None)."""
    try:
        from core import proximity
        if not proximity.available():
            return False, None
        return True, proximity.get_latest_distance_cm()
    except Exception:
        return False, None


# ── frame composition ─────────────────────────────────────────────────────────────

def _scale(rgb, k: float):
    k = max(0.0, min(1.0, k))
    return (int(rgb[0] * k), int(rgb[1] * k), int(rgb[2] * k))




def _make_iris_mask():
    """White disc over the cog's central aperture. The iris is composited through
    this mask so its glow never paints over the surrounding gear teeth."""
    r = _EYE_R
    if _display_module and hasattr(_display_module, 'aperture_radius'):
        r = _display_module.aperture_radius()
    m = Image.new("L", (W, H), 0)
    ImageDraw.Draw(m).ellipse(
        [_CX - r, _CY - r, _CX + r, _CY + r], fill=255)
    return m




def _make_bezel():
    if _display_module and hasattr(_display_module, 'render_bezel'):
        return _display_module.render_bezel()
    bg = Image.new("RGB", (W, H), (0, 0, 0))
    return bg

    GEAR = (60, 62, 70)     # gunmetal cog body
    EDGE = (120, 124, 138)  # brighter machined edge so the teeth catch light
    DARK = (24, 25, 30)     # recessed face / bolt holes
    RIM = (150, 44, 24)     # faint red rim around the aperture, ties glow to metal

    bg = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(bg)

    # Toothed cog body — the polygon fills solidly from the teeth inward.
    d.polygon(_gear_polygon(11, r_root=96, r_tip=117), fill=GEAR, outline=EDGE, width=3)

    # Bolt holes around the inner band (Mechanicus detail).
    for deg in range(0, 360, 30):
        a = math.radians(deg)
        bx, by = _CX + 86 * math.cos(a), _CY + 86 * math.sin(a)
        d.ellipse([bx - 3, by - 3, bx + 3, by + 3], fill=DARK)

    # Machined groove + recessed face stepping down to the eye aperture.
    d.ellipse([_CX - 80, _CY - 80, _CX + 80, _CY + 80], outline=EDGE, width=2)
    d.ellipse([_CX - 78, _CY - 78, _CX + 78, _CY + 78], fill=DARK)
    # Glowing red rim of the aperture (its inner part is hidden under the iris).
    d.ellipse([_CX - 75, _CY - 75, _CX + 75, _CY + 75], outline=RIM, width=3)
    return bg


def _render_frame(bezel, mask, amp: float, angle: float = 0.0, blink: float = 0.0, look_x: float = 0.0, look_y: float = 0.0):
    if _display_module and hasattr(_display_module, 'render_frame'):
        return _display_module.render_frame(bezel, mask, amp, angle, blink, look_x, look_y, _mood_rgb)
    img = bezel.rotate(angle, resample=Image.BICUBIC) if angle else bezel.copy()
    img.paste(Image.new("RGB", (W, H), _scale(_mood_rgb, 0.5 + 0.5 * amp)), (0, 0), mask)
    return img

    base = _mood_rgb
    intensity = 0.25 + 0.75 * amp           # never fully dark
    iris_r = 30 + 30 * amp                   # iris grows as it "speaks"

    cx = _CX + look_x
    cy = _CY + look_y

    iris = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(iris)

    def disc(r, colour):
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=colour)

    disc(iris_r * 2.0, _scale(base, intensity * 0.12))   # outer halo (fills aperture at peak)
    disc(iris_r * 1.45, _scale(base, intensity * 0.32))  # glow
    disc(iris_r, _scale(base, intensity))                # iris
    disc(iris_r * 0.55, _scale(base, min(1.0, intensity * 1.4)))  # hot core
    disc(iris_r * 0.26, (8, 0, 0))                       # pupil

    if blink > 0.0:
        # Squash the iris layer vertically about centre — an eyelid closing to a
        # slit. Rebuild on black so the closed band reads as a dark lid.
        open_h = max(1, int(round(H * (1.0 - blink))))
        squashed = iris.resize((W, open_h), resample=Image.BILINEAR)
        iris = Image.new("RGB", (W, H), (0, 0, 0))
        iris.paste(squashed, (0, (H - open_h) // 2))

    img.paste(iris, (0, 0), mask)
    return img


def _render_auspex_frame(bezel, mask, now: float):
    img = bezel.copy()
    base = _mood_rgb
    overlay = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(overlay)
    sweep_deg = (now * 240) % 360
    rad = math.radians(sweep_deg)
    x_end = _CX + 70 * math.cos(rad)
    y_end = _CY + 70 * math.sin(rad)
    d.line([(_CX, _CY), (x_end, y_end)], fill=base, width=3)
    for offset in range(5, 45, 10):
        trail_rad = math.radians(sweep_deg - offset)
        tx = _CX + 70 * math.cos(trail_rad)
        ty = _CY + 70 * math.sin(trail_rad)
        k = 1.0 - (offset / 45.0)
        d.line([(_CX, _CY), (tx, ty)], fill=_scale(base, k * 0.4), width=1)
    targets = [
        (-35, -25, 45),
        (40, -15, 340),
        (-20, 35, 120),
        (30, 30, 45),
    ]
    for tx, ty, trigger_ang in targets:
        ang_diff = (sweep_deg - trigger_ang) % 360
        if ang_diff < 90:
            intensity = 1.0 - (ang_diff / 90.0)
        else:
            intensity = 0.15
        cx, cy = _CX + tx, _CY + ty
        d.ellipse([cx - 3, cy - 3, cx + 3, cy + 3], fill=_scale(base, intensity))
        if intensity > 0.6:
            d.rectangle([cx - 6, cy - 6, cx + 6, cy + 6], outline=_scale(base, intensity * 0.6), width=1)
    d.ellipse([_CX - 60, _CY - 60, _CX + 60, _CY + 60], outline=_scale(base, 0.35), width=1)
    d.line([(_CX - 65, _CY), (_CX + 65, _CY)], fill=_scale(base, 0.2), width=1)
    d.line([(_CX, _CY - 65), (_CX, _CY + 65)], fill=_scale(base, 0.2), width=1)
    img.paste(overlay, (0, 0), mask)
    return img


def _render_noosphere_frame(bezel, mask, now: float):
    img = bezel.copy()
    base = _mood_rgb
    overlay = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(overlay)
    cycle_dur = 1.2
    num_rings = 3
    for i in range(num_rings):
        t = (now / cycle_dur + i / num_rings) % 1.0
        r = int(10 + t * 60)
        opacity = 1.0 - t
        d.ellipse([_CX - r, _CY - r, _CX + r, _CY + r], outline=_scale(base, opacity), width=2)
    core_pulsing = 0.6 + 0.4 * math.sin(now * 12)
    d.ellipse([_CX - 8, _CY - 8, _CX + 8, _CY + 8], fill=_scale(base, core_pulsing))
    offset = 48
    d.line([_CX - offset, _CY - offset, _CX - offset + 8, _CY - offset], fill=base, width=2)
    d.line([_CX - offset, _CY - offset, _CX - offset, _CY - offset + 8], fill=base, width=2)
    d.line([_CX + offset, _CY - offset, _CX + offset - 8, _CY - offset], fill=base, width=2)
    d.line([_CX + offset, _CY - offset, _CX + offset, _CY - offset + 8], fill=base, width=2)
    d.line([_CX - offset, _CY + offset, _CX - offset + 8, _CY + offset], fill=base, width=2)
    d.line([_CX - offset, _CY + offset, _CX - offset, _CY + offset - 8], fill=base, width=2)
    d.line([_CX + offset, _CY + offset, _CX + offset - 8, _CY + offset], fill=base, width=2)
    d.line([_CX + offset, _CY + offset, _CX + offset, _CY + offset - 8], fill=base, width=2)
    img.paste(overlay, (0, 0), mask)
    return img


def _render_targeting_frame(bezel, mask, now: float):
    img = bezel.copy()
    base = _mood_rgb
    overlay = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(overlay)
    dx = int(2.5 * math.sin(now * 18))
    dy = int(1.5 * math.cos(now * 22))
    cx, cy = _CX + dx, _CY + dy
    size = 38
    d.rectangle([cx - size, cy - size, cx + size, cy + size], outline=base, width=2)
    d.line([(cx - 15, cy), (cx - 5, cy)], fill=base, width=2)
    d.line([(cx + 5, cy), (cx + 15, cy)], fill=base, width=2)
    d.line([(cx, cy - 15), (cx, cy - 5)], fill=base, width=2)
    d.line([(cx, cy + 5), (cx, cy + 15)], fill=base, width=2)
    flash = int(now * 6) % 2 == 0
    if flash:
        offset = 45
        d.polygon([(cx - offset, cy), (cx - offset + 6, cy - 4), (cx - offset + 6, cy + 4)], fill=base)
        d.polygon([(cx + offset, cy), (cx + offset - 6, cy - 4), (cx + offset - 6, cy + 4)], fill=base)
    d.ellipse([cx - 2, cy - 2, cx + 2, cy + 2], fill=base)
    img.paste(overlay, (0, 0), mask)
    return img


def _render_web_search_frame(bezel, mask, now: float):
    img = bezel.copy()
    base = _mood_rgb
    overlay = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(overlay)
    angle = (now * 60) % 360
    for a_deg in range(0, 360, 45):
        rad = math.radians(a_deg + angle)
        x2 = _CX + 75 * math.cos(rad)
        y2 = _CY + 75 * math.sin(rad)
        d.line([(_CX, _CY), (x2, y2)], fill=_scale(base, 0.25), width=1)
    for r_base in [20, 45, 70]:
        r = int((r_base + (now * 25) % 60) % 80)
        opacity = max(0.1, 1.0 - (r / 80.0))
        d.ellipse([_CX - r, _CY - r, _CX + r, _CY + r], outline=_scale(base, opacity), width=1)
    for i in range(4):
        orbit_rad = math.radians(-angle * 1.5 + i * 90)
        dist = 40 + 15 * math.sin(now * 3 + i)
        px = int(_CX + dist * math.cos(orbit_rad))
        py = int(_CY + dist * math.sin(orbit_rad))
        d.rectangle([px - 3, py - 3, px + 3, py + 3], fill=base)
    core_r = int(6 + 3 * math.sin(now * 10))
    d.ellipse([_CX - core_r, _CY - core_r, _CX + core_r, _CY + core_r], fill=base)
    try:
        font = _get_font(10)
        d.text((_CX - 45, 45), "NOOSPHERE SEARCH", fill=base, font=font)
        d.text((_CX - 35, 180), "QUERYING...", fill=_scale(base, 0.7), font=font)
    except Exception:
        pass
    img.paste(overlay, (0, 0), mask)
    return img


def _render_rules_lookup_frame(bezel, mask, now: float):
    img = bezel.copy()
    base = _mood_rgb
    overlay = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(overlay)
    cog_r = 35
    teeth = 12
    cog_angle = (now * 90) % 360
    for i in range(teeth):
        a1 = math.radians(i * (360 / teeth) + cog_angle)
        a2 = math.radians(i * (360 / teeth) + 15 + cog_angle)
        x1 = _CX + (cog_r + 6) * math.cos(a1)
        y1 = _CY + (cog_r + 6) * math.sin(a1)
        x2 = _CX + (cog_r + 6) * math.cos(a2)
        y2 = _CY + (cog_r + 6) * math.sin(a2)
        d.line([(x1, y1), (x2, y2)], fill=base, width=3)
    d.ellipse([_CX - cog_r, _CY - cog_r, _CX + cog_r, _CY + cog_r], outline=base, width=2)
    d.ellipse([_CX - 15, _CY - 15, _CX + 15, _CY + 15], outline=_scale(base, 0.6), width=1)
    for line_idx in range(5):
        y_pos = int(50 + line_idx * 32 + (now * 40) % 32)
        if 40 <= y_pos <= 190:
            width_val = int(30 + 40 * math.sin(line_idx * 1.5 + now * 4))
            d.line([(_CX - width_val, y_pos), (_CX + width_val, y_pos)], fill=_scale(base, 0.4), width=1)
    b_off = 65
    d.rectangle([_CX - b_off, _CY - b_off, _CX + b_off, _CY + b_off], outline=_scale(base, 0.5), width=1)
    d.line([(_CX - b_off, _CY - b_off), (_CX - b_off + 12, _CY - b_off)], fill=base, width=2)
    d.line([(_CX - b_off, _CY - b_off), (_CX - b_off, _CY - b_off + 12)], fill=base, width=2)
    d.line([(_CX + b_off, _CY - b_off), (_CX + b_off - 12, _CY - b_off)], fill=base, width=2)
    d.line([(_CX + b_off, _CY - b_off), (_CX + b_off, _CY - b_off + 12)], fill=base, width=2)
    d.line([(_CX - b_off, _CY + b_off), (_CX - b_off + 12, _CY + b_off)], fill=base, width=2)
    d.line([(_CX - b_off, _CY + b_off), (_CX - b_off, _CY + b_off - 12)], fill=base, width=2)
    d.line([(_CX + b_off, _CY + b_off), (_CX + b_off - 12, _CY + b_off)], fill=base, width=2)
    d.line([(_CX + b_off, _CY + b_off), (_CX + b_off, _CY + b_off - 12)], fill=base, width=2)
    try:
        font = _get_font(10)
        d.text((_CX - 48, 42), "LIBRARIUM CODEX", fill=base, font=font)
        d.text((_CX - 38, 185), "SEARCHING...", fill=_scale(base, 0.7), font=font)
    except Exception:
        pass
    img.paste(overlay, (0, 0), mask)
    return img


def _render_news_fetch_frame(bezel, mask, now: float):
    img = bezel.copy()
    base = _mood_rgb
    overlay = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(overlay)
    points = []
    for x in range(35, 206, 3):
        y = int(_CY + 22 * math.sin((x * 0.08) + (now * 8)) * math.cos(now * 2))
        points.append((x, y))
    if len(points) > 1:
        d.line(points, fill=base, width=2)
    beacon_cy = 65
    for i in range(3):
        r = int(8 + ((now * 30 + i * 15) % 35))
        opacity = max(0.1, 1.0 - (r / 35.0))
        d.ellipse([_CX - r, beacon_cy - r, _CX + r, beacon_cy + r], outline=_scale(base, opacity), width=1)
    d.ellipse([_CX - 4, beacon_cy - 4, _CX + 4, beacon_cy + 4], fill=base)
    bar_x = 185
    for b in range(5):
        h_val = 6 + b * 6
        b_y = 150 - b * 9
        active = (int(now * 8) % 6) >= b
        fill_col = base if active else _scale(base, 0.25)
        d.rectangle([bar_x, b_y - h_val, bar_x + 5, b_y], fill=fill_col)
    try:
        font = _get_font(10)
        d.text((_CX - 42, 40), "VOX TRANSMISSION", fill=base, font=font)
        d.text((_CX - 40, 175), "RECEIVING RSS...", fill=_scale(base, 0.7), font=font)
    except Exception:
        pass
    img.paste(overlay, (0, 0), mask)
    return img


def _render_image_retrieval_frame(bezel, mask, now: float):
    img = bezel.copy()
    base = _mood_rgb
    overlay = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(overlay)
    scan_y = int(45 + ((now * 110) % 150))
    d.line([(35, scan_y), (205, scan_y)], fill=base, width=3)
    d.line([(35, scan_y - 2), (205, scan_y - 2)], fill=_scale(base, 0.5), width=1)
    d.line([(35, scan_y + 2), (205, scan_y + 2)], fill=_scale(base, 0.5), width=1)
    for gx in range(45, 200, 20):
        for gy in range(45, 200, 20):
            if gy < scan_y:
                d.rectangle([gx, gy, gx + 2, gy + 2], fill=_scale(base, 0.6))
            else:
                d.rectangle([gx, gy, gx + 1, gy + 1], fill=_scale(base, 0.15))
    ap_size = int(55 + 5 * math.sin(now * 6))
    d.rectangle([_CX - ap_size, _CY - ap_size, _CX + ap_size, _CY + ap_size], outline=_scale(base, 0.7), width=1)
    try:
        font = _get_font(10)
        d.text((_CX - 44, 40), "PICT-FEED RASTER", fill=base, font=font)
        d.text((_CX - 38, 185), "FETCHING ART...", fill=_scale(base, 0.7), font=font)
    except Exception:
        pass
    img.paste(overlay, (0, 0), mask)
    return img


def _render_alignment_frame(bezel, mask, now: float):
    img = bezel.copy()
    base = (0, 255, 128)  # Bright glowing green
    accent = (0, 229, 255)  # Cyan
    overlay = Image.new("RGB", (W, H), (10, 14, 20))
    d = ImageDraw.Draw(overlay)

    # Calibration outer rings
    d.ellipse([15, 15, 225, 225], outline=accent, width=2)
    d.ellipse([25, 25, 215, 215], outline=_scale(accent, 0.4), width=1)

    # Cardinal ticks (12 o'clock / UP is highlighted green)
    d.line([(120, 15), (120, 30)], fill=base, width=3)      # 12 o'clock (UP)
    d.line([(120, 210), (120, 225)], fill=accent, width=2)  # 6 o'clock
    d.line([(15, 120), (30, 120)], fill=accent, width=2)    # 9 o'clock
    d.line([(210, 120), (225, 120)], fill=accent, width=2)  # 3 o'clock

    # Subtle pulse animation for the arrow
    pulse = 1.0 + 0.05 * math.sin(now * 8.0)
    top_y = int(45 - (pulse - 1.0) * 10)

    # Large bold UP arrow pointing straight up towards 12 o'clock
    arrow_poly = [
        (120, top_y),
        (160, 115),
        (136, 115),
        (136, 160),
        (104, 160),
        (104, 115),
        (80, 115)
    ]
    d.polygon(arrow_poly, fill=base, outline=(255, 255, 255))

    # Text overlay
    try:
        font_sm = _get_font(10)
        font_lg = _get_font(12)
        d.text((120, 30), "UP ▲", fill=base, font=font_sm, anchor="mm")
        d.text((120, 176), "ALIGNMENT MODE", fill=accent, font=font_lg, anchor="mm")
        d.text((120, 194), f"OFFSET: {config.DISPLAY_FINE_ROTATION:+.1f}°", fill=_scale(accent, 0.8), font=font_sm, anchor="mm")
    except Exception:
        pass

    img.paste(overlay, (0, 0), mask)
    return img


def _render_music_frame(bezel, mask, now: float):
    img = bezel.copy()
    base = _mood_rgb
    overlay = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(overlay)
    num_bars = 8
    bar_width = 6
    spacing = 4
    total_width = num_bars * bar_width + (num_bars - 1) * spacing
    start_x = _CX - total_width // 2
    for i in range(num_bars):
        h_factor = 0.3 + 0.7 * (0.5 + 0.25 * math.sin(now * 8 + i * 2.3) + 0.25 * math.sin(now * 15 - i * 1.7))
        h = int(h_factor * 50)
        bx0 = start_x + i * (bar_width + spacing)
        by0 = _CY - h // 2
        bx1 = bx0 + bar_width
        by1 = _CY + h // 2
        d.rectangle([bx0, by0, bx1, by1], fill=base)
    d.ellipse([_CX - 55, _CY - 55, _CX + 55, _CY + 55], outline=_scale(base, 0.4), width=1)
    img.paste(overlay, (0, 0), mask)
    return img


# ── 3D Die projection helpers ───────────────────────────────────────────────────
def _rotate_x(x: float, y: float, z: float, angle: float) -> tuple[float, float, float]:
    rad = math.radians(angle)
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    return x, y * cos_a - z * sin_a, y * sin_a + z * cos_a


def _rotate_y(x: float, y: float, z: float, angle: float) -> tuple[float, float, float]:
    rad = math.radians(angle)
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    return x * cos_a + z * sin_a, y, -x * sin_a + z * cos_a


def _rotate_z(x: float, y: float, z: float, angle: float) -> tuple[float, float, float]:
    rad = math.radians(angle)
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    return x * cos_a - y * sin_a, x * sin_a + y * cos_a, z


def _draw_vector_digit(draw, x, y, width, height, char: str, color, thickness=3):
    w, h = width, height
    hw = w // 2
    hh = h // 2
    
    # 7 standard segments defined by their start/end points
    segments = {
        'a': [(x, y), (x + w, y)],
        'b': [(x + w, y), (x + w, y + hh)],
        'c': [(x + w, y + hh), (x + w, y + h)],
        'd': [(x, y + h), (x + w, y + h)],
        'e': [(x, y + hh), (x, y + h)],
        'f': [(x, y), (x, y + hh)],
        'g': [(x, y + hh), (x + w, y + hh)]
    }
    
    digit_map = {
        '0': ['a', 'b', 'c', 'd', 'e', 'f'],
        '1': ['b', 'c'],
        '2': ['a', 'b', 'g', 'e', 'd'],
        '3': ['a', 'b', 'g', 'c', 'd'],
        '4': ['f', 'g', 'b', 'c'],
        '5': ['a', 'f', 'g', 'c', 'd'],
        '6': ['a', 'f', 'e', 'd', 'c', 'g'],
        '7': ['a', 'b', 'c'],
        '8': ['a', 'b', 'c', 'd', 'e', 'f', 'g'],
        '9': ['a', 'b', 'c', 'd', 'f', 'g'],
        '-': ['g'],
        'A': ['a', 'b', 'c', 'e', 'f', 'g'],
        'B': ['c', 'd', 'e', 'f', 'g'], # lower b
        'C': ['a', 'd', 'e', 'f'],
        'D': ['b', 'c', 'd', 'e', 'g'], # lower d
        'E': ['a', 'd', 'e', 'f', 'g'],
        'F': ['a', 'e', 'f', 'g'],
        'G': ['a', 'c', 'd', 'e', 'f'],
        'H': ['b', 'c', 'e', 'f', 'g'],
        'I': ['b', 'c'],
        'J': ['b', 'c', 'd'],
        'L': ['d', 'e', 'f'],
        'N': ['a', 'b', 'c', 'e', 'f'],
        'O': ['a', 'b', 'c', 'd', 'e', 'f'],
        'P': ['a', 'b', 'e', 'f', 'g'],
        'R': ['e', 'g'], # lower r
        'S': ['a', 'f', 'g', 'c', 'd'],
        'T': ['d', 'e', 'f', 'g'],
        'U': ['b', 'c', 'd', 'e', 'f'],
        'Y': ['b', 'c', 'd', 'f', 'g']
    }
    
    char = char.upper()
    if char == 'X':
        draw.line([(x, y), (x + w, y + h)], fill=color, width=thickness)
        draw.line([(x + w, y), (x, y + h)], fill=color, width=thickness)
    elif char in digit_map:
        for seg in digit_map[char]:
            p1, p2 = segments[seg]
            draw.line([p1, p2], fill=color, width=thickness)


# The throw has to last long enough to be seen. At the default 15 fps the first
# version's 0.8s was twelve frames, two of them with the dice still outside the
# aperture, and the roll was over before anyone looked down.
_DIE_TUMBLE_END = 1.30   # seconds in the air before the dice land
_DIE_HOLD = 10.0         # how long the result stays up if nothing interrupts
# The motion is rendered faster than the rest of the eye. Dice in flight are the
# one thing here worth the extra SPI, and it is paid for just over a second;
# the result that follows goes back to the configured rate.
_DIE_MOTION_FPS = 30.0
_DIE_SETTLE = 0.28       # the bounce as they land
_DIE_STAGGER = 0.04      # each dice leaves the hand a little after the last
# Dice enter from beyond the aperture, but only just: thrown from much further
# out, the eye is empty for the first tenth of a second and the roll looks like
# a dropped frame rather than a throw. A tumbling cube is smaller than the flat
# dice it becomes, so it has to start nearer still to be in shot at all.
_DIE_THROW_FROM = 90.0
# Whole turns, so a dice lands upright however far it flew. Different counts
# per dice stop them turning as one block.
_DIE_TURNS = (3, 2, 4, 2, 3, 2)
# Degrees turned about each axis over the throw, per dice. The path eases to
# zero, so whatever these are the cube ends square-on with the rolled face to
# the front -- it cannot land on a corner.
_DIE_SPIN_3D = ((760, 520, 140), (520, 880, -180), (940, 400, 220),
                (620, 700, -120), (840, 560, 160), (480, 820, -200))


def _ease_out(t: float) -> float:
    return 1.0 - (1.0 - min(1.0, max(0.0, t))) ** 3


def _ease_out_back(t: float) -> float:
    """Decelerate past the mark and come back, so a dice lands with a bounce."""
    t = min(1.0, max(0.0, t))
    c1, c3 = 1.22, 2.22
    return 1.0 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2


def _draw_die_numeral(draw, cx, cy, size, colour, text: str) -> None:
    """A rolled number, for the dice that show numbers rather than symbols."""
    text = str(text)[:3]
    w = size * (0.34 if len(text) < 3 else 0.24)
    h = w * 1.75
    gap = w * 0.52  # wide enough that adjacent uprights do not read as one glyph
    total = len(text) * w + (len(text) - 1) * gap
    x = cx - total / 2
    for char in text:
        _draw_vector_digit(draw, x, cy - h / 2, w, h, char, colour,
                           thickness=max(2, int(size * 0.05)))
        x += w + gap


def _paint_die(draw, x, y, size, colour, symbol, detail, with_body: bool) -> None:
    """Draw one dice upright at (x, y)."""
    if with_body:
        dice_faces.draw_die_body(draw, x, y, size, colour,
                                 width=max(2, int(size * 0.035)))
    if symbol == "num":
        _draw_die_numeral(draw, x, y, size, colour, detail)
    else:
        dice_faces.draw_face(draw, symbol, x, y, size, colour, detail)


def _draw_one_die(draw, overlay, x, y, size, colour, symbol, detail,
                  with_body: bool, angle: float = 0.0) -> None:
    """Draw one dice, turned ``angle`` degrees.

    A turned dice is drawn to its own small tile and the tile is rotated, rather
    than every symbol being taught to rotate itself. Most of the faces are built
    from ellipses -- the skull, the pips, the bullet holes -- and those have no
    rotated form; rotating the finished tile turns all of them at once, and the
    hollows punched out of a face turn with it.

    Upright dice skip the tile: that is every frame once the roll has landed,
    and it is the common case.
    """
    if abs(angle) < 0.5:
        _paint_die(draw, x, y, size, colour, symbol, detail, with_body)
        return
    side = int(size * 1.7) | 1
    tile = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    _paint_die(ImageDraw.Draw(tile), side / 2, side / 2, size, colour, symbol,
               detail, with_body)
    tile = tile.rotate(angle, resample=Image.BILINEAR)
    overlay.paste(tile, (int(x - side / 2), int(y - side / 2)), tile)


def _draw_step_pips(draw, colour, index: int, total: int) -> None:
    """Which step of an attack is on screen, as a row of ticks.

    An attack is four rolls and it has to be clear which one is being watched.
    The seven-segment face has no V or W, so "SAVE" and "WOUND" cannot be
    written; ticks say the same thing and stay legible at this size.
    """
    if total < 2:
        return
    width, gap = 11, 6
    span = total * width + (total - 1) * gap
    x = _CX - span / 2
    y = _CY + 58
    for i in range(total):
        bright = colour if i <= index else _scale(colour, 0.28)
        draw.line([(x, y), (x + width, y)], fill=bright, width=4 if i == index else 2)
        x += width + gap


def _render_die_frame(bezel, mask, elapsed: float, result: str, kind: str = "d6",
                      faces: tuple = (), detail: tuple = (), chosen: int = -1,
                      step: int = 0, steps: int = 1):
    """The dice roll, shown as the faces the dice actually carry.

    Necromunda's dice are symbols, not numbers: a cross, a splintered burst, a
    skull, bullet holes, a crosshair. Drawing the symbol is both quicker to read
    across a table than a word and the thing a player is already looking for in
    their own hand, so the eye shows the face rather than spelling the result
    out. Numbered dice still get their number.

    Three beats: the dice tumble, land with a shock ring, then sit under a
    slowly turning rangefinder while the one that matters is ringed.
    """
    img = bezel.copy()
    base = _mood_rgb
    overlay = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(overlay)

    symbols = list(faces) if faces else ["num"]
    details = list(detail) if detail else [result]
    details += [None] * (len(symbols) - len(details))

    # A handful of numbered dice is better read as its total. Six pip faces
    # shrunk to fit are just a scatter of dots, and the sum is the answer the
    # player wanted anyway. Symbol dice never collapse: each one is a separate
    # result that has to be seen.
    if len(symbols) > 4 and all(sym in ("pip", "num") for sym in symbols):
        symbols, details = ["num"], [result]
    extra = max(0, len(symbols) - dice_faces.MAX_DRAWN)
    shown = symbols[:dice_faces.MAX_DRAWN]
    slots = dice_faces.layout(len(shown))
    pool = dice_faces.TUMBLE_POOL.get(kind, ())
    # Cubes for the dice that carry symbols, and only where there is room for
    # one: the five- and six-dice layouts drop the outline to keep the symbols
    # readable, and a cube at that size would spill out of the aperture.
    use_3d = dice3d.supports(kind) and slots[0][3]
    sides = [dice3d.sides_for(kind, sym) for sym in shown] if use_3d else []

    if elapsed < _DIE_TUMBLE_END:
        # The throw: each dice comes in off the rim, turning as it goes, and
        # decelerates into its slot. Every dice is given a whole number of
        # turns so it lands upright however long it spent in the air.
        for i, (x, y, size, with_body) in enumerate(slots):
            launch = i * _DIE_STAGGER
            flight = max(0.0, elapsed - launch) / max(0.01, _DIE_TUMBLE_END - launch)
            flight = min(1.0, flight)
            travel = _ease_out_back(flight)

            entry = math.radians((i * 137.5) + 20.0)   # spread, not a line
            sx = _CX + _DIE_THROW_FROM * math.cos(entry)
            sy = _CY + _DIE_THROW_FROM * math.sin(entry)
            px = sx + (x - sx) * travel
            py = sy + (y - sy) * travel

            if use_3d:
                # A real cube, carrying the six faces the dice really has, and
                # turning in space. It shows whichever sides happen to face the
                # viewer, so there is no need to fake a blur of faces: the
                # tumble IS the dice turning.
                ease = _ease_out(flight)
                spin = _DIE_SPIN_3D[i % len(_DIE_SPIN_3D)]
                angles = tuple(a * (1.0 - ease) for a in spin)
                dice3d.draw_die(d, px, py, size, base, (0, 0, 0), sides[i],
                                details[i], angles, dice3d.SCALE_TUMBLING)
                continue

            turns = _DIE_TURNS[i % len(_DIE_TURNS)]
            angle = turns * 360.0 * (1.0 - (1.0 - flight) ** 3)
            if i % 2:
                angle = -angle

            # Faces blur past while it is in the air and slow as it lands, so
            # the last face shown is nearly the one it settles on.
            step = int(elapsed / (0.045 + 0.10 * flight))
            if pool:
                face, face_detail = pool[(step + i) % len(pool)], None
            else:
                face, face_detail = "num", str(((step + i) % 6) + 1)
            _draw_one_die(d, overlay, px, py, size, _scale(base, 0.8), face,
                          face_detail, with_body, angle)
    else:
        settle = _ease_out((elapsed - _DIE_TUMBLE_END) / _DIE_SETTLE)
        # Land with a small overshoot, then hold.
        scale = 1.0 + 0.22 * (1.0 - settle) * math.cos(settle * math.pi * 1.5)
        for i, (x, y, size, with_body) in enumerate(slots):
            if use_3d and settle < 1.0:
                # Still a cube, now square-on, growing into the flat dice it
                # hands over to. Face-on they are the same silhouette, so the
                # changeover cannot be seen.
                grow = (dice3d.SCALE_TUMBLING
                        + (dice3d.SCALE_LANDED - dice3d.SCALE_TUMBLING) * settle)
                dice3d.draw_die(d, x, y, size, base, (0, 0, 0), sides[i],
                                details[i], (0.0, 0.0, 0.0), grow)
            else:
                _draw_one_die(d, overlay, x, y, size * scale, base, shown[i],
                              details[i], with_body)

        # The shock ring thrown off as they land.
        if settle < 1.0:
            ring_r = 24 + settle * 58
            d.ellipse([_CX - ring_r, _CY - ring_r, _CX + ring_r, _CY + ring_r],
                      outline=_scale(base, 0.9 * (1.0 - settle)),
                      width=max(1, int(5 * (1.0 - settle))))

        # Mark the dice whose result is the one being applied -- with Injury
        # dice the attacker picks one, and the eye should say which. Corner
        # brackets rather than a ring: a ring sits just outside the dice's own
        # rounded outline and reads as part of it.
        if 0 <= chosen < len(slots) and settle >= 0.6:
            x, y, size, _body = slots[chosen]
            pulse = 0.55 + 0.45 * math.sin(elapsed * 6.0)
            colour = _scale(base, pulse)
            # Trace the dice's own corners. Further out and the brackets on a
            # dice near the rim fall outside the aperture and are cut in half
            # by the iris mask.
            r = size * 0.56
            arm = size * 0.22
            thick = max(2, int(size * 0.055))
            for sx in (-1, 1):
                for sy in (-1, 1):
                    cx_, cy_ = x + sx * r, y + sy * r
                    d.line([(cx_, cy_), (cx_ - sx * arm, cy_)], fill=colour, width=thick)
                    d.line([(cx_, cy_), (cx_, cy_ - sy * arm)], fill=colour, width=thick)

        # A slow rangefinder sweep around the aperture, so the result is not a
        # frozen image for two and a half seconds.
        if settle >= 0.8:
            sweep = elapsed * 42.0
            for k in range(4):
                a0 = sweep + k * 90
                d.arc([_CX - 68, _CY - 68, _CX + 68, _CY + 68], a0, a0 + 26,
                      fill=_scale(base, 0.45), width=2)
            _draw_step_pips(d, base, step, steps)
            if extra:
                # The seven-segment map has no '+', so the sign is drawn.
                faint = _scale(base, 0.8)
                py = _CY + 58
                d.line([(_CX - 24, py), (_CX - 12, py)], fill=faint, width=2)
                d.line([(_CX - 18, py - 6), (_CX - 18, py + 6)], fill=faint, width=2)
                _draw_die_numeral(d, _CX + 6, py, 26, faint, str(extra))

    img.paste(overlay, (0, 0), mask)
    return img


def _render_omnissiah_frame(bezel, mask, now: float) -> Image.Image:
    age = max(0.0, now - _omnissiah_start_time)
    if _display_module and hasattr(_display_module, 'render_overlay'):
        try:
            return _display_module.render_overlay(bezel, mask, now, _omnissiah_start_time, _omnissiah_duration, _mood_rgb)
        except Exception:
            pass

    overlay = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(overlay)

    scale = min(1.0, age / 1.5)
    scale = scale * scale * (3.0 - 2.0 * scale)
    
    if scale > 0.01:
        gear_angle = (age * 60.0) % 360
        r_outer = 110.0 * scale
        r_inner = 85.0 * scale
        num_teeth = 12
        
        points = []
        for i in range(num_teeth):
            t_start = i * (360.0 / num_teeth)
            cycle_deg = 360.0 / num_teeth
            a1 = gear_angle + t_start
            a2 = gear_angle + t_start + cycle_deg * 0.4
            a3 = gear_angle + t_start + cycle_deg * 0.5
            a4 = gear_angle + t_start + cycle_deg * 0.9
            
            points.append((_CX + r_outer * math.cos(math.radians(a1)), _CY + r_outer * math.sin(math.radians(a1))))
            points.append((_CX + r_outer * math.cos(math.radians(a2)), _CY + r_outer * math.sin(math.radians(a2))))
            points.append((_CX + r_inner * math.cos(math.radians(a3)), _CY + r_inner * math.sin(math.radians(a3))))
            points.append((_CX + r_inner * math.cos(math.radians(a4)), _CY + r_inner * math.sin(math.radians(a4))))
            
        d.polygon(points, fill=(235, 230, 215))
        
        r_center = 68.0 * scale
        d.ellipse([_CX - r_center, _CY - r_center, _CX + r_center, _CY + r_center], fill=(0, 0, 0))
        
        # Left cranium (bone)
        d.pieslice([_CX - 27 * scale, _CY - 34 * scale, _CX + 27 * scale, _CY + 20 * scale], 90, 270, fill=(235, 230, 215))
        # Right cranium (machine)
        d.pieslice([_CX - 27 * scale, _CY - 34 * scale, _CX + 27 * scale, _CY + 20 * scale], 270, 90, fill=(80, 85, 95))
        
        # Left jaw
        d.polygon([
            (_CX - 15 * scale, _CY + 20 * scale),
            (_CX, _CY + 20 * scale),
            (_CX, _CY + 37 * scale),
            (_CX - 12 * scale, _CY + 37 * scale)
        ], fill=(235, 230, 215))
        # Right jaw
        d.polygon([
            (_CX, _CY + 20 * scale),
            (_CX + 15 * scale, _CY + 20 * scale),
            (_CX + 12 * scale, _CY + 37 * scale),
            (_CX, _CY + 37 * scale)
        ], fill=(80, 85, 95))
        
        # Cheekbones
        d.ellipse([_CX - 31 * scale, _CY - 3 * scale, _CX - 17 * scale, _CY + 10 * scale], fill=(235, 230, 215))
        d.ellipse([_CX + 17 * scale, _CY - 3 * scale, _CX + 31 * scale, _CY + 10 * scale], fill=(80, 85, 95))
        
        # Left eye
        d.ellipse([_CX - 15 * scale, _CY - 7 * scale, _CX - 5 * scale, _CY + 3 * scale], fill=(0, 0, 0))
        # Right eye
        d.ellipse([_CX + 5 * scale, _CY - 7 * scale, _CX + 15 * scale, _CY + 3 * scale], fill=(0, 230, 80))
        
        # Nose
        d.polygon([
            (_CX - 3 * scale, _CY + 14 * scale),
            (_CX, _CY + 7 * scale),
            (_CX + 3 * scale, _CY + 14 * scale)
        ], fill=(0, 0, 0))
        
        # Teeth slits
        for offset in (-8, -3):
            d.line([(_CX + offset * scale, _CY + 20 * scale), (_CX + offset * scale, _CY + 34 * scale)], fill=(0, 0, 0), width=1)
        for offset in (3, 8):
            d.line([(_CX + offset * scale, _CY + 20 * scale), (_CX + offset * scale, _CY + 34 * scale)], fill=(0, 0, 0), width=1)
        d.line([(_CX, _CY + 20 * scale), (_CX, _CY + 37 * scale)], fill=(0, 0, 0), width=1)

    return overlay




def _render_update_progress_frame(bezel, mask, now: float) -> 'Image.Image':
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return bezel.copy()
        
    frame = Image.new('RGB', (W, H), (0, 0, 0))
    draw = ImageDraw.Draw(frame)
    
    GREEN_PRIMARY = (0, 230, 80)
    GREEN_TRACK = (15, 45, 20)
    GREEN_SUBTEXT = (0, 180, 60)

    # Outer arc
    cx, cy = 120, 120
    r = 100
    bbox = [cx - r, cy - r, cx + r, cy + r]
    
    start_angle = -90
    end_angle = start_angle + int(360 * (_update_progress_percent / 100.0))
    
    # Draw background track
    draw.arc(bbox, 0, 360, fill=GREEN_TRACK, width=10)
    
    # Draw progress arc
    if end_angle > start_angle:
        draw.arc(bbox, start_angle, end_angle, fill=GREEN_PRIMARY, width=10)
        
    # Draw percentage text
    f_large = _get_font(40, bold=True)
    pct_text = f"{int(_update_progress_percent)}%"
    # textbox center
    left, top, right, bottom = draw.textbbox((0, 0), pct_text, font=f_large)
    tw, th = right - left, bottom - top
    draw.text((cx - tw//2, cy - th//2 - 10), pct_text, font=f_large, fill=GREEN_PRIMARY)
    
    # Draw stage text
    f_small = _get_font(16, bold=True)
    st_text = _update_stage_text.upper()
    left, top, right, bottom = draw.textbbox((0, 0), st_text, font=f_small)
    stw = right - left
    draw.text((cx - stw//2, cy + 30), st_text, font=f_small, fill=GREEN_SUBTEXT)
    
    return frame

# Render-error handling. A failing frame must never kill the render thread (that
# freezes the eye for good), and must not print 30 lines/s into the persistent
# journal either (SD-card writes): each distinct error is logged at most once per
# _RENDER_ERROR_LOG_INTERVAL, with a count of the repeats suppressed in between.
_RENDER_ERROR_LOG_INTERVAL = 60.0  # seconds between repeats of the same error message
_RENDER_ERROR_BACKOFF = 0.5        # seconds to pause after a failed frame
_render_error_log: dict[str, list] = {}  # message -> [last_logged_monotonic, suppressed_count]


def _render_error(what: str, e: Exception) -> None:
    """Rate-limited log of a per-frame render error, then back off briefly."""
    key = f"[display] {what} error: {e}"
    now = time.monotonic()
    entry = _render_error_log.get(key)
    if entry is None or now - entry[0] >= _RENDER_ERROR_LOG_INTERVAL:
        suppressed = entry[1] if entry else 0
        print(key + (f" (repeated {suppressed}x since last logged)" if suppressed else ""))
        if entry is None and len(_render_error_log) >= 64:
            _render_error_log.clear()  # bound memory if error text keeps varying
        _render_error_log[key] = [now, 0]
    else:
        entry[1] += 1
    _stop.wait(_RENDER_ERROR_BACKOFF)


def _loop():
    """Supervise the render loop: restart it after any unexpected error, never exit
    until stop() is called."""
    while not _stop.is_set():
        try:
            _render_loop()
        except Exception as e:
            _render_error("render loop", e)
            _stop.wait(1.0)


def _render_loop():
    global _rolling_die, _die_step, _showing_omnissiah_glyph, _showing_custom_image, _custom_image, _custom_image_expiry
    global _custom_reveal_src
    global _showing_alignment, _alignment_until, _showing_game
    global _last_activity_time, _active_idle_anim, _custom_idle_expiry, _requested_idle_anim
    bezel = _make_bezel()
    mask = _make_iris_mask()
    eye_gen = _eye_style_gen
    away = False          # True while a screensaver or sleep has the panel; the eye reshuffles on return
    shown = -1.0          # last amplitude actually drawn
    angle = 0.0           # current cog rotation (degrees), advanced while thinking
    t0 = time.monotonic()
    _last_activity_time = t0
    last = t0
    next_blink = t0 + random.uniform(*_BLINK_GAP)  # when the next blink starts
    blink_t0 = None       # start time of the in-progress blink, else None
    idle_anim_start_time = 0.0
    last_picked_anim = None
    
    # Gaze variables for looking around when idle
    look_x = 0.0
    look_y = 0.0
    target_look_x = 0.0
    target_look_y = 0.0
    next_gaze_time = t0 + random.uniform(2.0, 5.0)

    # Power saving: presence = display activity, or the rangefinder reading moving
    # more than _PRESENCE_DELTA_CM (or a target appearing/vanishing) since the quiet
    # period began. Idle rendering drops to DISPLAY_IDLE_FPS once nobody has been
    # around for DISPLAY_PRESENCE_TIMEOUT.
    presence_at = t0
    presence_cm = None
    low_power = False
    next_frame = t0        # frame deadline; pacing is measured against this

    def pace(fps: float) -> None:
        """Wait out the rest of this frame's slot. Timed from a deadline so render
        and SPI time don't stretch the period; reduced-rate waits end early on
        _poke() so activity gets the full frame rate at once."""
        nonlocal next_frame
        period = 1.0 / fps
        now = time.monotonic()
        next_frame += period
        if next_frame < now - period:  # fell well behind (slow frame, wake-up): resync
            next_frame = now
        delay = next_frame - now
        if delay <= 0:
            return
        if fps < config.DISPLAY_FPS:
            if _wake_event.wait(delay):
                next_frame = time.monotonic()
        else:
            _stop.wait(delay)

    while not _stop.is_set():
        _wake_event.clear()  # a _poke() from here on cuts this frame's wait short
        now = time.monotonic()
        dt, last = now - last, now

        # Check active status & minimum duration timers
        searching_web_active = _searching_web or (now < _web_search_until)
        rules_lookup_active = _looking_up_rules or (now < _rules_lookup_until)
        news_fetch_active = _fetching_news or (now < _news_fetch_until)
        image_retrieval_active = _retrieving_image or (now < _image_retrieval_until)

        # Update last activity time if active
        is_active = (
            _showing_omnissiah_glyph
            or _showing_update_progress
            or _rolling_die
            or _scanning_auspex
            or _scanning_noosphere
            or searching_web_active
            or rules_lookup_active
            or news_fetch_active
            or image_retrieval_active
            or _visualizing_music
            or _showing_custom_image
            or _showing_game
            or _speaking
            or _thinking
        )
        if is_active:
            _last_activity_time = now
            _active_idle_anim = None
        idle_due = not is_active and now - _last_activity_time >= config.DISPLAY_IDLE_TIMEOUT
        idle_requested = now < _custom_idle_expiry

        # Quiet hours with nothing to show: park the panel instead of running
        # screensavers all night. _poke() or the end of sleep hours wakes it.
        if (idle_due and not idle_requested and config.DISPLAY_SLEEP_IN_QUIET_HOURS
                and _in_sleep_hours(now)):
            if not _panel_asleep:
                _panel_sleep()
            away = True
            _wake_event.wait(5.0)
            continue
        if _panel_asleep:
            _panel_wake("sleep hours over" if idle_due and not idle_requested else "activity")
            next_frame = last = time.monotonic()

        prox_ok, dist = _read_distance()
        if (not prox_ok or _last_activity_time > presence_at
                or (dist is None) != (presence_cm is None)
                or (dist is not None and abs(dist - presence_cm) > _PRESENCE_DELTA_CM)):
            presence_at, presence_cm = now, dist
        nobody_around = (prox_ok and idle_due and not idle_requested
                         and now - presence_at >= config.DISPLAY_PRESENCE_TIMEOUT)
        if nobody_around != low_power:
            low_power = nobody_around
            print(f"[display] Nobody around — idle rendering at {config.DISPLAY_IDLE_FPS:g} fps."
                  if low_power else f"[display] Presence — back to {config.DISPLAY_FPS:g} fps.")

        if not is_active:
            if now >= _custom_idle_expiry:
                if _requested_idle_anim is not None:
                    _requested_idle_anim = None
                    _active_idle_anim = None

            # If idle and timeout reached or forced, run screensaver animation
            if idle_due or idle_requested:
                # Cycle to a new screensaver every 5 minutes (300 seconds) if not explicitly locked to a requested animation
                if _active_idle_anim is not None and (now - idle_anim_start_time >= 300.0) and (_requested_idle_anim is None):
                    _active_idle_anim = None

                if _active_idle_anim is None:
                    idle_anim_start_time = now
                    if _requested_idle_anim is not None:
                        _active_idle_anim = _requested_idle_anim
                    else:
                        if _screensavers and _screensavers.SCREENSAVER_ANIMS:
                            choices = [a for a in _screensavers.SCREENSAVER_ANIMS if a != last_picked_anim]
                            _active_idle_anim = random.choice(choices) if choices else random.choice(_screensavers.SCREENSAVER_ANIMS)
                        else:
                            _active_idle_anim = None
                    last_picked_anim = _active_idle_anim

                away = True
                try:
                    if _active_idle_anim and _screensavers:
                        _blit(_screensavers.render_screensaver_frame(_active_idle_anim, bezel, mask, now))
                except Exception as e:
                    _render_error(f"screensaver render ({_active_idle_anim})", e)
                pace(config.DISPLAY_IDLE_FPS if low_power else config.DISPLAY_FPS)
                continue
        if _showing_update_progress:
            try:
                _blit_static(("update", _update_progress_percent, _update_stage_text),
                             lambda: _render_update_progress_frame(bezel, mask, now))
            except Exception as e:
                _render_error("update progress render", e)
            pace(config.DISPLAY_STATIC_FPS)
            continue

        if _showing_omnissiah_glyph:
            glyph_elapsed = now - _omnissiah_start_time
            if glyph_elapsed >= _omnissiah_duration:
                _showing_omnissiah_glyph = False
            else:
                try:
                    _blit(_render_omnissiah_frame(bezel, mask, now))
                except Exception as e:
                    _render_error("omnissiah render", e)
                pace(config.DISPLAY_FPS)
                continue

        if _rolling_die:
            roll_elapsed = now - _die_start_time
            # Advance an attack to its next roll once this one has been seen.
            if _die_steps and _die_step < len(_die_steps) - 1:
                this_step = _die_steps[_die_step]
                shown_for = _DIE_TUMBLE_END + _DIE_SETTLE + this_step.get("hold", 1.1)
                if roll_elapsed >= shown_for:
                    _die_step += 1
                    nxt = _die_steps[_die_step]
                    start_die_roll(nxt.get("result", "0"), nxt.get("kind", "d6"),
                                   nxt.get("faces"), nxt.get("detail"),
                                   nxt.get("chosen", -1), _keep_sequence=True)
                    roll_elapsed = 0.0
            landed = roll_elapsed > _DIE_TUMBLE_END + _DIE_SETTLE
            # Something else wanting the panel takes it -- but never until the
            # dice have landed, so a roll is always seen through to its result.
            preempted = landed and (
                _scanning_auspex or _scanning_noosphere or searching_web_active
                or rules_lookup_active or news_fetch_active
                or image_retrieval_active or _showing_custom_image
                or _showing_alignment or _targeting or _visualizing_music)
            if roll_elapsed >= _DIE_HOLD or preempted:
                _rolling_die = False
            else:
                try:
                    _blit(_render_die_frame(bezel, mask, roll_elapsed, _die_result,
                                            _die_kind, _die_faces, _die_detail,
                                            _die_chosen, _die_step,
                                            len(_die_steps) or 1))
                except Exception as e:
                    _render_error("die render", e)
                pace(config.DISPLAY_FPS if landed
                     else max(config.DISPLAY_FPS, _DIE_MOTION_FPS))
                continue

        if _scanning_auspex:
            try:
                _blit(_render_auspex_frame(bezel, mask, now))
            except Exception as e:
                _render_error("auspex render", e)
            pace(config.DISPLAY_FPS)
            continue

        if _scanning_noosphere:
            try:
                _blit(_render_noosphere_frame(bezel, mask, now))
            except Exception as e:
                _render_error("noosphere render", e)
            pace(config.DISPLAY_FPS)
            continue

        if searching_web_active:
            try:
                _blit(_render_web_search_frame(bezel, mask, now))
            except Exception as e:
                _render_error("web search render", e)
            pace(config.DISPLAY_FPS)
            continue

        if rules_lookup_active:
            try:
                _blit(_render_rules_lookup_frame(bezel, mask, now))
            except Exception as e:
                _render_error("rules lookup render", e)
            pace(config.DISPLAY_FPS)
            continue

        if news_fetch_active:
            try:
                _blit(_render_news_fetch_frame(bezel, mask, now))
            except Exception as e:
                _render_error("news fetch render", e)
            pace(config.DISPLAY_FPS)
            continue

        if image_retrieval_active:
            try:
                _blit(_render_image_retrieval_frame(bezel, mask, now))
            except Exception as e:
                _render_error("image retrieval render", e)
            pace(config.DISPLAY_FPS)
            continue

        if _showing_alignment:
            if now >= _alignment_until:
                _showing_alignment = False
            else:
                try:
                    _blit(_render_alignment_frame(bezel, mask, now))
                except Exception as e:
                    _render_error("alignment render", e)
                pace(config.DISPLAY_FPS)
                continue

        if _targeting:
            try:
                _blit(_render_targeting_frame(bezel, mask, now))
            except Exception as e:
                _render_error("targeting render", e)
            pace(config.DISPLAY_FPS)
            continue

        if _visualizing_music and not _speaking and not _thinking:
            try:
                _blit(_render_music_frame(bezel, mask, now))
            except Exception as e:
                _render_error("music render", e)
            pace(config.DISPLAY_FPS)
            continue

        if _showing_game:
            try:
                from games.bardstale import agent as _bt_agent
                if _bt_agent.is_running():
                    key, frame = _bt_agent.eye_frame()
                    _blit_static(("game", key), lambda: frame)
                else:  # the game ended on its own (time limit, error)
                    _showing_game = False
            except Exception as e:
                _render_error("game frame", e)
            pace(config.DISPLAY_FPS)
            continue

        if _showing_custom_image:
            if now >= _custom_image_expiry:
                _showing_custom_image = False
                _custom_image = None
                _custom_reveal_src = None
            else:
                try:
                    view = _reveal_view(now)
                    if view is None:
                        _blit_static(("custom", _custom_image_seq), lambda: _custom_image)
                        pace(config.DISPLAY_STATIC_FPS)
                    else:
                        scale, px, py = view
                        _blit(_pan_zoom_frame(_custom_reveal_src, scale, px, py))
                        pace(config.DISPLAY_FPS)
                except Exception as e:
                    _render_error("custom image render", e)
                    pace(config.DISPLAY_STATIC_FPS)
                continue

        if _speaking:
            target = _target_amp
        else:
            # Slow idle breathing pulse (~0.2 Hz) so the eye looks "alive".
            target = 0.12 + 0.06 * (0.5 + 0.5 * math.sin((now - t0) * 1.2))
        # Ease toward the target to smooth the audio loop's jitter.
        if shown < 0:
            shown = target
        else:
            shown += (target - shown) * 0.35
        # Spin the cog while cogitating; hold the last angle when it stops so the
        # gear doesn't snap back to zero.
        if _thinking:
            angle = (angle + _SPIN_DEG_PER_SEC * dt) % 360

        # Gaze behavior: look around randomly when not speaking, not thinking, and not running screensavers
        if not _speaking and not _thinking and not is_active:
            if now >= next_gaze_time:
                if random.random() < 0.3:  # 30% chance to look back to center
                    target_look_x = 0.0
                    target_look_y = 0.0
                else:
                    gaze_angle = random.uniform(0, 2 * math.pi)
                    gaze_dist = random.uniform(6.0, 18.0)
                    target_look_x = gaze_dist * math.cos(gaze_angle)
                    target_look_y = gaze_dist * math.sin(gaze_angle)
                next_gaze_time = now + random.uniform(2.5, 6.0)
        else:
            # Center the eye when actively speaking, thinking, or in visualizer modes
            target_look_x = 0.0
            target_look_y = 0.0

        # Smoothly interpolate gaze position (snappy organic saccades)
        look_x += (target_look_x - look_x) * 0.65
        look_y += (target_look_y - look_y) * 0.65

        # Blink every few seconds: a quick close-and-open easing 0->1->0 (if enabled for personality).
        enable_blink = config.PERSONALITY.get("enable_blink", True)
        if enable_blink and blink_t0 is None and now >= next_blink:
            blink_t0 = now
        blink = 0.0
        if enable_blink and blink_t0 is not None:
            p = (now - blink_t0) / _BLINK_DUR
            if p >= 1.0:
                blink_t0 = None
                next_blink = now + random.uniform(*_BLINK_GAP)
            else:
                blink = math.sin(math.pi * p)  # 0 at edges, fully closed mid-blink
        if away:  # back from a screensaver or sleep
            away = False
            _shuffle_eye("back from screensaver")
        if eye_gen != _eye_style_gen:  # the eye style was switched: new bezel and aperture
            eye_gen = _eye_style_gen
            bezel = _make_bezel()
            mask = _make_iris_mask()
        try:
            _blit(_render_frame(bezel, mask, max(0.0, min(1.0, shown)), angle, blink, look_x, look_y))
        except Exception as e:
            _render_error("render", e)  # back off and keep going; never exit the thread
        pace(config.DISPLAY_FPS)


def start_die_sequence(steps: list) -> None:
    """Play a whole attack, one roll per step, on the display's own clock.

    Each step is a dict of the same fields ``start_die_roll`` takes, plus
    ``hold``: how long its result stays up before the next roll is thrown.

    The sequence runs here rather than in the tool that ordered it, because a
    tool that slept between steps would hold up the reply: the skull would
    finish rolling in silence and only then say what happened. Played from the
    render thread, the dice resolve on screen while it talks through them.
    """
    if not steps:
        return
    global _die_steps, _die_step
    _die_steps = list(steps)
    _die_step = 0
    first = _die_steps[0]
    start_die_roll(first.get("result", "0"), first.get("kind", "d6"),
                   first.get("faces"), first.get("detail"),
                   first.get("chosen", -1), _keep_sequence=True)


def start_die_roll(result: int | str, kind: str = "d6", faces=None,
                   detail=None, chosen: int = -1,
                   _keep_sequence: bool = False) -> None:
    """Show a dice roll.

    ``faces`` are symbol names from ``games.necromunda.dice.face_symbol`` -- the
    marks the dice carry -- and ``detail`` holds whatever each symbol needs
    (an arrow's direction, a numeral). ``chosen`` rings one dice as the result
    being applied. Without faces the roll is drawn as its number, which is what
    an ordinary dice shows anyway.
    """
    global _rolling_die, _die_start_time, _die_result
    global _die_kind, _die_faces, _die_detail, _die_chosen, _die_steps, _die_step
    if not _available:
        return
    if not _keep_sequence:      # a plain roll cancels any attack in progress
        _die_steps, _die_step = [], 0
    _die_result = str(result)
    _die_kind = kind or "d6"
    _die_faces = tuple(faces or ())
    _die_detail = tuple(detail or ())
    _die_chosen = int(chosen)
    _die_start_time = time.monotonic()
    _rolling_die = True
    _poke()


def start_update_progress() -> None:
    global _showing_update_progress, _update_progress_percent, _update_stage_text
    if not _available:
        return
    _update_progress_percent = 0.0
    _update_stage_text = "INITIATING..."
    _showing_update_progress = True
    _poke()

def set_update_progress(percent: float, text: str) -> None:
    global _update_progress_percent, _update_stage_text, _showing_update_progress
    _update_progress_percent = max(0.0, min(100.0, percent))
    _update_stage_text = text
    _showing_update_progress = True
    _poke()


def stop_update_progress() -> None:
    global _showing_update_progress
    _showing_update_progress = False



def start_omnissiah_glyph(duration: float = 4.0) -> None:
    global _showing_omnissiah_glyph, _omnissiah_start_time, _omnissiah_duration
    if not _available:
        return
    _omnissiah_duration = duration
    _omnissiah_start_time = time.monotonic()
    _showing_omnissiah_glyph = True
    _poke()


def to_rgb(img):
    """Every image bound for the panel must end up RGB.

    _blit packs three channels by indexing arr[..., 0:3]. A grayscale, palette or
    bilevel frame is a 2-D array there, so the pack silently produces 480 bytes
    instead of 115200 and the panel is sent garbage; an LA frame raises IndexError
    inside the render thread. Measured: L, P, 1 and I;16 all pack short, LA throws,
    and CMYK packs to the right size in the wrong colours. Alpha is composited onto
    black rather than dropped, so a transparent PNG does not come out as whatever
    happened to be in its colour channels.
    """
    from PIL import Image
    if img.mode == "RGB":
        return img
    if img.mode in ("I", "I;16", "I;16B", "I;16L", "I;16N", "F"):
        # These carry values well past 255 and convert("RGB") clips rather than
        # scales them, so a 16-bit greyscale piece arrives as a pure white panel --
        # measured at 100% white, mean 254. Normalise the range that is actually
        # present, and leave an 8-bit-range image alone so its tones are untouched.
        arr = np.asarray(img).astype("float32")
        hi, lo = float(arr.max()), float(arr.min())
        if hi > 255:
            arr = (arr - lo) * (255.0 / (hi - lo)) if hi > lo else np.zeros_like(arr)
            return Image.fromarray(arr.astype("uint8"), mode="L").convert("RGB")
        return img.convert("RGB")
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        flat = Image.new("RGB", rgba.size, (0, 0, 0))
        flat.paste(rgba, mask=rgba.split()[-1])
        return flat
    return img.convert("RGB")


def fit_to_panel(pil_img):
    """The 240x240 RGB image this panel would show for `pil_img`.

    Centre-cropped to a square and resized. Shared with the artwork chooser, which
    needs to judge the region that actually gets displayed rather than the whole
    picture: a wide piece can be full of detail and still have nothing but sky in
    the middle.
    """
    from PIL import Image
    pil_img = to_rgb(pil_img)
    w, h = pil_img.size
    side = min(w, h)
    left, top = (w - side) // 2, (h - side) // 2
    cropped = pil_img.crop((left, top, left + side, top + side))
    return cropped.resize((240, 240), resample=Image.BICUBIC)


# A picture is revealed rather than dropped on the panel cropped: the whole of it
# is shown first, scaled to fit inside the circle, and then it zooms in until it
# fills the screen. A centre crop alone can cut most of a wide piece away, which is
# how "40k ork" came out as something unidentifiable.
# A still image on a small round panel reads as a dead screen, so a picture fills
# the panel from its first frame and then keeps moving for as long as it is up:
# a creeping pan and zoom that gives the eye something to follow. 1.18 over the
# showing is about 1% a second.
KEN_BURNS_ZOOM = 1.18       # how much further in it creeps over the whole showing
KEN_BURNS_PAN = 0.70        # fraction of the available slack it drifts across
_custom_reveal_src = None   # the source at fill scale; None when not revealing
_custom_reveal_t0 = 0.0
_custom_reveal_pan = (0.5, 0.5, 0.5, 0.5)


def _reveal_source(pil_img):
    """`pil_img` at the largest size the drift needs, and no larger.

    Scaling once, here, means every frame is a resize DOWN from a small image rather
    than from the original download — a 3000 px piece resized per frame would not fit
    the render budget. The shorter side is 240 times the full zoom rather than 240
    flat, so the end of the drift is still a downscale: at 240 the last frames were
    being blown up 18% past the resolution they had.
    """
    from PIL import Image
    img = to_rgb(pil_img)
    w, h = img.size
    want = int(240 * KEN_BURNS_ZOOM) + 1
    k = want / min(w, h)
    # Never upscale the download itself to reach it; a small picture stays small.
    k = min(k, max(1.0, 240 / min(w, h)))
    return img.resize((max(240, round(w * k)), max(240, round(h * k))), Image.BICUBIC)


def _pan_zoom_frame(src, scale: float, px: float = 0.5, py: float = 0.5):
    """A 240x240 view of `src` at `scale`, centred at (px, py) of the slack.

    scale 1.0 fills the panel exactly, whatever resolution `src` is held at; below
    that the picture is letterboxed and centred, above it there is room to pan and
    px/py choose where in that room the window sits — 0.0 hard left or top, 1.0
    hard right or bottom.
    """
    from PIL import Image
    sw, sh = src.size
    # `scale` is relative to filling the panel, whatever resolution src happens to
    # be held at, so the source can carry the extra detail the zoom will want.
    fill = 240 / min(sw, sh)
    w = max(1, round(sw * fill * scale))
    h = max(1, round(sh * fill * scale))
    frame = Image.new("RGB", (240, 240), (0, 0, 0))
    x = (240 - w) // 2 if w <= 240 else -round((w - 240) * min(max(px, 0.0), 1.0))
    y = (240 - h) // 2 if h <= 240 else -round((h - 240) * min(max(py, 0.0), 1.0))
    # paste clips on its own, so an oversized frame simply crops to the window.
    frame.paste(src.resize((w, h), Image.BICUBIC), (x, y))
    return frame


def _ken_burns_path(size) -> tuple:
    """Where the drift starts and ends, as (px0, py0, px1, py1).

    Along the long axis, because that is where a filled panel has room to move: a
    wide picture pans sideways, a tall one vertically, a square one diagonally. The
    direction is chosen per picture so consecutive ones do not all drift the same
    way.
    """
    import random
    lo = (1.0 - KEN_BURNS_PAN) / 2.0
    hi = 1.0 - lo
    a, b = (lo, hi) if random.random() < 0.5 else (hi, lo)
    w, h = size
    if w > h * 1.05:
        return (a, 0.5, b, 0.5)
    if h > w * 1.05:
        return (0.5, a, 0.5, b)
    return (a, a, b, b)


def _reveal_view(now: float):
    """(scale, px, py) for this moment, or None if no picture is being animated.

    One phase: the picture fills the panel from the first frame and drifts across
    itself for the whole showing. There was an opening that held the whole picture
    letterboxed and then zoomed in to fill, which reads as a slideshow transition
    rather than a camera move; starting filled and moving at once is what was asked
    for and is the simpler thing to reason about.

    Linear, deliberately: a constant creep is what reads as Ken Burns, where an
    eased one visibly slows to a halt partway through the showing.
    """
    if _custom_reveal_src is None:
        return None
    span = max(0.1, _custom_image_expiry - _custom_reveal_t0)
    u = min(1.0, max(0.0, (now - _custom_reveal_t0) / span))
    px0, py0, px1, py1 = _custom_reveal_pan
    return (1.0 + (KEN_BURNS_ZOOM - 1.0) * u,
            px0 + (px1 - px0) * u,
            py0 + (py1 - py0) * u)


def display_pil_image(pil_img, duration: float = 10.0, reveal: bool = False) -> bool:
    """Show an image on the eye for `duration`. True if the panel took it.

    The return value matters: display_art used to announce "successfully projected"
    for pictures that never reached the panel, because this returns early when
    there is no panel and swallows anything that goes wrong.
    """
    global _showing_custom_image, _custom_image, _custom_image_expiry, _custom_image_seq
    global _custom_reveal_src, _custom_reveal_t0, _custom_reveal_pan
    global _retrieving_image, _image_retrieval_until
    if not _available:
        print("[display] No panel available — image not shown.")
        return False
    try:
        from PIL import ImageOps
        # A phone-shot piece carries its rotation in EXIF; without this it is sideways.
        try:
            pil_img = ImageOps.exif_transpose(pil_img) or pil_img
        except Exception:
            pass
        if reveal:
            _custom_reveal_src = _reveal_source(pil_img)
            _custom_reveal_t0 = time.monotonic()
            _custom_reveal_pan = _ken_burns_path(_custom_reveal_src.size)
        else:
            _custom_reveal_src = None
        # The settled frame is cropped from the original rather than from the
        # pre-scaled reveal source: the zoom's last frame and this are the same
        # view, but this one has not been through an extra resize, so the picture
        # it holds for the remaining ten seconds is the sharper of the two.
        _custom_image = fit_to_panel(pil_img)
        _custom_image_seq += 1
        _custom_image_expiry = time.monotonic() + duration
        _showing_custom_image = True
        # The retrieval animation has a three-second minimum, and it outranks the
        # custom image in the render loop. That was swallowing the reveal's opening
        # hold: by the time the animation cleared, the zoom was already underway and
        # the whole picture had never been seen. The picture is what the animation
        # was waiting for, so its arrival ends it.
        _retrieving_image = False
        _image_retrieval_until = 0.0
        _poke()
        return True
    except Exception as e:
        print(f"[display] display_pil_image error: {e}")
        return False


def show_access_code(code: str, duration: float = 60.0) -> None:
    """Show a short sign-in code in large digits, centred on the round eye."""
    try:
        from PIL import Image, ImageDraw
        img = Image.new("RGB", (240, 240), (0, 0, 0))
        d = ImageDraw.Draw(img)
        d.ellipse([6, 6, 233, 233], outline=(0, 90, 35), width=2)
        label_font = _get_font(15)
        for text, y in (("WEB REMOTE", 52), ("SIGN-IN CODE", 170)):
            w = d.textlength(text, font=label_font)
            d.text(((240 - w) / 2, y), text, fill=(0, 170, 70), font=label_font)
        size = 84
        font = _get_font(size)
        while d.textlength(code, font=font) > 196 and size > 30:
            size -= 4
            font = _get_font(size)
        box = d.textbbox((0, 0), code, font=font)
        x = (240 - (box[2] - box[0])) / 2 - box[0]
        y = (240 - (box[3] - box[1])) / 2 - box[1]
        d.text((x, y), code, fill=(120, 255, 160), font=font)
        display_pil_image(img, duration=duration)
    except Exception as e:
        print(f"[display] show_access_code error: {e}")


def show_setup_screen(ssid: str, password: str, address: str, duration: float = 150.0) -> None:
    """Setup-mode screen: hotspot name, its (random) password in large type, and the
    address of the setup wizard — readable on the round eye."""
    try:
        from PIL import Image, ImageDraw
        img = Image.new("RGB", (240, 240), (0, 0, 0))
        d = ImageDraw.Draw(img)
        d.ellipse([6, 6, 233, 233], outline=(0, 90, 35), width=2)

        def centred(text, y, size, fill, max_w=200):
            font = _get_font(size)
            while d.textlength(text, font=font) > max_w and size > 10:
                size -= 1
                font = _get_font(size)
            d.text(((240 - d.textlength(text, font=font)) / 2, y), text, fill=fill, font=font)

        centred("SETUP MODE", 34, 16, (0, 200, 80))
        centred("WI-FI", 64, 12, (0, 140, 55))
        centred(ssid, 80, 20, (120, 255, 160))
        centred("PASSWORD", 114, 12, (0, 140, 55))
        centred(password, 130, 30, (170, 255, 190), max_w=196)
        centred("THEN OPEN", 172, 12, (0, 140, 55))
        centred(address, 188, 16, (120, 255, 160), max_w=150)
        display_pil_image(img, duration=duration)
    except Exception as e:
        print(f"[display] show_setup_screen error: {e}")


def show_text(text: str, duration: float = 10.0) -> None:
    """Renders text onto a 240x240 image and displays it on the panel."""
    try:
        from PIL import Image, ImageDraw, ImageFont
        img = Image.new("RGB", (240, 240), (0, 0, 0))
        draw = ImageDraw.Draw(img)
        font = ImageFont.load_default()
        y = 60
        for line in text.split("\n"):
            draw.text((20, y), line, fill=(0, 255, 100), font=font)
            y += 20
        display_pil_image(img, duration=duration)
    except Exception as e:
        print(f"[display] show_text error: {e}")


def trigger_idle_animation(duration: float = 60.0, animation_name: str | None = None) -> None:
    global _custom_idle_expiry, _last_activity_time, _requested_idle_anim, _active_idle_anim
    if not _available:
        return
    _custom_idle_expiry = time.monotonic() + duration
    _active_idle_anim = None
    _last_activity_time = 0.0  # Force idle screensaver mode immediately
    if animation_name and _screensavers and animation_name in _screensavers.SCREENSAVER_ANIMS:
        _requested_idle_anim = animation_name
    else:
        _requested_idle_anim = None
    _poke(activity=False)  # wake the loop without undoing the forced idle above


# ── public API (mirrors eyes.py) ─────────────────────────────────────────────────

def setup() -> None:
    """Initialise the panel and start the render thread. Runs a virtual render loop
    for the web remote if hardware/libraries are unavailable."""
    global _available, _spi, _render_thread
    if not config.DISPLAY_ENABLED:
        return

    try:
        if _GPIO is not None and spidev is not None:
            _GPIO.setmode(_GPIO.BCM)
            _GPIO.setwarnings(False)
            for pin in (config.DISPLAY_DC_PIN, config.DISPLAY_RST_PIN, config.DISPLAY_BL_PIN):
                if pin >= 0:
                    _GPIO.setup(pin, _GPIO.OUT, initial=_GPIO.LOW)

            _spi = spidev.SpiDev()
            _spi.open(config.DISPLAY_SPI_BUS, config.DISPLAY_SPI_DEVICE)
            _spi.max_speed_hz = config.DISPLAY_SPI_HZ
            _spi.mode = 0

            _init_panel()
            if config.DISPLAY_BL_PIN >= 0:
                _GPIO.output(config.DISPLAY_BL_PIN, 1)  # backlight on
            _available = True
            print("[display] GC9A01 online — the machine spirit observes.")
        else:
            print("[display] Hardware libraries unavailable; running virtual render loop for web remote.")
            _available = False
    except Exception as e:
        print(f"[display] Hardware init failed ({e}); running virtual render loop for web remote.")
        _available = False

    _restore_eye_style()
    _stop.clear()
    _render_thread = threading.Thread(target=_loop, daemon=True)
    _render_thread.start()


def set_amplitude(amp: float) -> None:
    """Feed a normalized speech amplitude (0..1); marks the eye as speaking."""
    global _target_amp, _speaking, _thinking
    if not _available:
        return
    _target_amp = max(0.0, min(1.0, amp))
    _speaking = True
    _thinking = False  # speech has begun; stop spinning the cog
    _poke()


def set_mood(mood: str) -> None:
    """Tint the iris to match Omega-7's current disposition (see core/mood.py)."""
    global _mood_rgb, _mood_name
    new_mood = (mood or "").upper() or _mood_name
    if new_mood != _mood_name:
        _mood_name = new_mood
        _shuffle_eye(f"mood {new_mood}")
    if not _available:
        return
    _mood_rgb = _MOOD_COLOURS.get(_mood_name, (255, 40, 30))


def think(active: bool = True) -> None:
    """Spin the cog wheel while Omega-7 is cogitating (the silent gap between
    hearing a command and beginning to speak). The iris keeps its idle breathing
    pulse underneath. Call think(False) — or any speaking/idle entry point — to
    stop the spin."""
    global _thinking
    if not _available:
        return
    _thinking = active
    if active:
        _poke()


def on() -> None:
    """Full-intensity steady gaze (e.g. while attending a command)."""
    global _target_amp, _speaking, _thinking
    if not _available:
        return
    _target_amp = 1.0
    _speaking = True
    _thinking = False
    _poke()


def idle() -> None:
    """Return to the slow idle breathing pulse."""
    global _speaking, _target_amp, _thinking
    if not _available:
        return
    _speaking = False
    _target_amp = 0.0
    _thinking = False


# Alias so call sites that mirror eyes.off() read naturally.
off = idle


def start_auspex_scan() -> None:
    global _scanning_auspex
    _scanning_auspex = True
    _poke()


def stop_auspex_scan() -> None:
    global _scanning_auspex
    _scanning_auspex = False


def start_noosphere_scan() -> None:
    global _scanning_noosphere
    _scanning_noosphere = True
    _poke()


def stop_noosphere_scan() -> None:
    global _scanning_noosphere
    _scanning_noosphere = False


def start_web_search(min_duration: float = 3.0) -> None:
    global _searching_web, _web_search_until
    _web_search_until = time.monotonic() + min_duration
    _searching_web = True
    _poke()


def stop_web_search() -> None:
    global _searching_web
    _searching_web = False


def start_rules_lookup(min_duration: float = 3.5) -> None:
    global _looking_up_rules, _rules_lookup_until
    _rules_lookup_until = time.monotonic() + min_duration
    _looking_up_rules = True
    _poke()


def stop_rules_lookup() -> None:
    global _looking_up_rules
    _looking_up_rules = False


def start_news_fetch(min_duration: float = 3.0) -> None:
    global _fetching_news, _news_fetch_until
    _news_fetch_until = time.monotonic() + min_duration
    _fetching_news = True
    _poke()


def stop_news_fetch() -> None:
    global _fetching_news
    _fetching_news = False


def start_image_retrieval(min_duration: float = 3.0) -> None:
    global _retrieving_image, _image_retrieval_until
    _image_retrieval_until = time.monotonic() + min_duration
    _retrieving_image = True
    _poke()


def stop_image_retrieval() -> None:
    global _retrieving_image
    _retrieving_image = False


def set_targeting(active: bool) -> None:
    global _targeting
    _targeting = active
    if active:
        _poke()


def set_music_playing(active: bool) -> None:
    global _visualizing_music
    _visualizing_music = active
    if active:
        _poke()


def cleanup() -> None:
    global _available
    _stop.set()
    _wake_event.set()
    if _render_thread is not None:
        _render_thread.join(timeout=1.0)
    if not _available:
        return
    try:
        if config.DISPLAY_BL_PIN >= 0:
            _GPIO.output(config.DISPLAY_BL_PIN, 0)
        if _spi is not None:
            _spi.close()
    except Exception:
        pass
    _available = False


def start_game_display() -> None:
    """Tell the display loop to show live Bard's Tale game frames."""
    global _showing_game
    _showing_game = True
    _poke()


def stop_game_display() -> None:
    """Stop showing game frames; display returns to normal iris rendering."""
    global _showing_game
    _showing_game = False


def get_state() -> dict:
    global _showing_custom_image, _active_idle_anim, _speaking, _thinking, _target_amp
    global _scanning_auspex, _scanning_noosphere, _searching_web, _looking_up_rules, _fetching_news, _retrieving_image, _targeting, _visualizing_music, _rolling_die, _die_result
    global _web_search_until, _rules_lookup_until, _news_fetch_until, _image_retrieval_until, _showing_alignment, _alignment_until
    global _showing_game
    now = time.monotonic()
    return {
        "showing_custom_image": _showing_custom_image,
        "showing_game": _showing_game,
        "active_idle_anim": _active_idle_anim,
        "speaking": _speaking,
        "thinking": _thinking,
        "amplitude": _target_amp,
        "scanning_auspex": _scanning_auspex,
        "scanning_noosphere": _scanning_noosphere,
        "searching_web": _searching_web or (now < _web_search_until),
        "looking_up_rules": _looking_up_rules or (now < _rules_lookup_until),
        "fetching_news": _fetching_news or (now < _news_fetch_until),
        "retrieving_image": _retrieving_image or (now < _image_retrieval_until),
        "showing_alignment": _showing_alignment or (now < _alignment_until),
        "targeting": _targeting,
        "visualizing_music": _visualizing_music,
        "rolling_die": _rolling_die,
        "die_result": _die_result,
    }


def get_custom_image_bytes() -> bytes | None:
    global _custom_image
    if _custom_image is None:
        return None
    try:
        import io
        buf = io.BytesIO()
        _custom_image.save(buf, format="JPEG")
        return buf.getvalue()
    except Exception as e:
        print(f"[display] Failed to get custom image bytes: {e}")
        return None


def get_ocular_frame_bytes() -> bytes | None:
    """JPEG of the latest displayed frame, encoded lazily and only when asked for."""
    global _frame_jpeg_cache
    with _frame_lock:
        if _current_frame_image is None:
            return None
        seq, cached = _frame_jpeg_cache
        if seq == _current_frame_seq and cached is not None:
            return cached
        try:
            import io
            buf = io.BytesIO()
            _current_frame_image.save(buf, format="JPEG", quality=70)
            _frame_jpeg_cache = (_current_frame_seq, buf.getvalue())
            return _frame_jpeg_cache[1]
        except Exception as e:
            print(f"[display] Failed to get ocular frame bytes: {e}")
            return None
