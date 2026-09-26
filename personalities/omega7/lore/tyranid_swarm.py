"""Tyranid Bio-Swarm – a hive fleet descends on a world and strips it to bare rock.

A slowly turning globe (texture-mapped, tilted) is divided into named regions.
A numpy flocking swarm (leaders + alignment/cohesion/separation on a coarse
grid) spores down onto the surface, feeds region by region while branching
bio-vein networks crawl across the texture and the land fades to barren
grey-brown.  The Shadow in the Warp static thickens as the biomass counter
climbs; "PLANET CONSUMED" ends the cycle and a new world is generated.
"""

from __future__ import annotations

import math
import random

import numpy as np
from PIL import Image, ImageDraw

from ._common import CX, CY, SAFE_R, Session, font, safe_half_width

NAME = "tyranid_swarm"

_rng = random.Random()
_session = Session()

# ── Geometry ─────────────────────────────────────────────────────────────────
GR = 80                 # globe radius (px)
GCX, GCY = 120, 118     # globe centre
TILT = 0.38             # axial tilt towards the viewer (rad)
TW, TH = 512, 256       # equirectangular texture
CW, CH = TW // 4, TH // 4   # coarse consumption field
N_PART = 1600
N_LEAD = 6

_ct, _st = math.cos(TILT), math.sin(TILT)


def _globe_tables():
    yy, xx = np.mgrid[0:240, 0:240]
    nx = (xx - GCX + 0.5) / GR
    ny = -(yy - GCY + 0.5) / GR
    r2 = nx * nx + ny * ny
    m = r2 < 1.0
    gy, gx = yy[m].astype(np.intp), xx[m].astype(np.intp)
    vx, vy = nx[m], ny[m]
    vz = np.sqrt(np.maximum(0.0, 1.0 - vx * vx - vy * vy))
    my = vy * _ct + vz * _st
    mz = -vy * _st + vz * _ct
    lat = np.arcsin(np.clip(my, -1, 1))
    lon0 = np.arctan2(vx, mz)
    col0 = (lon0 % (2 * math.pi)) / (2 * math.pi) * TW
    row = np.clip(((math.pi / 2 - lat) / math.pi * TH).astype(np.intp), 0, TH - 1)
    # lighting: key light upper-left/front, soft limb darkening
    L = np.array([-0.55, 0.5, 0.67])
    L /= np.linalg.norm(L)
    lam = np.clip(vx * L[0] + vy * L[1] + vz * L[2], 0, 1)
    shade = (0.22 + 0.85 * lam) * (0.55 + 0.45 * vz ** 0.4)
    return gy, gx, col0.astype(np.float32), row, shade.astype(np.float32)[:, None]


_GY, _GX, _COL0, _ROW, _SHADE = _globe_tables()
_ROWC = _ROW >> 2

# texel direction vectors (for region voronoi)
_tr = (np.arange(TH) + 0.5) / TH
_tc = (np.arange(TW) + 0.5) / TW
_TLAT = (math.pi / 2 - _tr * math.pi)[:, None] * np.ones((1, TW))
_TLON = (_tc * 2 * math.pi)[None, :] * np.ones((TH, 1))
_TVEC = np.stack([np.cos(_TLAT) * np.sin(_TLON), np.sin(_TLAT), np.cos(_TLAT) * np.cos(_TLON)], -1).astype(np.float32)
_CVEC = _TVEC[2::4, 2::4]

# ── Static space background + atmosphere halo ───────────────────────────────
_yy, _xx = np.mgrid[0:240, 0:240]
_RR = np.sqrt((_xx - GCX + 0.5) ** 2 + (_yy - GCY + 0.5) ** 2)
_HALO = (np.clip(1 - np.abs(_RR - GR - 1.5) / 7.0, 0, 1) ** 1.6)[:, :, None] * np.array([70, 140, 255])
_HALO = (_HALO * (_RR >= GR - 1)[:, :, None]).astype(np.float32)

_NOISE = None  # static noise tiles (built lazily)

WORLD_NAMES = ["TYRAN", "SOTHA", "PRAL IV", "GRYPHONNE IV", "KALIDUS VII", "IXXAR", "VORLANE IX",
               "MACEDON SECUNDUS", "THANDROS", "OCTARIUS MINOR", "KELMARA", "DUSKHOLD", "AMBRAX III",
               "PERDITUS", "CALLOR PRIME", "JUDAH IV"]
FLEETS = ["BEHEMOTH", "KRAKEN", "LEVIATHAN", "GORGON", "JORMUNGANDR", "HYDRA", "KRONOS", "NAUGA"]
REGION_NAMES = ["HIVE PRIMUS", "AGRI-ZONE IV", "MANUFACTORUM", "ARBITES KEEP", "PDF BASTION",
                "CATHEDRAL SPIRE", "STARPORT", "OCEAN REFINERY", "PROMETHIUM FIELD", "HIVE SECUNDUS",
                "SCHOLA PROGENIUM", "GRAIN BELT", "MINING SPUR", "GOVERNOR'S PALACE", "LAND-TRAIN HUB",
                "MUNITORUM DEPOT"]
WORLD_TYPES = ["AGRI WORLD", "OCEAN WORLD", "HIVE WORLD", "FEUDAL WORLD"]

# ── State ────────────────────────────────────────────────────────────────────
_S: dict = {}


def _noise(h, w, cy, cx, octaves=4, persist=0.5):
    """Fractal value noise in [0,1], seamless in x."""
    acc = np.zeros((h, w), np.float32)
    amp, tot = 1.0, 0.0
    for o in range(octaves):
        gy, gx = cy * (2 ** o), cx * (2 ** o)
        base = np.array([[_rng.random() for _ in range(gx)] for _ in range(gy)], np.float32)
        tiled = np.concatenate([base, base, base], 1)
        im = Image.fromarray(tiled).resize((3 * w, h), Image.BICUBIC)
        a = np.asarray(im)[:, w:2 * w]
        acc += a * amp
        tot += amp
        amp *= persist
    acc /= tot
    lo, hi = float(acc.min()), float(acc.max())
    return (acc - lo) / max(1e-6, hi - lo)


def _build_world():
    wtype = _rng.choice(WORLD_TYPES)
    h = _noise(TH, TW, 4, 8, 5)
    det = _noise(TH, TW, 8, 16, 3)
    lat_abs = np.abs(_TLAT) / (math.pi / 2)
    sea = {"AGRI WORLD": 0.42, "OCEAN WORLD": 0.62, "HIVE WORLD": 0.35, "FEUDAL WORLD": 0.48}[wtype]
    sea += _rng.uniform(-0.05, 0.05)
    land = h > sea
    base = np.zeros((TH, TW, 3), np.float32)
    depth = np.clip((sea - h) / sea, 0, 1)[..., None]
    base[:] = (1 - depth) * np.array([34, 92, 150]) + depth * np.array([10, 30, 80])
    e = np.clip((h - sea) / (1 - sea), 0, 1)[..., None]
    if wtype == "HIVE WORLD":
        lo, hi = np.array([50, 110, 90]), np.array([120, 140, 120])
    elif wtype == "FEUDAL WORLD":
        lo, hi = np.array([70, 110, 40]), np.array([150, 130, 80])
    else:
        lo, hi = np.array([36, 120, 48]), np.array([120, 130, 70])
    lc = lo + (hi - lo) * np.clip(e * 1.6, 0, 1) + (det[..., None] - 0.5) * 30
    lc = np.where(e > 0.7, lc * 0.6 + np.array([150, 140, 125]) * 0.4, lc)
    base = np.where(land[..., None], lc, base)
    ice = (lat_abs + det * 0.18) > 0.86
    base[ice] = np.array([210, 225, 235])
    # regions (voronoi on the sphere, noisy borders)
    nreg = _rng.randint(6, 8)
    seeds = []
    tries = 0
    while len(seeds) < nreg and tries < 500:
        tries += 1
        la = _rng.uniform(-0.45, 0.8)
        lo_ = _rng.uniform(0, 2 * math.pi)
        v = np.array([math.cos(la) * math.sin(lo_), math.sin(la), math.cos(la) * math.cos(lo_)])
        if all(float(v @ s) < 0.72 for s in seeds):
            seeds.append(v)
    seeds = np.array(seeds, np.float32)
    nreg = len(seeds)
    dots = _TVEC @ seeds.T + (det[..., None] - 0.5) * 0.35
    region = np.argmax(dots, -1).astype(np.int8)
    edge = np.zeros((TH, TW), bool)
    edge[:, 1:] |= region[:, 1:] != region[:, :-1]
    edge[1:, :] |= region[1:, :] != region[:-1, :]
    base[edge] = base[edge] * 0.55 + np.array([200, 180, 90]) * 0.25
    # cities: bright clusters around each seed
    lights = 0.0
    ncity = 5 if wtype == "HIVE WORLD" else 3
    for s in seeds:
        sl = math.asin(float(s[1]))
        so = math.atan2(float(s[0]), float(s[2])) % (2 * math.pi)
        for k in range(ncity):
            cl = sl + _rng.gauss(0, 0.12)
            co = so + _rng.gauss(0, 0.16)
            r0 = int((math.pi / 2 - cl) / math.pi * TH)
            c0 = int(co / (2 * math.pi) * TW)
            rad = 2 if k else 3
            for dy in range(-rad, rad + 1):
                for dx in range(-rad - 1, rad + 2):
                    if dx * dx + dy * dy <= rad * rad + 1 and _rng.random() < 0.75:
                        rr = min(TH - 1, max(0, r0 + dy))
                        base[rr, (c0 + dx) % TW] = (255, 225, 120) if _rng.random() < 0.6 else (255, 250, 200)
    del lights
    base = np.clip(base, 0, 255).astype(np.float32)
    # barren husk: grey-brown with dark cracks
    n2 = _noise(TH, TW, 6, 12, 4)
    barren = np.array([104, 88, 70], np.float32) + (n2[..., None] - 0.5) * 50
    barren = np.where(land[..., None], barren, barren * 0.62)
    crack = np.abs(det - 0.5) < 0.018
    barren[crack] *= 0.45
    # coarse data
    reg_c = region[2::4, 2::4]
    cd = np.arccos(np.clip(np.einsum("ijk,ijk->ij", _CVEC, seeds[reg_c]), -1, 1))
    spread = np.zeros((CH, CW), np.float32)
    nzc = _noise(CH, CW, 4, 8, 3)
    for r in range(nreg):
        mk = reg_c == r
        if mk.any():
            dm = cd[mk]
            spread[mk] = dm / max(1e-3, float(dm.max()))
    spread = np.clip(spread * 0.75 + nzc * 0.35, 0, 1.05)
    cells = []
    for r in range(nreg):
        rr, cc = np.nonzero(reg_c == r)
        lat = math.pi / 2 - (rr + 0.5) / CH * math.pi
        lon = (cc + 0.5) / CW * 2 * math.pi
        keep = np.abs(lat) < 1.15
        if keep.sum() < 4:
            keep[:] = True
        cells.append((lat[keep].astype(np.float32), lon[keep].astype(np.float32)))
    names = _rng.sample(REGION_NAMES, nreg)
    return dict(wtype=wtype, base=base, barren=barren.astype(np.float32), region=region, reg_c=reg_c,
                seeds=seeds, nreg=nreg, spread=spread, cells=cells, names=names,
                fine=(_noise(TH, TW, 16, 32, 2) * 0.9).astype(np.float32))


def _seed_latlon(s):
    return math.asin(float(s[1])), math.atan2(float(s[0]), float(s[2])) % (2 * math.pi)


def _build_stars():
    arr = np.zeros((240, 240, 3), np.float32)
    arr[:] = (2, 0, 6)
    for _ in range(170):
        x, y = _rng.randrange(240), _rng.randrange(240)
        b = _rng.random() ** 2.5 * 200 + 30
        arr[y, x] = (b * 0.9, b * 0.85, b)
    # faint purple nebula (the hive fleet's warp shadow)
    neb = _noise(240, 240, 3, 3, 3)
    arr += (np.clip(neb - 0.55, 0, 1) * 110)[..., None] * np.array([0.6, 0.15, 0.8])
    return arr


def _new_cycle(t0):
    global _NOISE
    if _NOISE is None:
        g = np.random.default_rng(_rng.randrange(1 << 30))
        _NOISE = (g.standard_normal((480, 240, 1)) * 18.0).astype(np.float32)
    w = _build_world()
    nreg = w["nreg"]
    first = _rng.randrange(nreg)
    order = [first]
    while len(order) < nreg:
        last = w["seeds"][order[-1]]
        rest = [r for r in range(nreg) if r not in order]
        order.append(max(rest, key=lambda r: float(w["seeds"][r] @ last) + _rng.uniform(0, 0.25)))
    la, lo = _seed_latlon(w["seeds"][first])
    # particles start around the landing zone
    g = np.random.default_rng(_rng.randrange(1 << 30))
    plat = (la + g.normal(0, 0.12, N_PART)).astype(np.float32)
    plon = (lo + g.normal(0, 0.12, N_PART)).astype(np.float32)
    ang = _rng.uniform(0, 2 * math.pi)
    dist = 170 + g.random(N_PART) * 90
    spread = g.normal(0, 38, N_PART)
    sx0 = CX + math.cos(ang) * dist - math.sin(ang) * spread
    sy0 = CY + math.sin(ang) * dist + math.cos(ang) * spread
    pal = np.array([[150, 70, 200], [190, 100, 230], [110, 40, 150], [225, 205, 170], [240, 225, 195],
                    [170, 40, 120]], np.float32)
    pc = g.choice(len(pal), N_PART, p=[0.3, 0.2, 0.2, 0.14, 0.08, 0.08])
    _S.clear()
    _S.update(
        t0=t0, w=w, order=order, oi=0, prog=np.zeros(nreg, np.float32), tstart=None,
        F=np.zeros((CH, CW), np.float32), vein=Image.new("L", (TW, TH), 0),
        plat=plat, plon=plon, pvx=np.zeros(N_PART, np.float32), pvy=np.zeros(N_PART, np.float32),
        off_r=np.abs(g.normal(0, 0.1, N_PART)).astype(np.float32) + 0.015,
        off_a=(g.random(N_PART) * 2 * math.pi).astype(np.float32),
        lead_id=(np.arange(N_PART) % N_LEAD),
        delay=(1.5 + g.random(N_PART) ** 0.7 * 6.0).astype(np.float32),
        sx0=sx0.astype(np.float32), sy0=sy0.astype(np.float32), pcol=pal[pc].astype(np.uint8),
        lead=[[la + _rng.gauss(0, 0.05), lo + _rng.gauss(0, 0.05), la, lo, _rng.uniform(0.6, 1.4) *
               _rng.choice([-1, 1])] for _ in range(N_LEAD)],
        rot=lo, tips=[], fleet=_rng.choice(FLEETS), world=_rng.choice(WORLD_NAMES),
        biomass=0.0, done_t=None, last=None, lift=None,
        stars=_build_stars(), bmscale=_rng.uniform(2.0, 9.0),
    )


def _reset():
    _new_cycle(0.0)


def _wrap(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


def _project(lat, lon, rot):
    cl = np.cos(lat)
    d = lon - rot
    x = cl * np.sin(d)
    y = np.sin(lat)
    z = cl * np.cos(d)
    yv = y * _ct - z * _st
    zv = y * _st + z * _ct
    return GCX + GR * x, GCY - GR * yv, zv


def _sim(dt, t, active):
    S = _S
    w = S["w"]
    tgt = S["order"][min(S["oi"], len(S["order"]) - 1)]
    lat_cells, lon_cells = w["cells"][tgt]
    # leaders wander between waypoints in the target region
    lx = np.empty(N_LEAD, np.float32)
    ly = np.empty(N_LEAD, np.float32)
    for k, L in enumerate(S["lead"]):
        dlon = _wrap(L[3] - L[1]) * math.cos(L[0])
        dlat = L[2] - L[0]
        d = math.hypot(dlon, dlat)
        if d < 0.04 or _rng.random() < 0.004:
            i = _rng.randrange(len(lat_cells))
            L[2], L[3] = float(lat_cells[i]), float(lon_cells[i])
        else:
            sp = min(d, 0.32 * dt) / d
            L[0] += dlat * sp
            L[1] = (L[1] + dlon * sp / max(0.3, math.cos(L[0]))) % (2 * math.pi)
        lx[k], ly[k] = L[1], L[0]
    if not active:
        return
    lat, lon = S["plat"], S["plon"]
    vx, vy = S["pvx"], S["pvy"]
    lid = S["lead_id"]
    spin = np.array([L[4] for L in S["lead"]], np.float32)
    a = S["off_a"] + spin[lid] * t * 0.6
    tx = lx[lid]
    ty = ly[lid] + S["off_r"] * np.sin(a)
    cl = np.maximum(0.25, np.cos(lat))
    dx = ((tx - lon + math.pi) % (2 * math.pi) - math.pi) * cl + S["off_r"] * np.cos(a)
    dy = ty - lat
    dist = np.sqrt(dx * dx + dy * dy) + 1e-4
    pull = np.minimum(1.0, dist * 6.0)
    ax = dx / dist * pull * 1.8
    ay = dy / dist * pull * 1.8
    # alignment + separation on a coarse grid
    gr = np.clip(((math.pi / 2 - lat) / math.pi * 32).astype(np.intp), 0, 31)
    gc = ((lon % (2 * math.pi)) / (2 * math.pi) * 64).astype(np.intp) % 64
    idx = gr * 64 + gc
    cnt = np.bincount(idx, minlength=2048).astype(np.float32)
    mvx = np.bincount(idx, vx, 2048) / np.maximum(cnt, 1)
    mvy = np.bincount(idx, vy, 2048) / np.maximum(cnt, 1)
    ax += (mvx[idx] - vx) * 1.6
    ay += (mvy[idx] - vy) * 1.6
    dens = cnt.reshape(32, 64)
    gy_, gx_ = np.gradient(dens)
    ax -= gx_.ravel()[idx] * 0.012
    ay += gy_.ravel()[idx] * 0.012
    g = np.random.default_rng(_rng.randrange(1 << 30))
    ax += g.normal(0, 0.55, N_PART).astype(np.float32)
    ay += g.normal(0, 0.55, N_PART).astype(np.float32)
    vx += ax * dt
    vy += ay * dt
    damp = 1.0 - 1.2 * dt
    vx *= damp
    vy *= damp
    sp = np.sqrt(vx * vx + vy * vy)
    lim = np.where(sp > 0.55, 0.55 / np.maximum(sp, 1e-6), 1.0)
    vx *= lim
    vy *= lim
    lon += vx / cl * dt
    lat += vy * dt
    np.clip(lat, -1.25, 1.25, out=lat)
    np.mod(lon, 2 * math.pi, out=lon)


def _grow_veins(t, n_new):
    S = _S
    tips = S["tips"]
    landed = S["landed"]
    lat, lon = S["plat"], S["plon"]
    li = np.nonzero(landed)[0]
    for _ in range(n_new):
        if len(tips) > 40 or len(li) == 0 or S.get("vseg", 0) > 4500:
            break
        i = int(li[_rng.randrange(len(li))])
        c = float(lon[i]) / (2 * math.pi) * TW
        r = (math.pi / 2 - float(lat[i])) / math.pi * TH
        tips.append([c, r, _rng.uniform(0, 2 * math.pi), _rng.randint(40, 130), 2])
    d = ImageDraw.Draw(S["vein"])
    alive = []
    for tp in tips:
        c, r, ang, life, wd = tp
        la = math.pi / 2 - r / TH * math.pi
        ang += _rng.uniform(-0.35, 0.35)
        c2 = c + math.cos(ang) * 1.6 / max(0.3, math.cos(la))
        r2 = r + math.sin(ang) * 1.6
        if r2 < 12 or r2 > TH - 12:
            continue
        if 0.0 <= c2 < TW:
            d.line([(c % TW, r), (c2 % TW, r2)], fill=210 if wd > 1 else 150, width=1)
            S["vseg"] = S.get("vseg", 0) + 1
        life -= 1
        tp[:] = [c2 % TW, r2, ang, life, wd]
        if life > 0:
            alive.append(tp)
            if _rng.random() < 0.03 and len(tips) + len(alive) < 60:
                alive.append([c2 % TW, r2, ang + _rng.choice([-1, 1]) * _rng.uniform(0.5, 1.1),
                              int(life * 0.6), 1])
    S["tips"] = alive


_TXT: dict = {}


def _tsprite(text, size):
    key = (text, size)
    m = _TXT.get(key)
    if m is None:
        if len(_TXT) > 300:
            _TXT.clear()
        f = font(size)
        l, t, r, b = f.getbbox(text)
        im = Image.new("L", (max(1, int(r)) + 2, max(1, int(b)) + 2), 0)
        ImageDraw.Draw(im).text((0, 0), text, fill=255, font=f)
        m = _TXT[key] = (im, f.getlength(text))
    return m


def _text(img, x, y, text, fill, size, shadow=(0, 0, 0)):
    """Blit cached text (FreeType rendering is too slow to redo every frame)."""
    m, w = _tsprite(text, size)
    if shadow is not None:
        img.paste(shadow, (int(x) + 1, int(y) + 1), m)
    img.paste(fill, (int(x), int(y)), m)
    return w


def _fit(img, y, text, fill, size, shadow=(0, 0, 0)):
    hw = safe_half_width(y + size * 0.6, 4)
    while size > 9 and _tsprite(text, size)[1] > 2 * hw:
        size -= 1
    w = _tsprite(text, size)[1]
    _text(img, CX - w / 2, y, text, fill, size, shadow)


def _fmt_biomass(v):
    if v < 1000:
        return f"{v:6.1f} MT"
    if v < 1e6:
        return f"{v / 1e3:6.2f} GT"
    return f"{v / 1e6:6.2f} PT"


def render(bezel, mask, now: float) -> Image.Image:
    if _session.fresh(now):
        _reset()
    t_all = _session.t(now)
    S = _S
    if S.get("pending"):
        _new_cycle(t_all)
    S = _S
    t = t_all - S["t0"]
    dt = 1 / 30 if S["last"] is None else min(0.1, max(0.0, now - S["last"]))
    S["last"] = now
    w = S["w"]
    nreg = w["nreg"]

    # ── story control ──
    done = S["done_t"] is not None
    if not done:
        if t > 7.0 and S["tstart"] is None:
            S["tstart"] = t
        if S["tstart"] is not None and S["oi"] < nreg:
            r = S["order"][S["oi"]]
            S["prog"][r] = min(1.0, S["prog"][r] + dt / 10.0)
            if S["prog"][r] >= 1.0:
                S["oi"] += 1
        if S["oi"] >= nreg or t > 125:
            S["done_t"] = t
            S["prog"][:] = 1.0
            done = True
    tdone = (t - S["done_t"]) if done else -1.0

    # rotation: turn the feeding ground towards the viewer
    tgt = S["order"][min(S["oi"], nreg - 1)]
    tla, tlo = _seed_latlon(w["seeds"][tgt])
    if done:
        S["rot"] = (S["rot"] + 0.08 * dt) % (2 * math.pi)
    else:
        goal = tlo + 0.18 * math.sin(t * 0.21)
        S["rot"] = (S["rot"] + _wrap(goal - S["rot"]) * min(1.0, 0.9 * dt)) % (2 * math.pi)
    rot = S["rot"]

    landed = (t - S["delay"]) > 2.4
    S["landed"] = landed
    _sim(dt, t, True)

    # consumption field: swarm stamps + region forcing
    F = S["F"]
    if not done or tdone < 3:
        lat, lon = S["plat"], S["plon"]
        rr = np.clip(((math.pi / 2 - lat[landed]) / math.pi * CH).astype(np.intp), 0, CH - 1)
        cc = ((lon[landed] % (2 * math.pi)) / (2 * math.pi) * CW).astype(np.intp) % CW
        stamp = np.bincount(rr * CW + cc, minlength=CH * CW).reshape(CH, CW).astype(np.float32)
        F += np.minimum(stamp, 6) * (0.010 * dt * 30)
        force = np.clip((S["prog"][w["reg_c"]] * 1.35 - w["spread"]) * 4.0, 0, 1)
        np.maximum(F, force, out=F)
        np.minimum(F, 1.0, out=F)
        if landed.any():
            _grow_veins(t, 1 if _rng.random() < 0.45 else 0)
    cons_frac = float(F.mean())
    S["biomass"] = cons_frac * S["bmscale"] * 1e6 * (0.9 + 0.1 * cons_frac)
    if int(t * 5) != S.get("bmtick"):
        S["bmtick"] = int(t * 5)
        S["bmtxt"] = _fmt_biomass(S["biomass"])

    # ── compose ──
    atm = max(0.0, 1.0 - cons_frac * 1.15)
    if done:
        fade = min(1.0, tdone / 1.5)
        atm *= 1 - fade
    arr = S["stars"] + _HALO * atm
    # globe texture sampling
    col = ((_COL0 + rot / (2 * math.pi) * TW).astype(np.intp)) % TW
    base = w["base"][_ROW, col]
    barren = w["barren"][_ROW, col]
    fv = F[_ROWC, col >> 2]
    c = np.clip((fv * 1.4 - w["fine"][_ROW, col]) * 3.0, 0, 1)[:, None]
    colr = base + (barren - base) * c
    vein = np.asarray(S["vein"])[_ROW, col].astype(np.float32)[:, None] * (1 / 255) * (0.3 + 0.55 * c)
    pulse = 0.75 + 0.25 * math.sin(t * 3.1)
    vcol = np.array([150 * pulse + 40, 45, 185 * pulse + 30], np.float32)
    colr = colr + (vcol - colr) * vein
    colr *= _SHADE
    if done and tdone > 9.0:
        k = max(0.0, 1 - (tdone - 9.0) / 3.0)
        colr *= k
        arr = arr * k
    arr[_GY, _GX] = colr

    # particles
    lat, lon = S["plat"], S["plon"]
    sx, sy, sz = _project(lat, lon, rot)
    prog = np.clip((t - S["delay"]) / 2.4, 0, 1)
    e = prog * prog
    fx = S["sx0"] + (sx - S["sx0"]) * e
    fy = S["sy0"] + (sy - S["sy0"]) * e
    vis = (sz > 0.02) | (prog < 0.97)
    if done:
        # lift-off back to the hive ships
        lt = np.clip(tdone - 1.0 - (S["delay"] - 1.5) * 0.4, 0, None)
        ox, oy = fx - GCX, fy - GCY
        on = np.sqrt(ox * ox + oy * oy) + 1e-3
        push = lt * lt * 30.0
        fx = fx + ox / on * push
        fy = fy + oy / on * push - lt * 8
        vis = vis & (lt < 6)
        vis = vis | ((lt > 0) & (lt < 6))
    started = t > S["delay"] - 3.0
    vis &= started
    ix = fx.astype(np.intp)
    iy = fy.astype(np.intp)
    ok = vis & (ix >= 0) & (ix < 239) & (iy >= 0) & (iy < 239)
    ix, iy = ix[ok], iy[ok]
    pc = S["pcol"][ok].astype(np.float32)
    dimk = np.clip(sz[ok] * 1.5 + 0.35, 0.35, 1.0)[:, None]
    dimk = np.where((prog[ok] < 0.97)[:, None], 1.0, dimk)
    arr[iy, ix] = pc * dimk
    # streak / body pixel for in-flight spores and big warrior-forms
    big = (prog[ok] < 0.97) | (S["pcol"][ok][:, 0] > 215)
    arr[iy[big] + 1, ix[big]] = pc[big] * 0.55

    # Shadow in the Warp static
    warp = 0.10 + cons_frac * 0.5 + (0.35 if _rng.random() < 0.03 else 0.0)
    if done:
        warp = max(0.05, warp - tdone * 0.05)
    sh = _rng.randrange(240)
    arr += _NOISE[sh:sh + 240] * np.float32(warp)
    if _rng.random() < 0.05 + cons_frac * 0.08:
        y0 = _rng.randrange(20, 210)
        h = _rng.randint(2, 7)
        arr[y0:y0 + h] = np.roll(arr[y0:y0 + h], _rng.randint(-14, 14), 1) * 1.15 + np.array([20, 0, 30])
    np.clip(arr, 0, 255, out=arr)
    img = Image.fromarray(arr.astype(np.uint8))
    d = ImageDraw.Draw(img)

    # ── HUD ──
    # target reticle
    if not done and S["tstart"] is not None:
        px, py, pz = _project(np.float32(tla), np.float32(tlo), rot)
        if pz > 0.1:
            px, py = float(px), float(py)
            rr_ = 9 + 2 * math.sin(t * 5)
            colh = (255, 70, 90)
            for k in range(4):
                a0 = k * 90 + t * 60
                d.arc([px - rr_, py - rr_, px + rr_, py + rr_], a0, a0 + 50, fill=colh, width=1)
    # rim gauges: biomass (left), regions (right)
    rim = SAFE_R - 3
    box = [CX - rim, CY - rim, CX + rim, CY + rim]
    d.arc(box, 120, 240, fill=(50, 20, 60), width=4)
    fillb = min(1.0, cons_frac)
    if fillb > 0.005:
        d.arc(box, 240 - 120 * fillb, 240, fill=(190, 70, 230), width=4)
    seg = 120.0 / nreg
    for r in range(nreg):
        a0 = -60 + r * seg + 1.5
        pr = float(S["prog"][S["order"][r]])
        colg = (60, 140, 70) if pr <= 0 else ((170, 140, 90) if pr >= 1 else (230, 80, 100))
        d.arc(box, a0, a0 + seg - 3, fill=colg, width=4)
    top = f"HIVE FLEET {S['fleet']}"
    _fit(img, 22, top, (200, 120, 235), 11)
    _fit(img, 35, f"{S['world']} - {w['wtype']}", (170, 170, 150), 9)
    if not done:
        if S["tstart"] is None:
            msg = "BIO-SPORES INBOUND" if int(t * 2) % 2 or t > 2 else ""
            _fit(img, 196, msg, (255, 110, 120), 10)
        else:
            _fit(img, 196, "DEVOURING: " + w["names"][tgt], (235, 150, 150), 9)
        _fit(img, 207, "BIOMASS " + S["bmtxt"], (215, 195, 160), 10)
    else:
        if tdone < 12.0:
            if (int(tdone * 3) % 4 != 0 or tdone > 1.5) and tdone < 9.0:
                bw = 150
                d.rectangle([CX - bw // 2, CY - 18, CX + bw // 2, CY + 20], fill=(20, 0, 20), outline=(200, 60, 220))
                _fit(img, CY - 14, "PLANET CONSUMED", (240, 120, 255), 16)
                _fit(img, CY + 6, "BIOMASS " + S["bmtxt"], (215, 195, 160), 9)
            if tdone > 4:
                _fit(img, 200, "NEW PREY SOUGHT...", (170, 120, 200), 10)
        if tdone > 12.0:
            S["pending"] = True
    # flickering warp-shadow warning
    if warp > 0.3 and (int(now * 4) % 5 == 0):
        _fit(img, 49, "SHADOW IN THE WARP", (200, 90, 230), 9)
    return img
