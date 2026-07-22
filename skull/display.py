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

_last_activity_time = 0.0
_active_idle_anim = None
_custom_idle_expiry = 0.0
_requested_idle_anim = None

# Screensaver pools
_screensaver_anims = [
    "pong", "canticle_rain", "starfield", "oscilloscope", "game_of_life", "radar",
    "warp_core", "circuit_maze", "double_helix", "spinning_rings", "wireframe_cube",
    "bouncing_cog", "fractal_tree", "hud_status", "orbitals", "spectrum_bars",
    # New screensavers
    "plasma", "lissajous", "voronoi", "data_stream", "mandala",
    "rune_wheel", "glitch", "dna_helix", "neural_net", "gravity_well",
    "void_shield", "hex_grid", "kaleidoscope", "particle_burst"
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

# Voronoi state
_voronoi_sites = []
_voronoi_last_shift = 0.0

# Data Stream state
_data_stream_lines = []

# Neural Net state
_neural_nodes = []
_neural_edges = []
_neural_pulses = []

# Morse code state
_morse_message = ""
_morse_pos = 0
_morse_last_advance = 0.0

# Hex Grid state
_hex_grid_cells = []
_hex_last_flash = 0.0

# Particle Burst state
_pburst_particles = []



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


def get_screensaver_names() -> list[str]:
    """Return the authoritative list of available screensaver animation names.

    brain.py calls this at startup so the LLM tool schema is always in sync
    with display.py without requiring manual edits in two places.
    """
    return list(_screensaver_anims)


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


_current_frame_image = None
_frame_lock = threading.Lock()


def _blit(img) -> None:
    """Push a 240x240 PIL RGB image to the panel as big-endian RGB565."""
    global _current_frame_image
    try:
        with _frame_lock:
            _current_frame_image = img.copy()
    except Exception:
        pass

    if not _available or _spi is None:
        return

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


# ── New screensaver render functions ─────────────────────────────────────────

def _render_plasma_frame(bezel, mask, now):
    """Sine-wave interference plasma – vivid overlapping colour waves."""
    from PIL import Image
    import numpy as np
    x = np.linspace(0, 2 * math.pi, 240)
    y = np.linspace(0, 2 * math.pi, 240)
    xx, yy = np.meshgrid(x, y)
    t = now * 1.2
    v = (np.sin(xx + t) + np.sin(yy + t * 0.7)
         + np.sin((xx + yy) * 0.5 + t * 0.9)
         + np.sin(np.sqrt(xx**2 + yy**2) + t)) / 4.0
    v = (v + 1.0) / 2.0
    r = (np.sin(v * math.pi * 2 + t) * 127 + 128).clip(0, 255).astype(np.uint8)
    g = (np.sin(v * math.pi * 2 + t + 2.094) * 127 + 128).clip(0, 255).astype(np.uint8)
    b = (np.sin(v * math.pi * 2 + t + 4.189) * 127 + 128).clip(0, 255).astype(np.uint8)
    arr = np.stack([r, g, b], axis=-1)
    return Image.fromarray(arr, mode="RGB")


def _render_lissajous_frame(bezel, mask, now):
    """Lissajous curve tracer – parametric neon figures."""
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (240, 240), (0, 0, 0))
    d = ImageDraw.Draw(img)
    a, b_freq, delta = 3, 2, now * 0.4
    pts = []
    for i in range(600):
        t = i * math.pi * 2 / 600
        x = int(110 * math.sin(a * t + delta) + 120)
        y = int(110 * math.sin(b_freq * t) + 120)
        pts.append((x, y))
    for i in range(len(pts) - 1):
        frac = i / len(pts)
        r = int(255 * abs(math.sin(frac * math.pi + now)))
        g = int(255 * abs(math.sin(frac * math.pi + now + 2.094)))
        b = int(255 * abs(math.sin(frac * math.pi + now + 4.189)))
        d.line([pts[i], pts[i+1]], fill=(r, g, b), width=2)
    return img


_voronoi_sites = []
_voronoi_last_shift = 0.0
def _init_voronoi():
    global _voronoi_sites, _voronoi_last_shift
    _voronoi_sites = [{"x": random.uniform(20, 220), "y": random.uniform(20, 220),
                       "dx": random.uniform(-0.8, 0.8), "dy": random.uniform(-0.8, 0.8),
                       "c": (random.randint(80, 255), random.randint(10, 80), random.randint(0, 40))}
                      for _ in range(7)]
    _voronoi_last_shift = 0.0

def _render_voronoi_frame(bezel, mask, now):
    global _voronoi_sites
    if not _voronoi_sites:
        _init_voronoi()
    from PIL import Image
    import numpy as np
    for s in _voronoi_sites:
        s["x"] = (s["x"] + s["dx"]) % 240
        s["y"] = (s["y"] + s["dy"]) % 240
    xs = np.array([s["x"] for s in _voronoi_sites])
    ys = np.array([s["y"] for s in _voronoi_sites])
    colors = np.array([[s["c"][0], s["c"][1], s["c"][2]] for s in _voronoi_sites], dtype=np.uint8)
    px = np.arange(240)
    py = np.arange(240)
    gx, gy = np.meshgrid(px, py)
    dists = np.sqrt((gx[:,:,None] - xs)**2 + (gy[:,:,None] - ys)**2)
    nearest = np.argmin(dists, axis=2)
    arr = colors[nearest]
    # Darken slightly for moodiness
    arr = (arr * 0.7).clip(0, 255).astype(np.uint8)
    return Image.fromarray(arr, mode="RGB")


_data_stream_lines = []
def _init_data_stream():
    global _data_stream_lines
    _data_stream_lines = [{"y": random.uniform(0, 240), "speed": random.uniform(1.5, 4.5),
                           "text": "".join(random.choices("0123456789ABCDEF", k=20))} for _ in range(14)]

def _render_data_stream_frame(bezel, mask, now):
    global _data_stream_lines
    if not _data_stream_lines:
        _init_data_stream()
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (240, 240), (0, 0, 0))
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None
    for line in _data_stream_lines:
        line["y"] = (line["y"] + line["speed"]) % 250
        if random.random() < 0.04:
            line["text"] = "".join(random.choices("0123456789ABCDEF", k=20))
        y = int(line["y"])
        for i, ch in enumerate(line["text"]):
            xp = i * 12 + 2
            if xp > 238:
                break
            bright = random.randint(160, 255)
            c = (0, bright, int(bright * 0.5))
            if font:
                d.text((xp, y), ch, fill=c, font=font)
    return img


def _render_mandala_frame(bezel, mask, now):
    """Rotating concentric mandala geometry."""
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (240, 240), (0, 0, 0))
    d = ImageDraw.Draw(img)
    for ring in range(1, 8):
        r = ring * 14
        n_pts = ring * 6
        base_angle = now * (0.3 if ring % 2 == 0 else -0.3) * (ring * 0.2)
        t = now * 0.5
        red = int(200 * abs(math.sin(ring * 0.9 + t)))
        grn = int(100 * abs(math.sin(ring * 0.5 - t)))
        blu = int(255 * abs(math.sin(ring * 0.3 + t * 0.7)))
        pts = []
        for i in range(n_pts):
            a = base_angle + i * 2 * math.pi / n_pts
            pts.append((120 + r * math.cos(a), 120 + r * math.sin(a)))
        if len(pts) > 2:
            d.polygon(pts, outline=(red, grn, blu))
    return img


def _render_rune_wheel_frame(bezel, mask, now):
    """Spinning elder rune characters around concentric circles."""
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (240, 240), (0, 0, 0))
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None
    runes = list("ᚠᚢᚦᚨᚱᚲᚷᚹᚺᚾᛁᛃᛇᛈᛉᛊᛏᛒᛖᛗᛚᛜᛞᛟ")
    for ring_idx, (radius, speed, count) in enumerate([(40, 0.4, 8), (70, -0.25, 12), (100, 0.15, 16)]):
        for i in range(count):
            a = now * speed + i * 2 * math.pi / count
            x = int(120 + radius * math.cos(a))
            y = int(120 + radius * math.sin(a))
            t = now * 0.5
            r = int(200 * abs(math.sin(ring_idx + t)))
            g = int(80 * abs(math.sin(ring_idx * 0.7 + t)))
            b = int(255 * abs(math.sin(ring_idx * 0.5 - t)))
            rune = runes[(ring_idx * count + i) % len(runes)]
            if font:
                d.text((x - 4, y - 4), rune, fill=(r, g, b), font=font)
    return img


def _render_glitch_frame(bezel, mask, now):
    """Digital glitch / corruption aesthetic."""
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (240, 240), (0, 0, 0))
    d = ImageDraw.Draw(img)
    # Horizontal scan-line corruption
    for _ in range(random.randint(4, 14)):
        y = random.randint(0, 239)
        h = random.randint(1, 8)
        xoff = random.randint(-40, 40)
        r = random.randint(0, 255)
        g = random.randint(0, 255)
        b = random.randint(0, 255)
        d.rectangle([0, y, 239, y + h], fill=(int(r * 0.1), int(g * 0.1), int(b * 0.1)))
        d.rectangle([max(0, xoff), y, min(239, 239 + xoff), y + h], fill=(r, 0, 0) if r > 200 else (0, g, b))
    # Random bright pixels
    for _ in range(random.randint(20, 60)):
        x = random.randint(0, 239)
        y = random.randint(0, 239)
        c = random.choice([(255, 0, 0), (0, 255, 200), (255, 255, 0), (0, 180, 255)])
        d.point((x, y), fill=c)
    # Vertical tear lines
    for _ in range(random.randint(1, 4)):
        x = random.randint(0, 239)
        d.line([(x, 0), (x, 239)], fill=(random.randint(100, 255), 0, 0), width=1)
    return img


def _render_dna_helix_frame(bezel, mask, now):
    """Rotating double helix ribbons scrolling vertically."""
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (240, 240), (0, 0, 0))
    d = ImageDraw.Draw(img)
    for y in range(0, 240, 3):
        t = y * 0.06 + now * 2.0
        x1 = int(120 + 60 * math.sin(t))
        x2 = int(120 + 60 * math.sin(t + math.pi))
        frac = (math.sin(t) + 1) / 2
        c1 = (int(255 * frac), int(80 * (1 - frac)), int(200 * (1 - frac)))
        c2 = (int(80 * frac), int(200 * (1 - frac)), int(255 * frac))
        d.ellipse([x1 - 3, y - 3, x1 + 3, y + 3], fill=c1)
        d.ellipse([x2 - 3, y - 3, x2 + 3, y + 3], fill=c2)
        # Cross-links every ~20px
        if y % 20 < 3:
            d.line([(x1, y), (x2, y)], fill=(80, 80, 80), width=1)
    return img


_neural_nodes = []
_neural_edges = []
_neural_pulses = []
def _init_neural_net():
    global _neural_nodes, _neural_edges, _neural_pulses
    _neural_nodes = [{"x": random.uniform(30, 210), "y": random.uniform(30, 210)} for _ in range(16)]
    _neural_edges = []
    for i in range(len(_neural_nodes)):
        for j in range(i + 1, len(_neural_nodes)):
            dx = _neural_nodes[i]["x"] - _neural_nodes[j]["x"]
            dy = _neural_nodes[i]["y"] - _neural_nodes[j]["y"]
            if math.sqrt(dx*dx + dy*dy) < 80:
                _neural_edges.append((i, j))
    _neural_pulses = []

def _render_neural_net_frame(bezel, mask, now):
    global _neural_pulses
    if not _neural_nodes:
        _init_neural_net()
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (240, 240), (0, 0, 0))
    d = ImageDraw.Draw(img)
    for i, j in _neural_edges:
        d.line([(int(_neural_nodes[i]["x"]), int(_neural_nodes[i]["y"])),
                (int(_neural_nodes[j]["x"]), int(_neural_nodes[j]["y"]))],
               fill=(0, 30, 60), width=1)
    # Pulse along edges
    if random.random() < 0.15 and _neural_edges:
        e = random.choice(_neural_edges)
        _neural_pulses.append({"edge": e, "t": 0.0})
    new_pulses = []
    for p in _neural_pulses:
        p["t"] += 0.04
        if p["t"] < 1.0:
            i, j = p["edge"]
            x = int(_neural_nodes[i]["x"] * (1 - p["t"]) + _neural_nodes[j]["x"] * p["t"])
            y = int(_neural_nodes[i]["y"] * (1 - p["t"]) + _neural_nodes[j]["y"] * p["t"])
            bright = int(255 * (1 - abs(p["t"] - 0.5) * 2))
            d.ellipse([x-4, y-4, x+4, y+4], fill=(0, bright, int(bright * 0.6)))
            new_pulses.append(p)
    _neural_pulses = new_pulses
    for n in _neural_nodes:
        d.ellipse([int(n["x"]) - 3, int(n["y"]) - 3, int(n["x"]) + 3, int(n["y"]) + 3],
                  fill=(0, 150, 255))
    return img


def _render_gravity_well_frame(bezel, mask, now):
    """Particles spiraling into a singularity at centre."""
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (240, 240), (0, 0, 0))
    d = ImageDraw.Draw(img)
    n = 80
    for i in range(n):
        phase = i / n * 2 * math.pi
        t = (now * 0.4 + phase) % (2 * math.pi)
        r_orbit = 100 * (1 - t / (2 * math.pi)) + 2
        spiral_angle = phase + now * 0.6 + t * 3
        x = int(120 + r_orbit * math.cos(spiral_angle))
        y = int(120 + r_orbit * math.sin(spiral_angle))
        bright = int(255 * (1 - r_orbit / 100))
        c = (int(bright * 0.7), int(bright * 0.3), bright)
        d.ellipse([x-1, y-1, x+1, y+1], fill=c)
    # Singularity glow
    for rr in [12, 8, 4, 2]:
        alpha = int(255 * (1 - rr / 12))
        d.ellipse([120-rr, 120-rr, 120+rr, 120+rr], fill=(alpha, int(alpha*0.3), alpha))
    return img


_morse_message = ""
_morse_pos = 0
_morse_last_advance = 0.0
_MORSE_CODE = {
    "A": ".-", "B": "-...", "C": "-.-.", "D": "-..", "E": ".",
    "F": "..-.", "G": "--.", "H": "....", "I": "..", "J": ".---",
    "K": "-.-", "L": ".-..", "M": "--", "N": "-.", "O": "---",
    "P": ".--.", "Q": "--.-", "R": ".-.", "S": "...", "T": "-",
    "U": "..-", "V": "...-", "W": ".--", "X": "-..-", "Y": "-.--", "Z": "--..",
}
def _init_morse():
    global _morse_message, _morse_pos, _morse_last_advance
    phrases = ["OMNISSIAH", "ADEPTUS MECHANICUS", "AVE MACHINA", "OMEGA SEVEN",
               "GLORY TO THE MACHINE", "COGITATOR ACTIVE", "PRAISE THE OMNISSIAH"]
    text = random.choice(phrases)
    seq = []
    for ch in text:
        if ch == " ":
            seq.extend([" ", " ", " "])
        elif ch in _MORSE_CODE:
            for sym in _MORSE_CODE[ch]:
                seq.append(sym)
            seq.append(" ")
    _morse_message = seq
    _morse_pos = 0
    _morse_last_advance = 0.0

def _render_void_shield_frame(bezel, mask, now):
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (240, 240), (0, 0, 0))
    d = ImageDraw.Draw(img)
    
    cx, cy = 120, 120
    num_sides = 6
    angles = [now * 0.25, -now * 0.15, now * 0.08]
    pulse = 1.0 + 0.15 * math.sin(now * 1.5)
    base_radii = [30 * pulse, 55 * pulse, 80 * pulse]
    
    for ring in range(3):
        r = base_radii[ring]
        rot = angles[ring]
        pts = []
        for i in range(num_sides + 1):
            theta = rot + (i * 2 * math.pi / num_sides)
            px = cx + r * math.cos(theta)
            py = cy + r * math.sin(theta)
            pts.append((px, py))
            
        d.line(pts, fill=(0, 140, 40), width=1)
        
        for px, py in pts[:-1]:
            d.ellipse([px-2, py-2, px+2, py+2], fill=(50, 255, 100))
            
    inner_pts = []
    outer_pts = []
    for i in range(num_sides):
        theta_in = angles[0] + (i * 2 * math.pi / num_sides)
        px_in = cx + base_radii[0] * math.cos(theta_in)
        py_in = cy + base_radii[0] * math.sin(theta_in)
        inner_pts.append((px_in, py_in))
        
        theta_out = angles[2] + (i * 2 * math.pi / num_sides)
        px_out = cx + base_radii[2] * math.cos(theta_out)
        py_out = cy + base_radii[2] * math.sin(theta_out)
        outer_pts.append((px_out, py_out))
        
        d.line([(cx, cy), (px_in, py_in)], fill=(0, 70, 20), width=1)
        d.line([(px_in, py_in), (px_out, py_out)], fill=(0, 70, 20), width=1)

    img.paste(bezel, (0, 0), mask)
    return img


_hex_grid_cells = []
_hex_last_flash = 0.0
def _init_hex_grid():
    global _hex_grid_cells
    _hex_grid_cells = []
    size = 14
    for row in range(11):
        for col in range(9):
            x = col * size * 1.73 + (row % 2) * size * 0.87 + 5
            y = row * size * 1.5 + 5
            _hex_grid_cells.append({"x": x, "y": y, "flash": 0.0, "size": size})

def _render_hex_grid_frame(bezel, mask, now):
    global _hex_grid_cells, _hex_last_flash
    if not _hex_grid_cells:
        _init_hex_grid()
    from PIL import Image, ImageDraw
    import numpy as np
    img = Image.new("RGB", (240, 240), (0, 0, 0))
    d = ImageDraw.Draw(img)
    if now - _hex_last_flash > 0.08:
        _hex_last_flash = now
        for _ in range(random.randint(1, 3)):
            cell = random.choice(_hex_grid_cells)
            cell["flash"] = 1.0
    for cell in _hex_grid_cells:
        cell["flash"] = max(0.0, cell["flash"] - 0.06)
        f = cell["flash"]
        base = 0.12
        r = int(255 * (base + (1 - base) * f))
        g = int(80 * f)
        b = int(255 * (base * 0.5))
        s = cell["size"]
        x, y = cell["x"], cell["y"]
        pts = [(x + s * math.cos(math.radians(60 * i + 30)), y + s * math.sin(math.radians(60 * i + 30))) for i in range(6)]
        d.polygon(pts, outline=(r, g, b))
    return img


def _render_kaleidoscope_frame(bezel, mask, now):
    """Radially mirrored mandala pattern with shifting colours."""
    from PIL import Image, ImageDraw
    n_segments = 8
    img = Image.new("RGB", (240, 240), (0, 0, 0))
    d = ImageDraw.Draw(img)
    for seg in range(n_segments):
        base_a = seg * (2 * math.pi / n_segments) + now * 0.2
        for i in range(30):
            t = i / 30
            rr = 10 + t * 100
            a1 = base_a + t * 1.2 * math.sin(now * 0.7)
            a2 = base_a + (t + 0.1) * 1.2 * math.sin(now * 0.7)
            x1 = int(120 + rr * math.cos(a1))
            y1 = int(120 + rr * math.sin(a1))
            x2 = int(120 + (rr + 4) * math.cos(a2))
            y2 = int(120 + (rr + 4) * math.sin(a2))
            hue = (now * 60 + seg * 45 + t * 120) % 360
            hr = hue / 360
            # Convert HSV-ish to RGB
            region = int(hr * 6)
            fract = hr * 6 - region
            colors = [
                (255, int(255 * fract), 0),
                (int(255 * (1 - fract)), 255, 0),
                (0, 255, int(255 * fract)),
                (0, int(255 * (1 - fract)), 255),
                (int(255 * fract), 0, 255),
                (255, 0, int(255 * (1 - fract))),
            ]
            col = colors[region % 6]
            d.line([(x1, y1), (x2, y2)], fill=col, width=2)
    return img


_pburst_particles = []
def _init_particle_burst():
    global _pburst_particles
    _pburst_particles = []

def _render_particle_burst_frame(bezel, mask, now):
    global _pburst_particles
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (240, 240), (0, 0, 0))
    d = ImageDraw.Draw(img)
    # Spawn new burst every second
    if not hasattr(_render_particle_burst_frame, "last_burst"):
        _render_particle_burst_frame.last_burst = 0.0
    if now - _render_particle_burst_frame.last_burst > 0.8:
        _render_particle_burst_frame.last_burst = now
        n = random.randint(20, 40)
        bx = random.uniform(60, 180)
        by = random.uniform(60, 180)
        hue = random.uniform(0, 1)
        for _ in range(n):
            a = random.uniform(0, 2 * math.pi)
            spd = random.uniform(1.5, 5.0)
            _pburst_particles.append({"x": bx, "y": by, "vx": math.cos(a) * spd,
                                       "vy": math.sin(a) * spd, "life": 1.0, "hue": hue})
    new_p = []
    for p in _pburst_particles:
        p["x"] += p["vx"]
        p["y"] += p["vy"]
        p["vy"] += 0.08  # gravity
        p["life"] -= 0.025
        if p["life"] > 0:
            # Convert hue to RGB
            h6 = (p["hue"] * 6) % 6
            f = h6 - int(h6)
            palette = [
                (255, int(255*f), 0), (int(255*(1-f)), 255, 0), (0, 255, int(255*f)),
                (0, int(255*(1-f)), 255), (int(255*f), 0, 255), (255, 0, int(255*(1-f)))
            ]
            r, g, b = palette[int(h6) % 6]
            alpha = p["life"]
            col = (int(r * alpha), int(g * alpha), int(b * alpha))
            d.ellipse([int(p["x"]) - 2, int(p["y"]) - 2, int(p["x"]) + 2, int(p["y"]) + 2], fill=col)
            new_p.append(p)
    _pburst_particles = new_p
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
    global _showing_alignment, _alignment_until
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

        # Check active status & minimum duration timers
        searching_web_active = _searching_web or (now < _web_search_until)
        rules_lookup_active = _looking_up_rules or (now < _rules_lookup_until)
        news_fetch_active = _fetching_news or (now < _news_fetch_until)
        image_retrieval_active = _retrieving_image or (now < _image_retrieval_until)

        # Update last activity time if active
        is_active = (
            _showing_omnissiah_glyph
            or _rolling_die
            or _scanning_auspex
            or _scanning_noosphere
            or searching_web_active
            or rules_lookup_active
            or news_fetch_active
            or image_retrieval_active
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
                    elif _active_idle_anim == "voronoi":
                        _init_voronoi()
                    elif _active_idle_anim == "data_stream":
                        _init_data_stream()
                    elif _active_idle_anim == "neural_net":
                        _init_neural_net()
                    elif _active_idle_anim == "hex_grid":
                        _init_hex_grid()
                    elif _active_idle_anim == "particle_burst":
                        _init_particle_burst()

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
                    elif _active_idle_anim == "plasma":
                        _blit(_render_plasma_frame(bezel, mask, now))
                    elif _active_idle_anim == "lissajous":
                        _blit(_render_lissajous_frame(bezel, mask, now))
                    elif _active_idle_anim == "voronoi":
                        _blit(_render_voronoi_frame(bezel, mask, now))
                    elif _active_idle_anim == "data_stream":
                        _blit(_render_data_stream_frame(bezel, mask, now))
                    elif _active_idle_anim == "mandala":
                        _blit(_render_mandala_frame(bezel, mask, now))
                    elif _active_idle_anim == "rune_wheel":
                        _blit(_render_rune_wheel_frame(bezel, mask, now))
                    elif _active_idle_anim == "glitch":
                        _blit(_render_glitch_frame(bezel, mask, now))
                    elif _active_idle_anim == "dna_helix":
                        _blit(_render_dna_helix_frame(bezel, mask, now))
                    elif _active_idle_anim == "neural_net":
                        _blit(_render_neural_net_frame(bezel, mask, now))
                    elif _active_idle_anim == "gravity_well":
                        _blit(_render_gravity_well_frame(bezel, mask, now))
                    elif _active_idle_anim == "void_shield":
                        _blit(_render_void_shield_frame(bezel, mask, now))
                    elif _active_idle_anim == "hex_grid":
                        _blit(_render_hex_grid_frame(bezel, mask, now))
                    elif _active_idle_anim == "kaleidoscope":
                        _blit(_render_kaleidoscope_frame(bezel, mask, now))
                    elif _active_idle_anim == "particle_burst":
                        _blit(_render_particle_burst_frame(bezel, mask, now))
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

        if searching_web_active:
            try:
                _blit(_render_web_search_frame(bezel, mask, now))
            except Exception as e:
                print(f"[display] web search render error: {e}")
            time.sleep(1 / config.DISPLAY_FPS)
            continue

        if rules_lookup_active:
            try:
                _blit(_render_rules_lookup_frame(bezel, mask, now))
            except Exception as e:
                print(f"[display] rules lookup render error: {e}")
            time.sleep(1 / config.DISPLAY_FPS)
            continue

        if news_fetch_active:
            try:
                _blit(_render_news_fetch_frame(bezel, mask, now))
            except Exception as e:
                print(f"[display] news fetch render error: {e}")
            time.sleep(1 / config.DISPLAY_FPS)
            continue

        if image_retrieval_active:
            try:
                _blit(_render_image_retrieval_frame(bezel, mask, now))
            except Exception as e:
                print(f"[display] image retrieval render error: {e}")
            time.sleep(1 / config.DISPLAY_FPS)
            continue

        if _showing_alignment:
            if now >= _alignment_until:
                _showing_alignment = False
            else:
                try:
                    _blit(_render_alignment_frame(bezel, mask, now))
                except Exception as e:
                    print(f"[display] alignment render error: {e}")
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

        # Smoothly interpolate gaze position (snappy organic saccades)
        look_x += (target_look_x - look_x) * 0.65
        look_y += (target_look_y - look_y) * 0.65

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
    _last_activity_time = 0.0  # Force idle screensaver mode immediately
    if animation_name and animation_name in _screensaver_anims:
        _requested_idle_anim = animation_name
    else:
        _requested_idle_anim = None


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


def start_web_search(min_duration: float = 3.0) -> None:
    global _searching_web, _web_search_until
    _web_search_until = time.monotonic() + min_duration
    _searching_web = True


def stop_web_search() -> None:
    global _searching_web
    _searching_web = False


def start_rules_lookup(min_duration: float = 3.5) -> None:
    global _looking_up_rules, _rules_lookup_until
    _rules_lookup_until = time.monotonic() + min_duration
    _looking_up_rules = True


def stop_rules_lookup() -> None:
    global _looking_up_rules
    _looking_up_rules = False


def start_news_fetch(min_duration: float = 3.0) -> None:
    global _fetching_news, _news_fetch_until
    _news_fetch_until = time.monotonic() + min_duration
    _fetching_news = True


def stop_news_fetch() -> None:
    global _fetching_news
    _fetching_news = False


def start_image_retrieval(min_duration: float = 3.0) -> None:
    global _retrieving_image, _image_retrieval_until
    _image_retrieval_until = time.monotonic() + min_duration
    _retrieving_image = True


def stop_image_retrieval() -> None:
    global _retrieving_image
    _retrieving_image = False


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


def get_state() -> dict:
    global _showing_custom_image, _active_idle_anim, _speaking, _thinking, _target_amp
    global _scanning_auspex, _scanning_noosphere, _searching_web, _looking_up_rules, _fetching_news, _retrieving_image, _targeting, _visualizing_music, _rolling_die, _die_result
    global _web_search_until, _rules_lookup_until, _news_fetch_until, _image_retrieval_until, _showing_alignment, _alignment_until
    now = time.monotonic()
    return {
        "showing_custom_image": _showing_custom_image,
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
    global _current_frame_image
    with _frame_lock:
        if _current_frame_image is None:
            return None
        try:
            import io
            buf = io.BytesIO()
            # Compress at 70% quality for fast network transport
            _current_frame_image.save(buf, format="JPEG", quality=70)
            return buf.getvalue()
        except Exception as e:
            print(f"[display] Failed to get ocular frame bytes: {e}")
            return None
