"""Warp Core - a 3D reactor column seen through a green-phosphor auspex.

A glass containment column turns slowly in perspective. Containment coils ring
it, energy rings travel out from the pulsing core along its length, and plasma
motes spiral up and down inside. The showing cycles through STABLE, HARMONIC
RESONANCE (standing-wave coil pattern) and RAMP phases; once per cycle a power
surge spikes the output, turns the coils amber and is then damped back down.
"""

from __future__ import annotations

import math
import random

import numpy as np
from PIL import Image, ImageDraw

from ..lore._common import CX, CY, Session, font, safe_half_width
from ._phosphor import AMBER, GREEN, GREEN_DIM, GREEN_FAINT, GREEN_HI, GREEN_MID, RED, Phosphor, blank

NAME = "warp_core"

_rng = random.Random()
_nrng = np.random.default_rng()
_session = Session()
_ph = Phosphor(decay=0.62, bloom=0.6)
_S: dict = {}

CYCLE = 75.0
COL_R = 26.0
COL_H = 66.0
FOV, CAM = 250.0, 270.0
TILT = 0.5
COILS = np.array([-56, -40, -24, 24, 40, 56], np.float32)
N_RING = 40
_ANG = np.linspace(0, 2 * math.pi, N_RING + 1, dtype=np.float32)

# ── text sprites ─────────────────────────────────────────────────────────────
_TXT: dict = {}


def _tsprite(text, size):
    key = (text, size)
    m = _TXT.get(key)
    if m is None:
        if len(_TXT) > 250:
            _TXT.clear()
        f = font(size)
        _, _, r, b = f.getbbox(text)
        im = Image.new("L", (max(1, int(r)) + 2, max(1, int(b)) + 2), 0)
        ImageDraw.Draw(im).text((0, 0), text, fill=255, font=f)
        m = _TXT[key] = (im, f.getlength(text))
    return m


def _text(img, x, y, text, fill, size=11, anchor="c"):
    m, w = _tsprite(text, size)
    if anchor == "c":
        x = x - w / 2
    elif anchor == "r":
        x = x - w
    img.paste(fill, (int(x), int(y)), m)


def _col(c, k):
    k = max(0.0, k)
    return (min(255, int(c[0] * k)), min(255, int(c[1] * k)), min(255, int(c[2] * k)))


# ── geometry ─────────────────────────────────────────────────────────────────


def _xf(x, y, z, yaw):
    c, s = math.cos(yaw), math.sin(yaw)
    x, z = x * c + z * s, -x * s + z * c
    ct, st = math.cos(TILT), math.sin(TILT)
    y, z = y * ct - z * st, y * st + z * ct
    f = FOV / (z + CAM)
    return CX + x * f, CY + y * f, z


def _ring(h, r, yaw):
    x = np.cos(_ANG) * r
    z = np.sin(_ANG) * r
    return _xf(x, np.full_like(x, h), z, yaw)


def _draw_ring(dback, dfront, h, r, yaw, cf, cb, width=1):
    sx, sy, z = _ring(h, r, yaw)
    front = z < 0
    sxl, syl, fl = sx.tolist(), sy.tolist(), front.tolist()
    # split into contiguous runs of front / back
    run = [(sxl[0], syl[0])]
    cur = fl[0]
    for i in range(1, len(sxl)):
        run.append((sxl[i], syl[i]))
        if fl[i] != cur or i == len(sxl) - 1:
            (dfront if cur else dback).line(run, fill=cf if cur else cb, width=width if cur else 1)
            run = [(sxl[i], syl[i])]
            cur = fl[i]


def _build_bg():
    img = blank()
    d = ImageDraw.Draw(img)
    # rim graticule
    for k in range(72):
        a = k * math.pi / 36
        r0 = 104 if k % 6 else 99
        d.line([(CX + r0 * math.cos(a), CY + r0 * math.sin(a)),
                (CX + 108 * math.cos(a), CY + 108 * math.sin(a))], fill=GREEN_DIM if k % 6 else GREEN_MID)
    d.ellipse([CX - 110, CY - 110, CX + 110, CY + 110], outline=GREEN_FAINT)
    # gauge frames (left: output, right: harmonic)
    d.arc([CX - 94, CY - 94, CX + 94, CY + 94], 140, 220, fill=GREEN_DIM)
    d.arc([CX - 94, CY - 94, CX + 94, CY + 94], -40, 40, fill=GREEN_DIM)
    _text(img, CX, 20, "WARP DRIVE PRIMUS", GREEN_MID, 10)
    return img


def _reset():
    _S.clear()
    _S["bg"] = _build_bg()
    _S["yaw"] = _rng.uniform(0, 6.28)
    _S["last"] = None
    n = 70
    _S["pth"] = np.array([_rng.uniform(0, 6.28) for _ in range(n)], np.float32)
    _S["ph"] = np.array([_rng.uniform(-1, 1) for _ in range(n)], np.float32)
    _S["pr"] = np.array([_rng.uniform(4, COL_R - 5) for _ in range(n)], np.float32)
    _S["pv"] = np.array([_rng.uniform(0.25, 0.6) for _ in range(n)], np.float32)
    _S["ring_t"] = 0.0
    _S["surge_at"] = 50.0
    _S["harm"] = 3
    _S["cyc"] = -1
    _S["num"] = (0.0, "")
    _ph.reset()


def _phase(tc):
    if tc < 20:
        return "STABLE"
    if tc < 38:
        return "HARMONIC"
    return "RAMP"


def render(bezel, mask, now: float) -> Image.Image:
    if _session.fresh(now):
        _reset()
    S = _S
    ta = _session.t(now)
    dt = 1 / 30 if S["last"] is None else min(0.1, max(0.0, now - S["last"]))
    S["last"] = now
    cyc = int(ta // CYCLE)
    tc = ta - cyc * CYCLE
    if cyc != S["cyc"]:
        S["cyc"] = cyc
        S["surge_at"] = _rng.uniform(44, 60)
        S["harm"] = _rng.choice((3, 4, 5))
    phase = _phase(tc)
    harm = S["harm"]

    # power model
    base = 0.72 + 0.04 * math.sin(ta * 0.7)
    if phase == "HARMONIC":
        base += 0.08 * min(1.0, (tc - 20) / 4)
    elif phase == "RAMP":
        base += 0.08 + 0.12 * min(1.0, (tc - 38) / 10)
    ds = tc - S["surge_at"]
    surge = 0.0
    if ds > 0:
        surge = 0.62 * math.exp(-ds / 3.2) * math.cos(ds * 2.4)
        if ds > 18:
            base -= 0.2 * min(1.0, (ds - 18) / 6)  # settle back toward stable output
    power = max(0.3, base + surge)
    hot = max(0.0, (power - 1.0) / 0.4)  # 0..1 surge heat
    surging = 0 < ds < 14

    spin = 0.35 + 0.5 * max(0.0, surge)
    S["yaw"] += spin * dt
    yaw = S["yaw"]
    S["ring_t"] += dt * (0.35 + 0.45 * power + 0.8 * max(0.0, surge))

    img = S["bg"].copy()
    d = ImageDraw.Draw(img)
    db = d  # back strokes first, front later on same canvas

    # longerons (4 vertical struts outside the glass)
    strut_pts = []
    for k in range(6):
        a = yaw * 0 + k * math.pi / 3
        x, z = math.cos(a) * (COL_R + 7), math.sin(a) * (COL_R + 7)
        x0, y0, z0 = _xf(x, -COL_H, z, yaw)
        x1, y1, z1 = _xf(x, COL_H, z, yaw)
        strut_pts.append(((x0, y0), (x1, y1), (z0 + z1) * 0.5))
    for p0, p1, zm in strut_pts:
        if zm >= 0:
            d.line([p0, p1], fill=GREEN_DIM)

    # glass silhouette edges
    for side in (-1, 1):
        pts = []
        for h in (-COL_H, COL_H):
            # silhouette tangent point: perpendicular to view dir in xz plane
            x, y, z = _xf(0, h, 0, yaw)
            f = FOV / (z + CAM)
            pts.append((x + side * COL_R * f, y))
        d.line(pts, fill=GREEN_MID)

    # standing wave / travelling energy rings inside column
    rt = S["ring_t"]
    n_e = 4
    energy = []
    for k in range(n_e):
        u = (rt + k / n_e) % 1.0
        h = u * (COL_H - 6)
        b = (1.0 - u) ** 0.7 * (0.6 + 0.5 * power)
        for sgn in (-1, 1):
            energy.append((sgn * (h + 10), b))

    # coils: back halves
    coil_b = []
    for h in COILS.tolist():
        if phase == "HARMONIC":
            sw = abs(math.cos(h / COL_H * harm * math.pi / 2 + 0.0)) * (0.5 + 0.5 * math.cos(ta * 5.0))
            b = 0.45 + 0.75 * sw
        else:
            b = 0.55 + 0.25 * math.sin(ta * 2 + h * 0.05)
        coil_b.append(b)

    front_ops = []
    for h, b in zip(COILS.tolist(), coil_b):
        if hot > 0.05:
            cf = _col(AMBER, 0.5 + 0.5 * hot) if hot < 0.8 else RED
        else:
            cf = _col(GREEN, b)
        front_ops.append((h, COL_R + 3, cf, _col(GREEN_DIM, 0.8 + 0.4 * b), 2))
    # energy rings (inside glass)
    for h, b in energy:
        cf = _col(GREEN_HI, b) if b > 0.85 else _col(GREEN, 0.3 + b)
        front_ops.append((h, COL_R - 4, cf, _col(GREEN_DIM, 0.6 + b), 1))

    # end caps
    front_ops.append((-COL_H, COL_R, GREEN_MID, GREEN_DIM, 1))
    front_ops.append((COL_H, COL_R, GREEN_MID, GREEN_DIM, 1))
    front_ops.append((-COL_H - 6, COL_R + 10, GREEN, GREEN_DIM, 1))
    front_ops.append((COL_H + 6, COL_R + 10, GREEN, GREEN_DIM, 1))

    # draw back halves first (we route front runs to a buffer list)
    deferred = []

    class _Rec:
        def line(self, pts, fill, width=1):
            deferred.append((pts, fill, width))

    rec = _Rec()
    for h, r, cf, cb, w in front_ops:
        _draw_ring(db, rec, h, r, yaw, cf, cb, w)

    # plasma motes spiralling outward from the core
    ph_ = S["ph"]
    sgn = np.sign(ph_)
    ph_ += sgn * S["pv"] * dt * (0.5 + power)
    over = np.abs(ph_) > 1.0
    if over.any():
        ph_[over] = np.sign(ph_[over]) * _nrng.uniform(0.05, 0.2, int(over.sum())).astype(np.float32)
    S["pth"] += dt * (1.2 + power) * sgn
    th, pr = S["pth"], S["pr"]
    hh = ph_ * (COL_H - 4)
    mx, my, mz = _xf(np.cos(th) * pr, hh, np.sin(th) * pr, yaw)
    mb = 1.0 - np.abs(ph_)
    bright = (mb > 0.5).tolist()
    mxl, myl = mx.tolist(), my.tolist()
    hi_pts = [(mxl[i], myl[i]) for i in range(len(mxl)) if bright[i]]
    lo_pts = [(mxl[i], myl[i]) for i in range(len(mxl)) if not bright[i]]
    d.point(lo_pts, fill=GREEN_MID)
    d.point(hi_pts, fill=GREEN_HI)

    # core: pulsing sphere
    pulse = 0.5 + 0.5 * math.sin(ta * (4.0 + 3 * power))
    cr = 12 + 3 * pulse + 10 * max(0.0, surge)
    ccol = GREEN if hot < 0.2 else _col(AMBER, 1.0)
    for k, (rr, c) in enumerate(((cr + 7, _col(GREEN_DIM, 1.2)), (cr, ccol), (cr * 0.6, GREEN_HI))):
        if k == 0:
            d.ellipse([CX - rr, CY - rr * 0.8, CX + rr, CY + rr * 0.8], outline=c)
        else:
            d.ellipse([CX - rr, CY - rr * 0.8, CX + rr, CY + rr * 0.8], fill=c)
    d.ellipse([CX - cr * 0.25, CY - cr * 0.2, CX + cr * 0.25, CY + cr * 0.2], fill=(235, 255, 240))

    # front strokes
    for pts, fill, w in deferred:
        d.line(pts, fill=fill, width=w)
    for p0, p1, zm in strut_pts:
        if zm < 0:
            d.line([p0, p1], fill=GREEN_MID)

    # surge shock ring (screen space)
    if 0 < ds < 1.6:
        rr = 20 + ds * 70
        c = _col(AMBER, 1.0 - ds / 1.6)
        d.ellipse([CX - rr, CY - rr, CX + rr, CY + rr], outline=c, width=2)

    # ── HUD ──
    # output gauge on the left arc (140..220 deg), fills bottom->top
    lvl = min(1.0, power / 1.4)
    nseg = 16
    for k in range(nseg):
        a = math.radians(218 - k * 76 / (nseg - 1))
        on = k / nseg < lvl
        frac = k / nseg
        c = (RED if frac > 0.85 else AMBER if frac > 0.7 else GREEN) if on else GREEN_FAINT
        r0, r1 = 86, 92
        d.line([(CX + r0 * math.cos(a), CY - r0 * math.sin(a)),
                (CX + r1 * math.cos(a), CY - r1 * math.sin(a))], fill=c, width=2)
    # harmonic scope on right: small sine readout
    pts = []
    amp = 5 + 7 * (phase == "HARMONIC") + 10 * max(0.0, surge)
    for k in range(21):
        y = CY - 30 + k * 3
        x = CX + 76 + amp * 0.5 * math.sin(k * 0.6 * harm / 3 + ta * 6)
        pts.append((x, y))
    d.line(pts, fill=GREEN if not surging else AMBER)

    # numeric readouts (quantised for the text cache)
    if ta - S["num"][0] > 0.2 or not S["num"][1]:
        S["num"] = (ta, f"OUTPUT {power * 100:5.1f}%")
    _text(img, CX, 188, S["num"][1], GREEN_HI if not surging else AMBER, 11)
    if surging:
        lab = "SURGE DETECTED" if ds < 3.5 else "DAMPING FIELD"
        c = RED if ds < 3.5 and int(ta * 4) % 2 else AMBER
    elif phase == "HARMONIC":
        lab, c = f"HARMONIC LOCK {harm}", GREEN
    elif phase == "RAMP":
        lab, c = "OUTPUT RAMP", GREEN
    else:
        lab, c = "CONTAINMENT STABLE", GREEN_MID
    _text(img, CX, 202, lab, c, 10)
    _text(img, CX, 32, f"CYCLE {cyc + 1:02d}  T+{int(tc):02d}", GREEN_DIM if not surging else _col(AMBER, 0.6), 9)
    _text(img, 44, 84, "PWR", GREEN_MID, 9)
    _text(img, 196, 84, "HRM", GREEN_MID, 9)
    return _ph.compose(img)
