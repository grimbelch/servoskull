"""Orbitals - a tilted 3D orbital auspex.

A wireframe planet (turning latitude/longitude graticule, faint ring) sits in a
perspective-tilted system of three moons on Keplerian orbits that pass
correctly in front of and behind it. A voidship flies Hohmann transfers between
a low and a high parking orbit (burns flare amber, the arrival point is marked),
the outer moon's L4/L5 points are marked, and a tracking bracket cycles through
the bodies with period readouts. Transits and occultations are called out.
"""

from __future__ import annotations

import math
import random

import numpy as np
from PIL import Image, ImageDraw

from ..lore._common import CX, CY, Session, font
from ._phosphor import AMBER, GREEN, GREEN_DIM, GREEN_FAINT, GREEN_HI, GREEN_MID, RED, Phosphor, blank

NAME = "orbitals"

_rng = random.Random()
_session = Session()
_ph = Phosphor(decay=0.74, bloom=0.5)
_S: dict = {}

FOV, CAM = 410.0, 420.0
PR = 24.0                 # planet radius
T_REF, R_REF = 15.0, 48.0  # Kepler: period(r) = T_REF * (r/R_REF)^1.5
R_LO, R_HI = 36.0, 78.0
MOONS = [("PRIMUS", 48.0, 4.2), ("SECUNDUS", 64.0, 5.0), ("TERTIUS", 90.0, 6.0)]
PLANETS = ["KNOSSOS IV", "VALHALLA", "ARMAGEDDON", "CALTH", "PHALANX-VII", "MARS"]

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


def _period(r):
    return T_REF * (r / R_REF) ** 1.5


class _View:
    def __init__(self, yaw, tilt):
        self.cy, self.sy = math.cos(yaw), math.sin(yaw)
        self.ct, self.st = math.cos(tilt), math.sin(tilt)

    def p(self, x, y, z):
        """world (orbit plane = xz, y up-ish) -> screen x, y, depth (neg = near)."""
        x, z = x * self.cy + z * self.sy, -x * self.sy + z * self.cy
        y, z = y * self.ct - z * self.st, y * self.st + z * self.ct
        f = FOV / (z + CAM)
        return CX + x * f, CY + y * f, z


_ANG = np.linspace(0, 2 * math.pi, 73, dtype=np.float32)


def _runs(sx, sy, front):
    """Split a projected polyline into (points, is_front) runs."""
    sxl, syl, fl = sx.tolist(), sy.tolist(), front.tolist()
    out = []
    run = [(sxl[0], syl[0])]
    cur = fl[0]
    for i in range(1, len(sxl)):
        run.append((sxl[i], syl[i]))
        if fl[i] != cur or i == len(sxl) - 1:
            out.append((run, cur))
            run = [(sxl[i], syl[i])]
            cur = fl[i]
    return out


def _build_bg():
    img = blank()
    d = ImageDraw.Draw(img)
    rr = _rng
    for _ in range(40):
        a = rr.uniform(0, 6.283)
        r = 112 * math.sqrt(rr.random())
        d.point((CX + r * math.cos(a), CY + r * math.sin(a)), fill=GREEN_DIM if rr.random() < 0.3 else GREEN_FAINT)
    for k in range(36):
        a = k * math.pi / 18
        r0 = 103 if k % 3 else 99
        d.line([(CX + r0 * math.cos(a), CY + r0 * math.sin(a)),
                (CX + 107 * math.cos(a), CY + 107 * math.sin(a))], fill=GREEN_DIM)
    return img


def _reset():
    _S.clear()
    _S["bg"] = _build_bg()
    _S["last"] = None
    _S["m0"] = [_rng.uniform(0, 6.28) for _ in MOONS]
    _S["planet"] = _rng.choice(PLANETS)
    _S["yaw0"] = _rng.uniform(0, 6.28)
    # ship state machine
    _S["ship"] = {"mode": "PARK_LO", "t0": 0.0, "a0": _rng.uniform(0, 6.28), "dur": _rng.uniform(8, 14)}
    _S["trail"] = []
    _S["burn"] = -10.0
    _S["event"] = ("", -10.0)
    _S["nxfer"] = 0
    _ph.reset()


def _kepler_true(M, e):
    E = M
    for _ in range(6):
        E = E - (E - e * math.sin(E) - M) / (1 - e * math.cos(E))
    return 2 * math.atan2(math.sqrt(1 + e) * math.sin(E / 2), math.sqrt(1 - e) * math.cos(E / 2)), E


def _ship_pos(t):
    """Advance the ship state machine; return (r, angle, mode)."""
    sh = _S["ship"]
    a_t = (R_LO + R_HI) / 2
    e = (R_HI - R_LO) / (R_HI + R_LO)
    T_x = _period(a_t) / 2
    while True:
        m, t0, a0, dur = sh["mode"], sh["t0"], sh["a0"], sh["dur"]
        dt = t - t0
        if m in ("PARK_LO", "PARK_HI"):
            r = R_LO if m == "PARK_LO" else R_HI
            w = 2 * math.pi / _period(r)
            if dt < dur:
                return r, a0 + w * dt, m
            nxt = "XFER_UP" if m == "PARK_LO" else "XFER_DN"
            _S["ship"] = sh = {"mode": nxt, "t0": t0 + dur, "a0": a0 + w * dur, "dur": T_x}
            _S["burn"] = t0 + dur
            _S["nxfer"] += 1
            continue
        # transfer half-ellipse
        if dt < dur:
            M = math.pi * dt / dur
            if m == "XFER_UP":
                nu, E = _kepler_true(M, e)
                r = a_t * (1 - e * math.cos(E))
                return r, a0 + nu, m
            nu, E = _kepler_true(M + math.pi, e)
            r = a_t * (1 - e * math.cos(E))
            return r, a0 + nu - math.pi, m
        nxt = "PARK_HI" if m == "XFER_UP" else "PARK_LO"
        _S["ship"] = sh = {"mode": nxt, "t0": t0 + dur, "a0": a0 + math.pi,
                           "dur": _rng.uniform(18, 30) if nxt == "PARK_HI" else _rng.uniform(10, 16)}
        _S["burn"] = t0 + dur


def render(bezel, mask, now: float) -> Image.Image:
    if _session.fresh(now):
        _reset()
    S = _S
    ta = _session.t(now)
    S["last"] = now

    yaw = S["yaw0"] + ta * 0.045
    tilt = 0.52 + 0.13 * math.sin(ta * 0.05)
    V = _View(yaw, tilt)

    img = S["bg"].copy()
    d = ImageDraw.Draw(img)
    front_ops = []  # deferred drawing callables' data for things in front of the planet

    # ── orbits ──
    orbit_list = [(r, GREEN_DIM, GREEN_MID) for _, r, _ in MOONS]
    orbit_list += [(R_LO, GREEN_FAINT, GREEN_DIM), (R_HI, GREEN_FAINT, GREEN_DIM)]
    cosA, sinA = np.cos(_ANG), np.sin(_ANG)
    for r, cb, cf in orbit_list:
        sx, sy, sz = V.p(cosA * r, 0 * cosA, sinA * r)
        for run, fr in _runs(sx, sy, sz < 0):
            if fr:
                front_ops.append(("line", run, cf, 1))
            else:
                d.line(run, fill=cb)

    # planetary ring (two thin ellipses)
    for r, c in ((PR * 1.55, GREEN_DIM), (PR * 1.8, GREEN_FAINT)):
        sx, sy, sz = V.p(cosA * r, 0 * cosA, sinA * r)
        for run, fr in _runs(sx, sy, sz < 0):
            if fr:
                front_ops.append(("line", run, _col(GREEN_MID, 0.9) if c == GREEN_DIM else GREEN_DIM, 1))
            else:
                d.line(run, fill=c)

    # transfer ellipse preview + target marker
    sh = S["ship"]
    r_s, a_s, mode = _ship_pos(ta)
    a_t = (R_LO + R_HI) / 2
    e = (R_HI - R_LO) / (R_HI + R_LO)
    if mode.startswith("XFER"):
        base = sh["a0"] if mode == "XFER_UP" else sh["a0"] - math.pi
        nus = np.linspace(0, 2 * math.pi, 49, dtype=np.float32)
        rr = a_t * (1 - e * e) / (1 + e * np.cos(nus))
        ang = base + nus
        sx, sy, sz = V.p(np.cos(ang) * rr, 0 * rr, np.sin(ang) * rr)
        sxl, syl = sx.tolist(), sy.tolist()
        for i in range(0, 48, 2):
            d.line([(sxl[i], syl[i]), (sxl[i + 1], syl[i + 1])], fill=GREEN_DIM)
        tgt_a = sh["a0"] + math.pi
        tr = R_HI if mode == "XFER_UP" else R_LO
        tx, ty, tz = V.p(math.cos(tgt_a) * tr, 0, math.sin(tgt_a) * tr)
        blink = int(ta * 3) % 2
        c = AMBER if blink else _col(AMBER, 0.5)
        front_ops.append(("tgt", (tx, ty), c, 0))

    # ── bodies ──
    bodies = []  # (name, sx, sy, depth, radius_px, kind)
    for (name, r, sz0), m0 in zip(MOONS, S["m0"]):
        a = m0 + 2 * math.pi * ta / _period(r)
        inc = 0.08 * (r / 50)
        x, z = math.cos(a) * r, math.sin(a) * r
        y = math.sin(a) * r * inc
        px, py, pz = V.p(x, y, z)
        rad = sz0 * FOV / (pz + CAM)
        bodies.append((name, px, py, pz, rad, "moon", r))
    # Lagrange points of the outer moon
    name3, r3 = MOONS[2][0], MOONS[2][1]
    a3 = S["m0"][2] + 2 * math.pi * ta / _period(r3)
    for lab, off in (("L4", math.pi / 3), ("L5", -math.pi / 3)):
        lx, ly, lz = V.p(math.cos(a3 + off) * r3, math.sin(a3 + off) * r3 * 0.16, math.sin(a3 + off) * r3)
        front_ops.append(("lag", (lx, ly, lab), GREEN_MID if lz < 0 else GREEN_DIM, 0))

    # ship
    sx_, sy_, sz_ = V.p(math.cos(a_s) * r_s, 0, math.sin(a_s) * r_s)
    S["trail"].append((math.cos(a_s) * r_s, math.sin(a_s) * r_s))
    if len(S["trail"]) > 40:
        del S["trail"][0]
    bodies.append(("VOIDSHIP", sx_, sy_, sz_, 2.0, "ship", r_s))

    # draw back bodies
    def draw_body(b, occl=False):
        name, px, py, pz, rad, kind, _r = b
        if kind == "moon":
            c = GREEN if pz < 0 else GREEN_MID
            d.ellipse([px - rad, py - rad, px + rad, py + rad], fill=(0, 20, 8), outline=c)
            # terminator: lit half toward sun (screen left)
            d.chord([px - rad, py - rad, px + rad, py + rad], 90, 270, fill=_col(c, 0.8))
        else:
            c = GREEN_HI
            d.polygon([(px, py - 3), (px + 3, py), (px, py + 3), (px - 3, py)], outline=c)

    # ship trail (world trail projected)
    tr = S["trail"]
    if len(tr) > 2:
        arr = np.array(tr, np.float32)
        tx, ty, tz = V.p(arr[:, 0], 0 * arr[:, 0], arr[:, 1])
        pts = list(zip(tx.tolist(), ty.tolist()))
        n = len(pts)
        for i in range(n - 1):
            k = i / n
            d.line([pts[i], pts[i + 1]], fill=_col(GREEN, 0.15 + 0.7 * k))

    for b in bodies:
        if b[3] >= 0:
            draw_body(b)

    # ── planet ──
    spin = ta * 0.35
    ppx, ppy, _ = V.p(0, 0, 0)
    prad = PR * FOV / CAM
    d.ellipse([ppx - prad - 3, ppy - prad - 3, ppx + prad + 3, ppy + prad + 3], outline=GREEN_DIM)
    d.ellipse([ppx - prad, ppy - prad, ppx + prad, ppy + prad], fill=(0, 14, 6), outline=GREEN)
    ax_t = 0.35
    ca, sa = math.cos(ax_t), math.sin(ax_t)

    def planet_pts(x, y, z):
        # axial tilt about the view-plane z axis (world x-y), then system view
        x2 = x * ca - y * sa
        y2 = x * sa + y * ca
        return V.p(x2, y2, z)

    t_ang = np.linspace(0, 2 * math.pi, 37, dtype=np.float32)
    for lat in (-60, -30, 0, 30, 60):
        la = math.radians(lat)
        rr = PR * math.cos(la)
        yy = -PR * math.sin(la)
        sx, sy, sz = planet_pts(np.cos(t_ang) * rr, np.full_like(t_ang, yy), np.sin(t_ang) * rr)
        for run, fr in _runs(sx, sy, sz < 0):
            if fr:
                d.line(run, fill=GREEN_MID if lat else GREEN)
    ph_ang = np.linspace(-math.pi / 2, math.pi / 2, 19, dtype=np.float32)
    for k in range(8):
        lo = spin + k * math.pi / 4
        x = PR * np.cos(ph_ang) * math.cos(lo)
        z = PR * np.cos(ph_ang) * math.sin(lo)
        y = -PR * np.sin(ph_ang)
        sx, sy, sz = planet_pts(x, y, z)
        for run, fr in _runs(sx, sy, sz < 0):
            if fr:
                d.line(run, fill=GREEN_MID if k else GREEN)
    # night-side shading: dark crescent on the right
    d.arc([ppx - prad, ppy - prad, ppx + prad, ppy + prad], -80, 80, fill=GREEN_HI)

    # front orbit segments & markers
    for kind, data, c, w in front_ops:
        if kind == "line":
            d.line(data, fill=c, width=w)
        elif kind == "tgt":
            x, y = data
            d.line([(x - 5, y - 5), (x - 2, y - 5)], fill=c)
            d.line([(x - 5, y - 5), (x - 5, y - 2)], fill=c)
            d.line([(x + 5, y + 5), (x + 2, y + 5)], fill=c)
            d.line([(x + 5, y + 5), (x + 5, y + 2)], fill=c)
            d.line([(x + 5, y - 5), (x + 2, y - 5)], fill=c)
            d.line([(x + 5, y - 5), (x + 5, y - 2)], fill=c)
            d.line([(x - 5, y + 5), (x - 2, y + 5)], fill=c)
            d.line([(x - 5, y + 5), (x - 5, y + 2)], fill=c)
        elif kind == "lag":
            x, y, lab = data
            d.polygon([(x, y - 3), (x + 3, y + 2), (x - 3, y + 2)], outline=c)
            _text(img, x + 5, y - 6, lab, c, 9, "l")

    for b in bodies:
        if b[3] < 0:
            draw_body(b)

    # burn flare
    db = ta - S["burn"]
    if 0 <= db < 1.4:
        k = 1 - db / 1.4
        rr_ = 3 + 6 * db
        d.ellipse([sx_ - rr_, sy_ - rr_, sx_ + rr_, sy_ + rr_], outline=_col(AMBER, k))
        d.ellipse([sx_ - 2, sy_ - 2, sx_ + 2, sy_ + 2], fill=_col(AMBER, k))

    # transits / occultations
    ev, et = S["event"]
    for name, px, py, pz, rad, kind, _r in bodies:
        if kind != "moon":
            continue
        if (px - ppx) ** 2 + (py - ppy) ** 2 < (prad + rad * 0.5) ** 2:
            lab = ("TRANSIT " if pz < 0 else "OCCULTATION ") + name
            if lab == ev or ta - et > 14.0:
                S["event"] = (lab, ta)
                ev, et = lab, ta
    ev, et = S["event"]

    # tracking bracket cycles through bodies
    sel = int(ta / 7.0) % len(bodies)
    name, px, py, pz, rad, kind, r = bodies[sel]
    st = (ta / 7.0) % 1.0
    br = rad + 5 + 10 * max(0.0, 1 - st * 5)
    c = GREEN_HI
    for sx1, sy1 in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
        x0, y0 = px + sx1 * br, py + sy1 * br
        d.line([(x0, y0), (x0 - sx1 * 4, y0)], fill=c)
        d.line([(x0, y0), (x0, y0 - sy1 * 4)], fill=c)

    # ── HUD ──
    _text(img, CX, 20, "ORBITAL AUSPEX", GREEN_MID, 10)
    _text(img, CX, 32, S["planet"], GREEN, 11)
    if ta - et < 2.5 and ev:
        _text(img, CX, 178, ev, AMBER if ev.startswith("OCC") else GREEN_HI, 10)
    if kind == "ship":
        mtxt = {"PARK_LO": "LOW PARKING ORBIT", "PARK_HI": "HIGH PARKING ORBIT",
                "XFER_UP": "HOHMANN TRANSFER", "XFER_DN": "DESCENT TRANSFER"}[mode]
        _text(img, CX, 192, "VOIDSHIP", GREEN_HI, 11)
        _text(img, CX, 206, mtxt if not (0 <= db < 1.4) else "ENGINE BURN", AMBER if 0 <= db < 1.4 else GREEN_MID, 9)
    else:
        per = _period(r) * 0.9
        _text(img, CX, 192, f"MOON {name}", GREEN_HI, 11)
        _text(img, CX, 206, f"T {per:4.1f}H   A {r * 1.2:5.1f}MM", GREEN_MID, 9)
    # side readouts
    _text(img, CX, 44, f"XFR {S['nxfer']:02d}   INC {math.degrees(tilt):02.0f}", GREEN_DIM, 9)
    return _ph.compose(img)
