"""Titan Duel: Void Shield Telemetry.

A Warlord Titan's targeting display locked onto an Ork Gargant. The Gargant is
a slowly swaying 3D wireframe; the Titan's void-shield ring (six generator
sectors) flickers and collapses under incoming fire, the volcano cannon and
gatling blaster capacitors charge and discharge, hits blossom on the enemy
with damage locations, and the Gargant's power fields are stripped one by one.
Each duel ends with one side's plasma reactor going critical, then restarts.
"""

from __future__ import annotations

import math
import random

import numpy as np
from PIL import Image, ImageDraw

from ._common import CX, CY, Session, font, lerp_color, scale

NAME = "titan_duel"


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
GX, GY = 120.0, 108.0          # screen anchor of the Gargant model

AMBER = (255, 176, 40)
AMBER_DIM = (90, 60, 10)
CYAN = (90, 210, 255)
CYAN_DIM = (20, 60, 80)
RED = (255, 60, 40)
ENEMY = (255, 96, 50)
FIELD = (130, 255, 90)
WHITE = (255, 255, 255)

_NAMES = ["DA MEGA STOMPA", "GORK'Z FIST", "DA BIG KRUMPA", "MORK'Z GAZE", "DA IRON GOB",
          "DA DEFF BELLY", "KRUMPSMASHA", "DA RED STOMPA"]
_LEGIO = ["LEGIO GRYPHONICUS", "LEGIO METALICA", "LEGIO IGNATUM", "LEGIO INVIGILATA", "LEGIO ASTORUM"]
_ENEMY_GUNS = ["MEGA-KANNON", "DEFF KANNON", "GAZE BEAM", "SUPA-ZZAP", "ROKKIT BATTERY"]


# ------------------------------------------------------------- model ---

def _build_model():
    pts, edges = [], []

    def add(p):
        pts.append(p)
        return len(pts) - 1

    def ring(y, r, n=8, rot=0.0, zs=1.0, cx=0.0, cz=0.0):
        ids = [add((cx + r * math.cos(rot + 2 * math.pi * k / n), y, cz + r * zs * math.sin(rot + 2 * math.pi * k / n)))
               for k in range(n)]
        for k in range(n):
            edges.append((ids[k], ids[(k + 1) % n]))
        return ids

    def join(a, b):
        for i, j in zip(a, b):
            edges.append((i, j))

    def seg(p, q):
        edges.append((add(p), add(q)))

    # pot-bellied hull
    prof = [(-22, 26), (-8, 36), (8, 42), (26, 42), (42, 36), (54, 28)]
    prev = None
    for y, r in prof:
        cur = ring(y, r, rot=math.pi / 8)
        if prev:
            join(prev, cur)
        prev = cur
    # armour bands on belly
    ring(17, 43, n=12)
    # riveted belly plate / reactor hatch
    hatch = [add((12 * math.cos(k * math.pi / 3), 18 + 12 * math.sin(k * math.pi / 3), -43)) for k in range(6)]
    for k in range(6):
        edges.append((hatch[k], hatch[(k + 1) % 6]))
    seg((-8, 18, -43), (8, 18, -43))
    # head / cupola with jaw
    h0 = ring(-22, 18, n=6, rot=math.pi / 6)
    h1 = ring(-36, 14, n=6, rot=math.pi / 6)
    h2 = ring(-44, 8, n=6, rot=math.pi / 6)
    join(h0, h1)
    join(h1, h2)
    seg((-10, -30, -13), (10, -30, -13))       # jaw line
    seg((-8, -34, -12), (-3, -32, -13))        # eyes
    seg((3, -32, -13), (8, -34, -12))
    # smokestacks
    for sx in (-18, 18):
        seg((sx, -22, 12), (sx, -48, 12))
        ring(-48, 4, n=6, cx=sx, cz=12)
    # banner pole and flag
    seg((0, -44, 4), (0, -70, 4))
    a, b, c = add((0, -70, 4)), add((22, -64, 4)), add((0, -58, 4))
    edges += [(a, b), (b, c)]
    # left arm: shoulder, forearm, triple-barrelled kannon pointing at viewer
    seg((-34, -14, 0), (-58, -6, 0))
    la = ring(-6, 9, n=6, cx=-60, cz=0)
    lb = ring(-6, 9, n=6, cx=-60, cz=-26)
    join(la, lb)
    for dx, dy in ((-4, -3), (4, -3), (0, 4)):
        seg((-60 + dx, -6 + dy, -26), (-60 + dx, -6 + dy, -50))
    ring(-6, 7, n=6, cx=-60, cz=-50)
    # right arm: massive deff kannon block
    seg((34, -14, 0), (56, -4, 0))
    box = [add((52 + x, -14 + y, z)) for x in (0, 16) for y in (0, 22) for z in (6, -40)]
    for i in range(8):
        for j in range(i + 1, 8):
            if bin(i ^ j).count("1") == 1:
                edges.append((box[i], box[j]))
    seg((60, -3, -40), (60, -3, -56))
    # feet
    for fx in (-20, 20):
        f0 = ring(56, 12, n=4, cx=fx, cz=-4, rot=math.pi / 4)
        f1 = ring(64, 14, n=4, cx=fx, cz=-8, rot=math.pi / 4)
        join(f0, f1)
    P = np.array(pts, dtype=np.float32)
    E = np.array(edges, dtype=np.int32)
    return P, E


_P, _E = _build_model()
_MID = (_P[_E[:, 0]] + _P[_E[:, 1]]) * 0.5

_LOCS = {
    "HEAD":    (0.0, -33.0, -14.0),
    "BELLY":   (0.0, 18.0, -42.0),
    "L KANNON": (-60.0, -6.0, -30.0),
    "R KANNON": (60.0, -3.0, -30.0),
    "STACKS":  (0.0, -40.0, 12.0),
}
_LOC_EDGES = {}
for _k, _p in _LOCS.items():
    _dd = np.linalg.norm(_MID - np.array(_p, np.float32), axis=1)
    _LOC_EDGES[_k] = np.nonzero(_dd < (26 if _k != "BELLY" else 30))[0]


# ------------------------------------------------------------- state ---

class _S:
    pass


_st = _S()
_st.ready = False


def _reset():
    _st.ready = True
    _new_duel(0.0)


def _new_duel(t0):
    st = _st
    st.t0 = t0
    st.sim_t = 0.0
    st.name = _rng.choice(_NAMES)
    st.legio = _rng.choice(_LEGIO)
    st.titan_favoured = _rng.random() < 0.6
    st.vc = _rng.uniform(0.0, 0.4)         # volcano cannon capacitor
    st.gb = _rng.uniform(0.2, 0.6)         # gatling blaster capacitor
    st.gb_burst = 0                        # rounds left in current burst
    st.gb_cd = 0.0
    st.fields = 4
    st.field_regen = 0.0
    st.field_flash = 0.0
    st.shields = [1.0] * 6                 # 1.0 = up, <1 = regenerating
    st.shield_flash = [0.0] * 6
    st.reactor = _rng.uniform(18, 28)      # own reactor heat %
    st.loc_dmg = {k: 0.0 for k in _LOCS}
    st.tgt_reactor = 100.0
    st.aim = "BELLY"
    st.aim_xy = (GX, GY)
    st.enemy_cd = _rng.uniform(3.0, 4.5)
    st.shots = []      # incoming: [x0,y0,sector,age,dur,gun]
    st.beams = []      # outgoing: [x1,y1,life,kind]
    st.labels = []     # [text,x,y,age]
    st.events = []     # [text,age,col]
    st.flashes = []    # [x,y,age,size]
    st.shake = 0.0
    st.parts = np.zeros((0, 5), np.float32)   # x,y,vx,vy,life (screen space)
    st.ending = None   # "gargant" | "titan"
    st.end_t = 0.0
    st.range_km = _rng.uniform(2.2, 3.0)
    st.yaw0 = _rng.uniform(-0.3, 0.3)
    _event("TARGET LOCK: GARGANT", AMBER)


def _event(text, col):
    _st.events.insert(0, [text, 0.0, col])
    del _st.events[3:]


# ------------------------------------------------------------- projection ---

def _pose(t):
    st = _st
    yaw = st.yaw0 + 0.45 * math.sin(t * 0.17) + 0.12 * math.sin(t * 0.53)
    pitch = -0.12 + 0.05 * math.sin(t * 0.23)
    sway = math.sin(t * 1.3) * 0.03       # stomping gait roll
    bob = abs(math.sin(t * 1.3)) * 2.0
    zoom = 0.86 + 0.14 * max(0.0, min(1.0, (3.0 - st.range_km) / 2.0))
    return yaw, pitch, sway, bob, zoom


def _rotmat(yaw, pitch, roll):
    cy, sy = math.cos(yaw), math.sin(yaw)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cr, sr = math.cos(roll), math.sin(roll)
    ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]], np.float32)
    rx = np.array([[1, 0, 0], [0, cp, -sp], [0, sp, cp]], np.float32)
    rz = np.array([[cr, -sr, 0], [sr, cr, 0], [0, 0, 1]], np.float32)
    return rz @ rx @ ry


def _project(pts, t, jx=0.0, jy=0.0):
    yaw, pitch, roll, bob, zoom = _pose(t)
    R = _rotmat(yaw, pitch, roll)
    q = pts @ R.T
    zc = q[:, 2] + 240.0
    f = 188.0 * zoom / zc
    sx = GX + jx + q[:, 0] * f
    sy = GY + jy + (q[:, 1] + bob) * f
    return sx, sy, q[:, 2]


def _loc_screen(name, t):
    p = np.array([_LOCS[name]], np.float32)
    sx, sy, _ = _project(p, t)
    return float(sx[0]), float(sy[0])


# ------------------------------------------------------------- sim ---

def _sector_of(angle):
    return int(((angle + math.pi / 2) % (2 * math.pi)) / (2 * math.pi) * 6) % 6


def _pick_aim():
    st = _st
    if st.fields > 0:
        return "BELLY"
    if st.loc_dmg["BELLY"] >= 100:
        return "BELLY"   # reactor exposed behind the belly plates
    opts = [k for k, v in st.loc_dmg.items() if v < 100]
    weights = [3.0 if k == "BELLY" else 1.0 for k in opts]
    return _rng.choices(opts, weights)[0]


def _hit_gargant(dmg, kind, t):
    st = _st
    x, y = st.aim_xy
    st.flashes.append([x + _rng.uniform(-3, 3), y + _rng.uniform(-3, 3), 0.0, 14 if kind == "vc" else 6])
    if st.fields > 0:
        if kind == "vc" or _rng.random() < 0.10:
            st.fields -= 1
            st.field_flash = 0.6
            st.field_regen = 0.0
            _event("POWER FIELD DOWN", FIELD)
        return
    loc = st.aim
    if loc == "BELLY" and st.loc_dmg["BELLY"] >= 100:
        st.tgt_reactor -= dmg * (1.3 if st.titan_favoured else 0.8)
        if kind == "vc":
            st.labels.append(["REACTOR -%d" % int(dmg), x, y, 0.0])
        if st.tgt_reactor <= 0 and st.ending is None:
            st.ending = "gargant"
            st.end_t = st.sim_t
            _event("PLASMA BREACH!", WHITE)
        elif kind == "vc":
            _event("REACTOR HIT", AMBER)
        return
    before = st.loc_dmg[loc]
    st.loc_dmg[loc] = min(100.0, before + dmg)
    if kind == "vc":
        st.labels.append(["%s -%d%%" % (loc, int(dmg)), x, y, 0.0])
        if st.loc_dmg[loc] >= 100 > before:
            _event(loc + " DESTROYED" if loc != "BELLY" else "REACTOR EXPOSED", AMBER)
        else:
            _event("HIT: " + loc, AMBER)


def _step(dt):
    st = _st
    st.sim_t += dt
    t = st.sim_t
    # decay effects
    for e in st.events:
        e[1] += dt
    for lb in st.labels:
        lb[3] += dt
    st.labels = [lb for lb in st.labels if lb[3] < 1.6]
    for f in st.flashes:
        f[2] += dt
    st.flashes = [f for f in st.flashes if f[2] < 0.5]
    for b in st.beams:
        b[2] -= dt
    st.beams = [b for b in st.beams if b[2] > 0]
    st.shake = max(0.0, st.shake - dt * 3)
    st.field_flash = max(0.0, st.field_flash - dt)
    st.shield_flash = [max(0.0, v - dt) for v in st.shield_flash]
    # fire particles on damaged parts
    if st.parts.shape[0]:
        p = st.parts
        p[:, 0] += p[:, 2] * dt
        p[:, 1] += p[:, 3] * dt
        p[:, 4] -= dt
        st.parts = p[p[:, 4] > 0]

    if st.ending is not None:
        return
    if t < 3.0:
        return
    st.range_km = max(0.6, st.range_km - dt * 0.012)

    # aim tracking
    tx, ty = _loc_screen(st.aim, t)
    ax, ay = st.aim_xy
    st.aim_xy = (ax + (tx - ax) * min(1.0, dt * 5), ay + (ty - ay) * min(1.0, dt * 5))
    settled = math.hypot(tx - ax, ty - ay) < 3

    # --- volcano cannon ---
    heat_pen = 0.6 if st.reactor > 80 else 1.0
    st.vc = min(1.0, st.vc + dt / 6.5 * heat_pen)
    if st.vc >= 1.0 and settled:
        st.vc = 0.0
        st.reactor += 3.0
        x, y = st.aim_xy
        st.beams.append([x, y, 0.35, "vc"])
        dmg = _rng.uniform(28, 48) * (1.15 if st.titan_favoured else 0.85)
        _hit_gargant(dmg, "vc", t)
        st.aim = _pick_aim()
    # --- gatling blaster ---
    if st.gb_burst > 0:
        st.gb_cd -= dt
        if st.gb_cd <= 0:
            st.gb_cd = 0.12
            st.gb_burst -= 1
            st.gb = max(0.0, st.gb - 1 / 10)
            x, y = st.aim_xy
            st.beams.append([x + _rng.uniform(-6, 6), y + _rng.uniform(-6, 6), 0.1, "gb"])
            if _rng.random() < 0.55:
                _hit_gargant(_rng.uniform(1.5, 3.0), "gb", t)
    else:
        st.gb = min(1.0, st.gb + dt / 3.8)
        if st.gb >= 1.0 and settled:
            st.gb_burst = 10
    # --- gargant power field regeneration ---
    if st.fields < 4:
        st.field_regen += dt
        if st.field_regen > (14.0 if st.titan_favoured else 10.0):
            st.field_regen = 0.0
            st.fields += 1
            _event("POWER FIELD RESTORED", FIELD)
    # --- void shield regeneration: one generator at a time ---
    down = [i for i in range(6) if st.shields[i] < 1.0]
    if down:
        i = max(down, key=lambda k: st.shields[k])
        st.shields[i] = min(1.0, st.shields[i] + dt / (7.5 if st.titan_favoured else 10.0))
        if st.shields[i] >= 1.0:
            _event("VOID SHIELD RAISED", CYAN)
    st.reactor = max(10.0, st.reactor - dt * 0.35)

    # --- enemy fire ---
    st.enemy_cd -= dt
    if st.enemy_cd <= 0:
        st.enemy_cd = _rng.uniform(2.2, 4.2)
        gun = _rng.choice(["L KANNON", "R KANNON", "HEAD"])
        if st.loc_dmg.get(gun, 0) >= 100:
            gun = "HEAD" if st.loc_dmg["HEAD"] < 100 else None
        if gun is not None:
            x0, y0 = _loc_screen(gun, t)
            sector = _rng.randrange(6)
            name = {"L KANNON": "MEGA-KANNON", "R KANNON": "DEFF KANNON"}.get(gun, "GAZE BEAM")
            st.shots.append([x0, y0, sector, 0.0, 0.7, name])
    for s in st.shots:
        s[3] += dt
    for s in [s for s in st.shots if s[3] >= s[4]]:
        st.shots.remove(s)
        sec = s[2]
        ang = -math.pi / 2 + (sec + 0.5) * math.pi / 3
        hx, hy = CX + math.cos(ang) * 104, CY + math.sin(ang) * 104
        st.flashes.append([hx, hy, 0.0, 10])
        st.shield_flash[sec] = 0.35
        if st.shields[sec] >= 1.0:
            p_collapse = 0.38 if st.titan_favoured else 0.6
            if _rng.random() < p_collapse:
                st.shields[sec] = 0.0
                _event("VOID SHIELD COLLAPSE", RED)
            else:
                _event("SHIELD HOLDING", CYAN)
        else:
            up = sum(1 for v in st.shields if v >= 1.0)
            dmg = _rng.uniform(9, 16) * (0.8 if st.titan_favoured else 1.25) * (1.4 if up == 0 else 1.0)
            st.reactor += dmg
            st.shake = 1.0
            _event("HULL BREACH", RED)
            if st.reactor >= 100 and st.ending is None:
                st.reactor = 100.0
                st.ending = "titan"
                st.end_t = st.sim_t
                _event("REACTOR CRITICAL", RED)

    # smoke/fire from damaged locations
    for loc, v in st.loc_dmg.items():
        if v > 30 and _rng.random() < v / 100 * dt * 10:
            x, y = _loc_screen(loc, t)
            np_ = np.array([[x + _rng.uniform(-4, 4), y, _rng.uniform(-4, 4), _rng.uniform(-22, -10),
                             _rng.uniform(0.6, 1.4)]], np.float32)
            if st.parts.shape[0] < 120:
                st.parts = np.vstack([st.parts, np_])


# ------------------------------------------------------------- draw ---

def _draw_hud_static(d, st, t):
    # void shield ring: six generator sectors
    box = [CX - 108, CY - 108, CX + 108, CY + 108]
    for i in range(6):
        a0 = -90 + i * 60 + 3
        a1 = -90 + (i + 1) * 60 - 3
        v = st.shields[i]
        fl = st.shield_flash[i]
        if v >= 1.0:
            flick = 0.75 + 0.25 * math.sin(t * 9 + i * 1.7)
            col = lerp_color(scale(CYAN, flick), WHITE, fl * 2.5)
            d.arc(box, a0, a1, fill=col, width=5)
            d.arc([CX - 101, CY - 101, CX + 101, CY + 101], a0, a1, fill=scale(CYAN, 0.35), width=1)
        else:
            d.arc(box, a0, a1, fill=(50, 12, 10), width=5)
            if v > 0.02:
                d.arc(box, a0, a0 + (a1 - a0) * v, fill=CYAN_DIM, width=5)
            if int(t * 3 + i) % 2 or fl > 0:
                d.arc([CX - 110, CY - 110, CX + 110, CY + 110], a0, a1, fill=lerp_color(RED, WHITE, fl * 2), width=1)
    # capacitor arcs
    cap = [CX - 97, CY - 97, CX + 97, CY + 97]
    d.arc(cap, 145, 215, fill=AMBER_DIM, width=5)
    d.arc(cap, -35, 35, fill=AMBER_DIM, width=5)
    if st.vc > 0.01:
        c = WHITE if st.vc >= 1.0 and int(t * 8) % 2 else AMBER
        d.arc(cap, 145, 145 + 70 * st.vc, fill=c, width=5)
    if st.gb > 0.01:
        c = WHITE if st.gb >= 1.0 and int(t * 8) % 2 else (255, 210, 90)
        d.arc(cap, 35 - 70 * st.gb, 35, fill=c, width=5)
    for k in range(8):   # tick marks
        for base, sgn in ((145, 1), (35, -1)):
            a = math.radians(base + sgn * k * 10)
            d.line([(CX + math.cos(a) * 91, CY + math.sin(a) * 91), (CX + math.cos(a) * 93, CY + math.sin(a) * 93)],
                   fill=AMBER_DIM)


def _draw_gargant(d, st, t, jx, jy, explode_age=None):
    sx, sy, z = _project(_P, t, jx, jy)
    zmin, zmax = float(z.min()), float(z.max())
    depth = 1.0 - (z - zmin) / max(1.0, zmax - zmin)   # 1 near, 0 far
    e0, e1 = _E[:, 0], _E[:, 1]
    x0, y0, x1, y1 = sx[e0], sy[e0], sx[e1], sy[e1]
    dep = (depth[e0] + depth[e1]) * 0.5
    hot = np.zeros(len(_E), np.float32)
    for loc, v in st.loc_dmg.items():
        if v > 0:
            hot[_LOC_EDGES[loc]] = np.maximum(hot[_LOC_EDGES[loc]], v / 100.0)
    if explode_age is not None:
        mx, my = (x0 + x1) * 0.5 - GX, (y0 + y1) * 0.5 - GY
        rng = np.random.default_rng(len(_E))
        vx = mx * 1.2 + rng.uniform(-40, 40, len(_E))
        vy = my * 1.2 + rng.uniform(-60, 20, len(_E))
        a = explode_age
        x0 = x0 + vx * a
        x1 = x1 + vx * a
        y0 = y0 + vy * a + 30 * a * a
        y1 = y1 + vy * a + 30 * a * a
    flick = int(t * 12) % 2
    order = np.argsort(dep)
    for i in order.tolist():
        k = 0.35 + 0.65 * float(dep[i])
        h = float(hot[i])
        if h > 0:
            col = lerp_color(ENEMY, (255, 230, 120) if flick else (255, 140, 40), h)
        else:
            col = ENEMY
        if st.ending == "gargant" and explode_age is None:
            col = lerp_color(col, WHITE, 0.3 + 0.5 * flick)
        if explode_age is not None:
            k *= max(0.0, 1.0 - explode_age / 2.5)
            col = lerp_color(col, WHITE, max(0.0, 0.6 - explode_age))
        d.line([(float(x0[i]), float(y0[i])), (float(x1[i]), float(y1[i]))], fill=scale(col, k))
    return sx, sy


def _draw_fields(d, st, t, bx0, by0, bx1, by1):
    cx, cy = (bx0 + bx1) / 2, (by0 + by1) / 2
    rx, ry = (bx1 - bx0) / 2 + 6, (by1 - by0) / 2 + 4
    for i in range(st.fields + (1 if st.field_flash > 0 else 0)):
        ex, ey = rx + i * 4, ry + i * 4
        shatter = st.field_flash > 0 and i == st.fields
        base = FIELD if not shatter else WHITE
        k = 0.38 + 0.14 * math.sin(t * 5 + i)
        if shatter:
            k = st.field_flash / 0.6
            ex += (0.6 - st.field_flash) * 20
            ey += (0.6 - st.field_flash) * 20
        rot = (t * (25 + i * 8)) % 360
        for s in range(12):
            a0 = rot + s * 30
            d.arc([cx - ex, cy - ey, cx + ex, cy + ey], a0, a0 + (18 if not shatter else 9), fill=scale(base, k))


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
        _new_duel(t_all)
        t = 0.0

    img = Image.new("RGB", (240, 240), (4, 6, 8))
    d = ImageDraw.Draw(img)
    f9, f10 = font(9), font(10)

    end_age = t - st.end_t if st.ending else 0.0
    jx = jy = 0.0
    if st.shake > 0:
        jx, jy = _rng.uniform(-3, 3) * st.shake, _rng.uniform(-3, 3) * st.shake
    if st.ending == "gargant" and end_age < 1.2:
        jx, jy = _rng.uniform(-3, 3), _rng.uniform(-3, 3)
    if st.ending == "titan":
        jx, jy = _rng.uniform(-2, 2) * min(3, end_age), _rng.uniform(-2, 2) * min(3, end_age)

    # background: faint range scale + scanlines
    for r in (40, 70):
        d.ellipse([CX - r, CY - r, CX + r, CY + r], outline=(14, 18, 22))
    d.line([(CX - 88, CY), (CX + 88, CY)], fill=(14, 18, 22))
    d.line([(CX, CY - 88), (CX, CY + 88)], fill=(14, 18, 22))

    # --- gargant ---
    if st.ending == "gargant" and end_age > 1.2:
        explode = end_age - 1.2
    else:
        explode = None
    lock_in = min(1.0, t / 2.5)
    if lock_in >= 1.0 or int(t * 10) % 2:
        sx, sy = _draw_gargant(d, st, t, jx, jy, explode)
        bx0, by0, bx1, by1 = float(sx.min()), float(sy.min()), float(sx.max()), float(sy.max())
    else:
        bx0, by0, bx1, by1 = GX - 60, GY - 60, GX + 60, GY + 60
    if explode is None and st.fields > 0 or st.field_flash > 0:
        _draw_fields(d, st, t, bx0, by0, bx1, by1)

    # targeting brackets closing in during lock
    if explode is None:
        pad = 6 + (1.0 - lock_in) * 40
        L = 10
        c = AMBER if lock_in >= 1.0 else scale(AMBER, 0.6)
        for (x, y, sxn, syn) in ((bx0 - pad, by0 - pad, 1, 1), (bx1 + pad, by0 - pad, -1, 1),
                                 (bx0 - pad, by1 + pad, 1, -1), (bx1 + pad, by1 + pad, -1, -1)):
            d.line([(x, y), (x + L * sxn, y)], fill=c)
            d.line([(x, y), (x, y + L * syn)], fill=c)

    # particles (smoke / fire)
    if st.parts.shape[0]:
        for x, y, _, _, life in st.parts.tolist():
            c = lerp_color((90, 80, 70), (255, 150, 50), life - 0.4)
            d.rectangle([x, y, x + 1, y + 1], fill=c)

    # outgoing fire
    for x1, y1, life, kind in st.beams:
        if kind == "vc":
            k = life / 0.35
            d.line([(CX, 236), (x1, y1)], fill=scale((255, 120, 40), k), width=7)
            d.line([(CX, 236), (x1, y1)], fill=scale((255, 240, 200), k), width=3)
        else:
            src = (CX + 60, 226)
            mx, my = src[0] + (x1 - src[0]) * 0.8, src[1] + (y1 - src[1]) * 0.8
            d.line([(mx, my), (x1, y1)], fill=(255, 220, 120), width=2)
    # incoming fire
    for x0, y0, sec, age, dur, gun in st.shots:
        ang = -math.pi / 2 + (sec + 0.5) * math.pi / 3
        hx, hy = CX + math.cos(ang) * 104, CY + math.sin(ang) * 104
        u = age / dur
        px, py = x0 + (hx - x0) * u * u, y0 + (hy - y0) * u * u
        r = 1.5 + u * 4
        d.ellipse([px - r, py - r, px + r, py + r], fill=(255, 200, 80), outline=RED)
        tx, ty = x0 + (hx - x0) * max(0.0, u - 0.25) ** 2, y0 + (hy - y0) * max(0.0, u - 0.25) ** 2
        d.line([(tx, ty), (px, py)], fill=(160, 60, 20), width=2)
    # impact flashes
    for x, y, age, size in st.flashes:
        k = 1.0 - age / 0.5
        r = size * (0.4 + age * 2)
        d.ellipse([x - r, y - r, x + r, y + r], outline=scale((255, 230, 150), k), width=2)
        if age < 0.12:
            r2 = r * 0.6
            d.ellipse([x - r2, y - r2, x + r2, y + r2], fill=WHITE)

    # reticle on current aim point
    if st.ending is None and t > 2.5:
        ax, ay = st.aim_xy
        c = RED if st.vc > 0.85 else AMBER
        d.ellipse([ax - 7, ay - 7, ax + 7, ay + 7], outline=c)
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            d.line([(ax + dx * 4, ay + dy * 4), (ax + dx * 12, ay + dy * 12)], fill=c)
        lab = st.aim if not (st.aim == "BELLY" and st.loc_dmg["BELLY"] >= 100) else "REACTOR"
        _txt(d, (ax + 10, ay - 16), lab, scale(c, 0.9), 9)
    # hit labels drifting up
    for text, x, y, age in st.labels:
        k = min(1.0, 2.0 - age * 1.25)
        _txt(d, (x - 20, y + 8 - age * 14), text, scale((255, 240, 180), k), 9)

    _draw_hud_static(d, st, t)

    # ---- text HUD ----
    ttl = "TGT: GARGANT"
    w = _tlen(ttl, 10)
    _txt(d, (CX - w / 2, 32), ttl, AMBER, 10)
    w = _tlen(st.name, 9)
    _txt(d, (CX - w / 2, 44), st.name, scale(AMBER, 0.65), 9)
    _txt(d, (47, 57), "VOLC", AMBER if st.vc < 1 else WHITE, 9)
    _txt(d, (170, 57), "GATL", AMBER if st.gb < 1 else WHITE, 9)
    rng = "%.1fKM" % st.range_km
    _txt(d, (47, 176), rng, scale(AMBER, 0.6), 9)

    ylo = 168
    ftxt = "POWER FIELDS %d/4" % st.fields
    w = _tlen(ftxt, 10)
    d.rectangle([CX - w / 2 - 2, ylo, CX + w / 2 + 2, ylo + 12], fill=(4, 6, 8))
    _txt(d, (CX - w / 2, ylo), ftxt, FIELD if st.fields else scale(FIELD, 0.5), 10)
    up = sum(1 for v in st.shields if v >= 1.0)
    s1 = "VOID %d/6" % up
    s2 = "RCTR %d%%" % int(st.reactor)
    w1 = _tlen(s1, 9)
    _txt(d, (CX - 4 - w1, 182), s1, CYAN if up else RED, 9)
    rc = AMBER if st.reactor < 70 else (RED if int(t * 6) % 2 else WHITE)
    _txt(d, (CX + 4, 182), s2, rc, 9)
    # reactor bar
    d.rectangle([CX - 40, 194, CX + 40, 197], outline=AMBER_DIM)
    d.rectangle([CX - 39, 195, CX - 39 + 78 * min(1.0, st.reactor / 100), 196],
                fill=lerp_color(AMBER, RED, (st.reactor - 50) / 50))
    if st.events and st.ending is None:
        txt, age, col = st.events[0]
        if age < 3.5:
            k = 1.0 if (age > 0.4 or int(age * 20) % 2) else 0.25
            w = _tlen(txt, 9)
            _txt(d, (CX - w / 2, 201), txt, scale(col, k), 9)

    # ---- endings ----
    if st.ending == "gargant":
        if end_age < 1.2:
            if int(end_age * 10) % 2:
                w = _tlen("PLASMA BREACH", 10)
                _txt(d, (CX - w / 2, 150), "PLASMA BREACH", WHITE, 10)
        else:
            a = end_age - 1.2
            if a < 0.9:
                rf = 50 * (1 - a / 0.9)
                d.ellipse([GX - rf, GY - rf, GX + rf, GY + rf], fill=lerp_color((255, 240, 200), (200, 60, 10), a / 0.9))
            if a < 1.8:
                r = 10 + a * 90
                d.ellipse([GX - r, GY - r, GX + r, GY + r], outline=scale((255, 220, 140), 1 - a / 1.8), width=4)
                r2 = r * 0.6
                d.ellipse([GX - r2, GY - r2, GX + r2, GY + r2], outline=scale((255, 120, 40), 1 - a / 1.8), width=2)
            if a < 0.6:
                k = 1.0 - a / 0.6
                img = Image.blend(img, Image.new("RGB", (240, 240), (255, 250, 230)), k * 0.9)
                d = ImageDraw.Draw(img)
            if a > 1.4:
                _banner(d, "GARGANT DESTROYED", "FOR THE OMNISSIAH", AMBER, t)
    elif st.ending == "titan":
        if end_age < 3.0:
            k = 0.5 + 0.5 * math.sin(end_age * 12)
            img = Image.blend(img, Image.new("RGB", (240, 240), (160, 0, 0)), 0.25 * k)
            d = ImageDraw.Draw(img)
            cnt = 3 - int(end_age)
            _banner(d, "REACTOR CRITICAL", "MELTDOWN IN %d" % cnt, RED, t)
        else:
            a = end_age - 3.0
            if a < 1.0:
                img = Image.new("RGB", (240, 240), lerp_color(WHITE, (255, 120, 30), a))
            else:
                noise = np.random.randint(0, 70, (120, 120), dtype=np.uint8)
                n_img = Image.fromarray(noise, "L").resize((240, 240), Image.NEAREST)
                img = Image.merge("RGB", (n_img, n_img, n_img))
            d = ImageDraw.Draw(img)
            if a > 1.2:
                _banner(d, "SIGNAL LOST", st.legio + " MOURNS", RED, t)
    return img


def _banner(d, title, sub, col, t):
    f14, f9 = font(14), font(9)
    w = max(_tlen(title, 14), _tlen(sub, 9)) + 16
    w = min(w, 200)
    d.rectangle([CX - w / 2, 100, CX + w / 2, 140], fill=(6, 4, 4), outline=col)
    d.line([(CX - w / 2 + 3, 103), (CX + w / 2 - 3, 103)], fill=scale(col, 0.5))
    tw = _tlen(title, 14)
    _txt(d, (CX - tw / 2, 106), title, col if int(t * 3) % 4 else scale(col, 0.6), 14)
    sw = _tlen(sub, 9)
    _txt(d, (CX - sw / 2, 125), sub, AMBER, 9)
