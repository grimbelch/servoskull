"""Forge World Orbital - Mars, the Red Forge, from high orbit.

A per-pixel shaded Mars rotates beneath a fixed sun: rust plains, polar caps,
Tharsis and Olympus Mons, the scar of Valles Marineris, with a day/night
terminator and forge-city lights glittering across the night side. A noospheric
graticule and the Ring of Iron (orbital shipyards with dock nodes and berthed
hulls) are drawn in true 3D with back-face / planet occlusion. Lighters and
supply barges shuttle between the forges and the docks, Phobos wheels past, a
newly consecrated voidship launches each cycle, and output readouts tick toward
the Munitorum tithe.
"""

from __future__ import annotations

import math
import random

import numpy as np
from PIL import Image, ImageDraw

from ._common import CX, Session, font, lerp_color, scale

NAME = "forge_world_orbital"

_rng = random.Random()
_session = Session()

RP = 54.0          # planet radius (px)
PCX, PCY = 120.0, 114.0
RING_R = 1.45      # Ring of Iron radius in planet radii
TW, TH = 256, 128
CYCLE = 96.0

STEEL = (150, 165, 180)
AMBER = (255, 170, 60)
NOOS = (80, 200, 170)
HUD = (220, 120, 80)
HUD_DIM = (140, 90, 70)

# forge sites: (name, lat, lon) degrees
SITES = [("OLYMPUS MONS", 18.6, -134.0), ("ARSIA MONS", -8.3, -120.0), ("PAVONIS MONS", 1.5, -113.0),
         ("ASCRAEUS MONS", 11.9, -104.0), ("NOCTIS LABYRINTHUS", -7.0, -100.0), ("VALLES MARINERIS", -12.0, -60.0),
         ("HELLAS FORGE", -42.0, 70.0), ("ELYSIUM", 25.0, 147.0), ("ARABIA TERRA", 20.0, 15.0),
         ("SYRTIS MAJOR", 8.0, 70.0), ("UTOPIA", 45.0, 110.0), ("ARGYRE", -50.0, -43.0),
         ("CYDONIA", 40.0, -10.0), ("HESPERIA", -20.0, 110.0), ("CHRYSE", 22.0, -45.0)]
SHIPS = ["INVINCIBLE REASON", "OMNISSIAH'S GRACE", "ARK OF TESTAMENT", "LEX MECHANICUS", "COGITATIO",
         "MARTIAN WRATH", "VOLTAIC LORD", "BINARY LITANY", "FIDES MACHINA"]
READOUTS = ["FORGE OUTPUT", "HULLS ON SLIPS", "LIGHTERS ALOFT", "PROMETHIUM MT", "NOOSPHERE SYNC", "TITAN LEGIO"]

_S: dict = {}
_TEX: list = []


# --------------------------------------------------------------------------- helpers

def _rx(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])


def _ry(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def _sph(lat, lon):
    """Body-frame unit vector for latitude/longitude (radians)."""
    return np.array([math.cos(lat) * math.sin(lon), math.sin(lat), math.cos(lat) * math.cos(lon)])


def _noise(g, gw, gh):
    """Smooth value noise on the TW x TH map, wrapping in longitude."""
    grid = g.uniform(0, 1, (gh + 1, gw))
    grid = np.hstack([grid, grid[:, :1]])
    ys = np.linspace(0, gh, TH, endpoint=False)
    xs = np.linspace(0, gw, TW, endpoint=False)
    y0 = ys.astype(int)
    x0 = xs.astype(int)
    fy = (ys - y0)[:, None]
    fx = (xs - x0)[None, :]
    fy = fy * fy * (3 - 2 * fy)
    fx = fx * fx * (3 - 2 * fx)
    a = grid[y0][:, x0]
    b = grid[y0][:, x0 + 1]
    c = grid[y0 + 1][:, x0]
    d = grid[y0 + 1][:, x0 + 1]
    return (a * (1 - fx) + b * fx) * (1 - fy) + (c * (1 - fx) + d * fx) * fy


def _tex_coords(lat_deg, lon_deg):
    r = (90.0 - lat_deg) / 180.0 * TH
    c = (lon_deg + 180.0) / 360.0 * TW
    return r, c


def _build_textures(g):
    n = 0.5 * _noise(g, 8, 4) + 0.27 * _noise(g, 20, 10) + 0.14 * _noise(g, 56, 28) + 0.09 * _noise(g, 128, 64)
    rows = np.arange(TH)[:, None]
    cols = np.arange(TW)[None, :]
    lat = 90.0 - (rows + 0.5) / TH * 180.0
    lon = (cols + 0.5) / TW * 360.0 - 180.0
    dark = np.array([70, 38, 28], np.float32)
    rust = np.array([185, 92, 52], np.float32)
    ochre = np.array([215, 140, 85], np.float32)
    t = np.clip((n - 0.3) / 0.45, 0, 1)[:, :, None]
    alb = np.where(t < 0.5, dark + (rust - dark) * (t * 2), rust + (ochre - rust) * ((t - 0.5) * 2))
    # Valles Marineris: long dark canyon scar
    vm = np.exp(-((lat + 9 + 3 * np.sin(np.radians(lon) * 5)) / 2.2) ** 2) * ((lon > -112) & (lon < -40))
    alb *= (1 - 0.55 * vm)[:, :, None]
    # Tharsis volcanoes + Olympus Mons: bright shields with dark calderas
    for la, lo, rad in ((18.6, -134.0, 9.0), (-8.3, -120.0, 4.5), (1.5, -113.0, 4.0), (11.9, -104.0, 4.0)):
        dlo = (lon - lo + 180) % 360 - 180
        d2 = ((lat - la) / rad) ** 2 + (dlo * math.cos(math.radians(la)) / rad) ** 2
        alb = alb * (1 + 0.35 * np.exp(-d2 * 1.5))[:, :, None]
        alb = alb * (1 - 0.6 * np.exp(-d2 * 18))[:, :, None]
    # polar caps
    cap = np.clip((np.abs(lat) - (72 + 6 * n)) / 6.0, 0, 1)[:, :, None]
    alb = alb * (1 - cap) + np.array([225, 215, 205], np.float32) * cap
    # impact craters
    for _ in range(90):
        la, lo, rad = g.uniform(-65, 65), g.uniform(-180, 180), g.uniform(1.2, 4.5)
        r0 = max(0, int((90 - la - rad * 2) / 180 * TH))
        r1 = min(TH, int((90 - la + rad * 2) / 180 * TH) + 2)
        dlo = (lon - lo + 180) % 360 - 180
        d2 = ((lat[r0:r1] - la) / rad) ** 2 + (dlo * math.cos(math.radians(la)) / rad) ** 2
        ringm = np.exp(-((np.sqrt(d2) - 1.0) / 0.25) ** 2)
        alb[r0:r1] *= (1 - 0.25 * np.exp(-d2 * 2) + 0.15 * ringm)[:, :, None]
    # industrial scabs around forge sites
    lights = np.zeros((TH, TW), np.float32)
    for name, la, lo in SITES:
        dlo = (lon - lo + 180) % 360 - 180
        d2 = ((lat - la) / 7.0) ** 2 + (dlo * math.cos(math.radians(la)) / 7.0) ** 2
        alb = alb * (1 - 0.3 * np.exp(-d2))[:, :, None] + np.array([30, 30, 35], np.float32) * np.exp(-d2)[:, :, None]
        # cluster of city lights
        k = 110 if name == "OLYMPUS MONS" else 55
        la_p = la + g.normal(0, 4.5, k)
        lo_p = lo + g.normal(0, 6.5, k) / max(0.3, math.cos(math.radians(la)))
        r, c = _tex_coords(la_p, lo_p)
        r = np.clip(r.astype(int), 0, TH - 1)
        c = c.astype(int) % TW
        lights[r, c] = np.maximum(lights[r, c], g.uniform(0.4, 1.0, k))
    # scattered hab-lights and rail lines between forges
    k = 1600
    r = g.integers(8, TH - 8, k)
    c = g.integers(0, TW, k)
    lights[r, c] = np.maximum(lights[r, c], g.uniform(0.12, 0.55, k))
    for _ in range(14):
        a, b = g.choice(len(SITES), 2, replace=False)
        (_, la1, lo1), (_, la2, lo2) = SITES[a], SITES[b]
        if abs(lo1 - lo2) > 100:
            continue
        for s in np.linspace(0, 1, 60):
            rr, cc = _tex_coords(la1 + (la2 - la1) * s, lo1 + (lo2 - lo1) * s)
            lights[int(rr) % TH, int(cc) % TW] = max(lights[int(rr) % TH, int(cc) % TW], 0.35)
    return np.clip(alb, 0, 255).astype(np.float32), lights


def _new_cycle(t):
    g = np.random.default_rng(_rng.randrange(1 << 30))
    if not _TEX:  # Mars is Mars: build the surface maps once per process, not per showing
        _TEX.extend(_build_textures(g))
    _S["alb"], _S["lights"] = _TEX
    beta = _rng.uniform(0.28, 0.42)
    V = _rx(beta)
    sa = _rng.uniform(-2.3, -0.8) if _rng.random() < 0.5 else _rng.uniform(0.8, 2.3)
    L = np.array([math.sin(sa), 0.35, math.cos(sa) * 0.6])
    L /= np.linalg.norm(L)
    # --- per-pixel constants for the planet disc
    y0, y1 = int(PCY - RP - 1), int(PCY + RP + 2)
    x0, x1 = int(PCX - RP - 1), int(PCX + RP + 2)
    ys, xs = np.mgrid[y0:y1, x0:x1]
    nx = (xs + 0.5 - PCX) / RP
    ny = -(ys + 0.5 - PCY) / RP
    rr = nx * nx + ny * ny
    inside = rr <= 1.0
    py, px = ys[inside], xs[inside]
    nx, ny, rr = nx[inside], ny[inside], rr[inside]
    nz = np.sqrt(np.clip(1 - rr, 0, 1))
    nv = np.stack([nx, ny, nz], 1)
    nw = nv @ V  # V^T applied to row vectors
    lat = np.arcsin(np.clip(nw[:, 1], -1, 1))
    lon0 = np.arctan2(nw[:, 0], nw[:, 2])
    lat_i = np.clip(((math.pi / 2 - lat) / math.pi * TH).astype(np.int32), 0, TH - 1)
    lon0_s = ((lon0 + math.pi) / (2 * math.pi) * TW).astype(np.float32)
    lam = nv @ L
    shade = (0.05 + 0.95 * np.clip(lam, 0, 1) ** 0.85).astype(np.float32)
    tw = np.exp(-(lam / 0.09) ** 2)
    rim = np.clip((rr - 0.8) / 0.2, 0, 1) * np.clip(lam + 0.35, 0, 1)
    add = (tw[:, None] * np.array([70, 28, 6]) + rim[:, None] * np.array([90, 60, 50])).astype(np.float32)
    night = np.clip(-lam * 6 + 0.1, 0, 1).astype(np.float32)
    # --- static background: stars + atmospheric halo on the lit limb
    bg = np.zeros((240, 240, 3), np.float32)
    k = 260
    sx = g.integers(0, 240, k)
    sy = g.integers(0, 240, k)
    bg[sy, sx] = (g.uniform(40, 200, k) ** 1.0)[:, None] * np.array([1.0, 1.0, 1.1])[None, :]
    gy, gx = np.mgrid[0:240, 0:240]
    dx = (gx + 0.5 - PCX) / RP
    dy = -(gy + 0.5 - PCY) / RP
    dr = np.sqrt(dx * dx + dy * dy)
    halo = np.exp(-np.clip(dr - 1.0, 0, None) / 0.05) * (dr > 1.0)
    lit = np.clip((dx * L[0] + dy * L[1]) / np.maximum(dr, 1e-3) + 0.3, 0, 1)
    bg += (halo * lit)[:, :, None] * np.array([150, 90, 70])[None, :]
    # decorative outer cog ring
    img = Image.fromarray(np.clip(bg, 0, 255).astype(np.uint8), "RGB")
    d = ImageDraw.Draw(img)
    for i in range(72):
        a = i / 72 * 2 * math.pi
        r0, r1 = 109, 113 if i % 6 else 117
        d.line((CX + math.cos(a) * r0, 120 + math.sin(a) * r0, CX + math.cos(a) * r1, 120 + math.sin(a) * r1),
               fill=(70, 40, 35) if i % 6 else (120, 60, 45))
    _S.update(
        t0=t, V=V, L=L, beta=beta, py=py, px=px, lat_i=lat_i, lon0_s=lon0_s, shade=shade, add=add, night=night,
        bg=np.asarray(img).copy(), rot0=_rng.uniform(0, 2 * math.pi), rspeed=_rng.uniform(0.045, 0.07),
        docks=np.array(sorted(_rng.uniform(0, 2 * math.pi) for _ in range(12))),
        berthed=[_rng.random() < 0.45 for _ in range(12)],
        barges=[], launch_t=t + _rng.uniform(52, 66), launch=None, ship=_rng.choice(SHIPS),
        convoy_t=t + _rng.uniform(28, 40), msg=None, stats=[_rng.uniform(0, 1) for _ in READOUTS],
        phobos0=_rng.uniform(0, 6.28), ro=_rng.randrange(len(READOUTS)),
    )
    for _ in range(6):
        _spawn_barge(t, fresh=True)


def _reset():
    _S.clear()
    _new_cycle(0.0)


def _spawn_barge(t, site=None, fresh=False, delay=0.0):
    si = site if site is not None else _rng.randrange(len(SITES))
    name, la, lo = SITES[si]
    lonr = math.radians(lo)
    docks = _S["docks"]
    dl = (docks - lonr + math.pi) % (2 * math.pi) - math.pi
    k = int(np.argmin(np.abs(dl) + np.array([_rng.uniform(0, 0.6) for _ in docks])))
    dur = _rng.uniform(7, 11)
    up = _rng.random() < 0.6
    t0 = t + delay - (_rng.uniform(0, dur) if fresh else 0.0)
    _S["barges"].append(dict(site=_sph(math.radians(la), lonr), dock=k, dur=dur, t0=t0, up=up,
                             col=AMBER if _rng.random() < 0.6 else (120, 220, 255)))


def _msg(text, col, t):
    _S["msg"] = (text, col, t)


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


# --------------------------------------------------------------------------- 3D projection

def _to_view(pb, rot):
    """Body-frame points (N,3) -> view space (N,3) (x right, y up, z toward viewer)."""
    M = _S["V"] @ _ry(rot)
    return np.atleast_2d(pb) @ M.T


def _screen(v):
    return PCX + v[:, 0] * RP, PCY - v[:, 1] * RP


def _hidden(v):
    return (v[:, 2] < 0) & (v[:, 0] ** 2 + v[:, 1] ** 2 < 1.0)


def _runs(d, xs, ys, vis, fill, width=1):
    """Draw a polyline, split into runs where vis is True."""
    n = len(xs)
    i = 0
    pts = list(zip(xs.tolist(), ys.tolist()))
    while i < n:
        if not vis[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and vis[j + 1]:
            j += 1
        if j > i:
            d.line(pts[i:j + 1], fill=fill, width=width)
        i = j + 1


# graticule in body frame
_MER = [np.array([_sph(la, lo) for la in np.linspace(-math.pi / 2, math.pi / 2, 19)])
        for lo in np.radians(np.arange(-180, 180, 30))]
_PAR = [np.array([_sph(la, lo) for lo in np.linspace(-math.pi, math.pi, 49)])
        for la in np.radians([-60, -30, 0, 30, 60])]
_RING_A = np.linspace(0, 2 * math.pi, 97)


def render(bezel, mask, now: float) -> Image.Image:
    if _session.fresh(now):
        _reset()
    t = _session.t(now)
    if t - _S["t0"] >= CYCLE:
        _new_cycle(t)
    S = _S
    lt = t - S["t0"]
    rot = S["rot0"] + t * S["rspeed"]

    # ---------------------------------------------------------- shaded planet
    arr = S["bg"].copy()
    shift = rot / (2 * math.pi) * TW
    lon_i = (S["lon0_s"] - shift).astype(np.int32) & (TW - 1)
    li = S["lat_i"]
    col = S["alb"][li, lon_i] * S["shade"][:, None] + S["add"]
    lights = S["lights"][li, lon_i] * S["night"]
    flick = 0.85 + 0.15 * math.sin(t * 7.0)
    col += lights[:, None] * np.array([255 * flick, 185, 80], np.float32)
    arr[S["py"], S["px"]] = np.minimum(col, 255).astype(np.uint8)
    img = Image.fromarray(arr, "RGB")
    d = ImageDraw.Draw(img)

    # ---------------------------------------------------------- noospheric graticule (front only)
    gc = scale(NOOS, 0.35)
    for line in _MER + _PAR:
        v = _to_view(line * 1.003, rot)
        xs, ys = _screen(v)
        _runs(d, xs, ys, v[:, 2] > 0.05, gc)

    # ---------------------------------------------------------- Ring of Iron
    ca, sa = np.cos(_RING_A), np.sin(_RING_A)
    ring_parts = []
    for yoff, rad in ((0.03, RING_R), (-0.03, RING_R), (0.0, RING_R + 0.07)):
        pb = np.stack([sa * rad, np.full_like(ca, yoff), ca * rad], 1)
        v = _to_view(pb, rot)
        ring_parts.append(v)
    vis_back = []
    for v in ring_parts:
        xs, ys = _screen(v)
        hid = _hidden(v)
        back = v[:, 2] < 0
        _runs(d, xs, ys, back & ~hid, scale(STEEL, 0.45))
        vis_back.append((xs, ys, hid))
    # struts (draw all, dim if behind)
    v0, v1 = ring_parts[0], ring_parts[1]
    x0s, y0s = _screen(v0)
    x1s, y1s = _screen(v1)
    for i in range(0, 96, 4):
        if _hidden(v0[i:i + 1])[0]:
            continue
        k = 0.85 if v0[i, 2] >= 0 else 0.4
        d.line((x0s[i], y0s[i], x1s[i], y1s[i]), fill=scale(STEEL, k))
    for v in ring_parts:
        xs, ys = _screen(v)
        _runs(d, xs, ys, v[:, 2] >= 0, STEEL if v is not ring_parts[2] else scale(STEEL, 0.6))

    # dock nodes + berthed hulls
    docks = S["docks"]
    dpb = np.stack([np.sin(docks) * RING_R, np.zeros_like(docks), np.cos(docks) * RING_R], 1)
    dv = _to_view(dpb, rot)
    dx_, dy_ = _screen(dv)
    dh = _hidden(dv)
    tang = _to_view(np.stack([np.cos(docks), np.zeros_like(docks), -np.sin(docks)], 1), rot)
    for i in range(len(docks)):
        if dh[i]:
            continue
        front = dv[i, 2] >= 0
        k = 1.0 if front else 0.45
        x, y = dx_[i], dy_[i]
        s = 2.5 if front else 1.5
        d.rectangle((x - s, y - s, x + s, y + s), outline=scale(STEEL, k), fill=scale((60, 50, 45), k))
        if int(t * 2 + i) % 3 == 0:
            d.point((x, y), fill=scale(AMBER, k))
        if S["berthed"][i]:
            tx, ty = tang[i, 0], -tang[i, 1]
            n = math.hypot(tx, ty) + 1e-6
            tx, ty = tx / n, ty / n
            ox, oy = -ty * 5, tx * 5
            hx0, hy0 = x + ox - tx * 7, y + oy - ty * 7
            hx1, hy1 = x + ox + tx * 7, y + oy + ty * 7
            d.line((hx0, hy0, hx1, hy1), fill=scale((200, 190, 170), k), width=2)
            d.line((hx1, hy1, hx1 + tx * 3 - ty * 1.5, hy1 + ty * 3 + tx * 1.5), fill=scale((200, 190, 170), k))
            d.line((x, y, x + ox * 0.7, y + oy * 0.7), fill=scale(STEEL, 0.6 * k))

    # ---------------------------------------------------------- barges and lighters
    if lt >= S["convoy_t"] - S["t0"] and S.get("convoy_done") != S["t0"]:
        S["convoy_done"] = S["t0"]
        si = _rng.randrange(len(SITES))
        for j in range(5):
            _spawn_barge(t, site=si, delay=j * 0.9)
        _msg("CONVOY: " + SITES[si][0], AMBER, t)
    alive = []
    for b in S["barges"]:
        u = (t - b["t0"]) / b["dur"]
        if u > 1:
            continue
        alive.append(b)
        if u < 0:
            continue
        dd = np.array([math.sin(docks[b["dock"]]), 0.0, math.cos(docks[b["dock"]])])
        us = np.clip(np.array([u - k * 0.022 for k in range(6)]), 0, 1)
        if not b["up"]:
            us = 1 - us
        e = us * us * (3 - 2 * us)
        dirs = b["site"][None, :] * (1 - e[:, None]) + dd[None, :] * e[:, None]
        dirs /= np.linalg.norm(dirs, axis=1, keepdims=True)
        rad = 1.0 + (RING_R - 1.0) * (1 - (1 - us) ** 2.2)
        v = _to_view(dirs * rad[:, None], rot)
        xs, ys = _screen(v)
        vis = ~_hidden(v) & ((v[:, 2] > -0.05) | (rad > 1.02))
        _runs(d, xs, ys, vis, scale(b["col"], 0.55))
        if vis[0]:
            x, y = xs[0], ys[0]
            d.rectangle((x - 1, y - 1, x + 1, y + 1), fill=b["col"])
            if us[0] < 0.08 or us[0] > 0.92:
                d.ellipse((x - 3, y - 3, x + 3, y + 3), outline=scale(b["col"], 0.7))
    S["barges"] = alive
    while len(S["barges"]) < 6:
        _spawn_barge(t)

    # ---------------------------------------------------------- Phobos
    pa = S["phobos0"] + t * 0.16
    pw = np.array([[math.cos(pa) * 1.72, math.sin(pa) * 0.42, math.sin(pa) * 1.72]])
    pv = pw @ S["V"].T
    if not _hidden(pv)[0]:
        x, y = PCX + pv[0, 0] * RP, PCY - pv[0, 1] * RP
        r = 3.0 if pv[0, 2] >= 0 else 2.2
        d.ellipse((x - r, y - r, x + r, y + r), fill=(110, 100, 95))
        lx, ly = S["L"][0], -S["L"][1]
        d.ellipse((x - r + lx * 1.2, y - r + ly * 1.2, x + r * 0.6 + lx * 1.2, y + r * 0.6 + ly * 1.2), fill=(170, 160, 150))

    # ---------------------------------------------------------- voidship launch
    if S["launch"] is None and lt >= S["launch_t"] - S["t0"]:
        k = int(np.argmax(np.where(dh, -9, dv[:, 2])))
        p0 = np.array([dx_[k], dy_[k]])
        tv = np.array([tang[k, 0], -tang[k, 1]])
        tv /= np.linalg.norm(tv) + 1e-6
        out = p0 - np.array([PCX, PCY])
        out /= np.linalg.norm(out) + 1e-6
        S["launch"] = dict(t0=t, p0=p0, v=tv * 6 + out * 4, a=out * 6 + tv * 3)
        S["berthed"][k] = False
        _msg("VOIDSHIP LAUNCH", (255, 220, 150), t)
    L_ = S["launch"]
    if L_ is not None:
        tau = t - L_["t0"]
        if tau < 9:
            p = L_["p0"] + L_["v"] * tau + 0.5 * L_["a"] * tau * tau
            vel = L_["v"] + L_["a"] * tau
            f = vel / (np.linalg.norm(vel) + 1e-6)
            sgrow = 1 + tau * 0.25
            nx_, ny_ = -f[1], f[0]
            L0 = 13 * sgrow
            W0 = 3.8 * sgrow
            nose = p + f * L0
            tail = p - f * L0
            pts = [tuple(nose), tuple(p + np.array([nx_, ny_]) * W0), tuple(tail + np.array([nx_, ny_]) * W0 * 0.8),
                   tuple(tail - np.array([nx_, ny_]) * W0 * 0.8), tuple(p - np.array([nx_, ny_]) * W0)]
            d.polygon(pts, outline=(230, 215, 180))
            d.line((tuple(tail), tuple(nose)), fill=(160, 150, 130))
            spire = p - f * L0 * 0.4
            d.line((tuple(spire), tuple(spire + np.array([nx_, ny_]) * W0 * 1.4)), fill=(230, 215, 180))
            fl = (8 + 4 * math.sin(t * 25)) * sgrow
            d.line((tuple(tail), tuple(tail - f * fl)), fill=(120, 170, 255), width=3)
            d.line((tuple(tail), tuple(tail - f * fl * 0.5)), fill=(230, 240, 255), width=1)

    # ---------------------------------------------------------- Olympus Mons marker
    om = _to_view(_sph(math.radians(18.6), math.radians(-134.0))[None, :] * 1.01, rot)
    if om[0, 2] > 0.25:
        x, y = PCX + om[0, 0] * RP, PCY - om[0, 1] * RP
        k = min(1.0, (om[0, 2] - 0.25) / 0.2)
        c = scale((255, 230, 150), k)
        s = 5
        for sx_, sy_ in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
            d.line((x + sx_ * s, y + sy_ * s, x + sx_ * (s - 3), y + sy_ * s), fill=c)
            d.line((x + sx_ * s, y + sy_ * s, x + sx_ * s, y + sy_ * (s - 3)), fill=c)
        lx = x + 18 if x < CX else x - 18
        d.line((x + (s if x < CX else -s), y - s, lx, y - 16), fill=scale(c, 0.8))
        lab = "OLYMPUS MONS"
        w = _tw(lab, 9)
        _text(img, lx if x < CX else lx - w, y - 27, lab, c, 9)

    # ---------------------------------------------------------- HUD
    _tc(img, 16, "MARS", (240, 120, 70), 14)
    _tc(img, 33, "FORGE WORLD PRIME", HUD_DIM, 9)
    m = S["msg"]
    if m and t - m[2] < 3.0:
        on = (t - m[2]) > 0.6 or int((t - m[2]) * 8) % 2 == 0
        if on:
            _tc(img, 46, m[0], m[1], 10)
            if m[0] == "VOIDSHIP LAUNCH":
                _tc(img, 58, S["ship"], scale(m[1], 0.8), 9)
    # rotating readout pair
    slot = int(lt / 6.0)
    q = min(1.0, lt / (CYCLE - 8))
    for row, y in ((0, 180), (1, 192)):
        if row == 1 and q >= 1.0:
            _tc(img, y, "TITHE FULFILLED", (140, 240, 150), 9)
            continue
        i = (S["ro"] + slot * 2 + row) % len(READOUTS)
        base = S["stats"][i]
        wob = math.sin(t * 0.3 + i)
        name = READOUTS[i]
        if name == "FORGE OUTPUT":
            val = f"{94 + 4 * base + 1.2 * wob:4.1f}%"
        elif name == "HULLS ON SLIPS":
            val = str(9 + int(base * 8) - (1 if S["launch"] else 0))
        elif name == "LIGHTERS ALOFT":
            val = str(len(S["barges"]) + int(base * 20))
        elif name == "PROMETHIUM MT":
            val = f"{3 + base * 4 + 0.2 * wob:3.1f}"
        elif name == "NOOSPHERE SYNC":
            val = f"{97 + 2.5 * base + 0.3 * wob:4.1f}%"
        else:
            val = ["IGNATUM", "MORTIS", "INVIGILATA", "TEMPESTUS"][int(base * 4) % 4]
        text = f"{name} {val}"
        _tc(img, y, text, HUD if row == 0 else lerp_color(HUD, HUD_DIM, 0.4), 9)
    # tithe progress bar
    bx0, bx1, by = CX - 36, CX + 36, 206
    d.rectangle((bx0, by, bx1, by + 5), outline=HUD_DIM)
    w = int((bx1 - bx0 - 2) * q)
    if w > 0:
        d.rectangle((bx0 + 1, by + 1, bx0 + 1 + w, by + 4), fill=(200, 100, 60) if q < 1 else (120, 230, 140))

    fade = min(1.0, lt / 1.0, (CYCLE - lt) / 1.0)
    if fade < 1.0:
        img = Image.fromarray((np.asarray(img) * max(0.0, fade)).astype(np.uint8), "RGB")
    return img
