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

_state_lock = threading.Lock()
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
_requested_idle_anim = None

# Screensaver pools
_screensaver_anims = [
    "pong", "canticle_rain", "starfield", "oscilloscope", "game_of_life", "radar",
    "warp_core", "circuit_maze", "double_helix", "spinning_rings", "wireframe_cube",
    "bouncing_cog", "fractal_tree", "hud_status", "orbitals", "spectrum_bars"
]

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

# Circuit Maze state
_maze_grid = []
_maze_last_flip = 0.0

# Bouncing Cog state
_bc_x = 120.0
_bc_y = 120.0
_bc_dx = 1.8
_bc_dy = 1.3
_bc_angle = 0.0

# Orbitals state
_orbital_particles = []

# Spectrum Bars state
_spectrum_heights = [0.0] * 8
_spectrum_targets = [0.0] * 8
_spectrum_last_update = 0.0



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


def _render_frame(bezel, mask, amp: float, angle: float = 0.0, blink: float = 0.0, look_x: float = 0.0, look_y: float = 0.0):
    """Compose one iris frame for normalized amplitude `amp` (0..1). The iris is
    drawn on its own layer and pasted through `mask` so it stays in the aperture.

    `angle` (degrees) rotates the cog about its centre — used to spin the gear
    while Omega-7 is thinking. The cog fits inside the panel's inscribed circle
    (tip radius 117 < 120), so rotation never clips it; the iris is a centred
    disc and so is unaffected.

    `blink` (0=open..1=fully closed) squashes the iris vertically about its
    centre into a slit, so the eye reads as blinking.
    
    `look_x` and `look_y` shift the iris center to simulate looking around.
    """
    # rotate() returns a fresh image we can draw on; otherwise copy the shared bezel.
    img = bezel.rotate(angle, resample=Image.BICUBIC) if angle else bezel.copy()
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
    overlay = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(overlay)
    
    age = now - _omnissiah_start_time
    
    # ── 2. Adeptus Mechanicus Skull-Cog (Scaled to Full-Screen 240x240) ──
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


# ── render loop ────────────────────────────────────────────────────────────────────
def _init_circuit_maze():
    global _maze_grid, _maze_last_flip
    _maze_grid = [[random.choice([0, 1]) for _ in range(24)] for _ in range(24)]
    _maze_last_flip = 0.0


def _init_bouncing_cog():
    global _bc_x, _bc_y, _bc_dx, _bc_dy, _bc_angle
    _bc_x = 120.0
    _bc_y = 120.0
    _bc_dx = random.choice([-1.8, 1.8])
    _bc_dy = random.uniform(-1.5, 1.5)
    _bc_angle = 0.0


def _init_orbitals():
    global _orbital_particles
    _orbital_particles = []
    for i in range(3):
        _orbital_particles.append({
            "speed": random.uniform(1.5, 3.5),
            "radius_x": random.uniform(20, 45),
            "radius_y": random.uniform(10, 25),
            "rot": random.uniform(0, math.pi * 2)
        })


def _init_spectrum_bars():
    global _spectrum_heights, _spectrum_targets, _spectrum_last_update
    _spectrum_heights = [random.uniform(5, 160) for _ in range(12)]
    _spectrum_targets = [random.uniform(5, 160) for _ in range(12)]
    _spectrum_last_update = 0.0


def _init_canticle_rain():
    global _rain_cols
    _rain_cols = []
    for x in range(8, 233, 12):
        _rain_cols.append({
            "x": x,
            "y": random.uniform(-100, 240),
            "speed": random.uniform(2.0, 5.0),
            "chars": [random.choice(["0", "1"]) for _ in range(12)]
        })


def _init_starfield():
    global _starfield_stars
    _starfield_stars = []
    for _ in range(60):
        _starfield_stars.append({
            "x": random.uniform(-120, 120),
            "y": random.uniform(-120, 120),
            "z": random.uniform(1.0, 120.0),
            "speed": random.uniform(1.5, 3.5)
        })


def _init_game_of_life():
    global _gol_grid, _gol_last_grids
    _gol_grid = [[random.choice([0, 1]) for _ in range(24)] for _ in range(24)]
    _gol_last_grids = []


def _init_radar():
    global _radar_blips
    _radar_blips = []
    for _ in range(4):
        dist = random.uniform(30, 105)
        angle = random.uniform(0, math.pi * 2)
        _radar_blips.append({
            "x": 120.0 + dist * math.cos(angle),
            "y": 120.0 + dist * math.sin(angle),
            "brightness": 0.0,
            "angle": angle
        })


def _render_pong_frame(bezel, mask, now):
    global _pong_ball_x, _pong_ball_y, _pong_ball_dx, _pong_ball_dy
    global _pong_paddle_l_y, _pong_paddle_r_y, _pong_score_l, _pong_score_r
    min_x, max_x = 10, 230
    min_y, max_y = 10, 230
    
    _pong_ball_x += _pong_ball_dx
    _pong_ball_y += _pong_ball_dy
    
    if _pong_ball_y <= min_y + 3:
        _pong_ball_y = min_y + 3
        _pong_ball_dy = -_pong_ball_dy
    elif _pong_ball_y >= max_y - 3:
        _pong_ball_y = max_y - 3
        _pong_ball_dy = -_pong_ball_dy
        
    l_target = _pong_ball_y
    _pong_paddle_l_y += (l_target - _pong_paddle_l_y) * 0.12
    _pong_paddle_l_y = max(min_y + 15, min(max_y - 15, _pong_paddle_l_y))
    
    r_target = _pong_ball_y
    _pong_paddle_r_y += (r_target - _pong_paddle_r_y) * 0.12
    _pong_paddle_r_y = max(min_y + 15, min(max_y - 15, _pong_paddle_r_y))
    
    if _pong_ball_dx < 0 and _pong_ball_x <= min_x + 8:
        if abs(_pong_ball_y - _pong_paddle_l_y) <= 18:
            _pong_ball_x = min_x + 8
            _pong_ball_dx = -_pong_ball_dx
            _pong_ball_dy += (_pong_ball_y - _pong_paddle_l_y) * 0.15
        else:
            _pong_score_r += 1
            _pong_ball_x, _pong_ball_y = 120.0, 120.0
            _pong_ball_dx = 2.0
            _pong_ball_dy = random.uniform(-1.0, 1.0)
    elif _pong_ball_dx > 0 and _pong_ball_x >= max_x - 8:
        if abs(_pong_ball_y - _pong_paddle_r_y) <= 18:
            _pong_ball_x = max_x - 8
            _pong_ball_dx = -_pong_ball_dx
            _pong_ball_dy += (_pong_ball_y - _pong_paddle_r_y) * 0.15
        else:
            _pong_score_l += 1
            _pong_ball_x, _pong_ball_y = 120.0, 120.0
            _pong_ball_dx = -2.0
            _pong_ball_dy = random.uniform(-1.0, 1.0)
            
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (240, 240), (0, 10, 5))
    d = ImageDraw.Draw(img)
    
    for y in range(min_y, max_y, 10):
        d.line([(120, y), (120, y + 5)], fill=(0, 100, 40), width=1)
        
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None
    if font:
        d.text((95, 20), str(_pong_score_l), fill=(0, 200, 70), font=font)
        d.text((135, 20), str(_pong_score_r), fill=(0, 200, 70), font=font)
        
    d.rectangle([min_x, _pong_paddle_l_y - 15, min_x + 3, _pong_paddle_l_y + 15], fill=(0, 220, 80))
    d.rectangle([max_x - 3, _pong_paddle_r_y - 15, max_x, _pong_paddle_r_y + 15], fill=(0, 220, 80))
    d.ellipse([_pong_ball_x - 3, _pong_ball_y - 3, _pong_ball_x + 3, _pong_ball_y + 3], fill=(0, 255, 100))
    return img


def _render_canticle_rain_frame(bezel, mask, now):
    global _rain_cols
    if not _rain_cols:
        _init_canticle_rain()
        
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (240, 240), (0, 8, 3))
    d = ImageDraw.Draw(img)
    
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None
        
    for col in _rain_cols:
        col["y"] += col["speed"]
        if col["y"] > 240:
            col["y"] = -100
            col["speed"] = random.uniform(2.0, 5.0)
            
        y = col["y"]
        for idx, char in enumerate(col["chars"]):
            cy = y + idx * 10
            if -10 < cy < 250:
                alpha = int(255 * ((idx + 1) / len(col["chars"])))
                color = (0, alpha, int(alpha * 0.3))
                if font:
                    d.text((col["x"], cy), char, fill=color, font=font)
                else:
                    d.rectangle([col["x"], cy, col["x"] + 5, cy + 5], fill=color)
                    
            if random.random() < 0.05:
                col["chars"][idx] = random.choice(["0", "1"])
                
    return img


def _render_starfield_frame(bezel, mask, now):
    global _starfield_stars
    if not _starfield_stars:
        _init_starfield()
        
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (240, 240), (0, 5, 2))
    d = ImageDraw.Draw(img)
    
    for star in _starfield_stars:
        star["z"] -= star["speed"]
        if star["z"] <= 1.0:
            star["x"] = random.uniform(-120, 120)
            star["y"] = random.uniform(-120, 120)
            star["z"] = 120.0
            
        k = 100.0 / star["z"]
        px = int(120.0 + star["x"] * k)
        py = int(120.0 + star["y"] * k)
        
        if 0 <= px < 240 and 0 <= py < 240:
            size = max(1, int(3 * (1.0 - star["z"] / 120.0)))
            brightness = int(255 * (1.0 - star["z"] / 120.0))
            d.ellipse([px - size, py - size, px + size, py + size], fill=(0, brightness, int(brightness * 0.4)))
            
    return img


def _render_oscilloscope_frame(bezel, mask, now):
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (240, 240), (0, 10, 4))
    d = ImageDraw.Draw(img)
    
    for x in range(20, 240, 40):
        d.line([(x, 0), (x, 240)], fill=(0, 25, 10), width=1)
    for y in range(20, 240, 40):
        d.line([(0, y), (240, y)], fill=(0, 25, 10), width=1)
        
    pts1 = []
    pts2 = []
    for x in range(0, 241, 4):
        y1 = 120.0 + 35.0 * math.sin(x * 0.05 + now * 5.0) + 10.0 * math.sin(x * 0.12 - now * 2.0)
        y2 = 120.0 + 20.0 * math.cos(x * 0.08 - now * 4.0) + 8.0 * math.sin(x * 0.03 + now * 3.0)
        pts1.append((x, y1))
        pts2.append((x, y2))
        
    d.line(pts1, fill=(0, 180, 50), width=2)
    d.line(pts2, fill=(0, 240, 100), width=1)
    return img


def _render_game_of_life_frame(bezel, mask, now):
    global _gol_grid, _gol_last_grids
    if _gol_grid is None:
        _init_game_of_life()
        
    if not hasattr(_render_game_of_life_frame, "last_step"):
        _render_game_of_life_frame.last_step = 0.0
        
    if now - _render_game_of_life_frame.last_step > 0.1:
        _render_game_of_life_frame.last_step = now
        
        grid_tuple = tuple(tuple(row) for row in _gol_grid)
        _gol_last_grids.append(grid_tuple)
        if len(_gol_last_grids) > 6:
            _gol_last_grids.pop(0)
            
        is_static = len(_gol_last_grids) >= 6 and (
            _gol_last_grids[-1] == _gol_last_grids[-2] or
            _gol_last_grids[-1] == _gol_last_grids[-3] or
            _gol_last_grids[-1] == _gol_last_grids[-4]
        )
        total_cells = sum(sum(row) for row in _gol_grid)
        if total_cells < 5 or is_static:
            _init_game_of_life()
            
        new_grid = [[0 for _ in range(24)] for _ in range(24)]
        for r in range(24):
            for c in range(24):
                neighbors = 0
                for dr in [-1, 0, 1]:
                    for dc in [-1, 0, 1]:
                        if dr == 0 and dc == 0:
                            continue
                        nr, nc = (r + dr) % 24, (c + dc) % 24
                        neighbors += _gol_grid[nr][nc]
                if _gol_grid[r][c] == 1:
                    new_grid[r][c] = 1 if neighbors in [2, 3] else 0
                else:
                    new_grid[r][c] = 1 if neighbors == 3 else 0
        _gol_grid = new_grid
        
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (240, 240), (0, 8, 3))
    d = ImageDraw.Draw(img)
    
    for r in range(24):
        for c in range(24):
            if _gol_grid[r][c] == 1:
                d.rectangle([c * 10 + 1, r * 10 + 1, c * 10 + 9, r * 10 + 9], fill=(0, 220, 80))
            else:
                d.rectangle([c * 10, r * 10, c * 10 + 10, r * 10 + 10], outline=(0, 20, 5), width=1)
                
    return img


def _render_radar_frame(bezel, mask, now):
    global _radar_blips
    if not _radar_blips:
        _init_radar()
        
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (240, 240), (0, 10, 4))
    d = ImageDraw.Draw(img)
    
    sweep_angle = (now * 150.0) % 360.0
    sweep_rad = math.radians(sweep_angle)
    
    for r in range(30, 120, 30):
        d.ellipse([120 - r, 120 - r, 120 + r, 120 + r], outline=(0, 45, 15), width=1)
        
    d.line([(10, 120), (230, 120)], fill=(0, 45, 15), width=1)
    d.line([(120, 10), (120, 230)], fill=(0, 45, 15), width=1)
    
    sx = 120.0 + 110.0 * math.cos(sweep_rad)
    sy = 120.0 + 110.0 * math.sin(sweep_rad)
    d.line([(120, 120), (sx, sy)], fill=(0, 255, 100), width=2)
    
    for step in range(1, 15):
        a_trail = math.radians(sweep_angle - step * 2)
        tx = 120.0 + 110.0 * math.cos(a_trail)
        ty = 120.0 + 110.0 * math.sin(a_trail)
        val = int(200 * (1.0 - step / 15.0))
        d.line([(120, 120), (tx, ty)], fill=(0, val, int(val * 0.3)), width=1)
        
    for blip in _radar_blips:
        diff = abs(sweep_rad - blip["angle"]) % (math.pi * 2)
        if diff < 0.05:
            blip["brightness"] = 255.0
        else:
            blip["brightness"] = max(0.0, blip["brightness"] - 2.5)
            
        if blip["brightness"] > 0:
            val = int(blip["brightness"])
            d.ellipse([blip["x"] - 4, blip["y"] - 4, blip["x"] + 4, blip["y"] + 4], fill=(0, val, int(val * 0.4)))
            d.ellipse([blip["x"] - 7, blip["y"] - 7, blip["x"] + 7, blip["y"] + 7], outline=(0, int(val * 0.6), 0), width=1)
            
    return img


def _render_warp_core_frame(bezel, mask, now):
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (240, 240), (0, 10, 5))
    d = ImageDraw.Draw(img)
    
    core_r = 15.0 + 4.0 * math.sin(now * 8.0)
    d.ellipse([120 - core_r, 120 - core_r, 120 + core_r, 120 + core_r], fill=(0, 255, 120))
    d.ellipse([120 - core_r + 4, 120 - core_r + 4, 120 + core_r - 4, 120 + core_r - 4], fill=(150, 255, 200))
    
    for i in range(5):
        t = (now * 45.0 + i * 25.0) % 110.0
        r = core_r + t
        if r < 115.0:
            alpha = int(255 * (1.0 - r / 115.0))
            d.ellipse([120 - r, 120 - r, 120 + r, 120 + r], outline=(0, alpha, int(alpha * 0.4)), width=1)
            
    return img


def _render_circuit_maze_frame(bezel, mask, now):
    global _maze_grid, _maze_last_flip
    if not _maze_grid or len(_maze_grid) != 24:
        _init_circuit_maze()
        
    if now - _maze_last_flip > 0.2:
        _maze_last_flip = now
        for _ in range(2):
            r = random.randint(0, 23)
            c = random.randint(0, 23)
            _maze_grid[r][c] = 1 - _maze_grid[r][c]
        
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (240, 240), (0, 10, 4))
    d = ImageDraw.Draw(img)
    
    for r in range(24):
        for c in range(24):
            x1 = c * 10
            y1 = r * 10
            x2 = x1 + 10
            y2 = y1 + 10
            if _maze_grid[r][c] == 0:
                d.line([(x1, y1), (x2, y2)], fill=(0, 180, 60), width=1)
            else:
                d.line([(x2, y1), (x1, y2)], fill=(0, 180, 60), width=1)
                
    return img


def _render_double_helix_frame(bezel, mask, now):
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (240, 240), (0, 8, 3))
    d = ImageDraw.Draw(img)
    
    min_y, max_y = 10, 230
    helix_w = 45.0
    
    for y in range(min_y, max_y + 1, 6):
        phase = (y * 0.08) - (now * 4.0)
        x_offset1 = helix_w * math.sin(phase)
        x_offset2 = helix_w * math.sin(phase + math.pi)
        
        x1 = 120 + x_offset1
        x2 = 120 + x_offset2
        
        z1 = math.cos(phase)
        z2 = math.cos(phase + math.pi)
        
        d.line([(x1, y), (x2, y)], fill=(0, 80, 30), width=1)
        
        b1 = int(140 + 115 * z1)
        b2 = int(140 + 115 * z2)
        
        d.ellipse([x1 - 3, y - 3, x1 + 3, y + 3], fill=(0, b1, int(b1 * 0.4)))
        d.ellipse([x2 - 3, y - 3, x2 + 3, y + 3], fill=(0, b2, int(b2 * 0.4)))
        
    return img


def _render_spinning_rings_frame(bezel, mask, now):
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (240, 240), (0, 10, 4))
    d = ImageDraw.Draw(img)
    
    angle_offset = now * 120.0
    d.arc([10, 10, 230, 230], start=angle_offset, end=angle_offset + 140, fill=(0, 200, 70), width=2)
    d.arc([10, 10, 230, 230], start=angle_offset + 180, end=angle_offset + 320, fill=(0, 200, 70), width=2)
    
    angle_offset_mid1 = -now * 150.0
    d.arc([40, 40, 200, 200], start=angle_offset_mid1, end=angle_offset_mid1 + 200, fill=(0, 160, 50), width=1)
    d.arc([40, 40, 200, 200], start=angle_offset_mid1 + 240, end=angle_offset_mid1 + 330, fill=(0, 160, 50), width=1)
    
    angle_offset_mid2 = now * 220.0
    d.arc([70, 70, 170, 170], start=angle_offset_mid2, end=angle_offset_mid2 + 100, fill=(0, 180, 60), width=1)
    d.arc([70, 70, 170, 170], start=angle_offset_mid2 + 150, end=angle_offset_mid2 + 300, fill=(0, 180, 60), width=1)
    
    angle_offset_inner = -now * 300.0
    d.arc([100, 100, 140, 140], start=angle_offset_inner, end=angle_offset_inner + 120, fill=(0, 240, 80), width=2)
    d.arc([100, 100, 140, 140], start=angle_offset_inner + 180, end=angle_offset_inner + 300, fill=(0, 240, 80), width=2)
    
    d.ellipse([117, 117, 123, 123], fill=(0, 255, 100))
    return img


def _render_wireframe_cube_frame(bezel, mask, now):
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (240, 240), (0, 8, 3))
    d = ImageDraw.Draw(img)
    
    size = 55.0
    vertices = [
        [-size, -size, -size],
        [size, -size, -size],
        [size, size, -size],
        [-size, size, -size],
        [-size, -size, size],
        [size, -size, size],
        [size, size, size],
        [-size, size, size]
    ]
    
    edges = [
        (0, 1), (1, 2), (2, 3), (3, 0),
        (4, 5), (5, 6), (6, 7), (7, 4),
        (0, 4), (1, 5), (2, 6), (3, 7)
    ]
    
    rx = now * 1.0
    ry = now * 1.5
    rz = now * 0.7
    
    projected = []
    for vert in vertices:
        x, y, z = vert
        cos_y, sin_y = math.cos(ry), math.sin(ry)
        x, z = x * cos_y - z * sin_y, x * sin_y + z * cos_y
        cos_x, sin_x = math.cos(rx), math.sin(rx)
        y, z = y * cos_x - z * sin_x, y * sin_x + z * cos_x
        cos_z, sin_z = math.cos(rz), math.sin(rz)
        x, y = x * cos_z - y * sin_z, x * sin_z + y * cos_z
        
        px = x + 120.0
        py = y + 120.0
        projected.append((px, py))
        
    for edge in edges:
        p1 = projected[edge[0]]
        p2 = projected[edge[1]]
        d.line([p1, p2], fill=(0, 200, 70), width=2)
        
    for p in projected:
        d.ellipse([p[0] - 4, p[1] - 4, p[0] + 4, p[1] + 4], fill=(0, 255, 120))
        
    return img


def _render_bouncing_cog_frame(bezel, mask, now):
    global _bc_x, _bc_y, _bc_dx, _bc_dy, _bc_angle
    if not _bc_dx:
        _init_bouncing_cog()
        
    min_x, max_x = 10, 230
    min_y, max_y = 10, 230
    
    _bc_x += _bc_dx
    _bc_y += _bc_dy
    _bc_angle = (_bc_angle + 2.0) % 360
    
    r_cog = 25
    if _bc_x <= min_x + r_cog:
        _bc_x = min_x + r_cog
        _bc_dx = -_bc_dx
    elif _bc_x >= max_x - r_cog:
        _bc_x = max_x - r_cog
        _bc_dx = -_bc_dx
        
    if _bc_y <= min_y + r_cog:
        _bc_y = min_y + r_cog
        _bc_dy = -_bc_dy
    elif _bc_y >= max_y - r_cog:
        _bc_y = max_y - r_cog
        _bc_dy = -_bc_dy

    from PIL import Image, ImageDraw
    img = Image.new("RGB", (240, 240), (0, 10, 5))
    d = ImageDraw.Draw(img)
    
    d.rectangle([min_x, min_y, max_x, max_y], outline=(0, 45, 15), width=1)
    
    cx, cy = _bc_x, _bc_y
    num_teeth = 10
    teeth_r = r_cog + 6
    for i in range(num_teeth):
        a = math.radians(_bc_angle + i * (360 / num_teeth))
        tx = cx + teeth_r * math.cos(a)
        ty = cy + teeth_r * math.sin(a)
        d.line([(cx, cy), (tx, ty)], fill=(0, 220, 80), width=3)
        
    d.ellipse([cx - r_cog, cy - r_cog, cx + r_cog, cy + r_cog], fill=(0, 220, 80))
    d.ellipse([cx - r_cog + 8, cy - r_cog + 8, cx + r_cog - 8, cy + r_cog - 8], fill=(0, 10, 5))
    return img


def _render_fractal_tree_frame(bezel, mask, now):
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (240, 240), (0, 10, 4))
    d = ImageDraw.Draw(img)
    
    max_depth = 6
    branch_angle = 18.0 + 8.0 * math.sin(now * 2.0)
    
    def draw_branch(x1, y1, angle_deg, length, depth):
        if depth > max_depth:
            return
        rad = math.radians(angle_deg)
        x2 = x1 + length * math.cos(rad)
        y2 = y1 - length * math.sin(rad)
        
        green_val = int(255 - depth * 30)
        d.line([(x1, y1), (x2, y2)], fill=(0, green_val, 40), width=max(1, 6 - depth))
        
        next_len = length * 0.76
        draw_branch(x2, y2, angle_deg - branch_angle, next_len, depth + 1)
        draw_branch(x2, y2, angle_deg + branch_angle, next_len, depth + 1)
        
    draw_branch(120, 230, 90.0, 50.0, 1)
    return img


def _render_hud_status_frame(bezel, mask, now):
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (240, 240), (0, 10, 5))
    d = ImageDraw.Draw(img)
    
    d.rectangle([10, 10, 230, 230], outline=(0, 80, 30), width=2)
    
    import datetime
    t_str = datetime.datetime.now().strftime("%H:%M:%S")
    
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None
        
    if font:
        d.text((88, 30), t_str, fill=(0, 255, 100), font=font)
        d.text((35, 80), "CPU LOAD", fill=(0, 160, 50), font=font)
        d.text((35, 120), "MEM COG", fill=(0, 160, 50), font=font)
        d.text((35, 160), "VOX NET", fill=(0, 160, 50), font=font)
        
    cpu_w = 90.0 * (0.5 + 0.3 * math.sin(now * 3.0) + 0.2 * math.cos(now * 7.5))
    mem_w = 90.0 * (0.7 + 0.1 * math.sin(now * 0.5))
    vox_w = 90.0 * (0.4 + 0.4 * math.sin(now * 12.0) * math.sin(now * 1.5))
    
    d.rectangle([110, 82, 110 + int(cpu_w), 90], fill=(0, 220, 80))
    d.rectangle([110, 122, 110 + int(mem_w), 130], fill=(0, 220, 80))
    d.rectangle([110, 162, 110 + int(vox_w), 170], fill=(0, 220, 80))
    return img


def _render_orbitals_frame(bezel, mask, now):
    global _orbital_particles
    if not _orbital_particles:
        _init_orbitals()
        
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (240, 240), (0, 10, 4))
    d = ImageDraw.Draw(img)
    
    d.ellipse([115, 115, 125, 125], fill=(0, 255, 120))
    
    for blip in _orbital_particles:
        rx = blip["radius_x"] * 2.2
        ry = blip["radius_y"] * 2.2
        angle = now * blip["speed"]
        
        x_local = rx * math.cos(angle)
        y_local = ry * math.sin(angle)
        
        cos_r = math.cos(blip["rot"])
        sin_r = math.sin(blip["rot"])
        x_rot = x_local * cos_r - y_local * sin_r
        y_rot = x_local * sin_r + y_local * cos_r
        
        px = 120.0 + x_rot
        py = 120.0 + y_rot
        
        orbit_pts = []
        for a_step in range(0, 360, 10):
            rad = math.radians(a_step)
            xl = rx * math.cos(rad)
            yl = ry * math.sin(rad)
            xr = xl * cos_r - yl * sin_r + 120.0
            yr = xl * sin_r + yl * cos_r + 120.0
            orbit_pts.append((xr, yr))
        d.polygon(orbit_pts, outline=(0, 60, 20), width=1)
        
        d.ellipse([px - 4, py - 4, px + 4, py + 4], fill=(0, 240, 90))
        
    return img


def _render_spectrum_bars_frame(bezel, mask, now):
    global _spectrum_heights, _spectrum_targets, _spectrum_last_update
    if not _spectrum_heights:
        _init_spectrum_bars()
        
    if now - _spectrum_last_update > 0.15:
        _spectrum_last_update = now
        _spectrum_targets = [random.uniform(10, 160) for _ in range(12)]
        
    if len(_spectrum_heights) != 12:
        _spectrum_heights = [random.uniform(10, 160) for _ in range(12)]
        
    for i in range(12):
        _spectrum_heights[i] += (_spectrum_targets[i] - _spectrum_heights[i]) * 0.35
        
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (240, 240), (0, 10, 4))
    d = ImageDraw.Draw(img)
    
    start_x = 14
    for i in range(12):
        h = int(_spectrum_heights[i])
        bx1 = start_x + i * 18
        bx2 = bx1 + 14
        by2 = 220
        by1 = by2 - h
        
        for sy in range(by2, by1 - 1, -6):
            d.rectangle([bx1, sy - 4, bx2, sy], fill=(0, 230, 80))
            
    return img




def _loop():
    global _rolling_die, _showing_omnissiah_glyph, _showing_custom_image, _custom_image, _custom_image_expiry
    global _last_activity_time, _active_idle_anim, _custom_idle_expiry, _requested_idle_anim
    bezel = _make_bezel()
    mask = _make_iris_mask()
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
    while not _stop.is_set():
        now = time.monotonic()
        dt, last = now - last, now

        # Update last activity time if active
        is_active = (
            _showing_omnissiah_glyph
            or _rolling_die
            or _scanning_auspex
            or _scanning_noosphere
            or _visualizing_music
            or _showing_custom_image
            or _speaking
            or _thinking
        )
        if is_active:
            _last_activity_time = now
            _active_idle_anim = None
        else:
            if now >= _custom_idle_expiry:
                if _requested_idle_anim is not None:
                    _requested_idle_anim = None
                    _active_idle_anim = None

            # If idle and timeout reached or forced, run screensaver animation
            if (now - _last_activity_time >= config.DISPLAY_IDLE_TIMEOUT) or (now < _custom_idle_expiry):
                # Cycle to a new screensaver every 5 minutes (300 seconds) if not explicitly locked to a requested animation
                if _active_idle_anim is not None and (now - idle_anim_start_time >= 300.0) and (_requested_idle_anim is None):
                    _active_idle_anim = None

                if _active_idle_anim is None:
                    idle_anim_start_time = now
                    if _requested_idle_anim is not None:
                        _active_idle_anim = _requested_idle_anim
                    else:
                        choices = [a for a in _screensaver_anims if a != last_picked_anim]
                        _active_idle_anim = random.choice(choices) if choices else random.choice(_screensaver_anims)
                    last_picked_anim = _active_idle_anim
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
                    elif _active_idle_anim == "circuit_maze":
                        _init_circuit_maze()
                    elif _active_idle_anim == "bouncing_cog":
                        _init_bouncing_cog()
                    elif _active_idle_anim == "orbitals":
                        _init_orbitals()
                    elif _active_idle_anim == "spectrum_bars":
                        _init_spectrum_bars()

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
                    elif _active_idle_anim == "warp_core":
                        _blit(_render_warp_core_frame(bezel, mask, now))
                    elif _active_idle_anim == "circuit_maze":
                        _blit(_render_circuit_maze_frame(bezel, mask, now))
                    elif _active_idle_anim == "double_helix":
                        _blit(_render_double_helix_frame(bezel, mask, now))
                    elif _active_idle_anim == "spinning_rings":
                        _blit(_render_spinning_rings_frame(bezel, mask, now))
                    elif _active_idle_anim == "wireframe_cube":
                        _blit(_render_wireframe_cube_frame(bezel, mask, now))
                    elif _active_idle_anim == "bouncing_cog":
                        _blit(_render_bouncing_cog_frame(bezel, mask, now))
                    elif _active_idle_anim == "fractal_tree":
                        _blit(_render_fractal_tree_frame(bezel, mask, now))
                    elif _active_idle_anim == "hud_status":
                        _blit(_render_hud_status_frame(bezel, mask, now))
                    elif _active_idle_anim == "orbitals":
                        _blit(_render_orbitals_frame(bezel, mask, now))
                    elif _active_idle_anim == "spectrum_bars":
                        _blit(_render_spectrum_bars_frame(bezel, mask, now))
                except Exception as e:
                    print(f"[display] screensaver render error ({_active_idle_anim}): {e}")
                time.sleep(1 / config.DISPLAY_FPS)
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
                time.sleep(1 / config.DISPLAY_FPS)
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
                time.sleep(1 / config.DISPLAY_FPS)
                continue

        if _scanning_auspex:
            try:
                _blit(_render_auspex_frame(bezel, mask, now))
            except Exception as e:
                print(f"[display] auspex render error: {e}")
            time.sleep(1 / config.DISPLAY_FPS)
            continue

        if _scanning_noosphere:
            try:
                _blit(_render_noosphere_frame(bezel, mask, now))
            except Exception as e:
                print(f"[display] noosphere render error: {e}")
            time.sleep(1 / config.DISPLAY_FPS)
            continue

        if _targeting:
            try:
                _blit(_render_targeting_frame(bezel, mask, now))
            except Exception as e:
                print(f"[display] targeting render error: {e}")
            time.sleep(1 / config.DISPLAY_FPS)
            continue

        if _visualizing_music and not _speaking and not _thinking:
            try:
                _blit(_render_music_frame(bezel, mask, now))
            except Exception as e:
                print(f"[display] music render error: {e}")
            time.sleep(1 / config.DISPLAY_FPS)
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
                time.sleep(1 / config.DISPLAY_FPS)
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

        # Smoothly interpolate gaze position
        look_x += (target_look_x - look_x) * 0.08
        look_y += (target_look_y - look_y) * 0.08

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
            _blit(_render_frame(bezel, mask, max(0.0, min(1.0, shown)), angle, blink, look_x, look_y))
        except Exception as e:
            print(f"[display] render error: {e}")
            return
        time.sleep(1 / config.DISPLAY_FPS)


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


def trigger_idle_animation(duration: float = 60.0, animation_name: str | None = None) -> None:
    global _custom_idle_expiry, _last_activity_time, _requested_idle_anim, _active_idle_anim
    if not _available:
        return
    _custom_idle_expiry = time.monotonic() + duration
    _active_idle_anim = None
    if animation_name and animation_name in _screensaver_anims:
        _requested_idle_anim = animation_name
    else:
        _requested_idle_anim = None


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
