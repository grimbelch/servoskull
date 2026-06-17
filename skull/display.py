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
_mood_rgb = (255, 40, 30)  # base iris colour; default Imperial red

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
    import spidev
    import RPi.GPIO as GPIO
    from PIL import Image, ImageDraw
    import numpy as np
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


def _render_frame(bezel, mask, amp: float):
    """Compose one iris frame for normalized amplitude `amp` (0..1). The iris is
    drawn on its own layer and pasted through `mask` so it stays in the aperture."""
    img = bezel.copy()
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

    img.paste(iris, (0, 0), mask)
    return img


# ── render loop ────────────────────────────────────────────────────────────────────

def _loop():
    bezel = _make_bezel()
    mask = _make_iris_mask()
    shown = -1.0          # last amplitude actually drawn
    t0 = time.monotonic()
    while not _stop.is_set():
        if _speaking:
            target = _target_amp
        else:
            # Slow idle breathing pulse (~0.2 Hz) so the eye looks "alive".
            target = 0.12 + 0.06 * (0.5 + 0.5 * math.sin((time.monotonic() - t0) * 1.2))
        # Ease toward the target to smooth the audio loop's jitter.
        if shown < 0:
            shown = target
        else:
            shown += (target - shown) * 0.35
        try:
            _blit(_render_frame(bezel, mask, max(0.0, min(1.0, shown))))
        except Exception as e:
            print(f"[display] render error: {e}")
            return
        time.sleep(1 / 30)


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
    global _target_amp, _speaking
    if not _available:
        return
    _target_amp = max(0.0, min(1.0, amp))
    _speaking = True


def set_mood(mood: str) -> None:
    """Tint the iris to match Omega-7's current disposition (see skull/mood.py)."""
    global _mood_rgb
    if not _available:
        return
    _mood_rgb = _MOOD_COLOURS.get((mood or "").upper(), (255, 40, 30))


def on() -> None:
    """Full-intensity steady gaze (e.g. while attending a command)."""
    global _target_amp, _speaking
    if not _available:
        return
    _target_amp = 1.0
    _speaking = True


def idle() -> None:
    """Return to the slow idle breathing pulse."""
    global _speaking, _target_amp
    if not _available:
        return
    _speaking = False
    _target_amp = 0.0


# Alias so call sites that mirror eyes.off() read naturally.
off = idle


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
