"""Drop Pod Assault – orbital planetfall on a rotating 3D wireframe world.

A lit, textured planet rotates with a lat/long wireframe; a Battle Barge in
high orbit designates landing zones with insertion beams, drop pods streak in
on re-entry trails, impact flashes bloom, then Imperial control zones spread
across the surface while xenos-held zones pulse red and shrink. All zones live
on the sphere (proper 3D, back-facing hidden). The campaign ends with the world
secured – or Exterminatus if the xenos cannot be dislodged – then a new world.
"""

from __future__ import annotations

import math
import random

import numpy as np
from PIL import Image, ImageDraw

from ._common import CX, Session, font, lerp_color, scale

NAME = "drop_pod_assault"


# ------------------------------------------------------------- cached text ---
# Rasterising glyphs is the single most expensive thing per frame on the Pi, so
# each (text, size) is rendered once to an L mask and blitted with draw.bitmap.
_TXT_CACHE = {}
_LEN_CACHE = {}


def _tlen(text, size):
    key = (text, size)
    w = _LEN_CACHE.get(key)
    if w is None:
        if len(_LEN_CACHE) > 400:
            _LEN_CACHE.clear()
        w = _LEN_CACHE[key] = font(size).getlength(text)
    return w


def _txt(d, xy, text, fill, size):
    key = (text, size)
    m = _TXT_CACHE.get(key)
    if m is None:
        if len(_TXT_CACHE) > 400:
            _TXT_CACHE.clear()
        f = font(size)
        box = f.getbbox(text)
        m = Image.new("L", (max(1, int(box[2]) + 2), max(1, int(box[3]) + 2)), 0)
        ImageDraw.Draw(m).text((0, 0), text, fill=255, font=f)
        _TXT_CACHE[key] = m
    d.bitmap((int(round(xy[0])), int(round(xy[1]))), m, fill=fill)

_rng = random.Random()
_session = Session()

DT = 1.0 / 30.0
PR = 74                 # planet radius, px
PX, PY = CX, 118        # planet centre on screen
TILT = 0.38
TEX_H, TEX_W = 128, 256
SPIN = 0.11             # rad/s

HUD = (120, 200, 255)
GOLD = (255, 200, 80)
RED = (255, 60, 40)
WHITE = (255, 255, 255)

_WORLDS = ["CALTH", "ISTVAAN", "MACRAGGE", "OCTARIUS", "BADAB", "ARMAGEDDON", "PISCINA",
           "TALLARN", "HYDRAPHUR", "BAAL SECUNDUS", "CHOGORIS", "NOCTURNE", "FENRIS", "KRIEG"]
_SUFFIX = ["PRIME", "SECUNDUS", "TERTIUS", "IV", "VII", "MINORIS", "MAJORIS"]
_CHAPTERS = ["ULTRAMARINES", "IMPERIAL FISTS", "SALAMANDERS", "WHITE SCARS", "BLOOD ANGELS",
             "DARK ANGELS", "SPACE WOLVES", "RAVEN GUARD", "CRIMSON FISTS"]
_FOES = ["ORK", "TYRANID", "TRAITOR", "NECRON", "ELDAR"]

# world types: ocean, lowland, highland, ice colours
_PALETTES = {
    "HIVE WORLD":   [(30, 34, 44), (92, 84, 70), (140, 128, 110), (190, 190, 200)],
    "DEATH WORLD":  [(14, 40, 50), (40, 110, 44), (70, 90, 40), (170, 200, 180)],
    "ICE WORLD":    [(40, 70, 110), (170, 190, 210), (220, 230, 240), (250, 250, 255)],
    "DESERT WORLD": [(70, 46, 30), (190, 140, 80), (150, 96, 60), (230, 210, 170)],
    "AGRI WORLD":   [(20, 50, 100), (80, 140, 60), (120, 130, 70), (220, 230, 235)],
}


# ------------------------------------------------------------- static geometry ---

def _disc_geometry():
    yy, xx = np.mgrid[0:240, 0:240].astype(np.float32)
    dx, dy = (xx - PX) / PR, (yy - PY) / PR
    r2 = dx * dx + dy * dy
    inside = r2 < 1.0
    idx = np.nonzero(inside.ravel())[0]
    nx, ny = dx.ravel()[idx], dy.ravel()[idx]
    nz = -np.sqrt(np.maximum(0.0, 1.0 - nx * nx - ny * ny))
    N = np.stack([nx, ny, nz], axis=1).astype(np.float32)
    L = np.array([-0.55, -0.45, -0.70], np.float32)
    L /= np.linalg.norm(L)
    lam = np.clip(N @ L, 0.0, 1.0)
    light = (0.10 + 0.90 * lam ** 0.9).astype(np.float32)
    limb = np.clip(1.0 + nz * 1.0, 0, 1)   # 0 at centre, ~1 at limb
    return idx, N, light, limb, np.sqrt(r2)


_IDX, _N, _LIGHT, _LIMB, _RR = _disc_geometry()


def _tilted_polar():
    ct, stt = math.cos(TILT), math.sin(TILT)
    rx = np.array([[1, 0, 0], [0, ct, -stt], [0, stt, ct]], np.float32)
    U = _N @ rx
    lat = np.arcsin(np.clip(U[:, 1], -1, 1))
    lon = np.arctan2(U[:, 2], U[:, 0])
    li = np.clip(((lat + math.pi / 2) * (TEX_H / math.pi)).astype(np.int32), 0, TEX_H - 1)
    lo0 = ((lon + math.pi) * (TEX_W / (2 * math.pi))).astype(np.float32)
    step = math.pi / 6
    latgrid = np.abs(((lat + step / 2) % step) - step / 2) < 0.012
    gridcol = (np.array([70, 150, 220], np.float32)[None, :] * (0.35 + 0.65 * _LIGHT[:, None])).astype(np.float32)
    return li * TEX_W, lo0, lon.astype(np.float32), np.cos(lat).astype(np.float32), latgrid, gridcol


_LI0, _LO0, _LON0, _COSLAT, _LATGRID, _GRIDCOL = _tilted_polar()


def _rotmat(t):
    a = SPIN * t
    ca, sa = math.cos(a), math.sin(a)
    ry = np.array([[ca, 0, sa], [0, 1, 0], [-sa, 0, ca]], np.float32)
    ct, stt = math.cos(TILT), math.sin(TILT)
    rx = np.array([[1, 0, 0], [0, ct, -stt], [0, stt, ct]], np.float32)
    return rx @ ry   # world -> camera


def _rand_unit(rnd):
    z = rnd.uniform(-0.8, 0.8)
    a = rnd.uniform(0, 2 * math.pi)
    r = math.sqrt(1 - z * z)
    return np.array([r * math.cos(a), z, r * math.sin(a)], np.float32)


def _angdist(a, b):
    return math.acos(max(-1.0, min(1.0, float(np.dot(a, b)))))


# ------------------------------------------------------------- state ---

class _S:
    pass


_st = _S()
_st.ready = False


def _make_texture():
    rnd = _rng
    H, Wd = TEX_H, TEX_W
    lat = (np.arange(H, dtype=np.float32) + 0.5) / H * math.pi - math.pi / 2
    lon = (np.arange(Wd, dtype=np.float32) + 0.5) / Wd * 2 * math.pi - math.pi
    la, lo = np.meshgrid(lat, lon, indexing="ij")
    p = np.stack([np.cos(la) * np.cos(lo), np.sin(la), np.cos(la) * np.sin(lo)], axis=-1)
    n = np.zeros((H, Wd), np.float32)
    for k in range(9):
        d = np.array([rnd.gauss(0, 1) for _ in range(3)], np.float32)
        d /= np.linalg.norm(d)
        f = rnd.uniform(1.5, 5.5)
        n += np.sin(p @ d * f + rnd.uniform(0, 6.28)) / (1 + k * 0.35)
    n /= np.abs(n).max()
    ptype = rnd.choice(list(_PALETTES))
    pal = np.array(_PALETTES[ptype], np.float32)
    sea = rnd.uniform(-0.15, 0.2)
    cls = np.where(n < sea, 0, np.where(n < sea + 0.35, 1, 2))
    cls = np.where(np.abs(la) > 1.25, 3, cls)
    tex = pal[cls]
    # subtle shading by noise
    tex *= (0.85 + 0.25 * n[..., None])
    return np.clip(tex, 0, 255).astype(np.float32), ptype


def _make_bg():
    arr = np.zeros((240, 240, 3), np.float32)
    arr[:] = (2, 3, 8)
    for _ in range(90):
        x, y = _rng.randrange(240), _rng.randrange(240)
        b = _rng.uniform(40, 200)
        arr[y, x] = (b, b, min(255, b * 1.1))
    # atmosphere halo
    halo = np.clip(1.0 - (_RR - 1.0) * 9.0, 0, 1) * (_RR >= 1.0)
    yy, xx = np.mgrid[0:240, 0:240].astype(np.float32)
    side = np.clip(0.6 - ((xx - PX) * 0.55 + (yy - PY) * 0.45) / PR * 0.6, 0.2, 1.0)
    arr += (halo * side)[..., None] * np.array([60, 120, 220], np.float32)
    return np.clip(arr, 0, 255).astype(np.uint8)


def _reset():
    _st.ready = True
    _new_campaign(0.0)


def _new_campaign(t0):
    st = _st
    st.t0 = t0
    st.sim_t = 0.0
    st.tex, st.ptype = _make_texture()
    st.tex_flat = st.tex.reshape(-1, 3)
    st.bg = _make_bg()
    st.world = _rng.choice(_WORLDS) + " " + _rng.choice(_SUFFIX)
    st.chapter = _rng.choice(_CHAPTERS)
    st.foe = _rng.choice(_FOES)
    st.spin0 = _rng.uniform(0, 2 * math.pi) / SPIN
    st.barge_left = _rng.random() < 0.5
    # enemy strongholds: [centre, radius, alive]
    st.enemy = []
    n_e = _rng.randint(6, 9)
    tries = 0
    while len(st.enemy) < n_e and tries < 200:
        tries += 1
        c = _rand_unit(_rng)
        if c[1] > 0.5:
            continue
        if all(_angdist(c, e[0]) > 0.55 for e in st.enemy):
            st.enemy.append([c, _rng.uniform(0.18, 0.32), True])
    st.total = len(st.enemy)
    st.secured = 0
    st.imp = []          # [centre, radius, target radius, age]
    st.pods = []         # [world target, start cam xyz, age, dur]
    st.designate = []    # [world target, age, launched]
    st.impacts = []      # [world pt, age]
    st.events = []
    st.wave_cd = 4.0
    st.counter_cd = _rng.uniform(22, 32)
    st.resolve = _rng.uniform(0.6, 1.4)   # xenos resilience this campaign
    st.pods_used = 0
    st.ending = None
    st.end_t = 0.0
    _event("PLANETFALL: " + st.chapter, GOLD)
    _event(st.ptype + " - " + st.foe + " HELD", RED)
    st.events[0][1] = -3.5


def _event(text, col):
    _st.events.insert(0, [text, 0.0, col])
    del _st.events[3:]


# ------------------------------------------------------------- sim ---

def _spin_t():
    return _st.sim_t + _st.spin0


def _cam(p, R):
    return R @ p


def _step(dt):
    st = _st
    st.sim_t += dt
    t = st.sim_t
    for e in st.events:
        e[1] += dt
    for im in st.impacts:
        im[1] += dt
    st.impacts = [im for im in st.impacts if im[1] < 1.2]
    if st.ending is not None:
        if st.ending == "exterminatus" and t - st.end_t < 3.5 and _rng.random() < dt * 8:
            R = _rotmat(_spin_t())
            p = _rand_unit(_rng)
            if (R @ p)[2] > 0:
                p = -p
            st.impacts.append([p, 0.0])   # cyclonic torpedo strikes
        return
    R = _rotmat(_spin_t())

    # --- designate landing zones in waves ---
    st.wave_cd -= dt
    alive = [e for e in st.enemy if e[2]]
    if st.wave_cd <= 0 and alive:
        st.wave_cd = _rng.uniform(9, 14)
        visible = [e for e in alive if (R @ e[0])[2] < -0.2]
        if not visible:
            st.wave_cd = 2.0
        else:
            n = _rng.randint(3, 5)
            for _ in range(n):
                e = _rng.choice(visible)
                # land around the stronghold perimeter
                off = np.array([_rng.gauss(0, 1) for _ in range(3)], np.float32)
                off -= e[0] * float(np.dot(off, e[0]))
                off /= max(1e-6, float(np.linalg.norm(off)))
                ang = e[1] * _rng.uniform(0.7, 1.3)
                p = e[0] * math.cos(ang) + off * math.sin(ang)
                p /= np.linalg.norm(p)
                st.designate.append([p.astype(np.float32), -_rng.uniform(0, 1.2), False])
            _event("LANDING ZONES DESIGNATED", HUD)
    for dz in st.designate:
        dz[1] += dt
        if dz[1] > 1.4 and not dz[2]:
            dz[2] = True
            tc = R @ dz[0] * PR
            bx = -62.0 if st.barge_left else 62.0
            start = np.array([bx + _rng.uniform(-8, 8), -80.0 + _rng.uniform(-6, 6), -160.0], np.float32)
            st.pods.append([dz[0], start, 0.0, _rng.uniform(2.0, 2.8)])
            st.pods_used += 1
    st.designate = [dz for dz in st.designate if not dz[2]]

    # --- pods in flight ---
    for pod in st.pods:
        pod[2] += dt
    landed = [pod for pod in st.pods if pod[2] >= pod[3]]
    st.pods = [pod for pod in st.pods if pod[2] < pod[3]]
    for pod in landed:
        p = pod[0]
        st.impacts.append([p, 0.0])
        merged = False
        for z in st.imp:
            if _angdist(z[0], p) < z[1] * 0.8:
                z[2] = min(0.30, z[2] + 0.04)
                merged = True
                break
        if not merged:
            if len(st.imp) >= 22:
                # consolidate: retire the oldest zone far from any live stronghold
                live = [e for e in st.enemy if e[2]]
                idle = [z for z in st.imp if all(_angdist(z[0], e[0]) > e[1] + z[1] + 0.1 for e in live)]
                if idle:
                    old = max(idle, key=lambda z: z[3])
                    st.imp = [z for z in st.imp if z is not old]
            if len(st.imp) < 22:
                st.imp.append([p, 0.0, _rng.uniform(0.12, 0.2), 0.0])

    # --- zone dynamics ---
    for z in st.imp:
        z[3] += dt
        if z[1] < z[2]:
            z[1] = min(z[2], z[1] + dt * 0.02)
    for e in st.enemy:
        if not e[2]:
            continue
        press = 0.0
        for z in st.imp:
            dd = _angdist(e[0], z[0])
            if dd < e[1] + z[1] + 0.06:
                press += z[1] / 0.2
        if press > 0:
            e[1] -= dt * 0.0095 * press / st.resolve
            if e[1] < 0.035:
                e[2] = False
                st.secured += 1
                _event("SECTOR SECURED %d/%d" % (st.secured, st.total), GOLD)
                for z in st.imp:
                    if _angdist(e[0], z[0]) < 0.6:
                        z[2] = min(0.32, z[2] + 0.05)
    # xenos counter-attack
    st.counter_cd -= dt
    if st.counter_cd <= 0:
        st.counter_cd = _rng.uniform(20, 32)
        alive = [e for e in st.enemy if e[2]]
        if alive:
            e = _rng.choice(alive)
            e[1] = min(0.4, e[1] + 0.06 * st.resolve)
            lost = [z for z in st.imp if _angdist(z[0], e[0]) < e[1]]
            st.imp = [z for z in st.imp if _angdist(z[0], e[0]) >= e[1]]
            _event(("DROP ZONE OVERRUN" if lost else st.foe + " COUNTER-ATTACK"), RED)

    # --- endings ---
    if not any(e[2] for e in st.enemy):
        st.ending = "secured"
        st.end_t = t
        _event("WORLD SECURED", GOLD)
    elif t > 105:
        st.ending = "exterminatus"
        st.end_t = t
        _event("EXTERMINATUS AUTHORISED", RED)


# ------------------------------------------------------------- draw ---

def _pod_pos(pod, R, u):
    target = (R @ pod[0]) * PR
    s = pod[1]
    e = u * u
    return s + (target - s) * e


def _occluded(p):
    x, y, z = float(p[0]), float(p[1]), float(p[2])
    return z > 0 and x * x + y * y < PR * PR


def render(bezel, mask, now: float) -> Image.Image:
    if _session.fresh(now) or not _st.ready:
        _reset()
    t_all = _session.t(now)
    st = _st
    lt = t_all - st.t0
    steps = 0
    while st.sim_t < lt and steps < 12:
        _step(DT)
        steps += 1
    if st.sim_t < lt:
        st.sim_t = lt
    t = st.sim_t
    if st.ending is not None and t - st.end_t > 10.0:
        _new_campaign(t_all)
        t = 0.0
    end_age = t - st.end_t if st.ending else 0.0

    R = _rotmat(_spin_t())
    # latitude is fixed per pixel (spin is about the world axis); longitude just shifts
    a = SPIN * _spin_t()
    lo = (_LO0 + a * (TEX_W / (2 * math.pi))).astype(np.int32) % TEX_W
    col = np.take(st.tex_flat, _LI0 + lo, axis=0) * _LIGHT[:, None]

    # graticule every 30 degrees
    step = math.pi / 6
    dlon = np.abs(((_LON0 + (a + step / 2)) % step) - step / 2) * _COSLAT
    grid = _LATGRID | (dlon < 0.012)
    col[grid] = col[grid] * 0.4 + _GRIDCOL[grid]

    # zones: one matmul of static pixel normals against camera-space zone centres
    pulse = 0.5 + 0.5 * math.sin(t * 4)
    groups = (
        ([(e[0], e[1] * (1 + 0.06 * math.sin(t * 3 + i))) for i, e in enumerate(st.enemy) if e[2]],
         np.array([150, 20, 10], np.float32) * (0.5 + 0.3 * pulse), 0.55,
         np.array([255, 70, 40], np.float32) * (0.7 + 0.3 * pulse)),
        ([(z[0], z[1]) for z in st.imp if z[1] > 0.005],
         np.array([30, 90, 190], np.float32) * 0.7, 0.5,
         np.array([255, 215, 110], np.float32)),
    )
    for zl, tint, keep, edge_col in groups:
        if not zl:
            continue
        C = R @ np.stack([z[0] for z in zl], axis=1)          # (3,K) camera space
        rad = np.array([z[1] for z in zl], np.float32)
        vis = C[2] < np.sin(rad) + 0.02                        # cull zones wholly on the far side
        if not vis.any():
            continue
        C, rad = C[:, vis], rad[vis]
        c0 = np.cos(rad)
        band = np.cos(np.maximum(0.0, rad - 0.022)) - c0
        m = ((_N @ C) - c0) / band                             # >0 inside, >1 deeper than outline
        mmax = m.max(axis=1)
        m_in = mmax > 0
        m_ed = m_in & (mmax < 1)
        col[m_in] = col[m_in] * keep + tint
        col[m_ed] = edge_col

    if st.ending == "exterminatus":
        k = min(1.0, end_age / 5.0)
        burn = np.array([255, 90, 20], np.float32) * (0.6 + 0.4 * math.sin(t * 6)) + 40
        col = col * (1 - k) + burn * k * (0.35 + 0.65 * _LIGHT[:, None])

    frame = st.bg.copy()
    flat = frame.reshape(-1, 3)
    flat[_IDX] = np.clip(col, 0, 255).astype(np.uint8)
    img = Image.fromarray(frame, "RGB")
    d = ImageDraw.Draw(img)
    f9, f10 = font(9), font(10)

    # battle barge in high orbit
    bx = PX + (-62 if st.barge_left else 62)
    by = PY - 82
    d.polygon([(bx - 12, by + 2), (bx + 10, by - 1), (bx + 14, by + 2), (bx + 10, by + 5)], fill=(40, 50, 70),
              outline=(150, 180, 220))
    d.line([(bx - 12, by + 2), (bx - 15, by + 2)], fill=(120, 200, 255) if int(t * 6) % 2 else (60, 100, 160))

    # insertion beams for designated zones
    for p, age, _ in st.designate:
        if age < 0:
            continue
        c = R @ p * PR
        if c[2] > -5:
            continue
        tx, ty = PX + float(c[0]), PY + float(c[1])
        k = min(1.0, age / 0.4)
        for s in range(0, 12):
            if (s + int(t * 12)) % 3 == 0:
                continue
            u0, u1 = s / 12, (s + 0.6) / 12
            d.line([(bx + (tx - bx) * u0, by + (ty - by) * u0), (bx + (tx - bx) * u1, by + (ty - by) * u1)],
                   fill=scale((120, 220, 255), 0.7 * k))
        d.ellipse([tx - 3, ty - 3, tx + 3, ty + 3], outline=scale(GOLD, k))

    # drop pods with re-entry trails
    for pod in st.pods:
        u = pod[2] / pod[3]
        head = _pod_pos(pod, R, u)
        if _occluded(head):
            continue
        pts = [head] + [_pod_pos(pod, R, max(0.0, u - k * 0.05)) for k in (1, 2, 3, 4)]
        heat = min(1.0, max(0.0, (u - 0.3) / 0.5))
        for k in range(4):
            a, b = pts[k], pts[k + 1]
            c = lerp_color((255, 240, 200), (255, 90, 20), k / 3) if heat > 0.1 else (150, 170, 200)
            d.line([(PX + float(a[0]), PY + float(a[1])), (PX + float(b[0]), PY + float(b[1]))],
                   fill=scale(c, (1 - k / 4) * (0.5 + 0.5 * heat)), width=2 if k < 2 else 1)
        hx, hy = PX + float(head[0]), PY + float(head[1])
        r = 1.5 + heat * 1.8
        d.ellipse([hx - r, hy - r, hx + r, hy + r], fill=(255, 250, 220))

    # impact flashes
    for p, age in st.impacts:
        c = R @ p * PR
        if c[2] > -2:
            continue
        x, y = PX + float(c[0]), PY + float(c[1])
        fore = min(1.0, -float(c[2]) / PR + 0.2)   # foreshorten near limb
        r = 2 + age * 14
        k = 1.0 - age / 1.2
        d.ellipse([x - r, y - r * fore, x + r, y + r * fore], outline=scale((255, 230, 160), k))
        if age < 0.15:
            d.ellipse([x - 4, y - 4, x + 4, y + 4], fill=WHITE)

    # ---- HUD ----
    ttl = "PLANETFALL"
    w = _tlen(ttl, 10)
    _txt(d, (CX - w / 2, 14), ttl, HUD, 10)
    w = _tlen(st.world, 9)
    _txt(d, (CX - w / 2, 26), st.world, scale(HUD, 0.7), 9)

    sec = "SECURED %d/%d" % (st.secured, st.total)
    w = _tlen(sec, 10)
    _txt(d, (CX - w / 2, 196), sec, GOLD, 10)
    frac = st.secured / max(1, st.total)
    d.rectangle([CX - 40, 209, CX + 40, 212], outline=(60, 50, 20))
    if frac > 0:
        d.rectangle([CX - 39, 210, CX - 39 + 78 * frac, 211], fill=GOLD)
    _txt(d, (32, 58), "T+%03d" % int(t), scale(HUD, 0.6), 9)
    _txt(d, (30, 172), "PODS %d" % st.pods_used, scale(HUD, 0.6), 9)
    foe = st.foe
    w = _tlen(foe, 9)
    _txt(d, (208 - w, 58), foe, scale(RED, 0.8), 9)
    zs = "ZONES %d" % len(st.imp)
    w = _tlen(zs, 9)
    _txt(d, (210 - w, 172), zs, scale(GOLD, 0.7), 9)
    shown = [e for e in st.events if 0.0 <= e[1] < 4.0]
    if shown and st.ending is None:
        txt, age, c = min(shown, key=lambda e: e[1])
        if True:
            k = 1.0 if (age > 0.4 or int(age * 20) % 2) else 0.3
            w = _tlen(txt, 9)
            d.rectangle([CX - w / 2 - 2, 165, CX + w / 2 + 2, 176], fill=(0, 0, 0))
            _txt(d, (CX - w / 2, 165), txt, scale(c, k), 9)

    if st.ending is not None and end_age > 1.5:
        if st.ending == "secured":
            _banner(d, "WORLD SECURED", "IN THE EMPEROR'S NAME", GOLD, t)
        else:
            _banner(d, "EXTERMINATUS", "THE XENOS SHALL BURN", RED, t)
    return img


def _banner(d, title, sub, col, t):
    f14, f9 = font(14), font(9)
    w = max(_tlen(title, 14), _tlen(sub, 9)) + 18
    d.rectangle([CX - w / 2, 100, CX + w / 2, 138], fill=(4, 6, 12), outline=col)
    d.line([(CX - w / 2 + 3, 103), (CX + w / 2 - 3, 103)], fill=scale(col, 0.5))
    tw = _tlen(title, 14)
    _txt(d, (CX - tw / 2, 105), title, col if int(t * 3) % 4 else scale(col, 0.6), 14)
    sw = _tlen(sub, 9)
    _txt(d, (CX - sw / 2, 124), sub, WHITE, 9)
