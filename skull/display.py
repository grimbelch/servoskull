"""
Drives a GC9A01 1.28" round IPS panel (240x240, 4-wire SPI) as Omega-7's
"machine-spirit" eye. A background thread renders a glowing iris whose size and
brightness track speech amplitude (the same signal that pulses the eye LEDs),
with a slow idle "breathing" pulse when silent. Mood tints the iris colour.

Self-contained driver (spidev + RPi.GPIO + Pillow) so it carries no dependency
on luma/Adafruit supporting GC9A01. Mirrors eyes.py: if the hardware or libs are
absent (e.g. the Mac/Windows emulator), every entry point is a silent no-op.

Enable with DISPLAY_ENABLED=true in .env. Wiring lives in config.py.
"""

from __future__ import annotations
import math
import random
import threading
import time

from skull import config

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
_scanning_auspex = False
_scanning_noosphere = False
_targeting = False
_visualizing_music = False

_showing_omnissiah_glyph = False
_omnissiah_start_time = 0.0
_omnissiah_duration = 0.0

_showing_custom_image = False
_custom_image = None
_custom_image_expiry = 0.0

_last_activity_time = 0.0
_active_idle_anim = None
_custom_idle_expiry = 0.0

# Screensaver pools
_screensaver_anims = ["pong", "canticle_rain", "starfield", "oscilloscope", "game_of_life", "radar"]

# Pong state variables
_pong_ball_x = 120.0
_pong_ball_y = 120.0
_pong_ball_dx = 2.5
_pong_ball_dy = 1.2
_pong_paddle_l_y = 120.0
_pong_paddle_r_y = 120.0
_pong_score_l = 0
_pong_score_r = 0

# Canticle Rain state
_rain_cols = []

# Starfield state
_starfield_stars = []

# Game of Life state
_gol_grid = None
_gol_last_grids = []

# Radar state
_radar_blips = []



_SPIN_DEG_PER_SEC = 80.0   # cog rotation speed while thinking

_BLINK_DUR = 0.14          # seconds for one close-and-open blink
_BLINK_GAP = (2.5, 6.0)    # random idle interval (s) between blinks

W = H = 240
_CX = _CY = 120
_EYE_R = 73   # radius of the cog's central aperture; the iris lives inside this

# GC9A01 command set (subset).
_SWRESET = 0x01
_SLPOUT = 0x11
_DISPON = 0x29
_CASET = 0x2A
_RASET = 0x2B
_RAMWR = 0x2C
_MADCTL = 0x36
_COLMOD = 0x3A

# MADCTL orientation bits keyed by DISPLAY_ROTATION.
_MADCTL_BY_ROT = {0: 0x08, 90: 0x68, 180: 0xC8, 270: 0xA8}

# Mood -> base iris colour. Names match skull/mood.py dispositions; unknown moods
# fall back to Imperial red.
_MOOD_COLOURS = {
    "VIGILANT": (255, 40, 30),
    "DUTIFUL": (255, 70, 25),
    "FERVENT": (255, 120, 20),
    "SUSPICIOUS": (255, 200, 30),
    "CONTEMPLATIVE": (60, 140, 255),
    "MELANCHOLIC": (90, 90, 200),
}

try:
    from PIL import Image, ImageDraw
    import numpy as np
except ImportError:
    pass

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


def _blit(img) -> None:
    """Push a 240x240 PIL RGB image to the panel as big-endian RGB565."""
    if config.DISPLAY_FINE_ROTATION != 0.0:
        # PIL rotate is counter-clockwise. Pass -angle to rotate clockwise.
        img = img.rotate(-config.DISPLAY_FINE_ROTATION, resample=Image.BICUBIC)
    arr = np.asarray(img, dtype=np.uint16)
    r = (arr[..., 0] & 0xF8) << 8
    g = (arr[..., 1] & 0xFC) << 3
    b = (arr[..., 2] & 0xF8) >> 3
    rgb565 = (r | g | b).astype(">u2")  # big-endian: MSB first on the wire
    buf = rgb565.tobytes()
    _set_window(0, 0, W - 1, H - 1)
    _GPIO.output(config.DISPLAY_DC_PIN, 1)
    # spidev caps a single transfer at its bufsiz (commonly 4096 bytes); chunk.
    step = 4096
    for i in range(0, len(buf), step):
        _spi.writebytes(buf[i:i + step])


# ── frame composition ─────────────────────────────────────────────────────────────

def _scale(rgb, k: float):
    k = max(0.0, min(1.0, k))
    return (int(rgb[0] * k), int(rgb[1] * k), int(rgb[2] * k))


def _gear_polygon(n_teeth: int, r_root: float, r_tip: float,
                  tooth_frac: float = 0.52, tip_frac: float = 0.34,
                  gap_steps: int = 5):
    """Vertices of a cog: teeth alternate between the tip radius and the root
    radius around the rim. Teeth are trapezoidal (narrower at the tip); gaps are
    subdivided so the root follows the circle rather than chording across it."""
    period = 2 * math.pi / n_teeth
    half_base = period * tooth_frac / 2
    half_tip = period * tip_frac / 2
    polar = []
    for i in range(n_teeth):
        a = i * period
        polar.append((a - half_base, r_root))   # tooth base (rising)
        polar.append((a - half_tip, r_tip))     # tip left
        polar.append((a + half_tip, r_tip))     # tip right
        polar.append((a + half_base, r_root))   # tooth base (falling)
        gap_start, gap_end = a + half_base, a + period - half_base
        for s in range(1, gap_steps):           # arc across the gap to next tooth
            polar.append((gap_start + (gap_end - gap_start) * s / gap_steps, r_root))
    return [(_CX + r * math.cos(ang), _CY + r * math.sin(ang)) for ang, r in polar]


def _make_iris_mask():
    """White disc over the cog's central aperture. The iris is composited through
    this mask so its glow never paints over the surrounding gear teeth."""
    m = Image.new("L", (W, H), 0)
    ImageDraw.Draw(m).ellipse(
        [_CX - _EYE_R, _CY - _EYE_R, _CX + _EYE_R, _CY + _EYE_R], fill=255)
    return m


def _make_bezel():
    """Static background: an Adeptus Mechanicus cog wheel with a dark central
    aperture. Drawn once; the glowing iris is composited into the aperture each
    frame (see _render_frame), so we only repaint the cheap iris per tick."""
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


def _render_frame(bezel, mask, amp: float, angle: float = 0.0, blink: float = 0.0):
    """Compose one iris frame for normalized amplitude `amp` (0..1). The iris is
    drawn on its own layer and pasted through `mask` so it stays in the aperture.

    `angle` (degrees) rotates the cog about its centre — used to spin the gear
    while Omega-7 is thinking. The cog fits inside the panel's inscribed circle
    (tip radius 117 < 120), so rotation never clips it; the iris is a centred
    disc and so is unaffected.

    `blink` (0=open..1=fully closed) squashes the iris vertically about its
    centre into a slit, so the eye reads as blinking."""
    # rotate() returns a fresh image we can draw on; otherwise copy the shared bezel.
    img = bezel.rotate(angle, resample=Image.BICUBIC) if angle else bezel.copy()
    base = _mood_rgb
    intensity = 0.25 + 0.75 * amp           # never fully dark
    iris_r = 30 + 30 * amp                   # iris grows as it "speaks"

    iris = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(iris)

    def disc(r, colour):
        d.ellipse([_CX - r, _CY - r, _CX + r, _CY + r], fill=colour)

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
    d.line([(cx - 15, cy), (cx - 5, cy)], fill=base, width=1.5)
    d.line([(cx + 5, cy), (cx + 15, cy)], fill=base, width=1.5)
    d.line([(cx, cy - 15), (cx, cy - 5)], fill=base, width=1.5)
    d.line([(cx, cy + 5), (cx, cy + 15)], fill=base, width=1.5)
    flash = int(now * 6) % 2 == 0
    if flash:
        offset = 45
        d.polygon([(cx - offset, cy), (cx - offset + 6, cy - 4), (cx - offset + 6, cy + 4)], fill=base)
        d.polygon([(cx + offset, cy), (cx + offset - 6, cy - 4), (cx + offset - 6, cy + 4)], fill=base)
    d.ellipse([cx - 2, cy - 2, cx + 2, cy + 2], fill=base)
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


def _render_die_frame(bezel, mask, elapsed: float, result: str):
    # Build on top of the static bezel
    img = bezel.copy()
    base = _mood_rgb
 
    overlay = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(overlay)
 
    if elapsed < 1.5:
        # Cube rotation angles
        ax = elapsed * 480
        ay = elapsed * 640
        az = elapsed * 320
 
        # 8 Cube vertices (unit cube scaled)
        v = [(x, y, z) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]
 
        rotated_v = []
        for vx, vy, vz in v:
            # Scale the die size to fit nicely in the central aperture (radius 73)
            vx, vy, vz = vx * 0.45, vy * 0.45, vz * 0.45
            vx, vy, vz = _rotate_x(vx, vy, vz, ax)
            vx, vy, vz = _rotate_y(vx, vy, vz, ay)
            vx, vy, vz = _rotate_z(vx, vy, vz, az)
            rotated_v.append((vx, vy, vz))
 
        proj_v = []
        scale = 90
        dist = 3.0
        for vx, vy, vz in rotated_v:
            px = _CX + int(vx * scale / (vz + dist))
            py = _CY + int(vy * scale / (vz + dist))
            proj_v.append((px, py))
 
        edges = [
            (0, 1), (1, 3), (3, 2), (2, 0),
            (4, 5), (5, 7), (7, 6), (6, 4),
            (0, 4), (1, 5), (2, 6), (3, 7)
        ]
 
        for start, end in edges:
            d.line(proj_v[start] + proj_v[end], fill=base, width=2)
    else:
        # Draw vector 7-segment result inside circular HUD frame
        d.ellipse([_CX - 40, _CY - 40, _CX + 40, _CY + 40], outline=base, width=2)
        # Tech notches/tick marks
        for deg in range(0, 360, 45):
            rad = math.radians(deg)
            x0, y0 = _CX + 40 * math.cos(rad), _CY + 40 * math.sin(rad)
            x1, y1 = _CX + 46 * math.cos(rad), _CY + 46 * math.sin(rad)
            d.line([(x0, y0), (x1, y1)], fill=base, width=2)
 
        # Convert result to string and clean/strip it
        val_str = str(result).strip()
        if val_str:
            # Pick size based on length
            if len(val_str) == 1:
                w, h = 24, 42
                gap = 8
            elif len(val_str) == 2:
                w, h = 18, 32
                gap = 6
            elif len(val_str) == 3:
                w, h = 12, 22
                gap = 4
            else:
                w, h = 9, 16
                gap = 3
                
            total_w = len(val_str) * w + (len(val_str) - 1) * gap
            start_x = _CX - total_w // 2
            start_y = _CY - h // 2
            
            for i, char in enumerate(val_str):
                dx = start_x + i * (w + gap)
                _draw_vector_digit(d, dx, start_y, w, h, char, base, thickness=3 if h > 20 else 2)
 
    img.paste(overlay, (0, 0), mask)
    return img


def _render_omnissiah_frame(bezel, mask, now: float) -> Image.Image:
    img = bezel.copy()
    overlay = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(overlay)
    
    age = now - _omnissiah_start_time
    
    # ── 2. Adeptus Mechanicus Skull-Cog ──────────────────────────────────────
    scale = min(1.0, age / 1.5)
    scale = scale * scale * (3.0 - 2.0 * scale)
    
    if scale > 0.01:
        gear_angle = (age * 60.0) % 360
        r_outer = 65.0 * scale
        r_inner = 50.0 * scale
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
        
        r_center = 40.0 * scale
        d.ellipse([_CX - r_center, _CY - r_center, _CX + r_center, _CY + r_center], fill=(0, 0, 0))
        
        # Left cranium (bone)
        d.pieslice([_CX - 16 * scale, _CY - 20 * scale, _CX + 16 * scale, _CY + 12 * scale], 90, 270, fill=(235, 230, 215))
        # Right cranium (machine)
        d.pieslice([_CX - 16 * scale, _CY - 20 * scale, _CX + 16 * scale, _CY + 12 * scale], 270, 90, fill=(80, 85, 95))
        
        # Left jaw
        d.polygon([
            (_CX - 9 * scale, _CY + 12 * scale),
            (_CX, _CY + 12 * scale),
            (_CX, _CY + 22 * scale),
            (_CX - 7 * scale, _CY + 22 * scale)
        ], fill=(235, 230, 215))
        # Right jaw
        d.polygon([
            (_CX, _CY + 12 * scale),
            (_CX + 9 * scale, _CY + 12 * scale),
            (_CX + 7 * scale, _CY + 22 * scale),
            (_CX, _CY + 22 * scale)
        ], fill=(80, 85, 95))
        
        # Cheekbones
        d.ellipse([_CX - 18 * scale, _CY - 2 * scale, _CX - 10 * scale, _CY + 6 * scale], fill=(235, 230, 215))
        d.ellipse([_CX + 10 * scale, _CY - 2 * scale, _CX + 18 * scale, _CY + 6 * scale], fill=(80, 85, 95))
        
        # Left eye
        d.ellipse([_CX - 9 * scale, _CY - 4 * scale, _CX - 3 * scale, _CY + 2 * scale], fill=(0, 0, 0))
        # Right eye
        d.ellipse([_CX + 3 * scale, _CY - 4 * scale, _CX + 9 * scale, _CY + 2 * scale], fill=(0, 230, 80))
        
        # Nose
        d.polygon([
            (_CX - 2 * scale, _CY + 8 * scale),
            (_CX, _CY + 4 * scale),
            (_CX + 2 * scale, _CY + 8 * scale)
        ], fill=(0, 0, 0))
        
        # Teeth slits
        for offset in (-5, -2):
            d.line([(_CX + offset * scale, _CY + 12 * scale), (_CX + offset * scale, _CY + 20 * scale)], fill=(0, 0, 0), width=1)
        for offset in (2, 5):
            d.line([(_CX + offset * scale, _CY + 12 * scale), (_CX + offset * scale, _CY + 20 * scale)], fill=(0, 0, 0), width=1)
        d.line([(_CX, _CY + 12 * scale), (_CX, _CY + 22 * scale)], fill=(0, 0, 0), width=1)

    img.paste(overlay, (0, 0), mask)
    return img


# ── render loop ────────────────────────────────────────────────────────────────────

def _init_canticle_rain():
    global _rain_cols
    _rain_cols = []
    for x in range(72, 169, 10):
        _rain_cols.append({
            "x": x,
            "y": random.uniform(70, 170),
            "speed": random.uniform(1.5, 3.5),
            "chars": [random.choice(["0", "1"]) for _ in range(8)]
        })


def _init_starfield():
    global _starfield_stars
    _starfield_stars = []
    for _ in range(40):
        _starfield_stars.append({
            "x": random.uniform(-100, 100),
            "y": random.uniform(-100, 100),
            "z": random.uniform(1, 200)
        })


def _init_game_of_life():
    global _gol_grid, _gol_last_grids
    _gol_grid = [[1 if random.random() < 0.25 else 0 for _ in range(20)] for _ in range(20)]
    _gol_last_grids = []


def _init_radar():
    global _radar_blips
    _radar_blips = []
    for _ in range(4):
        _radar_blips.append({
            "angle": random.uniform(0, 2 * math.pi),
            "dist": random.uniform(15, 48),
            "intensity": 0.0,
            "type": random.choice(["dot", "cross"])
        })


def _render_canticle_rain_frame(bezel, mask, now):
    global _rain_cols
    if not _rain_cols:
        _init_canticle_rain()
        
    from PIL import Image, ImageDraw, ImageFont
    img = bezel.copy()
    overlay = Image.new("RGB", (240, 240), (0, 8, 3))
    d = ImageDraw.Draw(overlay)
    
    min_y, max_y = 70, 170
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None
        
    for col in _rain_cols:
        col["y"] += col["speed"]
        if col["y"] > max_y + 40:
            col["y"] = min_y
            col["speed"] = random.uniform(1.5, 3.5)
            
        y_pos = col["y"]
        for idx, char in enumerate(col["chars"]):
            cy = y_pos - idx * 10
            if min_y <= cy <= max_y:
                if idx == 0:
                    fill = (100, 255, 150)
                else:
                    alpha = max(0, 255 - idx * 30)
                    fill = (0, int(alpha * 0.8), int(alpha * 0.2))
                    
                if random.random() < 0.05:
                    col["chars"][idx] = random.choice(["0", "1"])
                    
                if font:
                    d.text((col["x"], cy), char, fill=fill, font=font)
                else:
                    d.rectangle([col["x"], cy, col["x"] + 4, cy + 6], fill=fill)
                    
    img.paste(overlay, (0, 0), mask)
    return img


def _render_starfield_frame(bezel, mask, now):
    global _starfield_stars
    if not _starfield_stars:
        _init_starfield()
        
    from PIL import Image, ImageDraw
    img = bezel.copy()
    overlay = Image.new("RGB", (240, 240), (0, 5, 2))
    d = ImageDraw.Draw(overlay)
    
    for star in _starfield_stars:
        star["z"] -= 3.0
        if star["z"] <= 1.0:
            star["x"] = random.uniform(-100, 100)
            star["y"] = random.uniform(-100, 100)
            star["z"] = 200.0
            
        f_scale = 75.0
        px = (star["x"] / star["z"]) * f_scale + 120.0
        py = (star["y"] / star["z"]) * f_scale + 120.0
        
        dist = math.hypot(px - 120.0, py - 120.0)
        if dist < 70.0:
            brightness = int(255 * (1.0 - star["z"] / 200.0))
            r = 1 if star["z"] > 100 else (2 if star["z"] > 40 else 3)
            d.ellipse([px - r, py - r, px + r, py + r], fill=(0, brightness, int(brightness * 0.4)))
            
    img.paste(overlay, (0, 0), mask)
    return img


def _render_oscilloscope_frame(bezel, mask, now):
    from PIL import Image, ImageDraw
    img = bezel.copy()
    overlay = Image.new("RGB", (240, 240), (0, 10, 5))
    d = ImageDraw.Draw(overlay)
    
    min_x, max_x = 70, 170
    d.line([(min_x, 120), (max_x, 120)], fill=(0, 60, 20), width=1)
    
    pts = []
    pts_bg1 = []
    pts_bg2 = []
    
    for x in range(min_x, max_x + 1):
        t = (x - min_x) * 0.08
        y = 120.0 + 22.0 * math.sin(t + now * 6.0) * math.cos(now * 1.5)
        y += 4.0 * math.sin(t * 5.0 - now * 12.0)
        pts.append((x, int(y)))
        
        y_bg1 = 120.0 + 15.0 * math.sin(t * 1.5 - now * 3.0)
        pts_bg1.append((x, int(y_bg1)))
        
        y_bg2 = 120.0 + 10.0 * math.cos(t * 2.5 + now * 4.5)
        pts_bg2.append((x, int(y_bg2)))
        
    d.line(pts_bg1, fill=(0, 70, 25), width=1)
    d.line(pts_bg2, fill=(0, 60, 20), width=1)
    d.line(pts, fill=(0, 240, 90), width=2)
    
    for tick_x in range(min_x + 10, max_x, 20):
        d.line([(tick_x, 117), (tick_x, 123)], fill=(0, 100, 35), width=1)
        
    img.paste(overlay, (0, 0), mask)
    return img


def _render_game_of_life_frame(bezel, mask, now):
    global _gol_grid, _gol_last_grids
    if _gol_grid is None:
        _init_game_of_life()
        
    frame_step = int(now * 8)
    if not hasattr(_render_game_of_life_frame, "last_step"):
        _render_game_of_life_frame.last_step = 0
        
    if frame_step != _render_game_of_life_frame.last_step:
        _render_game_of_life_frame.last_step = frame_step
        
        next_grid = [[0 for _ in range(20)] for _ in range(20)]
        for r in range(20):
            for c in range(20):
                neighbors = 0
                for dr in (-1, 0, 1):
                    for dc in (-1, 0, 1):
                        if dr == 0 and dc == 0:
                            continue
                        nr, nc = (r + dr) % 20, (c + dc) % 20
                        neighbors += _gol_grid[nr][nc]
                        
                if _gol_grid[r][c] == 1:
                    next_grid[r][c] = 1 if neighbors in (2, 3) else 0
                else:
                    next_grid[r][c] = 1 if neighbors == 3 else 0
                    
        grid_flat = [cell for row in next_grid for cell in row]
        if sum(grid_flat) < 5 or next_grid in _gol_last_grids:
            _init_game_of_life()
        else:
            _gol_last_grids.append(_gol_grid)
            if len(_gol_last_grids) > 6:
                _gol_last_grids.pop(0)
            _gol_grid = next_grid

    from PIL import Image, ImageDraw
    img = bezel.copy()
    overlay = Image.new("RGB", (240, 240), (0, 8, 3))
    d = ImageDraw.Draw(overlay)
    
    for r in range(20):
        for c in range(20):
            if _gol_grid[r][c] == 1:
                cx = 70 + c * 5
                cy = 70 + r * 5
                d.rectangle([cx, cy, cx + 4, cy + 4], fill=(0, 220, 70))
                
    d.rectangle([70, 70, 170, 170], outline=(0, 80, 30), width=1)
    img.paste(overlay, (0, 0), mask)
    return img


def _render_radar_frame(bezel, mask, now):
    global _radar_blips
    if not _radar_blips:
        _init_radar()
        
    from PIL import Image, ImageDraw
    img = bezel.copy()
    overlay = Image.new("RGB", (240, 240), (0, 12, 4))
    d = ImageDraw.Draw(overlay)
    
    sweep_angle = (now * 2.2) % (2 * math.pi)
    
    for r in (15, 30, 45):
        d.ellipse([120 - r, 120 - r, 120 + r, 120 + r], outline=(0, 80, 25), width=1)
        
    d.line([(120 - 48, 120), (120 + 48, 120)], fill=(0, 60, 20), width=1)
    d.line([(120, 120 - 48), (120, 120 + 48)], fill=(0, 60, 20), width=1)
    
    for blip in _radar_blips:
        angle_diff = (sweep_angle - blip["angle"]) % (2 * math.pi)
        if angle_diff < 0.08:
            blip["intensity"] = 1.0
        else:
            blip["intensity"] = max(0.0, blip["intensity"] - 0.015)
            
        if blip["intensity"] > 0.01:
            bx = 120 + blip["dist"] * math.cos(blip["angle"])
            by = 120 + blip["dist"] * math.sin(blip["angle"])
            color_val = int(255 * blip["intensity"])
            
            if blip["type"] == "cross":
                d.line([(bx - 3, by), (bx + 3, by)], fill=(0, color_val, int(color_val * 0.3)), width=1)
                d.line([(bx, by - 3), (bx, by + 3)], fill=(0, color_val, int(color_val * 0.3)), width=1)
            else:
                d.ellipse([bx - 2, by - 2, bx + 2, by + 2], fill=(0, color_val, int(color_val * 0.4)))
                
        if random.random() < 0.002:
            blip["angle"] = random.uniform(0, 2 * math.pi)
            blip["dist"] = random.uniform(15, 48)
            blip["intensity"] = 0.0
            
    for trail in range(8):
        alpha_factor = (8 - trail) / 8.0
        sa = sweep_angle - trail * 0.04
        sx = 120 + 48 * math.cos(sa)
        sy = 120 + 48 * math.sin(sa)
        color = (0, int(220 * alpha_factor), int(80 * alpha_factor))
        d.line([(120, 120), (sx, sy)], fill=color, width=1 if trail > 0 else 2)
        
    img.paste(overlay, (0, 0), mask)
    return img


def _render_pong_frame(bezel, mask, now):
    global _pong_ball_x, _pong_ball_y, _pong_ball_dx, _pong_ball_dy
    global _pong_paddle_l_y, _pong_paddle_r_y, _pong_score_l, _pong_score_r
    
    # Bounding box inside the 73-radius circular pupil area (100x100 square)
    min_x, max_x = 70, 170
    min_y, max_y = 70, 170
    
    # Move ball
    _pong_ball_x += _pong_ball_dx
    _pong_ball_y += _pong_ball_dy
    
    # Ball vertical bounce (top/bottom walls)
    if _pong_ball_y <= min_y + 3:
        _pong_ball_y = min_y + 3
        _pong_ball_dy = -_pong_ball_dy
    elif _pong_ball_y >= max_y - 3:
        _pong_ball_y = max_y - 3
        _pong_ball_dy = -_pong_ball_dy
        
    # AI Paddle movement (chase ball Y with speed limit)
    # Left Paddle
    paddle_speed = 1.8
    if _pong_paddle_l_y < _pong_ball_y:
        _pong_paddle_l_y = min(max_y - 12, _pong_paddle_l_y + paddle_speed)
    elif _pong_paddle_l_y > _pong_ball_y:
        _pong_paddle_l_y = max(min_y + 12, _pong_paddle_l_y - paddle_speed)
        
    # Right Paddle (make it slightly imperfect to allow scoring/dynamic games)
    if _pong_paddle_r_y < _pong_ball_y:
        _pong_paddle_r_y = min(max_y - 12, _pong_paddle_r_y + paddle_speed)
    elif _pong_paddle_r_y > _pong_ball_y:
        _pong_paddle_r_y = max(min_y + 12, _pong_paddle_r_y - paddle_speed)
        
    # Check left paddle bounce
    # Left paddle is at X = 78, width = 2, height = 24
    if _pong_ball_x <= 81:
        if _pong_paddle_l_y - 14 <= _pong_ball_y <= _pong_paddle_l_y + 14:
            _pong_ball_x = 81
            _pong_ball_dx = -_pong_ball_dx
            # Adjust bounce angle depending on hit location
            offset = (_pong_ball_y - _pong_paddle_l_y) / 14.0
            _pong_ball_dy = offset * 2.0 + random.uniform(-0.2, 0.2)
        elif _pong_ball_x < min_x:
            # Score for Right
            _pong_score_r += 1
            # Reset ball
            _pong_ball_x = 120.0
            _pong_ball_y = 120.0
            _pong_ball_dx = 2.0 if random.choice([True, False]) else -2.0
            _pong_ball_dy = random.uniform(-1.0, 1.0)
            
    # Check right paddle bounce
    # Right paddle is at X = 160, width = 2, height = 24
    elif _pong_ball_x >= 159:
        if _pong_paddle_r_y - 14 <= _pong_ball_y <= _pong_paddle_r_y + 14:
            _pong_ball_x = 159
            _pong_ball_dx = -_pong_ball_dx
            offset = (_pong_ball_y - _pong_paddle_r_y) / 14.0
            _pong_ball_dy = offset * 2.0 + random.uniform(-0.2, 0.2)
        elif _pong_ball_x > max_x:
            # Score for Left
            _pong_score_l += 1
            # Reset ball
            _pong_ball_x = 120.0
            _pong_ball_y = 120.0
            _pong_ball_dx = -2.0 if random.choice([True, False]) else 2.0
            _pong_ball_dy = random.uniform(-1.0, 1.0)

    # Render image
    from PIL import Image, ImageDraw, ImageFont
    img = bezel.copy()
    overlay = Image.new("RGB", (240, 240), (0, 10, 5))  # deep tactical green background
    d = ImageDraw.Draw(overlay)
    
    # Draw field boundary box
    d.rectangle([min_x, min_y, max_x, max_y], outline=(0, 120, 40), width=1)
    
    # Draw center line (dotted)
    for y_coord in range(min_y + 4, max_y, 8):
        d.line([(120, y_coord), (120, y_coord + 4)], fill=(0, 120, 40), width=1)
        
    # Draw scores - offset them inside the box!
    # Bounding box is [70, 170]. Let's draw scores at Y = 80!
    try:
        font = ImageFont.load_default()
        d.text((105, 80), str(_pong_score_l), fill=(0, 200, 70), font=font)
        d.text((128, 80), str(_pong_score_r), fill=(0, 200, 70), font=font)
    except Exception:
        pass
        
    # Draw paddles
    d.rectangle([78, _pong_paddle_l_y - 12, 80, _pong_paddle_l_y + 12], fill=(0, 230, 80))
    d.rectangle([160, _pong_paddle_r_y - 12, 162, _pong_paddle_r_y + 12], fill=(0, 230, 80))
    
    # Draw ball (circle size 6)
    d.ellipse([_pong_ball_x - 3, _pong_ball_y - 3, _pong_ball_x + 3, _pong_ball_y + 3], fill=(0, 255, 100))
    
    # Paste overlay inside the pupil area
    img.paste(overlay, (0, 0), mask)
    return img


def _loop():
    global _rolling_die, _showing_omnissiah_glyph, _showing_custom_image, _custom_image, _custom_image_expiry
    global _last_activity_time, _active_idle_anim, _custom_idle_expiry
    bezel = _make_bezel()
    mask = _make_iris_mask()
    shown = -1.0          # last amplitude actually drawn
    angle = 0.0           # current cog rotation (degrees), advanced while thinking
    t0 = time.monotonic()
    _last_activity_time = t0
    last = t0
    next_blink = t0 + random.uniform(*_BLINK_GAP)  # when the next blink starts
    blink_t0 = None       # start time of the in-progress blink, else None
    while not _stop.is_set():
        now = time.monotonic()
        dt, last = now - last, now

        # Update last activity time if active
        is_active = (
            _showing_omnissiah_glyph
            or _rolling_die
            or _scanning_auspex
            or _scanning_noosphere
            or _targeting
            or _visualizing_music
            or _showing_custom_image
            or _speaking
            or _thinking
        )
        if is_active:
            _last_activity_time = now
            _active_idle_anim = None
        else:
            # If idle and timeout reached or forced, run screensaver animation
            if (now - _last_activity_time >= config.DISPLAY_IDLE_TIMEOUT) or (now < _custom_idle_expiry):
                if _active_idle_anim is None:
                    _active_idle_anim = random.choice(_screensaver_anims)
                    if _active_idle_anim == "pong":
                        global _pong_ball_x, _pong_ball_y, _pong_ball_dx, _pong_ball_dy
                        global _pong_score_l, _pong_score_r
                        _pong_ball_x = 120.0
                        _pong_ball_y = 120.0
                        _pong_ball_dx = 2.0 if random.choice([True, False]) else -2.0
                        _pong_ball_dy = random.uniform(-1.0, 1.0)
                        _pong_score_l = 0
                        _pong_score_r = 0
                    elif _active_idle_anim == "canticle_rain":
                        _init_canticle_rain()
                    elif _active_idle_anim == "starfield":
                        _init_starfield()
                    elif _active_idle_anim == "game_of_life":
                        _init_game_of_life()
                    elif _active_idle_anim == "radar":
                        _init_radar()

                try:
                    if _active_idle_anim == "pong":
                        _blit(_render_pong_frame(bezel, mask, now))
                    elif _active_idle_anim == "canticle_rain":
                        _blit(_render_canticle_rain_frame(bezel, mask, now))
                    elif _active_idle_anim == "starfield":
                        _blit(_render_starfield_frame(bezel, mask, now))
                    elif _active_idle_anim == "oscilloscope":
                        _blit(_render_oscilloscope_frame(bezel, mask, now))
                    elif _active_idle_anim == "game_of_life":
                        _blit(_render_game_of_life_frame(bezel, mask, now))
                    elif _active_idle_anim == "radar":
                        _blit(_render_radar_frame(bezel, mask, now))
                except Exception as e:
                    print(f"[display] screensaver render error ({_active_idle_anim}): {e}")
                time.sleep(1 / 30)
                continue
        if _showing_omnissiah_glyph:
            glyph_elapsed = now - _omnissiah_start_time
            if glyph_elapsed >= _omnissiah_duration:
                _showing_omnissiah_glyph = False
            else:
                try:
                    _blit(_render_omnissiah_frame(bezel, mask, now))
                except Exception as e:
                    print(f"[display] omnissiah render error: {e}")
                time.sleep(1 / 30)
                continue

        if _rolling_die:
            roll_elapsed = now - _die_start_time
            if roll_elapsed >= 3.5:
                _rolling_die = False
            else:
                try:
                    _blit(_render_die_frame(bezel, mask, roll_elapsed, _die_result))
                except Exception as e:
                    print(f"[display] die render error: {e}")
                time.sleep(1 / 30)
                continue

        if _scanning_auspex:
            try:
                _blit(_render_auspex_frame(bezel, mask, now))
            except Exception as e:
                print(f"[display] auspex render error: {e}")
            time.sleep(1 / 30)
            continue

        if _scanning_noosphere:
            try:
                _blit(_render_noosphere_frame(bezel, mask, now))
            except Exception as e:
                print(f"[display] noosphere render error: {e}")
            time.sleep(1 / 30)
            continue

        if _targeting:
            try:
                _blit(_render_targeting_frame(bezel, mask, now))
            except Exception as e:
                print(f"[display] targeting render error: {e}")
            time.sleep(1 / 30)
            continue

        if _visualizing_music and not _speaking and not _thinking:
            try:
                _blit(_render_music_frame(bezel, mask, now))
            except Exception as e:
                print(f"[display] music render error: {e}")
            time.sleep(1 / 30)
            continue

        if _showing_custom_image:
            if now >= _custom_image_expiry:
                _showing_custom_image = False
                _custom_image = None
            else:
                try:
                    _blit(_custom_image)
                except Exception as e:
                    print(f"[display] custom image render error: {e}")
                time.sleep(1 / 30)
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
        # Blink every few seconds: a quick close-and-open easing 0->1->0.
        if blink_t0 is None and now >= next_blink:
            blink_t0 = now
        blink = 0.0
        if blink_t0 is not None:
            p = (now - blink_t0) / _BLINK_DUR
            if p >= 1.0:
                blink_t0 = None
                next_blink = now + random.uniform(*_BLINK_GAP)
            else:
                blink = math.sin(math.pi * p)  # 0 at edges, fully closed mid-blink
        try:
            _blit(_render_frame(bezel, mask, max(0.0, min(1.0, shown)), angle, blink))
        except Exception as e:
            print(f"[display] render error: {e}")
            return
        time.sleep(1 / 30)


def start_die_roll(result: int | str) -> None:
    global _rolling_die, _die_start_time, _die_result
    if not _available:
        return
    _die_result = str(result)
    _die_start_time = time.monotonic()
    _rolling_die = True


def start_omnissiah_glyph(duration: float = 4.0) -> None:
    global _showing_omnissiah_glyph, _omnissiah_start_time, _omnissiah_duration
    if not _available:
        return
    _omnissiah_duration = duration
    _omnissiah_start_time = time.monotonic()
    _showing_omnissiah_glyph = True


def display_pil_image(pil_img, duration: float = 10.0) -> None:
    global _showing_custom_image, _custom_image, _custom_image_expiry
    if not _available:
        return
    try:
        from PIL import Image
        w, h = pil_img.size
        min_side = min(w, h)
        left = (w - min_side) // 2
        top = (h - min_side) // 2
        right = left + min_side
        bottom = top + min_side
        cropped = pil_img.crop((left, top, right, bottom))
        resized = cropped.resize((240, 240), resample=Image.BICUBIC)
        
        _custom_image = resized
        _custom_image_expiry = time.monotonic() + duration
        _showing_custom_image = True
    except Exception as e:
        print(f"[display] display_pil_image error: {e}")


def trigger_idle_animation(duration: float = 60.0) -> None:
    global _custom_idle_expiry, _last_activity_time
    if not _available:
        return
    _custom_idle_expiry = time.monotonic() + duration


# ── public API (mirrors eyes.py) ─────────────────────────────────────────────────

def setup() -> None:
    """Initialise the panel and start the render thread. No-op if disabled or
    the hardware/libraries are unavailable."""
    global _available, _spi, _render_thread
    if not config.DISPLAY_ENABLED:
        return
    if _GPIO is None:
        print("[display] DISPLAY_ENABLED but spidev/RPi.GPIO/Pillow unavailable — skipping.")
        return
    try:
        _GPIO.setmode(_GPIO.BCM)  # eyes.py already sets BCM; harmless to repeat
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

        _stop.clear()
        _render_thread = threading.Thread(target=_loop, daemon=True)
        _render_thread.start()
        print("[display] GC9A01 online — the machine spirit observes.")
    except Exception as e:
        print(f"[display] init failed: {e}")
        _available = False


def set_amplitude(amp: float) -> None:
    """Feed a normalized speech amplitude (0..1); marks the eye as speaking."""
    global _target_amp, _speaking, _thinking
    if not _available:
        return
    _target_amp = max(0.0, min(1.0, amp))
    _speaking = True
    _thinking = False  # speech has begun; stop spinning the cog


def set_mood(mood: str) -> None:
    """Tint the iris to match Omega-7's current disposition (see skull/mood.py)."""
    global _mood_rgb
    if not _available:
        return
    _mood_rgb = _MOOD_COLOURS.get((mood or "").upper(), (255, 40, 30))


def think(active: bool = True) -> None:
    """Spin the cog wheel while Omega-7 is cogitating (the silent gap between
    hearing a command and beginning to speak). The iris keeps its idle breathing
    pulse underneath. Call think(False) — or any speaking/idle entry point — to
    stop the spin."""
    global _thinking
    if not _available:
        return
    _thinking = active


def on() -> None:
    """Full-intensity steady gaze (e.g. while attending a command)."""
    global _target_amp, _speaking, _thinking
    if not _available:
        return
    _target_amp = 1.0
    _speaking = True
    _thinking = False


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


def stop_auspex_scan() -> None:
    global _scanning_auspex
    _scanning_auspex = False


def start_noosphere_scan() -> None:
    global _scanning_noosphere
    _scanning_noosphere = True


def stop_noosphere_scan() -> None:
    global _scanning_noosphere
    _scanning_noosphere = False


def set_targeting(active: bool) -> None:
    global _targeting
    _targeting = active


def set_music_playing(active: bool) -> None:
    global _visualizing_music
    _visualizing_music = active


def cleanup() -> None:
    global _available
    _stop.set()
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
