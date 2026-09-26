"""Auspex Tactical Engagement – top-down Epic-scale battle on a procedural map.

Imperial Guard companies (friendly rectangles, steel blue) advance on Ork mobs
(hostile diamonds, green) across a freshly generated battlefield of woods,
ruins and hills. Units advance, take cover, trade fire, lose models, break and
fall back; Orks charge into melee. When one army is broken a victory banner is
shown and a new map is generated.
"""

from __future__ import annotations

import math
import random

import numpy as np
from PIL import Image, ImageChops, ImageDraw

from ._common import CX, CY, Session, font, lerp_color, scale

NAME = "auspex_engagement"


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
BATTLE_R = 78.0  # radius of the playable battlefield
FX, FY = 120.0, 110.0  # battlefield centre (shifted up to leave room for the HUD)

IG_COL = (120, 175, 255)
IG_DARK = (30, 55, 95)
ORK_COL = (110, 235, 70)
ORK_DARK = (25, 70, 20)
HUD = (90, 255, 150)
HUD_DIM = (20, 80, 45)
AMBER = (255, 190, 60)
RED = (255, 70, 50)

_SECTORS = ["ARMAGEDDON", "GOLGOTHA", "TARTARUS", "PISCINA IV", "ACHERON", "HELSREACH",
            "RYNN'S WORLD", "CADIA", "TALLARN", "VRAKS", "PHAEDRA", "MINERVA"]
_IG_NAMES = ["1ST", "2ND", "3RD", "4TH", "5TH", "6TH", "7TH", "8TH"]

_KINDS = {
    # speed px/s, range, reload s, shots/model factor, hit chance, melee power, morale resist
    "inf":   dict(speed=3.0, rng=64.0, reload=2.2, hit=0.26, melee=0.07, nerve=1.0),
    "tank":  dict(speed=3.5, rng=85.0, reload=4.0, hit=0.55, melee=0.02, nerve=3.0),
    "boyz":  dict(speed=2.3, rng=36.0, reload=2.4, hit=0.10, melee=0.09, nerve=1.1),
    "nobz":  dict(speed=2.2, rng=32.0, reload=2.6, hit=0.14, melee=0.22, nerve=2.0),
    "buggy": dict(speed=7.0, rng=48.0, reload=1.8, hit=0.20, melee=0.05, nerve=1.3),
}


class _Unit:
    __slots__ = ("side", "kind", "name", "x", "y", "n", "n0", "morale", "state", "tx", "ty",
                 "target", "cd", "hitflash", "foe", "ptime", "home")

    def __init__(self, side, kind, name, x, y, n, home):
        self.side, self.kind, self.name = side, kind, name
        self.x, self.y = x, y
        self.n = self.n0 = n
        self.morale = 1.0
        self.state = "advance"
        self.tx, self.ty = x, y
        self.target = None
        self.cd = _rng.uniform(0.5, 2.0)
        self.hitflash = 0.0
        self.foe = None  # melee partner
        self.ptime = 0.0
        self.home = home

    @property
    def active(self):
        return self.n > 0 and self.state not in ("broken", "dead")


class _S:
    pass


_st = _S()
_st.bg = None


# ---------------------------------------------------------------- terrain ---

def _noise(res, octave_seed):
    g = np.array([[octave_seed.random() for _ in range(res)] for _ in range(res)], dtype=np.float32)
    im = Image.fromarray((g * 255).astype(np.uint8), "L").resize((240, 240), Image.BICUBIC)
    return np.asarray(im, dtype=np.float32) / 255.0


def _gen_map():
    rnd = _rng
    n = _noise(5, rnd) * 0.7 + _noise(9, rnd) * 0.3
    yy, xx = np.mgrid[0:240, 0:240].astype(np.float32)
    rr = np.hypot(xx - CX, yy - CY)

    # base ground: dark earth tone graded by elevation band
    bands = np.clip((n * 7).astype(np.int32), 0, 6)
    base = np.array([18, 26, 22], np.float32)
    rgb = np.empty((240, 240, 3), np.float32)
    shade = 0.75 + bands[..., None] * 0.09
    rgb[:] = base * shade
    # contour lines where bands change (hills)
    edge = np.zeros((240, 240), bool)
    edge[:, 1:] |= bands[:, 1:] != bands[:, :-1]
    edge[1:, :] |= bands[1:, :] != bands[:-1, :]
    hi = bands >= 4
    rgb[edge] = np.where(hi[edge][:, None], np.array([70, 80, 55], np.float32),
                         np.array([40, 52, 44], np.float32))

    cover = Image.new("L", (240, 240), 0)
    cd = ImageDraw.Draw(cover)
    img = Image.fromarray(rgb.clip(0, 255).astype(np.uint8), "RGB")
    d = ImageDraw.Draw(img)

    # road
    a = rnd.uniform(0, math.pi)
    pts = []
    for i in range(9):
        s = -110 + i * 27.5
        off = math.sin(i * 0.9 + rnd.uniform(0, 6)) * 12
        pts.append((FX + math.cos(a) * s - math.sin(a) * off, FY + math.sin(a) * s + math.cos(a) * off))
    d.line(pts, fill=(52, 44, 32), width=5)
    d.line(pts, fill=(66, 56, 40), width=1)

    covers = []
    # woods
    for _ in range(rnd.randint(3, 5)):
        ang, rad = rnd.uniform(0, 2 * math.pi), rnd.uniform(12, 62)
        wx, wy = FX + math.cos(ang) * rad, FY + math.sin(ang) * rad
        blobs = []
        for _ in range(rnd.randint(8, 14)):
            bx, by = wx + rnd.gauss(0, 7), wy + rnd.gauss(0, 5)
            br = rnd.uniform(3, 6)
            blobs.append((bx, by, br))
            d.ellipse([bx - br, by - br, bx + br, by + br], fill=(16, 52, 28))
            cd.ellipse([bx - br, by - br, bx + br, by + br], fill=1)
        for bx, by, br in blobs:
            d.ellipse([bx - br * 0.5, by - br * 0.5, bx + br * 0.5, by + br * 0.5], fill=(28, 78, 40))
            d.point((bx, by), fill=(60, 120, 70))
        covers.append((wx, wy, "WOODS"))
    # ruins
    for _ in range(rnd.randint(2, 4)):
        ang, rad = rnd.uniform(0, 2 * math.pi), rnd.uniform(8, 60)
        rx, ry = FX + math.cos(ang) * rad, FY + math.sin(ang) * rad
        for _ in range(rnd.randint(4, 7)):
            bx, by = rx + rnd.gauss(0, 7), ry + rnd.gauss(0, 7)
            bw, bh = rnd.uniform(4, 9), rnd.uniform(4, 9)
            box = [bx - bw / 2, by - bh / 2, bx + bw / 2, by + bh / 2]
            d.rectangle(box, fill=(34, 34, 36))
            # broken walls: draw only some sides
            sides = [((box[0], box[1]), (box[2], box[1])), ((box[2], box[1]), (box[2], box[3])),
                     ((box[2], box[3]), (box[0], box[3])), ((box[0], box[3]), (box[0], box[1]))]
            for sa, sb in sides:
                if rnd.random() < 0.7:
                    d.line([sa, sb], fill=(120, 116, 104))
            cd.rectangle(box, fill=2)
        covers.append((rx, ry, "RUINS"))

    # auspex grid + range rings baked in
    arr = np.asarray(img, dtype=np.int16).copy()
    grid = ((xx.astype(np.int32) % 24) == 0) | ((yy.astype(np.int32) % 24) == 0)
    arr[grid] += np.array([0, 22, 12], np.int16)
    for rad in (30, 60, 90):
        ring = np.abs(rr - rad) < 0.6
        arr[ring] += np.array([0, 38, 18], np.int16)
    # vignette + outer bezel
    vign = np.clip(1.25 - rr / 125.0, 0.25, 1.0)
    arr = (arr * vign[..., None])
    arr[(rr > 110) & (rr < 112)] = (30, 120, 70)
    arr[rr >= 112] = (0, 0, 0)
    img = Image.fromarray(arr.clip(0, 255).astype(np.uint8), "RGB")
    d = ImageDraw.Draw(img)
    for k in range(72):
        ang = k * math.pi / 36
        r0 = 105 if k % 6 else 100
        d.line([(CX + math.cos(ang) * r0, CY + math.sin(ang) * r0),
                (CX + math.cos(ang) * 110, CY + math.sin(ang) * 110)], fill=(40, 150, 90))
    return img, np.asarray(cover), covers


# ---------------------------------------------------------------- set-up ---

def _reset():
    _st.cycle_t0 = None
    _new_battle(0.0)


def _new_battle(t0):
    _st.t0 = t0
    _st.sim_t = 0.0
    _st.bg, _st.cover, _st.covers = _gen_map()
    _st.sector = _rng.choice(_SECTORS) + " " + "".join(_rng.choice("ABGKZ") for _ in range(1)) + str(_rng.randint(1, 99))
    _st.theta = _rng.uniform(0, 2 * math.pi)
    _st.units = []
    _st.tracers = []   # [x0,y0,x1,y1,life,col]
    _st.blasts = []    # [x,y,age,maxr,col]
    _st.wrecks = []    # (x,y,side)
    _st.events = []    # [text, age, col]
    _st.loss = [0, 0]
    _st.winner = None
    _st.end_t = 0.0
    _st.arty_cd = _rng.uniform(18, 30)
    _st.waaagh = False
    ux, uy = math.cos(_st.theta), math.sin(_st.theta)   # IG home direction
    px, py = -uy, ux                                    # lateral
    names = _IG_NAMES[:]
    _rng.shuffle(names)
    # Imperial Guard line
    n_inf = _rng.randint(3, 4)
    n_tank = _rng.randint(1, 2)
    kinds = ["inf"] * n_inf + ["tank"] * n_tank
    _rng.shuffle(kinds)
    for i, k in enumerate(kinds):
        lat = (i - (len(kinds) - 1) / 2) * 21 + _rng.uniform(-3, 3)
        dep = 58 + _rng.uniform(-4, 4) + (8 if k == "tank" else 0) - abs(lat) * 0.35
        x, y = FX + ux * dep + px * lat, FY + uy * dep + py * lat
        n = 10 if k == "inf" else 3
        nm = (names.pop() + " COY") if k == "inf" else ("RUSS " + _rng.choice("ABCDEFG") + str(_rng.randint(1, 9)))
        _st.units.append(_Unit(0, k, nm, x, y, n, (ux, uy)))
    # Ork horde
    kinds = ["boyz"] * _rng.randint(3, 5) + ["nobz"] * _rng.randint(0, 1) + ["buggy"] * _rng.randint(1, 2)
    _rng.shuffle(kinds)
    for i, k in enumerate(kinds):
        lat = (i - (len(kinds) - 1) / 2) * 18 + _rng.uniform(-4, 4)
        dep = 62 + _rng.uniform(-5, 5) - abs(lat) * 0.35
        x, y = FX - ux * dep + px * lat, FY - uy * dep + py * lat
        n = {"boyz": _rng.randint(14, 20), "nobz": 6, "buggy": 2}[k]
        nm = {"boyz": "BOYZ MOB", "nobz": "NOBZ", "buggy": "WARBUGGY"}[k]
        _st.units.append(_Unit(1, k, nm, x, y, n, (-ux, -uy)))
    # IG: pick cover objectives in their half of the field
    for u in _st.units:
        if u.side == 0:
            u.tx, u.ty = _pick_cover(u)
    _event("AUSPEX LOCK ACQUIRED", HUD)


def _pick_cover(u):
    ux, uy = u.home
    best, bs = None, 1e9
    for cx, cy, _ in _st.covers:
        fwd = (cx - FX) * ux + (cy - FY) * uy   # >0 means on IG side
        if fwd < -15:
            continue
        dd = math.hypot(cx - u.x, cy - u.y)
        s = dd - fwd * 0.3
        if dd < 75 and s < bs:
            bs, best = s, (cx + _rng.uniform(-5, 5), cy + _rng.uniform(-5, 5))
    if best is None:
        best = (u.x - ux * 30, u.y - uy * 30)
    return best


def _event(text, col):
    _st.events.insert(0, [text, 0.0, col])
    del _st.events[3:]


# ---------------------------------------------------------------- sim ---

def _cover_at(x, y):
    xi, yi = int(x), int(y)
    if 0 <= xi < 240 and 0 <= yi < 240:
        return int(_st.cover[yi, xi])
    return 0


def _kill(u, k, attacker_side):
    k = min(k, u.n)
    if k <= 0:
        return
    u.n -= k
    _st.loss[u.side] += k
    u.hitflash = 0.35
    u.morale -= k / u.n0 * (0.9 / _KINDS[u.kind]["nerve"])
    if len(_st.wrecks) < 60:
        _st.wrecks.append((u.x + _rng.uniform(-3, 3), u.y + _rng.uniform(-3, 3), u.side))
    if u.n <= 0:
        u.state = "dead"
        if u.foe is not None:
            u.foe.foe = None
            if u.foe.state == "melee":
                u.foe.state = "advance"
        u.foe = None
        if u.side == 0:
            _event(u.name + (" DESTROYED" if u.kind == "tank" else " WIPED OUT"), RED)
        else:
            _event(u.name + " PURGED", IG_COL)
        _blast(u.x, u.y, 9, AMBER)
        for o in _st.units:  # nearby friends waver
            if o is not u and o.side == u.side and o.active and math.hypot(o.x - u.x, o.y - u.y) < 40:
                o.morale -= 0.08 / _KINDS[o.kind]["nerve"]
        return
    if u.state in ("advance", "hold", "melee") and u.morale < 0.4:
        if _rng.random() < 0.55 - u.morale:
            _break(u)


def _break(u):
    u.state = "broken"
    if u.foe is not None:
        u.foe.foe = None
        if u.foe.state == "melee":
            u.foe.state = "advance"
        u.foe = None
    _event(u.name + " BROKEN" if u.side == 0 else u.name + " FLEES", AMBER if u.side == 0 else HUD)


def _blast(x, y, r, col):
    if len(_st.blasts) < 30:
        _st.blasts.append([x, y, 0.0, r, col])


def _nearest_enemy(u):
    best, bd = None, 1e9
    for o in _st.units:
        if o.side != u.side and o.n > 0 and o.state != "dead":
            dd = (o.x - u.x) ** 2 + (o.y - u.y) ** 2
            if o.state == "broken":
                dd *= 2.5
            if dd < bd:
                bd, best = dd, o
    return best, math.sqrt(bd) if best else 1e9


def _fire(u, tgt, dist):
    kd = _KINDS[u.kind]
    shots = max(1, u.n // 3) if u.kind in ("inf", "boyz", "nobz") else u.n
    cover = _cover_at(tgt.x, tgt.y)
    hit = kd["hit"] * (1.0 - 0.45 * (cover > 0) - 0.15 * (cover == 2)) * (1.2 - dist / kd["rng"] * 0.5)
    if tgt.state == "broken":
        hit *= 1.3
    kills = sum(1 for _ in range(shots) if _rng.random() < hit)
    if u.kind == "tank":
        kills = _rng.randint(1, 3) if _rng.random() < hit else 0
        if tgt.kind in ("buggy",):
            kills = min(kills, 1)
        col = (255, 230, 120)
        _st.tracers.append([u.x, u.y, tgt.x, tgt.y, 0.25, col])
        _blast(tgt.x + _rng.uniform(-4, 4), tgt.y + _rng.uniform(-4, 4), 8, AMBER)
    else:
        if tgt.kind == "tank":  # small arms barely scratch armour
            kills = 1 if kills and _rng.random() < 0.12 else 0
        col = (255, 90, 70) if u.side == 0 else (255, 220, 90)
        for _ in range(min(3, shots)):
            _st.tracers.append([u.x + _rng.uniform(-3, 3), u.y + _rng.uniform(-3, 3),
                                tgt.x + _rng.uniform(-4, 4), tgt.y + _rng.uniform(-4, 4),
                                _rng.uniform(0.12, 0.25), col])
    _kill(tgt, kills, u.side)


def _step(dt):
    _st.sim_t += dt
    st = _st
    for tr in st.tracers:
        tr[4] -= dt
    st.tracers = [tr for tr in st.tracers if tr[4] > 0]
    for b in st.blasts:
        b[2] += dt
    st.blasts = [b for b in st.blasts if b[2] < 0.7]
    for e in st.events:
        e[1] += dt

    if st.winner is not None:
        return
    if st.sim_t < 3.0:   # deployment
        return

    # Basilisk fire mission
    st.arty_cd -= dt
    if st.arty_cd <= 0:
        st.arty_cd = _rng.uniform(22, 34)
        tgts = [o for o in st.units if o.side == 1 and o.active]
        if tgts:
            t = max(tgts, key=lambda o: o.n)
            _event("BASILISK BARRAGE", AMBER)
            st.arty = [t, 1.2, 5]   # target, delay, shells
    arty = getattr(st, "arty", None)
    if arty:
        arty[1] -= dt
        if arty[1] <= 0 and arty[2] > 0:
            t = arty[0]
            arty[1] = 0.35
            arty[2] -= 1
            bx, by = t.x + _rng.uniform(-10, 10), t.y + _rng.uniform(-10, 10)
            _blast(bx, by, 13, (255, 150, 60))
            if t.n > 0 and math.hypot(bx - t.x, by - t.y) < 9:
                _kill(t, _rng.randint(1, 2), 0)
        if arty[2] <= 0:
            st.arty = None

    for u in st.units:
        if u.n <= 0 or u.state == "dead":
            continue
        kd = _KINDS[u.kind]
        u.hitflash = max(0.0, u.hitflash - dt)
        u.cd -= dt
        if u.state == "broken":
            # run for home edge; recover occasionally if far from enemies
            hx, hy = u.home
            u.x += hx * kd["speed"] * 1.3 * dt
            u.y += hy * kd["speed"] * 1.3 * dt
            if math.hypot(u.x - FX, u.y - FY) > BATTLE_R + 6:
                u.state = "dead"
                u.n = 0
            continue
        if u.state == "melee":
            f = u.foe
            if f is None or f.n <= 0 or f.state in ("dead", "broken"):
                u.state, u.foe = "advance", None
                continue
            if u.cd <= 0:
                u.cd = 1.0
                exp = u.n * kd["melee"]
                k = int(exp) + (1 if _rng.random() < exp - int(exp) else 0)
                if f.kind == "tank":
                    k = 1 if _rng.random() < 0.18 else 0
                _kill(f, k, u.side)
                st.tracers.append([u.x, u.y, f.x, f.y, 0.1, (255, 255, 255)])
            continue

        enemy, dist = _nearest_enemy(u)
        if enemy is None:
            continue
        ex, ey = enemy.x - u.x, enemy.y - u.y
        if u.side == 1:
            # Orks: advance, shoot, then charge
            charge = dist < 30
            if charge and not st.waaagh and u.kind != "buggy":
                st.waaagh = True
                _event("WAAAGH!!", ORK_COL)
            sp = kd["speed"] * (2.0 if charge and u.kind != "buggy" else 1.0)
            if u.kind == "buggy" and dist < 28:
                sp = -kd["speed"] * 0.4   # buggies skirmish
            if dist > 5:
                u.x += ex / dist * sp * dt
                u.y += ey / dist * sp * dt
            if dist < 7 and u.kind != "buggy" and enemy.active:
                u.state, u.foe = "melee", enemy
                if enemy.foe is None:
                    enemy.state, enemy.foe = "melee", u
                u.cd = 0.2
                continue
            if dist < kd["rng"] and u.cd <= 0:
                u.cd = kd["reload"] * _rng.uniform(0.8, 1.2)
                _fire(u, enemy, dist)
        else:
            # Guard: move to cover, then hold and fire; tanks creep forward
            ddx, ddy = u.tx - u.x, u.ty - u.y
            dd = math.hypot(ddx, ddy)
            if u.state == "advance" and dd > 2:
                sp = kd["speed"] * (0.5 if dist < kd["rng"] else 1.0)
                u.x += ddx / dd * sp * dt
                u.y += ddy / dd * sp * dt
            elif u.state == "advance":
                u.state = "hold"
            if u.kind == "tank" and dist > kd["rng"] * 0.8:
                u.tx, u.ty = u.x + ex / dist * 10, u.y + ey / dist * 10
                u.state = "advance"
            if dist < kd["rng"] and u.cd <= 0:
                u.cd = kd["reload"] * _rng.uniform(0.8, 1.2)
                _fire(u, enemy, dist)
            # rally slowly while in cover
            if _cover_at(u.x, u.y) and u.morale < 1.0:
                u.morale += 0.01 * dt
        # keep inside the battlefield
        for o in st.units:   # keep formations from stacking
            if o is not u and o.side == u.side and o.n > 0 and o.state != "dead":
                sx, sy = u.x - o.x, u.y - o.y
                sd2 = sx * sx + sy * sy
                if 0.01 < sd2 < 196:
                    sd = math.sqrt(sd2)
                    push = (14 - sd) * 0.8 * dt
                    u.x += sx / sd * push
                    u.y += sy / sd * push
        rr = math.hypot(u.x - FX, u.y - FY)
        if rr > BATTLE_R:
            u.x = FX + (u.x - FX) * BATTLE_R / rr
            u.y = FY + (u.y - FY) * BATTLE_R / rr

    # victory check
    alive = [sum(u.n for u in st.units if u.side == s and u.active) for s in (0, 1)]
    if alive[0] == 0 or alive[1] == 0 or st.sim_t > 125:
        if alive[0] == 0:
            st.winner = 1
        elif alive[1] == 0:
            st.winner = 0
        else:
            st.winner = 0 if alive[0] * 1.6 >= alive[1] else 1
        st.end_t = st.sim_t
        for u in st.units:
            if u.side != st.winner and u.n > 0 and u.state not in ("dead",):
                u.state = "broken"
                u.foe = None
        _event("ENGAGEMENT RESOLVED", HUD)


# ---------------------------------------------------------------- draw ---

def _draw_unit(d, u, sweep_boost, t):
    x, y = u.x, u.y
    frac = u.n / u.n0
    if u.side == 0:
        col = IG_COL
        if u.state == "broken":
            col = AMBER if int(t * 4) % 2 else (120, 90, 40)
        col = lerp_color(col, (255, 255, 255), sweep_boost * 0.6 + (0.8 if u.hitflash > 0.2 else 0))
        w, h = (7, 5) if u.kind == "inf" else (8, 5)
        d.rectangle([x - w, y - h, x + w, y + h], fill=IG_DARK, outline=col)
        if u.kind == "inf":
            d.line([(x - w, y - h), (x + w, y + h)], fill=col)
            d.line([(x - w, y + h), (x + w, y - h)], fill=col)
        else:
            d.ellipse([x - w + 2, y - 3, x + w - 2, y + 3], outline=col)
    else:
        col = ORK_COL
        if u.state == "broken":
            col = (90, 120, 60) if int(t * 4) % 2 else (50, 80, 40)
        col = lerp_color(col, (255, 255, 255), sweep_boost * 0.6 + (0.8 if u.hitflash > 0.2 else 0))
        s = 7 if u.kind != "buggy" else 5
        d.polygon([(x, y - s), (x + s, y), (x, y + s), (x - s, y)], fill=ORK_DARK, outline=col)
        if u.kind == "nobz":
            d.line([(x - 3, y), (x + 3, y)], fill=col)
            d.line([(x, y - 3), (x, y + 3)], fill=col)
        elif u.kind == "boyz":
            d.point([(x - 2, y), (x + 2, y), (x, y - 2), (x, y + 2)], fill=col)
        else:
            d.ellipse([x - 1.5, y - 1.5, x + 1.5, y + 1.5], fill=col)
    # strength bar
    bw = 14
    by = y + 8
    d.line([(x - bw / 2, by), (x + bw / 2, by)], fill=(40, 40, 40))
    bc = (80, 255, 120) if frac > 0.6 else (AMBER if frac > 0.3 else RED)
    d.line([(x - bw / 2, by), (x - bw / 2 + bw * frac, by)], fill=bc)


def render(bezel, mask, now: float) -> Image.Image:
    if _session.fresh(now) or _st.bg is None:
        _reset()
    t = _session.t(now)
    st = _st
    lt = t - st.t0
    # advance simulation at fixed steps
    steps = 0
    while st.sim_t < lt and steps < 12:
        _step(DT)
        steps += 1
    if st.sim_t < lt:
        st.sim_t = lt
    # banner time over -> new battle
    if st.winner is not None and st.sim_t - st.end_t > 8.0:
        _new_battle(t)
        lt = 0.0

    img = st.bg.copy()
    d = ImageDraw.Draw(img)
    f9, f10, f11 = font(9), font(10), font(11)

    # casualty markers
    for wx, wy, s in st.wrecks:
        c = (70, 50, 40) if s == 0 else (45, 65, 35)
        d.line([(wx - 1.5, wy - 1.5), (wx + 1.5, wy + 1.5)], fill=c)
        d.line([(wx - 1.5, wy + 1.5), (wx + 1.5, wy - 1.5)], fill=c)

    # sweep: additive fading wedge + bright leading edge
    sw = (t * 1.9) % (2 * math.pi)
    wedge = Image.new("RGB", (240, 240), (0, 0, 0))
    wd = ImageDraw.Draw(wedge)
    deg = math.degrees(sw)
    for k in range(6):
        wd.pieslice([CX - 109, CY - 109, CX + 109, CY + 109], deg - 50 + k * 8, deg,
                    fill=(0, 9 + k * 3, 4 + k * 2))
    img = ImageChops.add(img, wedge)
    d = ImageDraw.Draw(img)
    d.line([(CX, CY), (CX + math.cos(sw) * 109, CY + math.sin(sw) * 109)], fill=(120, 255, 170))

    # tracers
    for x0, y0, x1, y1, life, col in st.tracers:
        d.line([(x0, y0), (x1, y1)], fill=scale(col, min(1.0, life * 5)))
    # blasts
    for bx, by, age, mr, col in st.blasts:
        r = 2 + mr * min(1.0, age / 0.35)
        fade = 1.0 - age / 0.7
        if age < 0.12:
            d.ellipse([bx - r, by - r, bx + r, by + r], fill=scale((255, 240, 200), fade))
        else:
            d.ellipse([bx - r, by - r, bx + r, by + r], outline=scale(col, fade))
            r2 = r * 0.5
            d.ellipse([bx - r2, by - r2, bx + r2, by + r2], outline=scale((255, 230, 150), fade))

    # units
    fade_in = min(1.0, lt / 2.5)
    for u in st.units:
        if u.n <= 0 or u.state == "dead":
            continue
        ang = math.atan2(u.y - CY, u.x - CX) % (2 * math.pi)
        diff = (sw - ang) % (2 * math.pi)
        boost = max(0.0, 1.0 - diff / 0.9)
        if fade_in < 1.0 and (int(t * 10) % 3 == 0 or _rng.random() > fade_in):
            continue
        _draw_unit(d, u, boost, t)
        if u.state == "melee" and u.foe is not None and int(t * 8) % 2:
            mx, my = (u.x + u.foe.x) / 2, (u.y + u.foe.y) / 2
            d.line([(mx - 4, my - 4), (mx + 4, my + 4)], fill=(255, 255, 255))
            d.line([(mx - 4, my + 4), (mx + 4, my - 4)], fill=(255, 255, 255))

    # ---- HUD text ----
    title = st.sector
    w = _tlen(title, 10)
    d.rectangle([CX - w / 2 - 3, 17, CX + w / 2 + 3, 29], fill=(0, 20, 10))
    _txt(d, (CX - w / 2, 18), title, HUD, 10)
    clock = "T+%03d" % int(min(st.sim_t, 999))
    phase = "DEPLOY" if st.sim_t < 3 else ("MELEE" if st.waaagh else "CONTACT")
    if st.winner is not None:
        phase = "RESOLVED"
    s2 = clock + "  " + phase
    w = _tlen(s2, 9)
    _txt(d, (CX - w / 2, 30), s2, HUD_DIM if st.sim_t < 3 else (60, 190, 110), 9)

    # force strength / losses at bottom
    ig_str = sum(u.n for u in st.units if u.side == 0 and u.active)
    ig_tot = sum(u.n0 for u in st.units if u.side == 0)
    ok_str = sum(u.n for u in st.units if u.side == 1 and u.active)
    ok_tot = sum(u.n0 for u in st.units if u.side == 1)
    y0 = 191
    d.rectangle([54, y0 - 2, 186, y0 + 22], fill=(0, 14, 8))
    _txt(d, (58, y0), "IMP", IG_COL, 9)
    _txt(d, (58, y0 + 10), "-%d" % st.loss[0], RED, 9)
    _txt(d, (164, y0), "ORK", ORK_COL, 9)
    lw = _tlen("-%d" % st.loss[1], 9)
    _txt(d, (182 - lw, y0 + 10), "-%d" % st.loss[1], RED, 9)
    bx0, bx1 = 80, 160
    d.rectangle([bx0, y0 + 1, bx1, y0 + 5], outline=HUD_DIM)
    d.rectangle([bx0, y0 + 13, bx1, y0 + 17], outline=HUD_DIM)
    if ig_tot:
        d.rectangle([bx0 + 1, y0 + 2, bx0 + 1 + (bx1 - bx0 - 2) * ig_str / ig_tot, y0 + 4], fill=IG_COL)
    if ok_tot:
        d.rectangle([bx1 - 1 - (bx1 - bx0 - 2) * ok_str / ok_tot, y0 + 14, bx1 - 1, y0 + 16], fill=ORK_COL)
    # event line
    if st.events:
        txt, age, col = st.events[0]
        if age < 6.0:
            k = 1.0 if age > 0.3 or int(age * 20) % 2 else 0.3
            k *= min(1.0, (6.0 - age) / 1.0)
            w = _tlen(txt, 9)
            _txt(d, (CX - w / 2, 216), txt, scale(col, k), 9)

    # victory banner
    if st.winner is not None:
        age = st.sim_t - st.end_t
        if age > 0.8:
            txt = "IMPERIAL VICTORY" if st.winner == 0 else "WAAAGH! OVERRUN"
            sub = "THE EMPEROR PROTECTS" if st.winner == 0 else "SECTOR LOST TO XENOS"
            col = IG_COL if st.winner == 0 else ORK_COL
            k = min(1.0, (age - 0.8) / 0.5)
            bw = 88 * k
            d.rectangle([CX - bw, 98, CX + bw, 140], fill=(0, 8, 4), outline=col)
            d.line([(CX - bw + 3, 101), (CX + bw - 3, 101)], fill=scale(col, 0.5))
            d.line([(CX - bw + 3, 137), (CX + bw - 3, 137)], fill=scale(col, 0.5))
            if k >= 1.0:
                f14 = font(14)
                w = _tlen(txt, 14)
                flash = 1.0 if int(age * 3) % 4 else 0.55
                _txt(d, (CX - w / 2, 105), txt, scale(col, flash), 14)
                w = _tlen(sub, 9)
                _txt(d, (CX - w / 2, 124), sub, AMBER, 9)
    return img
