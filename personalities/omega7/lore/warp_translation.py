"""Warp Translation - a Navigator's view through the Immaterium.

Realspace stars streak into a swirling tunnel of purple, teal and magenta. The
Astronomican burns as a golden beacon that warp currents push off-heading; a
course-correction reticle hauls it back. Warp storms shove the course and batter
the Geller field (a flickering integrity ring), daemonic eyes and talons press
against it, and readouts track Geller integrity, warp tide and the divergence
between ship-time and realspace time. The voyage ends with emergence over the
destination world, then a new translation is plotted.
"""

from __future__ import annotations

import math
import random

import numpy as np
from PIL import Image, ImageDraw

from ._common import CX, CY, Session, font, lerp_color, scale

NAME = "warp_translation"

_rng = random.Random()
_session = Session()

SR = 120  # tunnel is computed at half resolution then upscaled
TW = TH = 128
RING_R = 106.0
GOLD = (255, 205, 90)
HUD = (170, 235, 255)
HUD_DIM = (90, 140, 170)
WARN = (255, 90, 80)

_SYSTEMS = ["CADIA", "MACRAGGE", "BAAL", "ARMAGEDDON", "FENRIS", "NOCTURNE", "VALHALLA",
            "CATACHAN", "RYZA", "OPHELIA VII", "VOSTROYA", "BADAB", "HYDRAPHUR", "KRIEG",
            "BAKKA", "AGRIPINAA", "SCINTILLA", "GUDRUN"]

# half-res pixel centres in full-res units, relative to the panel centre
_g = (np.arange(SR, dtype=np.float32) + 0.5) * (240.0 / SR) - 120.0
GX, GY = np.meshgrid(_g, _g)
# oversized polar grids so the tunnel centre can move by slicing (no per-frame trig)
_M = 26
_gb = (np.arange(SR + 2 * _M, dtype=np.float32) + 0.5 - _M) * (240.0 / SR) - 120.0
_BX, _BY = np.meshgrid(_gb, _gb)
_BR = np.sqrt(_BX * _BX + _BY * _BY) + 0.5
_BTH = (np.arctan2(_BY, _BX) / (2 * math.pi)).astype(np.float32)
_BD = (1600.0 / (_BR + 10.0)).astype(np.float32)
_BB = (np.clip((_BR - 6.0) / 75.0, 0.05, 1.0) ** 0.9).astype(np.float32)
_LUTM = (0.10 + 0.90 * (np.arange(256, dtype=np.float32) / 255.0) ** 1.7).astype(np.float32)

# glow sprite for the Astronomican
_GS = 45
_gy, _gx = np.mgrid[-_GS:_GS + 1, -_GS:_GS + 1].astype(np.float32)
_GR2 = _gx * _gx + _gy * _gy
_GLOW = (np.exp(-_GR2 / (2 * 7.0 ** 2)) * 1.0 + np.exp(-_GR2 / (2 * 20.0 ** 2)) * 0.45)[:, :, None] \
    * np.array([255, 200, 90], np.float32)[None, None, :]

_S: dict = {}


def _tileable_tex(n_waves, ridged):
    u = np.arange(TW, dtype=np.float32)[None, :] / TW
    v = np.arange(TH, dtype=np.float32)[:, None] / TH
    acc = np.zeros((TH, TW), np.float32)
    for _ in range(n_waves):
        fx = _rng.randint(1, 6)
        fy = _rng.randint(-4, 4)
        a = _rng.uniform(0.4, 1.0)
        acc += a * np.sin(2 * math.pi * (fx * u + fy * v) + _rng.uniform(0, 6.28)).astype(np.float32)
    acc /= max(1e-6, float(np.abs(acc).max()))
    if ridged:
        acc = 1.0 - np.abs(acc)
        acc = acc ** 3
    else:
        acc = acc * 0.5 + 0.5
    return (acc * 255).astype(np.int32)


def _palette(stops):
    xs = np.linspace(0, 256, len(stops) + 1)
    cols = np.array(stops + [stops[0]], np.float32)
    i = np.arange(256)
    return np.stack([np.interp(i, xs, cols[:, c]) for c in range(3)], axis=1).astype(np.float32)


def _planet_sprite(R):
    n = 2 * R + 8
    yy, xx = np.mgrid[0:n, 0:n].astype(np.float32)
    dx, dy = (xx - n / 2) / R, (yy - n / 2) / R
    rr = dx * dx + dy * dy
    dz = np.sqrt(np.clip(1 - rr, 0, 1))
    L = np.array([-0.6, -0.35, 0.72])
    L /= np.linalg.norm(L)
    lam = np.clip(dx * L[0] + dy * L[1] + dz * L[2], 0, 1)
    k1, k2 = _rng.uniform(5, 11), _rng.uniform(2, 5)
    tex = 0.7 + 0.3 * np.sin(dy * k1 + np.sin(dx * k2) * 1.8) * np.cos(dx * k2 * 0.7)
    base = np.array(_rng.choice([(70, 120, 200), (170, 120, 80), (90, 160, 110), (160, 150, 140), (200, 90, 60)]), np.float32)
    rgb = base[None, None, :] * (lam * tex)[:, :, None]
    atm = np.clip(1 - np.abs(np.sqrt(rr) - 1.0) / 0.08, 0, 1) * np.clip(lam + 0.25, 0, 1)
    rgb += np.array([90, 160, 255], np.float32)[None, None, :] * atm[:, :, None] * 0.8
    alpha = np.clip((1.04 - np.sqrt(rr)) / 0.04, 0, 1) * 255
    arr = np.dstack([np.clip(rgb, 0, 255), alpha]).astype(np.uint8)
    return Image.fromarray(arr, "RGBA")


def _new_voyage(t):
    origin, dest = _rng.sample(_SYSTEMS, 2)
    D = _rng.uniform(112, 132)
    warp_start, warp_end = 11.0, D - 13.0
    storms = []
    n = _rng.randint(1, 3)
    slots = sorted(_rng.uniform(warp_start + 12, warp_end - 12) for _ in range(n))
    last = -99
    for s in slots:
        if s - last > 16:
            storms.append(dict(t=t + s, dur=_rng.uniform(7, 11), dir=_rng.uniform(0, 2 * math.pi),
                               power=_rng.uniform(0.7, 1.0)))
            last = s
    daemons = []
    for _ in range(_rng.randint(2, 3)):
        side = _rng.choice([0.0, math.pi])
        daemons.append(dict(t=t + _rng.uniform(warp_start + 8, warp_end - 12), dur=_rng.uniform(7, 11),
                            ang=side + _rng.uniform(-0.75, 0.75), kind=_rng.choice(["eye", "eye", "maw"]),
                            seen=False))
    variant = _rng.randrange(3)
    if variant == 0:
        stops = [(35, 0, 60), (170, 30, 170), (40, 190, 190), (10, 20, 70), (120, 20, 140), (230, 90, 220)]
    elif variant == 1:
        stops = [(10, 30, 60), (30, 170, 180), (150, 30, 170), (20, 10, 50), (90, 220, 210), (200, 60, 200)]
    else:
        stops = [(40, 5, 50), (210, 50, 150), (60, 120, 200), (15, 5, 40), (150, 40, 200), (60, 210, 180)]
    storm_stops = [(60, 0, 10), (220, 40, 60), (120, 0, 90), (30, 0, 20), (255, 110, 60), (160, 20, 120)]
    stars = np.stack([np.array([_rng.uniform(-100, 100) for _ in range(260)]),
                      np.array([_rng.uniform(-100, 100) for _ in range(260)]),
                      np.array([_rng.uniform(4, 100) for _ in range(260)])], axis=1).astype(np.float32)
    _S.update(
        t0=t, D=D, ws=t + warp_start, we=t + warp_end, origin=origin, dest=dest,
        storms=storms, daemons=daemons,
        tex1=_tileable_tex(7, True), tex2=_tileable_tex(5, False),
        pal_c=_palette(stops), pal_s=_palette(storm_stops),
        spd=_rng.uniform(0.35, 0.5), rot=_rng.uniform(0.02, 0.05) * _rng.choice([-1, 1]),
        twist=_rng.uniform(0.6, 1.4) * _rng.choice([-1, 1]),
        cur=[_rng.uniform(0.07, 0.16), _rng.uniform(0.05, 0.13), _rng.uniform(0, 6.28), _rng.uniform(0, 6.28)],
        err=np.zeros(2), errv=np.zeros(2), geller=1.0, tide=_rng.uniform(1.2, 2.5),
        ship_days=0.0, real_days=0.0, stars=stars,
        planet=_planet_sprite(64), pl_pos=(_rng.uniform(-35, 35), _rng.uniform(-30, 20)),
        msg=None, last_msg_t=-99.0, shake=0.0,
    )


def _reset():
    _S.clear()
    _S["last_t"] = 0.0
    _new_voyage(0.0)


def _msg(text, col, t):
    _S["msg"] = (text, col, t)


# --------------------------------------------------------------------------- simulation

def _storm_level(t):
    lvl, st = 0.0, None
    for s in _S["storms"]:
        u = (t - s["t"]) / s["dur"]
        if 0 <= u <= 1:
            e = min(1.0, u / 0.15, (1 - u) / 0.25) * s["power"]
            if e > lvl:
                lvl, st = e, s
    return lvl, st


def _update(t, dt):
    S = _S
    ws, we = S["ws"], S["we"]
    in_warp = ws <= t <= we
    storm, st = _storm_level(t)
    S["storm"] = storm
    if in_warp:
        # warp currents + storm shoves push the heading off the Astronomican; the helm corrects
        c = S["cur"]
        f = np.array([math.sin(t * c[0] + c[2]) + 0.6 * math.sin(t * 0.31 + c[3]),
                      math.cos(t * c[1] + c[3]) + 0.5 * math.sin(t * 0.23 + c[2])]) * 9.0
        if st is not None:
            f += np.array([math.cos(st["dir"]), math.sin(st["dir"])]) * 55.0 * storm
            f += np.array([_rng.uniform(-1, 1), _rng.uniform(-1, 1)]) * 60.0 * storm
        e = S["err"]
        k = 0.9 if np.linalg.norm(e) > 12 else 0.35  # helm works harder once off-course
        S["errv"] = S["errv"] * (1 - 2.2 * dt) + (f - k * e) * dt
        S["err"] = e + S["errv"] * dt * 3.0
        n = float(np.linalg.norm(S["err"]))
        if n > 68:
            S["err"] *= 68 / n
        # Geller field: storms and daemons batter it, it recovers slowly
        press = sum(_daemon_press(dm, t) for dm in S["daemons"])
        drain = storm * 0.045 + press * 0.025
        S["geller"] = min(1.0, max(0.22, S["geller"] - drain * dt + (0.022 if drain < 0.005 else 0.006) * dt))
        target_tide = 1.6 + 1.2 * math.sin(t * 0.07 + c[2]) ** 2 + storm * 6.5
        S["tide"] += (target_tide - S["tide"]) * min(1.0, dt * 1.5)
        S["ship_days"] += dt * 0.22
        S["real_days"] += dt * 0.22 * (4 + S["tide"] * 3.2 + 6 * math.sin(t * 0.13) ** 2)
        S["shake"] = storm
        # announcements
        if storm > 0.3 and t - S["last_msg_t"] > 5:
            _msg("WARP STORM - HOLD COURSE", WARN, t)
            S["last_msg_t"] = t
        for dm in S["daemons"]:
            if not dm["seen"] and t >= dm["t"] + 1.0:
                dm["seen"] = True
                _msg(_rng.choice(["INCURSION WARNING", "DO NOT LOOK UPON IT", "ENTITY AT THE FIELD"]), WARN, t)
                S["last_msg_t"] = t
        if n > 16 and t - S["last_msg_t"] > 6:
            _msg("COURSE CORRECTION", GOLD, t)
            S["last_msg_t"] = t
    else:
        S["shake"] = 0.0
    if t - S["t0"] > S["D"]:
        _new_voyage(t)


def _daemon_press(dm, t):
    u = (t - dm["t"]) / dm["dur"]
    if u < 0 or u > 1:
        return 0.0
    return min(1.0, u / 0.2, (1 - u) / 0.2)


# --------------------------------------------------------------------------- rendering

def _tunnel(t, ox, oy, storm, alpha):
    S = _S
    ix = int(round(_M - ox * SR / 240.0))
    iy = int(round(_M - oy * SR / 240.0))
    ix = min(2 * _M, max(0, ix))
    iy = min(2 * _M, max(0, iy))
    sl = (slice(iy, iy + SR), slice(ix, ix + SR))
    depth = _BD[sl]
    u = _BTH[sl] + (t * S["rot"]) + depth * (0.0025 * S["twist"])
    if storm > 0.01:
        u = u + (storm * 0.08) * np.sin(depth * 0.6 + t * 7.0)
    v = depth * 0.035 + t * S["spd"] * (1 + storm * 1.5)
    iu = (u * TW).astype(np.int32) & (TW - 1)
    iv = (v * TH).astype(np.int32) & (TH - 1)
    m = S["tex1"][iv, iu]
    ci = (S["tex2"][(iv >> 1) + 11 & (TH - 1), iu] + (depth * 3.0).astype(np.int32) + int(t * 18)) & 255
    pal = S["pal_c"] if storm < 0.01 else S["pal_c"] * (1 - storm) + S["pal_s"] * storm
    bright = _LUTM[m] * _BB[sl] * (alpha * (1 + 0.5 * storm))
    # dark shadows where daemons press on the field
    for dm in S["daemons"]:
        pr = _daemon_press(dm, t)
        if pr > 0:
            ex, ey = math.cos(dm["ang"]) * 96, math.sin(dm["ang"]) * 96
            bright = bright * (1 - 0.75 * pr * np.exp(-((GX - ex) ** 2 + (GY - ey) ** 2) * (1.0 / (2 * 30.0 ** 2))))
    col = pal[ci] * bright[:, :, None]
    small = Image.fromarray(col.astype(np.uint8), "RGB")
    return np.array(small.resize((240, 240), Image.BILINEAR))


def _add_glow(arr, x, y, k):
    x, y = int(x), int(y)
    x0, y0 = x - _GS, y - _GS
    x1, y1 = x + _GS + 1, y + _GS + 1
    sx0, sy0 = max(0, -x0), max(0, -y0)
    sx1, sy1 = _GLOW.shape[1] - max(0, x1 - 240), _GLOW.shape[0] - max(0, y1 - 240)
    if sx1 <= sx0 or sy1 <= sy0:
        return
    reg = arr[max(0, y0):min(240, y1), max(0, x0):min(240, x1)]
    reg[:] = np.minimum(reg + _GLOW[sy0:sy1, sx0:sx1] * k, 255).astype(np.uint8)


def _stars(d, t, speed, streak, tint):
    S = _S
    st = S["stars"]
    st[:, 2] -= speed * S.get("dt", 0.033)
    wrap = st[:, 2] < 1.5
    if wrap.any():
        st[wrap, 2] += 98.0
    z = st[:, 2]
    x1 = CX + st[:, 0] / z * 60
    y1 = CY + st[:, 1] / z * 60
    z2 = z + streak
    x2 = CX + st[:, 0] / z2 * 60
    y2 = CY + st[:, 1] / z2 * 60
    b = np.clip(1.4 - z / 80.0, 0.15, 1.0)
    rows = np.column_stack([x1, y1, x2, y2, b]).tolist()
    for a1, b1, a2, b2, k in rows:
        c = scale(tint, k)
        if streak > 0.4:
            d.line((a2, b2, a1, b1), fill=c)
        else:
            d.point((a1, b1), fill=c)


# --------------------------------------------------------------------------- cached text
# FreeType text (especially with an outline stroke) costs ~2 ms per call on the Pi, so glyph
# masks are rendered once and pasted. Strings with digits (live readouts) are composed per glyph.
_TXT: dict = {}


def _masks(s, size):
    key = (s, size)
    m = _TXT.get(key)
    if m is None:
        f = font(size)
        l, tp, r, b = f.getbbox(s, stroke_width=2)
        w, h = max(1, r - l), max(1, b - tp)
        fm = Image.new("L", (w, h), 0)
        ImageDraw.Draw(fm).text((-l, -tp), s, font=f, fill=255)
        sm = Image.new("L", (w, h), 0)
        ImageDraw.Draw(sm).text((-l, -tp), s, font=f, fill=255, stroke_width=2, stroke_fill=255)
        m = (fm, sm, l, tp, f.getlength(s))
        if len(_TXT) > 500:
            _TXT.clear()
        _TXT[key] = m
    return m


def _pieces(s, size):
    if any(c.isdigit() for c in s):
        out, x = [], 0.0
        for c in s:
            m = _masks(c, size)
            out.append((x, m))
            x += m[4]
        return out, x
    m = _masks(s, size)
    return [(0.0, m)], m[4]


def _tw(s, size):
    return _pieces(s, size)[1]


def _text(img, x, y, s, fill, size=11, outline=True):
    parts, _w = _pieces(s, size)
    if outline:
        for dx, (fm, sm, l, tp, adv) in parts:
            img.paste((0, 0, 0), (int(x + dx + l), int(y + tp)), sm)
    for dx, (fm, sm, l, tp, adv) in parts:
        img.paste(fill, (int(x + dx + l), int(y + tp)), fm)


def _tc(img, y, s, fill, size=11, outline=True):
    _text(img, CX - _tw(s, size) / 2, y, s, fill, size, outline)


def _fmt_days(days):
    if days >= 365:
        return f"{int(days // 365)}Y {int(days % 365):03d}D"
    return f"{days:5.1f}D"


def _draw_ring(d, t, g, jx, jy):
    S = _S
    n = 72
    angs = np.linspace(0, 2 * math.pi, n + 1)
    rr = np.full(n + 1, RING_R)
    for dm in S["daemons"]:
        pr = _daemon_press(dm, t)
        if pr > 0:
            da = (angs - dm["ang"] + math.pi) % (2 * math.pi) - math.pi
            rr -= 16 * pr * np.exp(-(da / 0.28) ** 2)
    wob = 1.5 * S["storm"] * np.sin(angs * 7 + t * 13)
    rr = rr + wob
    xs = CX + jx + np.cos(angs) * rr
    ys = CY + jy + np.sin(angs) * rr
    pulse = 0.75 + 0.25 * math.sin(t * 3.1)
    base = lerp_color((255, 80, 70), (140, 230, 255), (g - 0.2) / 0.6)
    pts = np.column_stack([xs, ys]).tolist()
    for i in range(n):
        if _rng.random() > 0.35 + 0.65 * g ** 0.7:
            continue
        k = pulse * (0.6 + 0.4 * _rng.random() if g < 0.7 else 1.0)
        d.line((pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1]), fill=scale(base, k), width=2)
    # inner faint ward ring with runic ticks
    r2 = RING_R - 6
    for i in range(0, 36):
        a = i / 36 * 2 * math.pi + t * 0.05
        x, y = CX + jx + math.cos(a) * r2, CY + jy + math.sin(a) * r2
        x2, y2 = CX + jx + math.cos(a) * (r2 - (3 if i % 3 else 5)), CY + jy + math.sin(a) * (r2 - (3 if i % 3 else 5))
        d.line((x, y, x2, y2), fill=scale(base, 0.45 * g))


def _draw_daemon(d, dm, t, jx, jy):
    pr = _daemon_press(dm, t)
    if pr <= 0:
        return
    a = dm["ang"]
    ca, sa = math.cos(a), math.sin(a)
    tx, ty = -sa, ca  # tangent
    R = 100 - 16 * pr
    ex, ey = CX + jx + ca * R, CY + jy + sa * R
    # talons/tendrils reaching in from beyond the field
    for k in (-1, 0, 1):
        pts = []
        for j in range(7):
            s = j / 6
            rad = 128 - s * (30 + 12 * pr)
            off = k * (16 - 6 * s) + 4 * math.sin(t * 3 + j + k * 2)
            pts.append((CX + jx + ca * rad + tx * off, CY + jy + sa * rad + ty * off))
        d.line(pts, fill=(70, 10, 70), width=3)
        d.line(pts, fill=(160, 40, 130), width=1)
    if dm["kind"] == "eye":
        blink = abs(math.sin(t * 0.9 + a)) ** 0.3
        wv = 18 * (0.6 + 0.4 * pr)
        hv = 8 * blink * pr + 0.5
        pts = []
        for j in range(13):
            s = -1 + 2 * j / 12
            pts.append((ex + tx * s * wv - ca * (1 - s * s) * hv, ey + ty * s * wv - sa * (1 - s * s) * hv))
        for j in range(11, 0, -1):
            s = -1 + 2 * j / 12
            pts.append((ex + tx * s * wv + ca * (1 - s * s) * hv, ey + ty * s * wv + sa * (1 - s * s) * hv))
        d.polygon(pts, fill=(60, 0, 20), outline=(220, 60, 60))
        ir = min(hv, 7.5)
        if ir > 1.5:
            d.ellipse((ex - ir, ey - ir, ex + ir, ey + ir), fill=(255, int(150 + 80 * pr), 40))
            # slit pupil along the radial axis
            px, py = tx * 1.2, ty * 1.2
            d.polygon([(ex - ca * ir, ey - sa * ir), (ex + px, ey + py), (ex + ca * ir, ey + sa * ir), (ex - px, ey - py)],
                      fill=(20, 0, 0))
    else:
        # a fanged maw pressing against the field
        wv, hv = 16 * pr, 6 + 4 * abs(math.sin(t * 2.3))
        top, bot = [], []
        for j in range(9):
            s = -1 + 2 * j / 8
            top.append((ex + tx * s * wv - ca * (1 - s * s) * hv, ey + ty * s * wv - sa * (1 - s * s) * hv))
            bot.append((ex + tx * s * wv + ca * (1 - s * s) * hv * 0.6, ey + ty * s * wv + sa * (1 - s * s) * hv * 0.6))
        d.polygon(top + bot[::-1], fill=(40, 0, 10), outline=(200, 60, 90))
        for j in range(1, 8):
            x0, y0 = top[j]
            d.line((x0, y0, x0 + ca * 4, y0 + sa * 4), fill=(240, 220, 200))
            x0, y0 = bot[j]
            d.line((x0, y0, x0 - ca * 3, y0 - sa * 3), fill=(240, 220, 200))


def _draw_reticle(d, t, bx, by, jx, jy, locked):
    col = (140, 255, 170) if locked else GOLD
    c = (CX + jx, CY + jy)
    r = 15
    for q in range(4):
        a0 = q * 90 + 20
        d.arc((c[0] - r, c[1] - r, c[0] + r, c[1] + r), a0, a0 + 50, fill=col, width=1)
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        d.line((c[0] + dx * 19, c[1] + dy * 19, c[0] + dx * 25, c[1] + dy * 25), fill=col)
    d.point(c, fill=col)
    # heading error indicator: dotted guide to the beacon + diamond
    ex, ey = bx - c[0], by - c[1]
    dist = math.hypot(ex, ey)
    if dist > 20:
        n = int(dist / 6)
        for i in range(2, n):
            s = i / n
            d.point((c[0] + ex * s, c[1] + ey * s), fill=scale(GOLD, 0.8))
    m = 6
    d.polygon([(bx, by - m - 3), (bx + m + 3, by), (bx, by + m + 3), (bx - m - 3, by)], outline=scale(GOLD, 0.9))


def render(bezel, mask, now: float) -> Image.Image:
    if _session.fresh(now):
        _reset()
    t = _session.t(now)
    dt = min(0.1, max(0.0, t - _S.get("last_t", t)))
    _S["last_t"] = t
    _S["dt"] = dt
    _update(t, dt)
    S = _S
    lt = t - S["t0"]
    ws, we = S["ws"] - S["t0"], S["we"] - S["t0"]
    D = S["D"]
    storm = S.get("storm", 0.0)
    shake = S["shake"]
    jx = _rng.uniform(-2.5, 2.5) * shake
    jy = _rng.uniform(-2.5, 2.5) * shake

    err = S["err"]
    ox, oy = -err[0] * 0.35 + 4 * math.sin(t * 0.37), -err[1] * 0.35 + 4 * math.cos(t * 0.29)

    # --- choose phase
    if lt < ws - 4:
        phase = "real"
    elif lt < ws:
        phase = "entry"
    elif lt < we:
        phase = "warp"
    elif lt < we + 4:
        phase = "exit"
    else:
        phase = "arrive"

    if phase in ("warp", "entry", "exit"):
        if phase == "entry":
            alpha = max(0.0, (lt - (ws - 1.5)) / 1.5)
        elif phase == "exit":
            alpha = max(0.0, 1 - (lt - we) / 2.5)
        else:
            alpha = min(1.0, (lt - ws) / 1.0 + 0.6)
        if alpha > 0.01:
            arr = _tunnel(t, ox + jx, oy + jy, storm, alpha)
        else:
            arr = np.zeros((240, 240, 3), np.uint8)
    else:
        arr = np.zeros((240, 240, 3), np.uint8)

    beacon = None
    if phase == "warp" or (phase == "entry" and lt > ws - 0.5):
        vis = 1.0 - 0.6 * storm
        flick = 0.85 + 0.15 * math.sin(t * 5.0) if storm < 0.2 else _rng.uniform(0.3, 1.0)
        bx, by = CX + err[0] + jx, CY + err[1] + jy
        _add_glow(arr, bx, by, vis * flick * (0.8 + 0.2 * math.sin(t * 2.2)) * min(1.0, (lt - ws + 0.5) / 2.0))
        beacon = (bx, by, vis * flick)

    # flash at translation boundaries
    for tb in (ws, we + 0.5):
        u = abs(lt - tb)
        if u < 0.6:
            k = (1 - u / 0.6) ** 2
            arr = np.minimum(arr.astype(np.int16) + int(220 * k), 255).astype(np.uint8)

    img = Image.fromarray(arr, "RGB")
    d = ImageDraw.Draw(img)

    # --- realspace star layer
    if phase == "real":
        spd = 2.0 + max(0.0, lt - (ws - 9)) * 3.0
        _stars(d, t, spd, 0.0 if spd < 5 else min(8, spd * 0.15), (220, 225, 255))
    elif phase == "entry":
        u = (lt - (ws - 4)) / 4.0
        spd = 20 + 160 * u * u
        _stars(d, t, spd, 2 + 40 * u, lerp_color((220, 225, 255), (220, 120, 255), u))
    elif phase == "exit":
        u = (lt - we) / 4.0
        if u > 0.45:
            v = (u - 0.45) / 0.55
            spd = 150 * (1 - v) + 3
            _stars(d, t, spd, max(0.0, 35 * (1 - v)), lerp_color((220, 120, 255), (220, 225, 255), v))
    elif phase == "arrive":
        u = min(1.0, (lt - we - 4) / (D - we - 4))
        # destination world swells into view
        R = int(24 + 44 * (1 - (1 - u) ** 2))
        sp = S["planet"].resize((2 * R + 8, 2 * R + 8), Image.BILINEAR)
        px, py = CX + S["pl_pos"][0], CY + S["pl_pos"][1] + 10
        _stars(d, t, 1.5, 0.0, (200, 205, 230))
        img.paste(sp, (int(px - R - 4), int(py - R - 4)), sp)
        d = ImageDraw.Draw(img)

    # --- warp overlays
    g = S["geller"]
    if phase in ("warp", "exit", "entry"):
        ring_on = 1.0 if phase == "warp" else (max(0.0, 1 - (lt - we) / 3.0) if phase == "exit" else min(1.0, (lt - (ws - 4)) / 3))
        if ring_on > 0.05:
            _draw_ring(d, t, g * ring_on + 0.2 * (1 - ring_on), jx, jy)
    if phase == "warp" and storm > 0.25 and _rng.random() < 0.35 * storm:
        # warp lightning arcing across the tunnel
        a = _rng.uniform(0, 2 * math.pi)
        pts = []
        for j in range(8):
            rad = 112 - j * 11
            a += _rng.uniform(-0.18, 0.18)
            pts.append((CX + jx + math.cos(a) * rad, CY + jy + math.sin(a) * rad))
        d.line(pts, fill=(200, 120, 255), width=3)
        d.line(pts, fill=(255, 235, 255), width=1)
    if phase == "warp":
        for dm in S["daemons"]:
            _draw_daemon(d, dm, t, jx, jy)
        if beacon:
            bx, by, bk = beacon
            for i in range(6):
                a = i * math.pi / 3 + t * 0.2
                ln = (14 + 8 * math.sin(t * 3 + i)) * bk
                d.line((bx, by, bx + math.cos(a) * ln, by + math.sin(a) * ln), fill=scale((255, 230, 150), bk))
            d.ellipse((bx - 3, by - 3, bx + 3, by + 3), fill=(255, 250, 225))
            locked = math.hypot(err[0], err[1]) < 7
            _draw_reticle(d, t, bx, by, jx, jy, locked)

    # --- HUD
    msg = S["msg"]
    if phase == "real":
        _tc(img, 30, "TRANSLATION PROTOCOL", HUD, 11)
        _tc(img, 46, "ORIGIN " + S["origin"], HUD_DIM, 9)
        _tc(img, 58, "DEST " + S["dest"], HUD_DIM, 9)
        cnt = max(0, int(ws - lt) + 1)
        if lt > 1.5:
            _tc(img, 170, "GELLER FIELD ENGAGED", (140, 230, 255), 10)
        _tc(img, 186, f"WARP JUMP IN {cnt}", GOLD, 12)
    elif phase == "entry":
        if int(lt * 6) % 2 == 0:
            _tc(img, 186, "TRANSLATING", (230, 140, 255), 12)
    elif phase == "warp":
        gp = g * 100
        gcol = HUD if g > 0.6 else (WARN if int(t * 4) % 2 else (150, 60, 50))
        _tc(img, 28, f"GELLER  {gp:4.1f}%", gcol, 10)
        tide = S["tide"]
        state = "CALM" if tide < 2.5 else ("SWELL" if tide < 4.5 else "STORM")
        _tc(img, 41, f"WARP TIDE {tide:3.1f} {state}", WARN if state == "STORM" else HUD_DIM, 9)
        _tc(img, 170, f"SHIP-TIME {_fmt_days(S['ship_days'])}", HUD, 10)
        _tc(img, 183, f"REALSPACE +{_fmt_days(S['real_days'])}", (230, 170, 255), 10)
        _tc(img, 197, "BOUND FOR " + S["dest"], HUD_DIM, 9)
        if msg and t - msg[2] < 2.6:
            on = (t - msg[2]) > 0.6 or int((t - msg[2]) * 8) % 2 == 0
            if on:
                _tc(img, 60, msg[0], msg[1], 10)
    elif phase == "exit":
        if int(lt * 5) % 2 == 0:
            _tc(img, 186, "REALSPACE EMERGENCE", (140, 230, 255), 11)
    else:
        u = lt - we - 4
        _tc(img, 26, "TRANSLATION COMPLETE", (140, 255, 170), 11)
        if u > 1.0:
            _tc(img, 40, "ARRIVED " + S["dest"], GOLD, 11)
        if u > 2.5:
            _tc(img, 176, f"SHIP-TIME {_fmt_days(S['ship_days'])}", HUD, 10)
            _tc(img, 189, f"REALSPACE +{_fmt_days(S['real_days'])}", (230, 170, 255), 10)
        if u > 4:
            _tc(img, 203, "THE EMPEROR GUIDES", HUD_DIM, 9)

    # fade in/out at the ends of a voyage
    k = min(1.0, lt / 0.8, (D - lt) / 1.0)
    if k < 1.0:
        img = Image.fromarray((np.asarray(img) * max(0.0, k)).astype(np.uint8), "RGB")
    return img
