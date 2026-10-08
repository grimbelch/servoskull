"""Omega-7's startup animation: the Omnissiah cog-skull struck onto a green CRT.

The concept is carried over from the original boot glyph -- a Mechanicus
cog-skull that assembles and whose bionic eye ignites in the mood colour --
redrawn in the vocabulary the current screensavers use: stroked vectors instead
of flat fills, the shared green-phosphor palette, and the Phosphor compositor
for afterglow, bloom, scanlines and vignette.

Unlike the original, the sequence is normalised to the `duration` the caller
asks for (core/main.py starts it at 4s twice and 6s once), so every stage lands
in proportion however long the showing runs:

    0.00-0.08  the raster strikes: a line opens into the full panel
    0.08-0.48  the cog traces in at the rim while the rite log types in the hub
    0.48-0.80  the log clears and the skull assembles in the space it leaves
    0.80-0.90  the bionic lens ignites in the mood colour
    0.90-1.00  the cog recedes, the benediction holds for the handoff to the eye
"""

from __future__ import annotations

import math

from PIL import ImageDraw

from .classic._phosphor import (
    AMBER,
    GREEN,
    GREEN_DIM,
    GREEN_HI,
    GREEN_MID,
    Phosphor,
    blank,
)
from .lore._common import CX, CY, font, lerp_color, safe_half_width, scale

# Stage boundaries as a fraction of the requested duration.
_T_STRIKE, _T_RITE, _T_SKULL, _T_IGNITE = 0.08, 0.48, 0.80, 0.90

# The rite log: (label, result, result colour, fraction of the log phase).
_RITE = [
    ("RITE OF AWAKENING", "", GREEN_HI, 0.00),
    ("COGITATOR", "OK", GREEN, 0.22),
    ("NOOSPHERE", "OK", GREEN, 0.45),
    ("ANIMA", "LIT", AMBER, 0.68),
]
_BENEDICTION = ("OMNISSIAH", "BE PRAISED")


def _polyline_segments(paths):
    """Flatten polylines into (a, b, length) segments for progressive tracing."""
    segs = []
    for pts in paths:
        for i in range(len(pts) - 1):
            a, b = pts[i], pts[i + 1]
            segs.append((a, b, math.hypot(b[0] - a[0], b[1] - a[1])))
    return segs


def _cog_paths():
    """The gear rim, hub and spokes, in unit coordinates about the centre."""
    teeth, r_out, r_in, r_hub = 12, 110.0, 88.0, 74.0
    rim = []
    for i in range(teeth * 4 + 1):
        a = 2 * math.pi * i / (teeth * 4) - math.pi / 2
        r = r_out if (i % 4) in (1, 2) else r_in
        rim.append((r * math.cos(a), r * math.sin(a)))
    paths = [rim]
    paths.append([(r_in * math.cos(2 * math.pi * i / 64), r_in * math.sin(2 * math.pi * i / 64))
                  for i in range(65)])
    paths.append([(r_hub * math.cos(2 * math.pi * i / 56), r_hub * math.sin(2 * math.pi * i / 56))
                  for i in range(57)])
    for k in range(6):
        a = math.pi / 6 + k * math.pi / 3
        paths.append([(r_hub * math.cos(a), r_hub * math.sin(a)),
                      (r_in * math.cos(a), r_in * math.sin(a))])
    return paths


# Half the skull silhouette, from the crown clockwise to the chin, in panel
# units about the centre. Mirrored for the other half. Stroked line art needs a
# continuous outline -- the original animation got away with disconnected
# fragments only because it filled them as solid pieslices.
_SIL = [(0, -72), (18, -70), (33, -61), (43, -47), (48, -31), (50, -13),
        (48, 2), (42, 14), (34, 22), (30, 31), (29, 41), (26, 52),
        (19, 62), (9, 67), (0, 68)]

_JAW_Y, _TEETH_Y = 41.0, 60.0
_SOCKET_Y = -16.0


def _skull_paths():
    """The cog-skull as polylines split by half: 'bone' (left) and 'machine' (right).

    Sized to fill the cog hub (r=74) rather than float inside it, so the skull
    -- not the gear -- is what the frame reads as.
    """
    bone = [[(-x, y) for x, y in _SIL]]
    mach = [list(_SIL)]

    # Jaw line and the teeth palisade, enclosed by the silhouette either side.
    bone.append([(-29, _JAW_Y), (0, _JAW_Y)])
    mach.append([(0, _JAW_Y), (29, _JAW_Y)])
    bone.append([(-27, _TEETH_Y), (0, _TEETH_Y)])
    mach.append([(0, _TEETH_Y), (27, _TEETH_Y)])
    for x in (-19, -10, 0):
        bone.append([(x, _JAW_Y), (x, _TEETH_Y)])
    for x in (10, 19):
        mach.append([(x, _JAW_Y), (x, _TEETH_Y)])

    # Nasal aperture.
    bone.append([(0, 6), (-8, 28), (0, 24)])
    mach.append([(0, 24), (8, 28), (0, 6)])

    # Brow ridge.
    bone.append([(-42, -36), (-20, -40)])
    mach.append([(20, -40), (42, -36)])

    # Organic socket (left) is a plain ring; the bionic lens (right) gets a
    # bezel and a mounting strut, so it reads as hardware before it lights.
    bone.append([(-20 + 14 * math.cos(2 * math.pi * i / 24), _SOCKET_Y + 14 * math.sin(2 * math.pi * i / 24))
                 for i in range(25)])
    mach.append([(20 + 15 * math.cos(2 * math.pi * i / 24), _SOCKET_Y + 15 * math.sin(2 * math.pi * i / 24))
                 for i in range(25)])
    mach.append([(20 + 8 * math.cos(2 * math.pi * i / 16), _SOCKET_Y + 8 * math.sin(2 * math.pi * i / 16))
                 for i in range(17)])
    mach.append([(35, _SOCKET_Y), (45, _SOCKET_Y)])

    # Cranial circuitry on the machine half.
    mach.append([(9, -62), (13, -50), (6, -40)])
    mach.append([(22, -58), (22, -47), (36, -47), (41, -40)])
    return bone, mach


_COG = _polyline_segments(_cog_paths())
_COG_LEN = sum(s[2] for s in _COG) or 1.0
_BONE, _MACH = (_polyline_segments(p) for p in _skull_paths())
_SKULL_LEN = (sum(s[2] for s in _BONE) + sum(s[2] for s in _MACH)) or 1.0

_phos = Phosphor(decay=0.74, bloom=0.60, flicker=0.035)
_last_start = None
_last_age = 0.0


def _trace(d, segs, target, colour, spin=0.0, grow=1.0, width=1, glow=None):
    """Draw segments up to `target` arc-length, rotated by `spin` and scaled by `grow`.

    Returns the pen position at the cut, or None if the whole run was drawn.
    """
    cos_s, sin_s = math.cos(spin), math.sin(spin)

    def place(p):
        x, y = p[0] * grow, p[1] * grow
        return CX + x * cos_s - y * sin_s, CY + x * sin_s + y * cos_s

    acc, pen = 0.0, None
    for a, b, length in segs:
        if acc >= target:
            break
        if acc + length <= target:
            end = b
        else:
            f = (target - acc) / length if length else 1.0
            end = (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)
            pen = end
        pa, pb = place(a), place(end)
        if glow is not None:
            d.line([pa, pb], fill=glow, width=width + 2)
        d.line([pa, pb], fill=colour, width=width)
        acc += length
    return place(pen) if pen is not None else None


def _rite_log(d, u, fade):
    """The staged boot telemetry, typed in and dimmed by `fade` as it clears.

    Lines stay inside r=66 so they clear the cog hub ring entirely.
    """
    f = font(10)
    for i, (label, result, rcol, at) in enumerate(_RITE):
        k = (u - at) * 6.0
        if k <= 0:
            break
        y = 90 + i * 16
        shown = label[: max(1, int(len(label) * min(1.0, k)))]
        if not result:
            w = d.textlength(shown, font=f)
            d.text((CX - w / 2, y), shown, fill=scale(GREEN_HI, fade), font=f)
            continue
        hw = min(66.0, safe_half_width(y + 5, 10))
        x0, x1 = CX - hw, CX + hw
        d.text((x0, y), shown, fill=scale(GREEN_MID, fade), font=f)
        if k >= 1.0:
            lw = d.textlength(label, font=f)
            rw = d.textlength(result, font=f)
            dots = int(max(0, (x1 - rw - 4) - (x0 + lw + 4)) // 4)
            if dots:
                d.text((x0 + lw + 4, y), "." * dots, fill=scale(GREEN_DIM, fade), font=f)
            d.text((x1 - rw, y), result, fill=scale(rcol, fade), font=f)


def _graticule(d, k, fade):
    """A progress graticule under the log, ticking with the rite."""
    y, hw = 162, 60.0
    x0, x1 = CX - hw, CX + hw
    d.line([(x0, y), (x1, y)], fill=scale(GREEN_DIM, fade))
    for i in range(11):
        x = x0 + (x1 - x0) * i / 10
        d.line([(x, y - (4 if i % 5 == 0 else 2)), (x, y)], fill=scale(GREEN_DIM, fade))
    xk = x0 + (x1 - x0) * max(0.0, min(1.0, k))
    d.line([(x0, y - 1), (xk, y - 1)], fill=scale(GREEN, fade), width=2)
    d.line([(xk, y - 6), (xk, y + 3)], fill=scale(GREEN_HI, fade))


def _eye(d, k, mood_rgb, t):
    """The bionic lens igniting: a flare that collapses into a steady pupil."""
    ex, ey = CX + 20, CY + _SOCKET_Y
    k = max(0.0, min(1.0, k))
    ease = k * k * (3.0 - 2.0 * k)

    if k < 0.7:
        fr = 14 + 34 * (k / 0.7)
        d.ellipse([ex - fr, ey - fr, ex + fr, ey + fr],
                  outline=scale(lerp_color(GREEN_HI, mood_rgb, ease), 1.0 - k / 0.7))

    core = lerp_color(GREEN_HI, mood_rgb, ease)
    r = 2.0 + 8.0 * ease
    d.ellipse([ex - r - 3, ey - r - 3, ex + r + 3, ey + r + 3], fill=scale(core, 0.30 * ease))
    d.ellipse([ex - r, ey - r, ex + r, ey + r], fill=core)
    if ease > 0.55:
        pr = 1.4 + 0.8 * math.sin(t * 6.0)
        d.ellipse([ex - pr, ey - pr, ex + pr, ey + pr], fill=GREEN_HI)

    if ease > 0.4:
        a = 0.30 * (ease - 0.4) / 0.6
        for sx in (40, 58):
            d.line([(ex + 14, ey), (ex + sx, ey - sx * 0.16)], fill=scale(core, a))
            d.line([(ex + 14, ey), (ex + sx, ey + sx * 0.16)], fill=scale(core, a))


def render(now: float, start_time: float, duration: float, mood_rgb: tuple):
    """One 240x240 frame of the startup animation."""
    global _last_start, _last_age

    duration = max(0.5, float(duration))
    age = max(0.0, now - start_time)
    # Reset the phosphor on a new showing, and also if time runs backwards --
    # start_time is a monotonic clock, but a replay must not inherit the trails.
    if start_time != _last_start or age < _last_age:
        _phos.reset()
    _last_start, _last_age = start_time, age

    u = min(1.0, age / duration)
    img = blank()
    d = ImageDraw.Draw(img)

    # Phase 1 -- the raster strikes.
    if u < _T_STRIKE:
        k = u / _T_STRIKE
        if k < 0.45:
            w = 16 + 200 * (k / 0.45)
            d.line([(CX - w / 2, CY), (CX + w / 2, CY)], fill=GREEN_HI, width=2)
        else:
            kk = (k - 0.45) / 0.55
            h = 2 + 150 * kk
            d.rectangle([CX - 108, CY - h / 2, CX + 108, CY + h / 2], outline=scale(GREEN_DIM, 1 - kk))
            d.line([(CX - 108, CY), (CX + 108, CY)], fill=scale(GREEN_HI, 1 - kk * 0.6), width=2)
        return _phos.compose(img)

    # Phase 2 -- the cog traces in at the rim and spins up. It recedes once the
    # lens is lit so the benediction reads against it.
    cog_k = min(1.0, (u - _T_STRIKE) / (_T_RITE - _T_STRIKE))
    ease = cog_k * cog_k * (3.0 - 2.0 * cog_k)
    spin = math.radians(150.0 * (1.0 - ease) ** 2 + 5.0 * age)
    dim = 1.0 if u < _T_IGNITE else max(0.30, 1.0 - (u - _T_IGNITE) / (1.0 - _T_IGNITE))
    pen = _trace(d, _COG, _COG_LEN * ease, scale(GREEN_MID, dim),
                 spin=spin, grow=0.62 + 0.38 * ease, glow=scale(GREEN_MID, 0.28 * dim))
    if pen is not None:
        d.ellipse([pen[0] - 2, pen[1] - 2, pen[0] + 2, pen[1] + 2], fill=GREEN_HI)

    # Phase 3 -- the rite log has the hub to itself, then clears for the skull.
    if u < _T_RITE:
        span = _T_RITE - _T_STRIKE
        log_u = (u - _T_STRIKE) / span
        fade = min(1.0, (_T_RITE - u) / (0.26 * span))
        _rite_log(d, log_u, fade)
        _graticule(d, log_u, fade)
    else:
        # Phase 4 -- the skull assembles in the space the log left.
        sk = min(1.0, (u - _T_RITE) / (_T_SKULL - _T_RITE))
        sk_ease = sk * sk * (3.0 - 2.0 * sk)
        bone_len = sum(s[2] for s in _BONE)
        target = _SKULL_LEN * sk_ease
        p1 = _trace(d, _BONE, min(target, bone_len), GREEN_HI, glow=scale(GREEN_HI, 0.20))
        p2 = _trace(d, _MACH, target - bone_len, GREEN_MID, glow=scale(GREEN_MID, 0.30)) \
            if target > bone_len else None
        for pt in (p1, p2):
            if pt is not None:
                d.ellipse([pt[0] - 2, pt[1] - 2, pt[0] + 2, pt[1] + 2], fill=GREEN_HI)

    # Phase 5 -- the lens ignites and the benediction holds for the handoff.
    if u >= _T_SKULL:
        _eye(d, (u - _T_SKULL) / (_T_IGNITE - _T_SKULL), mood_rgb, age)
    if u >= _T_IGNITE:
        hold = min(1.0, (u - _T_IGNITE) / (0.25 * (1.0 - _T_IGNITE)))
        f = font(10)
        for i, line in enumerate(_BENEDICTION):
            w = d.textlength(line, font=f)
            d.text((CX - w / 2, 193 + i * 13), line,
                   fill=scale(GREEN_HI if i == 0 else GREEN_MID, hold), font=f)

    return _phos.compose(img)
