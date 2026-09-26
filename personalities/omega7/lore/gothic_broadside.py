"""Battlefleet Gothic Engagement - a wireframe broadside duel in the void.

An Imperial cruiser (prow ram, cathedral spires, bridge tower) and a Chaos or
Ork capital ship trade fire on parallel or passing courses while the camera
slowly orbits them against a starfield. Lance strikes, macro-cannon salvoes and
torpedo spreads (with turret interception) wear down void shields and hull;
breaches vent atmosphere and burn. When one ship's hull fails it breaks into
sections, its plasma drive detonates, and after the verdict a new engagement
begins with fresh ships.
"""

from __future__ import annotations

import math
import random

import numpy as np
from PIL import Image, ImageDraw

from ._common import CX, CY, Session, font, lerp_color, scale

NAME = "gothic_broadside"

_rng = random.Random()
_session = Session()

FOV = 185.0
PCAP = 2400  # particle ring-buffer capacity

IMP_COL = (230, 195, 110)
CHAOS_COL = (225, 70, 55)
ORK_COL = (120, 215, 70)
SHIELD_COL = (90, 170, 255)
HUD_COL = (120, 220, 150)
HUD_DIM = (50, 110, 70)

_IMP_NAMES = ["FIDELITAS", "DIVINE RIGHT", "LORD SOLAR", "HAMMER OF THRACE", "EMPEROR'S WRATH",
              "SWORD OF RETRIBUTION", "MACHARIUS", "DOMINUS ASTRA", "INVINCIBLE", "RIGHTEOUS FURY"]
_IMP_CLS = ["LUNAR CLS CRUISER", "GOTHIC CLS CRUISER", "DOMINATOR CLS", "TYRANT CLS CRUISER"]
_CHAOS_NAMES = ["DESECRATOR", "INFIDEL'S BANE", "BLOODIED FANG", "HELLBLADE", "FOUL LEGACY",
                "DARK FURY", "RAPACIOUS", "SONG OF WOE"]
_CHAOS_CLS = ["SLAUGHTER CLS", "CARNAGE CLS", "MURDER CLS", "ACHERON CLS"]
_ORK_NAMES = ["KILL KROOZA", "DA BIG STOMPA", "GUTRIPPA", "DEFF SKREEMA", "WAAAGH GORKA"]
_ORK_CLS = ["ORK KILL KROOZA", "ORK TERROR SHIP", "ORK HAMMER"]


# --------------------------------------------------------------------------- math

def _rx(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]], dtype=np.float64)


def _ry(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]], dtype=np.float64)


def _axis_angle(axis, a):
    x, y, z = axis
    c, s = math.cos(a), math.sin(a)
    C = 1 - c
    return np.array([[c + x * x * C, x * y * C - z * s, x * z * C + y * s],
                     [y * x * C + z * s, c + y * y * C, y * z * C - x * s],
                     [z * x * C - y * s, z * y * C + x * s, c + z * z * C]], dtype=np.float64)


def _unit(v):
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-9 else v


# --------------------------------------------------------------------------- ship models

class _Model:
    def __init__(self):
        self.v = []
        self.s = []

    def p(self, x, y, z):
        self.v.append((x, y, z))
        return len(self.v) - 1

    def line(self, a, b):
        self.s.append((a, b))

    def poly(self, idx, closed=True):
        for i in range(len(idx) - 1):
            self.s.append((idx[i], idx[i + 1]))
        if closed:
            self.s.append((idx[-1], idx[0]))

    def ring(self, x, prof):
        r = [self.p(x, y, z) for (y, z) in prof]
        self.poly(r)
        return r

    def loft(self, rings):
        for a, b in zip(rings, rings[1:]):
            for i, j in zip(a, b):
                self.line(i, j)

    def spire(self, x, y0, z, bw, h):
        base = [self.p(x - bw, y0, z - bw), self.p(x + bw, y0, z - bw),
                self.p(x + bw, y0, z + bw), self.p(x - bw, y0, z + bw)]
        self.poly(base)
        apex = self.p(x, y0 + h, z)
        for b in base:
            self.line(b, apex)

    def box(self, x0, x1, y0, y1, z0, z1):
        lo = [self.p(x0, y0, z0), self.p(x1, y0, z0), self.p(x1, y0, z1), self.p(x0, y0, z1)]
        hi = [self.p(x0, y1, z0), self.p(x1, y1, z0), self.p(x1, y1, z1), self.p(x0, y1, z1)]
        self.poly(lo)
        self.poly(hi)
        for a, b in zip(lo, hi):
            self.line(a, b)
        return hi

    def octagon(self, x, y, z, r):
        idx = [self.p(x, y + r * math.sin(a), z + r * math.cos(a))
               for a in np.linspace(0, 2 * math.pi, 8, endpoint=False)]
        self.poly(idx)


def _hex(w, h):
    return [(h, 0), (h * 0.55, w), (-h * 0.45, w * 0.9), (-h, 0), (-h * 0.45, -w * 0.9), (h * 0.55, -w)]


def _build_imperial(r):
    m = _Model()
    st = [(-58, 9, 8), (-44, 13, 11), (-10, 12.5, 10.5), (20, 11.5, 9.5), (42, 8.5, 7)]
    rings = [m.ring(x, _hex(w, h)) for x, w, h in st]
    m.loft(rings)
    # armoured prow ram
    tip = m.p(76, -4, 0)
    for i in rings[-1]:
        m.line(i, tip)
    crest = m.p(56, 8, 0)
    m.line(rings[-1][0], crest)
    m.line(crest, tip)
    # bridge tower: stepped cathedral with a great spire
    bx = -36 + r.uniform(-3, 3)
    m.box(bx - 9, bx + 9, 11, 19, -5.5, 5.5)
    m.box(bx - 6, bx + 5, 19, 26, -3.5, 3.5)
    m.spire(bx, 26, 0, 2.5, r.uniform(12, 17))
    # spires along the spine
    for x in (-16, 0, 15, 29):
        if r.random() < 0.85:
            m.spire(x + r.uniform(-2, 2), 10.5, 0, 2.0, r.uniform(6, 13))
    # flanking pinnacles
    for sgn in (-1, 1):
        m.spire(-22 + r.uniform(-3, 3), 7, sgn * 9, 1.4, r.uniform(5, 8))
    # broadside gun decks (battery ports)
    xs = np.array([s[0] for s in st], float)
    ws = np.array([s[1] for s in st], float)
    for sgn in (-1, 1):
        for x in range(-36, 32, 6):
            w = float(np.interp(x, xs, ws)) * 0.95
            a = m.p(x, 1.5, sgn * w)
            b = m.p(x, 1.5, sgn * (w + 2.8))
            m.line(a, b)
    # ventral keel
    k = [m.p(-50, -8, 0), m.p(-40, -17, 0), m.p(18, -15, 0), m.p(40, -7, 0)]
    m.poly(k, closed=False)
    engines = [(-59, 0, z, 3.2) for z in (-5.5, 0, 5.5)]
    for e in engines:
        m.octagon(*e)
    return m, engines, xs, ws, (72, -3, 0)


def _build_chaos(r):
    m = _Model()
    st = [(-54, 8, 9), (-38, 12, 13), (-6, 11.5, 12), (24, 9.5, 9), (40, 7, 6)]
    rings = []
    for x, w, h in st:
        prof = [(y + r.uniform(-1, 1), z + r.uniform(-1, 1)) for (y, z) in _hex(w, h)]
        rings.append(m.ring(x, prof))
    m.loft(rings)
    # forked claw prow
    for zt in (-7, 7):
        tip = m.p(68 + r.uniform(-3, 3), 1, zt)
        for i in rings[-1]:
            if (zt > 0) == (m.v[i][2] >= 0) or m.v[i][2] == 0:
                m.line(i, tip)
    lower = m.p(60, -9, 0)
    m.line(rings[-1][3], lower)
    # jagged dorsal sail of spikes
    prev = None
    for x in range(-44, 34, 7):
        h = float(np.interp(x, [s[0] for s in st], [s[2] for s in st]))
        a = m.p(x - 3, h, 0)
        apex = m.p(x + 3, h + r.uniform(7, 16) * (1.2 if x < -20 else 0.9), 0)
        m.line(a, apex)
        if prev is not None:
            m.line(prev, apex)
        prev = apex
    # twisted command tower
    tx = -42
    m.box(tx - 6, tx + 6, 12, 20, -4, 4)
    m.spire(tx + 2, 20, 0, 3, r.uniform(14, 20))
    # side spikes raking backwards
    xs = np.array([s[0] for s in st], float)
    ws = np.array([s[1] for s in st], float)
    for sgn in (-1, 1):
        for x in range(-40, 30, 9):
            w = float(np.interp(x, xs, ws))
            a = m.p(x, 2, sgn * w)
            b = m.p(x - 6, 3 + r.uniform(-2, 3), sgn * (w + r.uniform(5, 10)))
            m.line(a, b)
    engines = [(-55, 0, z, 3.0) for z in (-4.5, 4.5)]
    for e in engines:
        m.octagon(*e)
    return m, engines, xs, ws, (64, 0, 0)


def _build_ork(r):
    m = _Model()
    st = [(-50, 12, 11), (-30, 13, 12), (0, 12, 10), (25, 11, 9), (38, 12, 8)]
    rings = []
    for x, w, h in st:
        w2, h2 = w + r.uniform(-1.5, 1.5), h + r.uniform(-1.5, 1.5)
        prof = [(h2, -w2 * 0.8), (h2 + r.uniform(-1, 2), w2 * 0.8), (-h2, w2), (-h2, -w2)]
        rings.append(m.ring(x + r.uniform(-2, 2), prof))
    m.loft(rings)
    # massive toothed ram
    tipt = m.p(70, 2, 0)
    tipb = m.p(66, -10, 0)
    for i in rings[-1]:
        m.line(i, tipt if m.v[i][1] > 0 else tipb)
    m.line(tipt, tipb)
    for k in range(4):
        x = 44 + k * 6
        a = m.p(x, -4 - k, -6 + k)
        b = m.p(x + 3, -9 - k, -6 + k)
        m.line(a, b)
    # ramshackle towers
    for x in (-40, -22, -5, 14):
        if r.random() < 0.8:
            hgt = r.uniform(6, 16)
            z = r.uniform(-5, 5)
            m.box(x - 4, x + 4, 11, 11 + hgt, z - 3, z + 3)
    # big gunz poking out
    xs = np.array([s[0] for s in st], float)
    ws = np.array([s[1] for s in st], float)
    for sgn in (-1, 1):
        for x in range(-38, 30, 10):
            w = float(np.interp(x, xs, ws))
            a = m.p(x, 3, sgn * w)
            b = m.p(x + 2, 3, sgn * (w + 6))
            m.line(a, b)
    engines = [(-51, y, z, 3.6) for y in (-4, 4) for z in (-6, 6)]
    for e in engines:
        m.octagon(*e)
    return m, engines, xs, ws, (66, 0, 0)


_BUILD = {"imperial": _build_imperial, "chaos": _build_chaos, "ork": _build_ork}


# --------------------------------------------------------------------------- state

_S: dict = {}
_P = {}


def _reset_particles():
    _P["pos"] = np.zeros((PCAP, 3))
    _P["vel"] = np.zeros((PCAP, 3))
    _P["life"] = np.zeros(PCAP)
    _P["max"] = np.ones(PCAP)
    _P["col"] = np.zeros((PCAP, 3))
    _P["big"] = np.zeros(PCAP, dtype=bool)
    _P["drag"] = np.zeros(PCAP)
    _P["i"] = 0


def _spawn(pos, vel, life, col, big=False, drag=0.0):
    vel = np.atleast_2d(vel)
    k = vel.shape[0]
    idx = (_P["i"] + np.arange(k)) % PCAP
    _P["i"] = (_P["i"] + k) % PCAP
    _P["pos"][idx] = pos
    _P["vel"][idx] = vel
    life = np.broadcast_to(np.asarray(life, float), (k,))
    _P["life"][idx] = life
    _P["max"][idx] = np.maximum(life, 1e-3)
    _P["col"][idx] = col
    _P["big"][idx] = big
    _P["drag"][idx] = drag


def _burst(pos, n, speed, life, cols, big_frac=0.2, drag=0.3):
    d = np.array([_rng.gauss(0, 1) for _ in range(3 * n)]).reshape(n, 3)
    d /= np.maximum(np.linalg.norm(d, axis=1, keepdims=True), 1e-6)
    sp = np.array([_rng.uniform(0.25, 1.0) for _ in range(n)])[:, None] * speed
    lf = np.array([_rng.uniform(0.5, 1.0) for _ in range(n)]) * life
    cl = np.array([cols[_rng.randrange(len(cols))] for _ in range(n)], float)
    big = np.array([_rng.random() < big_frac for _ in range(n)])
    _spawn(pos, d * sp, lf, cl, big, drag)


def _make_ship(kind, side, t):
    m, engines, xs, ws, prow = _BUILD[kind](_rng)
    V = np.array(m.v, dtype=np.float64)
    Sg = np.array(m.s, dtype=np.int32)
    xmin, xmax = float(V[:, 0].min()), float(V[:, 0].max())
    L = xmax - xmin
    cuts = [xmin + L * _rng.uniform(0.30, 0.38), xmin + L * _rng.uniform(0.60, 0.68)]
    vsect = np.digitize(V[:, 0], cuts)
    sidx = [np.nonzero(vsect == s)[0] for s in range(3)]
    centers = [V[i].mean(axis=0) if len(i) else np.zeros(3) for i in sidx]
    if kind == "imperial":
        name, cls, col, beam = _rng.choice(_IMP_NAMES), _rng.choice(_IMP_CLS), IMP_COL, (255, 225, 140)
        hull, shields = 10, 2
    elif kind == "chaos":
        name, cls, col, beam = _rng.choice(_CHAOS_NAMES), _rng.choice(_CHAOS_CLS), CHAOS_COL, (255, 90, 200)
        hull, shields = 10, 2
    else:
        name, cls, col, beam = _rng.choice(_ORK_NAMES), _rng.choice(_ORK_CLS), ORK_COL, (140, 255, 90)
        hull, shields = 12, 1
    if side < 0:
        yaw = _rng.uniform(-0.08, 0.08)
    else:
        yaw = _rng.choice([0.0, math.pi]) + _rng.uniform(-0.15, 0.15)
    return dict(
        kind=kind, name=name, cls=cls, col=col, beam=beam,
        V=V, Sg=Sg, vsect=vsect, sidx=sidx, centers=centers, cuts=cuts,
        seg_same=vsect[Sg[:, 0]] == vsect[Sg[:, 1]],
        engines=np.array([e[:3] for e in engines], float), prow=np.array(prow, float),
        xs=xs, ws=ws,
        P=np.array([_rng.uniform(-8, 8), _rng.uniform(-6, 6), side * _rng.uniform(38, 46)]),
        yaw=yaw, roll_ph=_rng.uniform(0, 6.28),
        hull=hull, hull_max=hull, shields=shields, shield_max=shields, regen_t=t + 6,
        next_lance=t + _rng.uniform(6, 9), next_macro=t + _rng.uniform(7, 11),
        next_torp=t + _rng.uniform(9, 16) if kind != "chaos" or _rng.random() < 0.6 else t + 1e9,
        dead=False, broken=False, break_t=0.0, det=[False, False, False],
        drift=[np.zeros(3)] * 3, axes=[np.array([0, 1.0, 0])] * 3, spin=[0.0] * 3,
        breaches=[], Rt=[np.eye(3)] * 3, off=[np.zeros(3)] * 3, bbox=None, lost=0.0,
    )


def _planet_sprite():
    R = _rng.randint(22, 34)
    n = 2 * R + 2
    yy, xx = np.mgrid[0:n, 0:n].astype(np.float64)
    dx, dy = (xx - R - 0.5) / R, (yy - R - 0.5) / R
    rr = dx * dx + dy * dy
    inside = rr <= 1.0
    dz = np.sqrt(np.clip(1 - rr, 0, 1))
    L = _unit(np.array([_rng.uniform(-1, 1), _rng.uniform(-0.8, 0.2), 0.6]))
    lam = np.clip(dx * L[0] + dy * L[1] + dz * L[2], 0, 1)
    band = 0.75 + 0.25 * np.sin(dy * _rng.uniform(8, 15) + np.sin(dx * 3) * 1.5)
    base = np.array(_rng.choice([(90, 110, 150), (150, 110, 70), (80, 130, 120), (130, 90, 120)]), float)
    rgb = base[None, None, :] * (lam * band)[:, :, None] * 0.85 + 4
    rim = np.clip((rr - 0.82) / 0.18, 0, 1) * lam
    rgb += np.array([60, 90, 140])[None, None, :] * rim[:, :, None] * 0.6
    alpha = np.where(inside, 255, 0).astype(np.uint8)
    arr = np.dstack([np.clip(rgb, 0, 255).astype(np.uint8), alpha])
    return Image.fromarray(arr, "RGBA"), R


def _new_engagement(t):
    enemy = _rng.choice(["chaos", "chaos", "ork"])
    imp = _make_ship("imperial", -1, t)
    en = _make_ship(enemy, +1, t)
    imp_wins = _rng.random() < 0.72
    # star sphere: plain stars plus a faint nebula cluster
    n = 420
    d = np.array([_rng.gauss(0, 1) for _ in range(3 * n)]).reshape(n, 3)
    d /= np.linalg.norm(d, axis=1, keepdims=True)
    b = np.array([_rng.random() ** 2.5 for _ in range(n)]) * 200 + 40
    cols = np.stack([b, b, b * 1.1], axis=1)
    nd = _unit(np.array([_rng.gauss(0, 1) for _ in range(3)]))
    m = 500
    neb = nd[None, :] + np.array([_rng.gauss(0, 0.3) for _ in range(3 * m)]).reshape(m, 3)
    neb /= np.linalg.norm(neb, axis=1, keepdims=True)
    tint = np.array(_rng.choice([(70, 30, 90), (30, 60, 90), (90, 40, 40)]), float)
    ncol = tint[None, :] * np.array([_rng.uniform(0.25, 0.8) for _ in range(m)])[:, None]
    pdir = _unit(np.array([_rng.gauss(0, 1), _rng.uniform(-0.6, 0.1), _rng.gauss(0, 1)]))
    sprite, pr = _planet_sprite()
    _S.clear()
    _S.update(
        t0=t, phase="intro", phase_t=t, ships=[imp, en], imp_wins=imp_wins,
        winner=imp if imp_wins else en, loser=en if imp_wins else imp,
        force_t=t + _rng.uniform(70, 88),
        cam_yaw0=_rng.uniform(0, 2 * math.pi), cam_dir=_rng.choice([-1, 1]),
        cam_pitch0=_rng.uniform(0.28, 0.5),
        stars=np.vstack([d, neb]), star_col=np.vstack([cols, ncol]).clip(0, 255),
        pdir=pdir, sprite=sprite, sprite_r=pr,
        lances=[], shells=[], torps=[], expl=[], flares=[], pending=[],
        msg=None, flash=0.0, target=np.zeros(3), dist=235.0, verdict=None,
    )
    _reset_particles()


def _reset():
    _S.clear()
    _S["last_t"] = 0.0
    _new_engagement(0.0)
    _S["last_t"] = 0.0


# --------------------------------------------------------------------------- simulation helpers

def _pose(ship, t):
    roll = 0.03 * math.sin(t * 0.4 + ship["roll_ph"])
    Rs = _ry(ship["yaw"]) @ _rx(roll)
    P = ship["P"]
    Rt, off = [], []
    for s in range(3):
        if ship["broken"]:
            tau = t - ship["break_t"]
            Rl = _axis_angle(ship["axes"][s], ship["spin"][s] * tau)
            c = ship["centers"][s]
            R = Rs @ Rl
            o = Rs @ (c - Rl @ c + ship["drift"][s] * tau) + P
        else:
            R, o = Rs, P
        Rt.append(R)
        off.append(o)
    ship["Rt"], ship["off"], ship["Rs"] = Rt, off, Rs


def _l2w(ship, loc):
    s = int(np.digitize([loc[0]], ship["cuts"])[0])
    return ship["Rt"][s] @ loc + ship["off"][s], s


def _rand_vertex(ship):
    for _ in range(8):
        i = _rng.randrange(len(ship["V"]))
        if not ship["det"][ship["vsect"][i]]:
            return ship["V"][i].copy()
    return ship["V"][0].copy()


def _battery(ship, tgt, lance=False):
    loc = ship["Rs"].T @ (tgt["P"] - ship["P"])
    sgn = 1.0 if loc[2] >= 0 else -1.0
    x = _rng.uniform(-20, 20) if lance else _rng.uniform(-34, 28)
    w = float(np.interp(x, ship["xs"], ship["ws"])) + 1.5
    return np.array([x, 1.5 if not lance else 6.0, sgn * w])


def _msg(text, col, t):
    _S["msg"] = (text, col, t)


def _add_breach(ship, loc, t):
    out = np.array([0.0, _rng.uniform(-0.3, 0.6), 1.0 if loc[2] >= 0 else -1.0])
    ship["breaches"].append(dict(loc=loc, dir=_unit(out), until=t + _rng.uniform(3, 6)))
    if len(ship["breaches"]) > 10:
        ship["breaches"].pop(0)


def _damage(tgt, amount, loc, t, kind):
    if tgt["dead"]:
        return
    wpos, _ = _l2w(tgt, loc)
    if tgt["shields"] > 0:
        tgt["shields"] -= 1
        tgt["regen_t"] = t + _rng.uniform(5, 8)
        _S["flares"].append(dict(ship=tgt, loc=loc, t0=t, a0=_rng.uniform(0, 360)))
        _burst(wpos, 14, 14, 0.6, [(150, 200, 255), (220, 240, 255)], 0.1, 1.0)
        _msg("VOID SHIELDS FLARE" if tgt["shields"] > 0 else "SHIELDS DOWN", SHIELD_COL, t)
        return
    if tgt is _S["winner"] and tgt["hull"] - amount < 3:
        _burst(wpos, 10, 10, 0.5, [(255, 200, 120)], 0.1, 1.0)
        _msg("ARMOUR HOLDS", tgt["col"], t)
        return
    tgt["hull"] -= amount
    _add_breach(tgt, loc, t)
    _burst(wpos, 26 + 10 * amount, 16, 1.6, [(255, 230, 160), (255, 150, 50), (190, 70, 30), (150, 150, 160)], 0.3, 0.4)
    _S["expl"].append(dict(pos=wpos, t0=t, dur=0.7 + 0.2 * amount, r=4 + 2 * amount))
    _msg("CRITICAL HIT" if amount > 1 else "HULL BREACH", tgt["col"], t)
    if tgt["hull"] <= 0:
        _kill(tgt, t)


def _kill(ship, t):
    ship["dead"] = True
    ship["broken"] = True
    ship["break_t"] = t
    cm = sum(ship["centers"]) / 3.0
    ship["drift"] = [_unit(c - cm + np.array([0, _rng.uniform(-3, 3), _rng.uniform(-3, 3)])) * _rng.uniform(1.8, 3.2)
                     for c in ship["centers"]]
    ship["axes"] = [_unit(np.array([_rng.gauss(0, 1) for _ in range(3)])) for _ in range(3)]
    ship["spin"] = [_rng.uniform(0.04, 0.16) * _rng.choice([-1, 1]) for _ in range(3)]
    ship["shields"] = 0
    _S["phase"] = "breakup"
    _S["phase_t"] = t
    for k in range(9):
        _S["pending"].append((t + 0.2 + k * 0.45 + _rng.uniform(0, 0.3), "chain", ship))
    _S["pending"].append((t + 4.6, "drive", ship))
    for k in range(5):
        _S["pending"].append((t + 6.5 + k * 1.6 + _rng.uniform(0, 0.8), "chain", ship))
    _msg("HULL INTEGRITY FAILING", ship["col"], t)


# weapons ---------------------------------------------------------------

def _fire_lance(sh, tg, t, acc):
    src = _battery(sh, tg, lance=True)
    loc = _rand_vertex(tg)
    hit = _rng.random() < acc
    miss = np.zeros(3) if hit else np.array([_rng.uniform(-30, 30), _rng.uniform(8, 20) * _rng.choice([-1, 1]), 0.0])
    _S["lances"].append(dict(sh=sh, tg=tg, src=src, loc=loc, miss=miss, t0=t, dur=_rng.uniform(0.6, 0.9)))
    if hit:
        _S["pending"].append((t + 0.15, "hit", (tg, 1, loc, "lance")))
    if sh["kind"] == "ork":
        _msg("ZZAP CANNON", sh["col"], t)
    else:
        _msg("LANCE STRIKE", sh["col"], t)


def _fire_macro(sh, tg, t, acc):
    hit = _rng.random() < acc
    n = _rng.randint(9, 15)
    land = t + 2.0
    for i in range(n):
        src = _battery(sh, tg)
        p0, _ = _l2w(sh, src)
        loc = _rand_vertex(tg)
        p1, _ = _l2w(tg, loc)
        if not hit or _rng.random() < 0.35:
            p1 = p1 + np.array([_rng.uniform(-18, 18), _rng.uniform(-14, 14), _rng.uniform(-10, 10)])
        ts = t + i * 0.06 + _rng.uniform(0, 0.25)
        _S["shells"].append(dict(p0=p0, p1=p1, t0=ts, T=_rng.uniform(1.3, 1.7)))
        _spawn(p0, np.array([_rng.uniform(-2, 2) for _ in range(3)]), 0.35, (255, 220, 140), True, 1.0)
    if hit:
        _S["pending"].append((land, "hit", (tg, 1, _rand_vertex(tg), "macro")))
    _msg("BROADSIDE", sh["col"], t)


def _launch_torps(sh, tg, t):
    n = _rng.randint(4, 6)
    p0, _ = _l2w(sh, sh["prow"])
    tgt_w = tg["P"]
    fwd = _unit(tgt_w - p0)
    lat = _unit(np.cross(fwd, np.array([0, 1.0, 0])))
    pkill = 0.45 if tg is _S["winner"] else 0.3
    for i in range(n):
        k = i - (n - 1) / 2.0
        vel = _unit(fwd + lat * k * 0.16 + sh["Rs"] @ np.array([0.5, 0, 0])) * 20.0
        _S["torps"].append(dict(
            pos=p0 + lat * k * 1.5, vel=vel, tg=tg, loc=_rand_vertex(tg), trail=[],
            kill=_rng.uniform(10, 38) if _rng.random() < pkill else -1.0,
            t0=t + i * 0.12, age=0.0, sh=sh))
    _msg("TORPEDOES AWAY", sh["col"], t)


# --------------------------------------------------------------------------- per-frame update

def _update(t, dt):
    S = _S
    ships = S["ships"]
    for sh in ships:
        _pose(sh, t)
    ph = S["phase"]
    since = t - S["phase_t"]
    if ph == "intro" and since > 5.5:
        S["phase"], S["phase_t"] = "battle", t
    elif ph == "battle":
        for sh, tg in ((ships[0], ships[1]), (ships[1], ships[0])):
            if sh["dead"] or tg["dead"]:
                continue
            eff = 0.55 + 0.45 * sh["hull"] / sh["hull_max"]
            acc = 0.85 if sh is S["winner"] else 0.55
            if t >= sh["next_lance"]:
                _fire_lance(sh, tg, t, acc)
                sh["next_lance"] = t + _rng.uniform(4.5, 7.5) / eff
            if t >= sh["next_macro"]:
                _fire_macro(sh, tg, t, acc)
                sh["next_macro"] = t + _rng.uniform(6.5, 9.5) / eff
            if t >= sh["next_torp"]:
                _launch_torps(sh, tg, t)
                sh["next_torp"] = t + _rng.uniform(15, 22)
            if sh["shields"] < sh["shield_max"] and t >= sh["regen_t"]:
                sh["shields"] += 1
                sh["regen_t"] = t + _rng.uniform(6, 9)
        if t >= S["force_t"] and not S["loser"]["dead"]:
            lo = S["loser"]
            lo["shields"] = 0
            _msg("MAGAZINE DETONATION", lo["col"], t)
            _damage(lo, lo["hull"], _rand_vertex(lo), t, "force")
    elif ph == "breakup" and since > 14.0:
        S["phase"], S["phase_t"] = "verdict", t
    elif ph == "verdict" and since > 5.0:
        S["phase"], S["phase_t"] = "fade", t
    elif ph == "fade" and since > 1.6:
        _new_engagement(t)
        for sh in _S["ships"]:
            _pose(sh, t)
        return

    # pending timed events
    keep = []
    for ev in S["pending"]:
        if t < ev[0]:
            keep.append(ev)
            continue
        kind, data = ev[1], ev[2]
        if kind == "hit":
            tg, amt, loc, why = data
            _damage(tg, amt, loc, t, why)
        elif kind == "chain":
            loc = _rand_vertex(data)
            wpos, _ = _l2w(data, loc)
            _burst(wpos, 30, 14, 1.8, [(255, 230, 160), (255, 140, 40), (160, 60, 30), (130, 130, 140)], 0.35, 0.3)
            S["expl"].append(dict(pos=wpos, t0=t, dur=0.8, r=_rng.uniform(4, 8)))
            _add_breach(data, loc, t)
        elif kind == "drive":
            sh = data
            wpos, _ = _l2w(sh, sh["centers"][0])
            sh["det"][0] = True
            _burst(wpos, 260, 30, 3.5, [(255, 255, 230), (255, 210, 120), (255, 120, 40), (200, 60, 40), (140, 140, 150)], 0.4, 0.2)
            S["expl"].append(dict(pos=wpos, t0=t, dur=1.8, r=26))
            S["flash"] = 1.0
            _msg("PLASMA DRIVE DETONATION", (255, 200, 120), t)
    S["pending"] = keep

    # torpedoes
    alive = []
    for tp in S["torps"]:
        if t < tp["t0"]:
            alive.append(tp)
            continue
        tp["age"] += dt
        tg = tp["tg"]
        tw, _ = _l2w(tg, tp["loc"])
        if not tg["dead"]:
            want = _unit(tw - tp["pos"])
            tp["vel"] = _unit(tp["vel"] + want * dt * 2.5) * 20.0
        tp["pos"] = tp["pos"] + tp["vel"] * dt
        tp["trail"].append(tp["pos"].copy())
        if len(tp["trail"]) > 16:
            tp["trail"].pop(0)
        dist = float(np.linalg.norm(tw - tp["pos"]))
        if tp["age"] > 9:
            continue
        if not tg["dead"] and dist < 55 and _rng.random() < 0.6:
            src, _ = _l2w(tg, _rand_vertex(tg))
            aim = _unit(tp["pos"] - src + np.array([_rng.uniform(-3, 3) for _ in range(3)]))
            _spawn(src, aim * 70.0, min(1.0, dist / 70.0 + 0.1), (255, 240, 170), False, 0.0)
        if tp["kill"] > 0 and dist < tp["kill"] and not tg["dead"]:
            _burst(tp["pos"], 16, 9, 0.7, [(255, 220, 140), (255, 140, 60)], 0.2, 0.8)
            S["expl"].append(dict(pos=tp["pos"].copy(), t0=t, dur=0.35, r=2.5))
            if _rng.random() < 0.3:
                _msg("TURRETS INTERCEPT", tg["col"], t)
            continue
        if dist < 3.0 and not tg["dead"]:
            _damage(tg, 2, tp["loc"], t, "torp")
            continue
        alive.append(tp)
    S["torps"] = alive

    # breaches: venting atmosphere
    for sh in ships:
        for br in sh["breaches"]:
            if t < br["until"]:
                wpos, s = _l2w(sh, br["loc"])
                if sh["det"][s]:
                    continue
                dirw = sh["Rt"][s] @ br["dir"]
                v = dirw[None, :] * np.array([[_rng.uniform(4, 10)], [_rng.uniform(4, 10)]]) \
                    + np.array([_rng.uniform(-1.5, 1.5) for _ in range(6)]).reshape(2, 3)
                _spawn(wpos, v, _rng.uniform(1.0, 1.8), (170, 200, 230), False, 0.5)

    S["shells"] = [s for s in S["shells"] if t < s["t0"] + s["T"] + 0.05]
    S["lances"] = [l for l in S["lances"] if t < l["t0"] + l["dur"]]
    S["expl"] = [e for e in S["expl"] if t < e["t0"] + e["dur"]]
    S["flares"] = [f for f in S["flares"] if t < f["t0"] + 0.8]
    S["flash"] = max(0.0, S["flash"] - dt * 1.6)

    # particles
    life = _P["life"]
    a = life > 0
    if a.any():
        _P["pos"][a] += _P["vel"][a] * dt
        _P["vel"][a] *= (1.0 - np.minimum(_P["drag"][a], 5.0) * dt)[:, None]
        life[a] -= dt


# --------------------------------------------------------------------------- rendering

class _Cam:
    def __init__(self, t):
        S = _S
        yaw = S["cam_yaw0"] + S["cam_dir"] * 0.045 * (t - S["t0"])
        pitch = S["cam_pitch0"] + 0.12 * math.sin((t - S["t0"]) * 0.06)
        self.C = _rx(pitch) @ _ry(yaw)
        self.T = S["target"]
        self.dist = S["dist"]

    def proj(self, pts):
        c = (np.atleast_2d(pts) - self.T) @ self.C.T
        z = c[:, 2] + self.dist
        zz = np.maximum(z, 1.0)
        sx = CX + FOV * c[:, 0] / zz
        sy = CY - FOV * c[:, 1] / zz
        return sx, sy, z

    def proj1(self, p):
        sx, sy, z = self.proj(p)
        return float(sx[0]), float(sy[0]), float(z[0])


def _draw_ship(d, cam, sh, t, reveal):
    V = sh["V"]
    W = np.empty_like(V)
    for s in range(3):
        idx = sh["sidx"][s]
        if len(idx):
            W[idx] = V[idx] @ sh["Rt"][s].T + sh["off"][s]
    sx, sy, z = cam.proj(W)
    Sg = sh["Sg"]
    keep = np.ones(len(Sg), dtype=bool)
    if sh["broken"]:
        keep &= sh["seg_same"]
    det = np.array(sh["det"])
    if det.any():
        keep &= ~det[sh["vsect"][Sg[:, 0]]]
    if reveal < 1.0:
        keep[int(len(Sg) * reveal):] = False
    a, b = Sg[keep, 0], Sg[keep, 1]
    zm = (z[a] + z[b]) * 0.5
    ok = (z[a] > 5) & (z[b] > 5)
    k = np.clip(1.15 - (zm - (cam.dist - 90)) / 180.0 * 0.75, 0.35, 1.0)
    col = np.array(sh["col"], float)
    if sh["dead"]:
        fade = max(0.25, 1.0 - (t - sh["break_t"]) / 10.0)
        col = col * fade + np.array([120, 30, 10]) * (1 - fade) * 0.6
    cols = (k[:, None] * col[None, :]).astype(np.int32)
    rows = np.column_stack([sx[a], sy[a], sx[b], sy[b], cols])[ok].tolist()
    for x1, y1, x2, y2, r, g, bb in rows:
        d.line((x1, y1, x2, y2), fill=(int(r), int(g), int(bb)))
    vis = z > 5
    if vis.any():
        sh["bbox"] = (float(sx[vis].min()), float(sy[vis].min()), float(sx[vis].max()), float(sy[vis].max()))
    # engine plumes
    if not sh["broken"] and reveal >= 1.0:
        back = sh["Rs"] @ np.array([-1.0, 0, 0])
        E = sh["engines"] @ sh["Rt"][0].T + sh["off"][0]
        ln = 10 + 3 * math.sin(t * 23 + sh["roll_ph"])
        ex, ey, ez = cam.proj(E)
        tx, ty, tz = cam.proj(E + back * ln)
        for i in range(len(E)):
            if ez[i] > 5 and tz[i] > 5:
                d.line((ex[i], ey[i], tx[i], ty[i]), fill=(200, 90, 30), width=3)
                mx, my = (ex[i] * 2 + tx[i]) / 3, (ey[i] * 2 + ty[i]) / 3
                d.line((ex[i], ey[i], mx, my), fill=(255, 220, 150), width=1)
    # burning breaches
    for br in sh["breaches"]:
        wpos, s = _l2w(sh, br["loc"])
        if sh["det"][s]:
            continue
        x, y, zz = cam.proj1(wpos)
        if zz > 5:
            fl = _rng.random()
            r = 1.0 + fl * 1.3
            d.ellipse((x - r, y - r, x + r, y + r), fill=(255, int(120 + 100 * fl), 40))


def _draw_fx(d, cam, t):
    S = _S
    # macro shells
    for s in S["shells"]:
        u = (t - s["t0"]) / s["T"]
        if u < 0 or u > 1:
            continue
        p = s["p0"] + (s["p1"] - s["p0"]) * u
        q = s["p0"] + (s["p1"] - s["p0"]) * max(0.0, u - 0.05)
        x1, y1, z1 = cam.proj1(p)
        x2, y2, z2 = cam.proj1(q)
        if z1 > 5 and z2 > 5:
            d.line((x2, y2, x1, y1), fill=(255, 200, 110))
        if u > 0.97:
            _spawn(s["p1"], np.array([[_rng.uniform(-4, 4) for _ in range(3)] for _ in range(4)]), 0.5, (255, 170, 80), False, 1.0)
    # torpedoes
    for tp in S["torps"]:
        tr = tp["trail"]
        if len(tr) < 2:
            continue
        sx, sy, z = cam.proj(np.array(tr))
        n = len(tr)
        for i in range(n - 1):
            if z[i] > 5 and z[i + 1] > 5:
                k = (i + 1) / n
                d.line((sx[i], sy[i], sx[i + 1], sy[i + 1]), fill=(int(90 * k + 30), int(110 * k + 30), int(160 * k + 40)))
        if z[-1] > 5:
            x, y = sx[-1], sy[-1]
            d.rectangle((x - 1, y - 1, x + 1, y + 1), fill=(255, 250, 220))
    # lance beams
    for l in S["lances"]:
        p = (t - l["t0"]) / l["dur"]
        env = math.sin(math.pi * min(1.0, max(0.0, p))) * (0.75 + 0.25 * _rng.random())
        a, _ = _l2w(l["sh"], l["src"])
        b, _ = _l2w(l["tg"], l["loc"])
        b = b + l["miss"] * (1.0 if l["miss"].any() else 0.0)
        if l["miss"].any():
            b = a + (b - a) * 1.6
        x1, y1, z1 = cam.proj1(a)
        x2, y2, z2 = cam.proj1(b)
        if z1 < 5 or z2 < 5:
            continue
        c = l["sh"]["beam"]
        d.line((x1, y1, x2, y2), fill=scale(c, env * 0.45), width=5)
        d.line((x1, y1, x2, y2), fill=scale(c, env), width=2)
        d.line((x1, y1, x2, y2), fill=scale((255, 255, 240), env), width=1)
        rr = 2 + 3 * env
        d.ellipse((x1 - rr, y1 - rr, x1 + rr, y1 + rr), fill=scale(c, env))
        if not l["miss"].any():
            rr = 2 + 4 * env
            d.ellipse((x2 - rr, y2 - rr, x2 + rr, y2 + rr), fill=scale((255, 250, 230), env))
    # void shield flares
    for f in S["flares"]:
        p = (t - f["t0"]) / 0.8
        sh = f["ship"]
        wpos, _ = _l2w(sh, f["loc"])
        x, y, z = cam.proj1(wpos)
        if z <= 5:
            continue
        k = 1.0 - p
        for j, r0 in enumerate((5, 10, 15)):
            r = r0 * (0.5 + p) * FOV / z * 1.2
            a0 = f["a0"] + j * 70 + p * 60
            d.arc((x - r, y - r, x + r, y + r), a0, a0 + 150 - j * 25, fill=scale(SHIELD_COL, k * (1 - j * 0.25)), width=2 if j == 0 else 1)
        bb = sh.get("bbox")
        if bb and p < 0.6:
            m = 8
            d.ellipse((bb[0] - m, bb[1] - m, bb[2] + m, bb[3] + m), outline=scale(SHIELD_COL, (0.6 - p) * 0.8))
    # explosions
    for e in S["expl"]:
        p = (t - e["t0"]) / e["dur"]
        x, y, z = cam.proj1(e["pos"])
        if z <= 5:
            continue
        r = e["r"] * FOV / z * (0.3 + 1.2 * math.sqrt(p))
        if p < 0.3:
            d.ellipse((x - r, y - r, x + r, y + r), fill=(255, 245, 210))
        elif p < 0.65:
            q = (p - 0.3) / 0.35
            r2 = r * (1 - 0.6 * q)
            d.ellipse((x - r2, y - r2, x + r2, y + r2), fill=lerp_color((255, 220, 150), (200, 70, 20), q))
        d.ellipse((x - r * 1.3, y - r * 1.3, x + r * 1.3, y + r * 1.3), outline=scale((255, 140, 50), 1 - p))
        if e["r"] > 12:
            r3 = r * 2.2
            d.ellipse((x - r3, y - r3, x + r3, y + r3), outline=scale((255, 210, 150), (1 - p) * 0.7))


def _draw_particles(arr, cam):
    life = _P["life"]
    a = np.nonzero(life > 0)[0]
    if len(a) == 0:
        return
    sx, sy, z = cam.proj(_P["pos"][a])
    xi = sx.astype(np.int32)
    yi = sy.astype(np.int32)
    ok = (z > 5) & (xi >= 0) & (xi < 239) & (yi >= 0) & (yi < 239)
    a, xi, yi = a[ok], xi[ok], yi[ok]
    b = (life[a] / _P["max"][a]) ** 0.6
    col = (_P["col"][a] * b[:, None]).astype(np.uint8)
    arr[yi, xi] = np.maximum(arr[yi, xi], col)
    big = _P["big"][a]
    if big.any():
        xb, yb, cb = xi[big], yi[big], col[big]
        arr[yb, xb + 1] = np.maximum(arr[yb, xb + 1], cb)
        arr[yb + 1, xb] = np.maximum(arr[yb + 1, xb], cb)


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


def _hud(img, d, t):
    S = _S
    imp, en = S["ships"]
    ph = S["phase"]
    since = t - S["phase_t"]
    # top line: messages or status
    m = S["msg"]
    if ph == "intro":
        if int(since * 3) % 2 == 0 or since > 2:
            _tc(img, 26, "+ AUSPEX CONTACT +", (255, 90, 70), 11)
        _tc(img, 40, en["name"], en["col"], 13)
        _tc(img, 56, en["cls"], scale(en["col"], 0.7), 9)
        if since > 2.5:
            _tc(img, 172, "BATTLE STATIONS", IMP_COL, 12)
            _tc(img, 187, imp["name"], scale(IMP_COL, 0.7), 9)
        return
    if ph in ("verdict", "fade"):
        if S["verdict"] is None:
            if S["imp_wins"]:
                S["verdict"] = ("ENEMY DESTROYED", en["name"] + " IS NO MORE", "PRAISE THE OMNISSIAH", IMP_COL)
            else:
                S["verdict"] = (imp["name"] + " LOST", "ALL HANDS WITH HER", "AVE IMPERATOR", (220, 90, 70))
        a, b, c, col = S["verdict"]
        k = 1.0 if ph == "verdict" else max(0.0, 1 - since / 1.2)
        _tc(img, 40, a, scale(col, k), 13)
        _tc(img, 58, b, scale(col, 0.7 * k), 9)
        _tc(img, 176, c, scale((210, 200, 170), k), 11)
        return
    if m and t - m[2] < 2.4:
        on = (t - m[2]) > 0.5 or int((t - m[2]) * 8) % 2 == 0
        if on:
            _tc(img, 28, m[0], m[1], 11)
    else:
        _tc(img, 28, "BROADSIDE ENGAGEMENT", HUD_DIM, 9)
    # bottom: hull + shield status for both ships
    for sh, x0, align in ((imp, 60, "L"), (en, 124, "R")):
        col = sh["col"]
        lab = "IMPERIAL" if sh["kind"] == "imperial" else sh["kind"].upper()
        tw = _tw(lab, 9)
        lx = x0 if align == "L" else x0 + 56 - tw
        _text(img, lx, 178, lab, scale(col, 0.85), 9, outline=False)
        frac = max(0.0, sh["hull"] / sh["hull_max"])
        d.rectangle((x0, 191, x0 + 56, 197), outline=scale(col, 0.5))
        w = int(54 * frac)
        if w > 0:
            hc = col if frac > 0.35 else ((255, 80, 40) if int(t * 4) % 2 else (150, 40, 20))
            if align == "L":
                d.rectangle((x0 + 1, 192, x0 + 1 + w, 196), fill=hc)
            else:
                d.rectangle((x0 + 55 - w, 192, x0 + 55, 196), fill=hc)
        for i in range(sh["shield_max"]):
            px = (x0 + i * 8) if align == "L" else (x0 + 52 - i * 8)
            on = i < sh["shields"]
            d.ellipse((px, 201, px + 4, 205), fill=SHIELD_COL if on else None, outline=scale(SHIELD_COL, 0.6))
    _tc(img, 199, "VOID", scale(SHIELD_COL, 0.5), 9)


def render(bezel, mask, now: float) -> Image.Image:
    if _session.fresh(now):
        _reset()
    t = _session.t(now)
    dt = min(0.1, max(0.0, t - _S.get("last_t", t)))
    _S["last_t"] = t
    _update(t, dt)
    S = _S

    # camera: slow orbit; after a kill, drift toward the wreck
    ph = S["phase"]
    if ph in ("breakup", "verdict", "fade"):
        u = min(1.0, (t - S["loser"]["break_t"]) / 6.0)
        u = u * u * (3 - 2 * u)
        S["target"] = S["loser"]["P"] * 0.3 * u
        S["dist"] = 218.0 - 20.0 * u
    else:
        S["target"] = np.zeros(3)
        S["dist"] = 218.0 + 10.0 * math.sin((t - S["t0"]) * 0.05)
    cam = _Cam(t)

    # 1. stars + nebula (directions at infinity: rotate only)
    arr = np.zeros((240, 240, 3), dtype=np.uint8)
    c = S["stars"] @ cam.C.T
    vz = c[:, 2] > 0.2
    sx = (CX + FOV * c[vz, 0] / c[vz, 2]).astype(np.int32)
    sy = (CY - FOV * c[vz, 1] / c[vz, 2]).astype(np.int32)
    col = S["star_col"][vz]
    ok = (sx >= 0) & (sx < 240) & (sy >= 0) & (sy < 240)
    arr[sy[ok], sx[ok]] = col[ok].astype(np.uint8)
    img = Image.fromarray(arr, "RGB")

    # 2. distant planet
    pc = cam.C @ S["pdir"]
    if pc[2] > 0.3:
        px = CX + FOV * pc[0] / pc[2]
        py = CY - FOV * pc[1] / pc[2]
        R = S["sprite_r"]
        if -R * 2 < px < 240 + R * 2 and -R * 2 < py < 240 + R * 2:
            img.paste(S["sprite"], (int(px - R), int(py - R)), S["sprite"])

    d = ImageDraw.Draw(img)
    # 3. ships, far one first
    reveal = 1.0
    if ph == "intro":
        reveal = min(1.0, (t - S["phase_t"]) / 3.0)
    ships = sorted(S["ships"], key=lambda s: -cam.proj1(s["P"])[2])
    for sh in ships:
        _draw_ship(d, cam, sh, t, reveal)
    _draw_fx(d, cam, t)

    # 4. particles
    arr = np.array(img)
    _draw_particles(arr, cam)
    if S["flash"] > 0:
        add = int(60 * S["flash"] ** 2)
        arr = np.minimum(arr.astype(np.int16) + np.array([add, int(add * 0.8), int(add * 0.55)], np.int16), 255).astype(np.uint8)
    if ph == "fade":
        k = max(0.0, 1.0 - (t - S["phase_t"]) / 1.6)
        arr = (arr * k).astype(np.uint8)
    elif ph == "intro":
        k = min(1.0, (t - S["phase_t"]) / 1.0)
        if k < 1.0:
            arr = (arr * k).astype(np.uint8)
    img = Image.fromarray(arr, "RGB")
    d = ImageDraw.Draw(img)
    _hud(img, d, t)
    return img
