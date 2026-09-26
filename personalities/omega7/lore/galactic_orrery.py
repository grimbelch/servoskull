"""Astronomican Orrery - a slowly turning 3D map of the galaxy.

A spiral-galaxy point cloud rotates and tilts in 3D. Holy Terra burns at the
heart of the Astronomican, whose pulsing light-sphere gilds the stars within its
range. Segmentum boundaries ring Terra; the Eye of Terror and the Maelstrom
swirl as warp-storm vortices (and, in M42 epochs, the Great Rift scars the
galaxy). Fleets ply warp routes between labelled systems, and twice per cycle
the orrery zooms into a system to show its orbital schematic and record.
"""

from __future__ import annotations

import math
import random

import numpy as np
from PIL import Image, ImageDraw

from ._common import CX, CY, Session, font, scale

NAME = "galactic_orrery"

_rng = random.Random()
_session = Session()

GOLD = (255, 205, 100)
HUD = (150, 220, 255)
HUD_DIM = (80, 130, 160)
SEG_COL = (90, 150, 210)
CYCLE = 118.0

TERRA = np.array([-44.0, -14.0, 0.0])
SYSTEMS = {
    "TERRA": ((-44, -14), ("SOL SYSTEM", "THRONEWORLD", "SEGMENTUM SOLAR", "HOLY TERRA")),
    "CADIA": ((-60, 36), ("CADIAN GATE", "FORTRESS WORLD", "SEGMENTUM OBSCURUS", "CADIA")),
    "FENRIS": ((-84, 10), ("FENRIS SYSTEM", "DEATH WORLD", "SPACE WOLVES", "FENRIS")),
    "ARMAGEDDON": ((-24, 18), ("ARMAGEDDON", "HIVE WORLD", "SEGMENTUM SOLAR", "ARMAGEDDON")),
    "MACRAGGE": ((80, -6), ("ULTRAMAR", "CIVILISED WORLD", "ULTRAMARINES", "MACRAGGE")),
    "BAAL": ((58, -50), ("BAAL SYSTEM", "DESERT MOONS", "BLOOD ANGELS", "BAAL SECUNDUS")),
    "CATACHAN": ((-30, -64), ("CATACHAN", "DEATH WORLD", "SEGMENTUM TEMPESTUS", "CATACHAN")),
    "NOCTURNE": ((46, 16), ("NOCTURNE", "VOLCANIC WORLD", "SALAMANDERS", "NOCTURNE")),
    "RYZA": ((-66, -40), ("RYZA", "FORGE WORLD", "ADEPTUS MECHANICUS", "RYZA")),
}
ROUTES = [("TERRA", "CADIA"), ("TERRA", "ARMAGEDDON"), ("TERRA", "RYZA"), ("TERRA", "CATACHAN"),
          ("TERRA", "NOCTURNE"), ("NOCTURNE", "MACRAGGE"), ("TERRA", "BAAL"), ("BAAL", "MACRAGGE"),
          ("CADIA", "FENRIS"), ("ARMAGEDDON", "NOCTURNE"), ("RYZA", "CATACHAN")]
EYE = np.array([-72.0, 48.0])
MAEL = np.array([-4.0, 38.0])
RAIDS = [(EYE, "CADIA", (255, 70, 90)), (EYE, "FENRIS", (255, 70, 90)), (MAEL, "ARMAGEDDON", (120, 255, 90))]
SEGMENTA = [("OBSCURUS", 90), ("ULTIMA", 0), ("TEMPESTUS", 270), ("PACIFICUS", 180)]

HR = 120  # half-res glow buffer
_S: dict = {}

_gy, _gx = np.mgrid[-24:25, -24:25].astype(np.float32)
_GR = np.sqrt(_gx * _gx + _gy * _gy)
_GLOW = (np.exp(-_GR ** 2 / (2 * 5.0 ** 2)) + 0.4 * np.exp(-_GR ** 2 / (2 * 11.0 ** 2))) * np.clip(1 - _GR / 24.0, 0, 1) ** 2


def _rz(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


def _rx(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])


def _build_galaxy(g):
    pts, cols = [], []
    # bulge
    n = 800
    r = np.abs(g.normal(0, 9, n)) + 0.5
    a = g.uniform(0, 2 * math.pi, n)
    pts.append(np.stack([r * np.cos(a), r * np.sin(a) * 0.85, g.normal(0, 3.5, n) * np.exp(-r / 20)], 1))
    b = g.uniform(0.5, 1.0, n)[:, None]
    cols.append(np.array([255, 215, 150])[None, :] * b * 0.75)
    # spiral arms
    arms = 4
    pitch = math.radians(g.uniform(12, 16))
    n = 3000
    k = g.integers(0, arms, n)
    u = g.uniform(0, 1, n) ** 0.85
    r = 7 + 93 * u
    th = k * (2 * math.pi / arms) + np.log(r / 7) / math.tan(pitch) + g.normal(0, 0.22, n) * (1 - 0.4 * u)
    r = r + g.normal(0, 3, n)
    pts.append(np.stack([r * np.cos(th), r * np.sin(th), g.normal(0, 1.4, n)], 1))
    b = g.uniform(0.35, 1.0, n)[:, None]
    base = np.where((g.uniform(0, 1, n) < 0.06)[:, None], np.array([255, 120, 170])[None, :],
                    np.array([165, 190, 255])[None, :])
    warm = np.clip(1 - r / 40, 0, 1)[:, None]
    cols.append((base * (1 - warm) + np.array([255, 220, 170])[None, :] * warm) * b * 0.6)
    # diffuse disc
    n = 700
    r = 100 * np.sqrt(g.uniform(0, 1, n))
    a = g.uniform(0, 2 * math.pi, n)
    pts.append(np.stack([r * np.cos(a), r * np.sin(a), g.normal(0, 2.5, n)], 1))
    cols.append(np.array([120, 130, 170])[None, :] * g.uniform(0.2, 0.6, n)[:, None])
    P = np.vstack(pts)
    C = np.vstack(cols)
    dT = np.linalg.norm(P[:, :2] - TERRA[None, :2], axis=1)
    return P.astype(np.float32), C.astype(np.float32), dT.astype(np.float32)


def _build_storm(g, n, rad):
    rho = rad * g.uniform(0, 1, n) ** 0.7
    psi = g.uniform(0, 2 * math.pi, n) + rho * 0.5
    z = g.normal(0, 1.2, n)
    c = np.where((g.uniform(0, 1, n) < 0.5)[:, None], np.array([230, 60, 200])[None, :], np.array([150, 40, 255])[None, :])
    hot = np.clip(1 - rho / (rad * 0.35), 0, 1)[:, None]
    c = c * (1 - hot) + np.array([255, 170, 230])[None, :] * hot
    return rho.astype(np.float32), psi.astype(np.float32), z.astype(np.float32), (c * g.uniform(0.3, 0.7, n)[:, None]).astype(np.float32)


def _bezier(a, b, bend):
    a, b = np.asarray(a, float), np.asarray(b, float)
    m = (a + b) / 2
    d = b - a
    perp = np.array([-d[1], d[0]])
    c = m + perp * bend
    return a, c, b


def _bz(curve, u):
    a, c, b = curve
    u = np.asarray(u, float)[..., None]
    return (1 - u) ** 2 * a + 2 * (1 - u) * u * c + u * u * b


def _new_cycle(t):
    g = np.random.default_rng(_rng.randrange(1 << 30))
    P, C, dT = _build_galaxy(g)
    eye = _build_storm(g, 380, 11.0)
    mael = _build_storm(g, 220, 7.0)
    m42 = _rng.random() < 0.5
    if m42:
        n = 700
        u = g.uniform(0, 1, n)
        curve = _bezier(EYE, (92, 20), 0.18)
        base = _bz(curve, u)
        wid = 2.5 + 5 * np.sin(u * math.pi)
        off = g.normal(0, 1, (n, 2)) * wid[:, None]
        rift = np.column_stack([base + off, g.normal(0, 1.2, n)]).astype(np.float32)
        rcol = (np.array([170, 40, 200])[None, :] * g.uniform(0.15, 0.55, n)[:, None]).astype(np.float32)
    else:
        rift = np.zeros((0, 3), np.float32)
        rcol = np.zeros((0, 3), np.float32)
    routes = {}
    for a, b in ROUTES:
        routes[(a, b)] = _bezier(SYSTEMS[a][0], SYSTEMS[b][0], _rng.uniform(-0.18, 0.18))
    for src, dst, _c in RAIDS:
        routes[("RAID", dst, tuple(src))] = _bezier(src, SYSTEMS[dst][0], _rng.uniform(-0.15, 0.15))
    zooms = _rng.sample(list(SYSTEMS.keys()), 2)
    if "TERRA" not in zooms and _rng.random() < 0.3:
        zooms[0] = "TERRA"
    _S.update(
        t0=t, P=P, C=C, dT=dT, eye=eye, mael=mael, rift=rift, rcol=rcol, m42=m42,
        routes=routes, fleets=[], zooms=zooms, ztimes=[_rng.uniform(22, 30), _rng.uniform(68, 76)],
        yaw0=_rng.uniform(0, 2 * math.pi), ydir=_rng.choice([-1, 1]), tilt0=_rng.uniform(0.55, 0.8),
        spin0=_rng.uniform(0, 2 * math.pi), year=_rng.randint(100, 999),
        planets=None, zkey=None,
    )
    for _ in range(7):
        _spawn_fleet(t, fresh=True)


def _spawn_fleet(t, fresh=False):
    keys = list(_S["routes"].keys())
    raid = _rng.random() < 0.3
    cand = [k for k in keys if (k[0] == "RAID") == raid]
    key = _rng.choice(cand)
    if key[0] == "RAID":
        col = next(c for s, d, c in RAIDS if d == key[1] and tuple(s) == key[2])
        rev = False
    else:
        col = GOLD if _rng.random() < 0.8 else (200, 220, 255)
        rev = _rng.random() < 0.5
    dur = _rng.uniform(14, 30)
    t0 = t - (_rng.uniform(0, dur) if fresh else 0.0)
    _S["fleets"].append(dict(key=key, rev=rev, t0=t0, dur=dur, col=col))


def _reset():
    _S.clear()
    _S["last_t"] = 0.0
    _new_cycle(0.0)


def _ease(u):
    u = min(1.0, max(0.0, u))
    return u * u * (3 - 2 * u)


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


def _label(img, x, y, text, fill, size=9):
    if (x - CX) ** 2 + (y - CY) ** 2 > 100 ** 2 or y < 60 or y > 190:
        return
    w = _tw(text, size)
    lx = x + 4 if x + 4 + w < CX + math.sqrt(max(0.0, 106 ** 2 - (y - CY) ** 2)) else x - 4 - w
    _text(img, lx, y - 11, text, fill, size)


def render(bezel, mask, now: float) -> Image.Image:
    if _session.fresh(now):
        _reset()
    t = _session.t(now)
    _S["last_t"] = t
    if t - _S["t0"] >= CYCLE:
        _new_cycle(t)
    S = _S
    lt = t - S["t0"]

    # ---------------------------------------------------------- camera / zoom
    zoom, focus, zk, zphase = 1.0, np.zeros(2), None, 0.0
    for key, zt in zip(S["zooms"], S["ztimes"]):
        u = lt - zt
        if 0 <= u <= 20:
            zk = key
            zphase = _ease(u / 4.0) if u < 16 else _ease((20 - u) / 4.0)
            focus = np.array(SYSTEMS[key][0], float) * _ease(zphase * 1.8)
            zoom = 1.0 + 4.5 * zphase
    spin = S["spin0"] + lt * 0.018
    yaw = S["yaw0"] + S["ydir"] * lt * 0.01
    tilt = S["tilt0"] + 0.18 * math.sin(lt * 0.045)
    V = _rx(tilt) @ _rz(yaw)
    full = V @ _rz(spin)
    F = full @ np.array([focus[0], focus[1], 0.0])
    sc = 0.98 * zoom

    def proj(p):
        q = p @ full.T - F
        den = 1.0 - q[:, 2] * min(sc, 2.4) / 700.0
        persp = 1.0 / np.maximum(den, 0.5)
        sx = CX + q[:, 0] * sc * persp
        sy = CY - q[:, 1] * sc * persp
        behind = den < 0.5  # too close to the camera: drop rather than smear
        if behind.any():
            sx[behind] = -9999.0
        return sx, sy, q[:, 2]

    # ---------------------------------------------------------- galaxy point cloud
    pulse = 0.5 + 0.5 * math.sin(lt * 1.6)
    wT = np.clip(1.0 - S["dT"] / (55 + 6 * pulse), 0, 1)
    col = S["C"] + np.array([90, 60, 0], np.float32)[None, :] * (wT * (0.4 + 0.35 * pulse))[:, None]
    # storms: swirl in their own frame
    allp, allc = [S["P"]], [col]
    for (rho, psi, z, c), ctr, w in ((S["eye"], EYE, 0.35), (S["mael"], MAEL, -0.45)):
        ang = psi + lt * w * (3.0 / (0.6 + rho * 0.25))
        sp = np.column_stack([ctr[0] + rho * np.cos(ang), ctr[1] + rho * np.sin(ang), z])
        allp.append(sp.astype(np.float32))
        allc.append(c * (0.75 + 0.25 * math.sin(lt * 2.3 + ctr[0])))
    if len(S["rift"]):
        allp.append(S["rift"])
        allc.append(S["rcol"] * (0.8 + 0.2 * math.sin(lt * 1.1)))
    Pp = np.vstack(allp)
    Cc = np.vstack(allc)
    sx, sy, _z = proj(Pp)

    # soft half-res glow layer
    hx = (sx * 0.5).astype(np.int32)
    hy = (sy * 0.5).astype(np.int32)
    ok = (hx >= 0) & (hx < HR) & (hy >= 0) & (hy < HR)
    idx = hy[ok] * HR + hx[ok]
    cc = Cc[ok]
    dens = 0.55 / math.sqrt(zoom)
    glow = np.stack([np.bincount(idx, weights=cc[:, ch], minlength=HR * HR) for ch in range(3)], 1)
    glow = np.clip(glow * dens, 0, 255).astype(np.uint8).reshape(HR, HR, 3)
    arr = np.array(Image.fromarray(glow, "RGB").resize((240, 240), Image.BILINEAR), dtype=np.uint16)
    # sharp full-res stars
    fx = sx.astype(np.int32)
    fy = sy.astype(np.int32)
    ok = (fx >= 0) & (fx < 240) & (fy >= 0) & (fy < 240)
    arr[fy[ok], fx[ok]] += (Cc[ok] * 0.8).astype(np.uint16)

    # Terra's glow
    tx, ty, _ = proj(TERRA[None, :].astype(np.float32))
    tx, ty = float(tx[0]), float(ty[0])
    x0, y0 = int(tx) - 24, int(ty) - 24
    if -48 < x0 < 240 and -48 < y0 < 240:
        gx0, gy0 = max(0, -x0), max(0, -y0)
        gx1, gy1 = 49 - max(0, x0 + 49 - 240), 49 - max(0, y0 + 49 - 240)
        reg = arr[y0 + gy0:y0 + gy1, x0 + gx0:x0 + gx1]
        reg += (_GLOW[gy0:gy1, gx0:gx1, None] * np.array([255, 210, 120])[None, None, :] * (0.7 + 0.3 * pulse)).astype(np.uint16)
    np.minimum(arr, 255, out=arr)
    img = Image.fromarray(arr.astype(np.uint8), "RGB")
    d = ImageDraw.Draw(img)

    over = 1.0 - zphase  # galactic overlays fade while zoomed in

    # ---------------------------------------------------------- Astronomican beam and light-sphere
    up = full @ np.array([0, 0, 1.0])
    bl = 40 * (0.8 + 0.2 * pulse) * zoom ** 0.5
    if over > 0.3:
        d.line((tx, ty, tx + up[0] * bl, ty - up[1] * bl), fill=scale(GOLD, 0.8 * over), width=1)
    circ = np.linspace(0, 2 * math.pi, 49)
    for k in range(2 if over > 0.5 else 0):
        ph = ((lt * 0.22 + k * 0.5) % 1.0)
        rad = 6 + 52 * ph
        ring = np.column_stack([TERRA[0] + rad * np.cos(circ), TERRA[1] + rad * np.sin(circ), np.zeros(49)]).astype(np.float32)
        rx, ry, _ = proj(ring)
        c = scale(GOLD, (1 - ph) * 0.55 * (over - 0.5) * 2)
        if c[0] > 8:
            d.line(list(zip(rx.tolist(), ry.tolist())), fill=c)

    # ---------------------------------------------------------- segmentum boundaries
    if over > 0.05:
        segc = scale(SEG_COL, 0.8 * over)
        solar = np.column_stack([TERRA[0] + 15 * np.cos(circ), TERRA[1] + 15 * np.sin(circ), np.zeros(49)]).astype(np.float32)
        rx, ry, _ = proj(solar)
        pts = list(zip(rx.tolist(), ry.tolist()))
        for i in range(0, 48, 2):
            d.line((pts[i], pts[i + 1]), fill=segc)
        outer = np.column_stack([TERRA[0] + 62 * np.cos(circ), TERRA[1] + 62 * np.sin(circ), np.zeros(49)]).astype(np.float32)
        rx, ry, _ = proj(outer)
        pts = list(zip(rx.tolist(), ry.tolist()))
        for i in range(0, 48, 3):
            d.line((pts[i], pts[i + 1]), fill=scale(SEG_COL, 0.5 * over))
        for a in (45, 135, 225, 315):
            ar = math.radians(a)
            sp = np.array([[TERRA[0] + 15 * math.cos(ar), TERRA[1] + 15 * math.sin(ar), 0],
                           [TERRA[0] + 62 * math.cos(ar), TERRA[1] + 62 * math.sin(ar), 0]], np.float32)
            rx, ry, _ = proj(sp)
            d.line((rx[0], ry[0], rx[1], ry[1]), fill=scale(SEG_COL, 0.45 * over))

    # ---------------------------------------------------------- warp routes + fleets
    if over > 0.05:
        uu = np.linspace(0, 1, 20)
        for key, cur in S["routes"].items():
            if key[0] == "RAID":
                continue
            p2 = _bz(cur, uu)
            rx, ry, _ = proj(np.column_stack([p2, np.zeros(20)]).astype(np.float32))
            for i in range(0, 19, 2):
                d.line((rx[i], ry[i], rx[i + 1], ry[i + 1]), fill=scale((120, 110, 70), over))
    alive = []
    for fl in S["fleets"]:
        u = (t - fl["t0"]) / fl["dur"]
        if u > 1:
            continue
        alive.append(fl)
        if u < 0:
            continue
        cur = S["routes"][fl["key"]]
        us = np.clip(np.array([u - k * 0.025 for k in range(6)]), 0, 1)
        if fl["rev"]:
            us = 1 - us
        p2 = _bz(cur, us)
        rx, ry, _ = proj(np.column_stack([p2, np.zeros(6)]).astype(np.float32))
        pts = list(zip(rx.tolist(), ry.tolist()))
        for i in range(5):
            d.line((pts[i], pts[i + 1]), fill=scale(fl["col"], (1 - i / 5) * 0.8))
        x, y = pts[0]
        d.rectangle((x - 1, y - 1, x + 1, y + 1), fill=fl["col"])
    S["fleets"] = alive
    while len(S["fleets"]) < 7:
        _spawn_fleet(t)

    # ---------------------------------------------------------- labels
    if over > 0.6:
        lc = (over - 0.6) / 0.4
        names = list(SYSTEMS.keys())
        slot = int(lt / 5.0)
        lit = {"TERRA"} | {names[1 + (slot * 3 + j) % (len(names) - 1)] for j in range(3)}
        seg_on = 8 < lt % 40 < 24
        for name, ((x, y), _info) in SYSTEMS.items():
            px, py, _ = proj(np.array([[x, y, 0]], np.float32))
            px, py = float(px[0]), float(py[0])
            c = GOLD if name == "TERRA" else (230, 230, 210)
            d.rectangle((px - 1, py - 1, px + 1, py + 1), fill=scale(c, lc))
            if name in lit and not (seg_on and name != "TERRA"):
                _label(img, px, py, name, scale(c, lc * 0.95), 9)
        for nm, ctr in (() if seg_on else (("EYE OF TERROR", EYE), ("MAELSTROM", MAEL))):
            px, py, _ = proj(np.array([[ctr[0], ctr[1], 0]], np.float32))
            _label(img, float(px[0]), float(py[0]) + 16, nm, scale((255, 110, 220), lc * 0.9), 9)
        if seg_on:
            for nm, ang in SEGMENTA:
                ar = math.radians(ang)
                px, py, _ = proj(np.array([[TERRA[0] + 48 * math.cos(ar), TERRA[1] + 48 * math.sin(ar), 0]], np.float32))
                px, py = float(px[0]), float(py[0])
                if (px - CX) ** 2 + (py - CY) ** 2 < 95 ** 2 and 52 < py < 182:
                    _text(img, px - _tw(nm, 9) / 2, py - 5, nm, scale(SEG_COL, lc), 9)

    # ---------------------------------------------------------- system zoom overlay
    if zk is not None and zphase > 0.4:
        k = (zphase - 0.4) / 0.6
        if S["zkey"] != zk:
            S["zkey"] = zk
            n = _rng.randint(3, 5)
            S["planets"] = [(16 + i * 13 + _rng.uniform(-2, 2), _rng.uniform(0, 6.28), _rng.uniform(0.25, 0.7) / (1 + i * 0.6))
                            for i in range(n)]
            S["main"] = _rng.randrange(n)
        # orbits lie in the galactic plane, so they tilt with the view
        R2 = full[:2, :2]
        e = np.stack([np.cos(circ), np.sin(circ)], 1)
        ex, ey = e @ R2[0], e @ R2[1]
        d.ellipse((CX - 3, CY - 3, CX + 3, CY + 3), fill=scale((255, 240, 200), k))
        for i, (rad, ph0, w) in enumerate(S["planets"]):
            ox = CX + ex * rad
            oy = CY - ey * rad
            pts = list(zip(ox.tolist(), oy.tolist()))
            for j in range(0, 48, 2):
                d.line((pts[j], pts[j + 1]), fill=scale((110, 170, 210), k * 0.7))
            a = ph0 + lt * w
            px = CX + (math.cos(a) * R2[0, 0] + math.sin(a) * R2[0, 1]) * rad
            py = CY - (math.cos(a) * R2[1, 0] + math.sin(a) * R2[1, 1]) * rad
            if i == S["main"]:
                d.ellipse((px - 3, py - 3, px + 3, py + 3), fill=scale((120, 220, 255), k), outline=scale(GOLD, k))
                d.line((px + 4, py - 4, px + 12, py - 12), fill=scale(GOLD, k))
                nm = SYSTEMS[zk][1][3]
                w = _tw(nm, 9)
                lx = px + 13 if px + 13 + w < 212 else px - 13 - w
                _text(img, lx, py - 20, nm, scale(GOLD, k), 9)
            else:
                d.ellipse((px - 1.5, py - 1.5, px + 1.5, py + 1.5), fill=scale((170, 170, 180), k))
        info = SYSTEMS[zk][1]
        _tc(img, 30, info[0], scale(GOLD, k), 12)
        _tc(img, 46, info[1], scale(HUD, k), 9)
        _tc(img, 180, info[2], scale(HUD, k), 9)
        _tc(img, 193, "NOOSPHERIC RECORD", scale(HUD_DIM, k), 9)
    else:
        if zk is None or zphase < 0.2:
            S["zkey"] = None
        k = 1.0 - min(1.0, zphase / 0.4) if zk is not None else 1.0
        if k > 0.05:
            _tc(img, 22, "ASTRONOMICAN", scale(GOLD, k), 11)
            _tc(img, 36, "ORRERY", scale(HUD_DIM, k), 9)
            epoch = f"{S['year']:03d}.M{42 if S['m42'] else 41}"
            _tc(img, 192, f"EPOCH {epoch}", scale(HUD_DIM, k), 9)
            _tc(img, 205, f"FLEETS IN TRANSIT {len(S['fleets'])}", scale(HUD_DIM, k), 9)

    fade = min(1.0, lt / 1.0, (CYCLE - lt) / 1.0)
    if fade < 1.0:
        img = Image.fromarray((np.asarray(img) * max(0.0, fade)).astype(np.uint8), "RGB")
    return img
