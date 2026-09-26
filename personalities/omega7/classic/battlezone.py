"""COG-BATTLEZONE – periscope tank sim, green-phosphor vector edition.

Gameplay kept from the original: enemy tanks hunt the player (close to
engagement range, circle, back off when too close), respawn ahead when they
fall far behind, and the periscope sweeps toward the nearest tank and halts to
fight it; the gun fires when a tank sits in the reticle.

Visuals: true 3D wireframe tanks (tracks, hull, rotating turret, barrel, mast)
and pyramid/block obstacles with depth shading, a mountain range with a
crescent moon and an erupting volcano, a sweeping radar scope, enemy shells,
exploding tank fragments, cracked-glass hits, lives and score.
"""

from __future__ import annotations

import math
import random

import numpy as np
from PIL import Image, ImageDraw

from ..lore._common import CX, CY, Session, font, lerp_color, scale
from ._phosphor import (AMBER, GREEN, GREEN_DIM, GREEN_FAINT, GREEN_HI, GREEN_MID, RED,
                        Phosphor, blank)

NAME = "battlezone"

# ------------------------------------------------------------- cached text ---
_TXT = {}


def _mask(text, size):
    key = (text, size)
    m = _TXT.get(key)
    if m is None:
        if len(_TXT) > 300:
            _TXT.clear()
        f = font(size)
        box = f.getbbox(text)
        m = Image.new("L", (max(1, int(box[2]) + 2), max(1, int(box[3]) + 2)), 0)
        ImageDraw.Draw(m).text((0, 0), text, fill=255, font=f)
        _TXT[key] = m
    return m


def _txt(d, x, y, text, fill, size=9, align="l"):
    m = _mask(text, size)
    if align == "c":
        x -= m.width / 2
    elif align == "r":
        x -= m.width
    d.bitmap((int(round(x)), int(round(y))), m, fill=fill)


# ------------------------------------------------------------- constants ---
_rng = random.Random()
_session = Session()
_ph = Phosphor(decay=0.45, bloom=0.7)

F = 160.0          # focal length (px)
HOR = 122.0        # horizon line
CAMH = 15.0        # periscope height above the ground
NEAR = 6.0

SPAWN_ARC = 0.6        # half-angle (rad) ahead of the player where new tanks appear
ENGAGE_DIST = 70.0     # tanks close to this range, then circle the player
RECYCLE_DIST = 300.0   # tanks farther than this (or well behind) respawn ahead

# --- tank model (x right, y up, z forward)
_TV = np.array([
    # tracks / lower hull (0-3), fender line (4-7), upper deck (8-11)
    (-15, 0, -20), (15, 0, -20), (15, 0, 20), (-15, 0, 20),
    (-16, 6, -22), (16, 6, -22), (16, 6, 25), (-16, 6, 25),
    (-11, 10, -17), (11, 10, -17), (11, 10, 11), (-11, 10, 11),
], dtype=np.float64) * 0.72
_TE = [(0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4), (8, 9), (9, 10), (10, 11), (11, 8),
       (0, 4), (1, 5), (2, 6), (3, 7), (4, 8), (5, 9), (6, 10), (7, 11)]
# turret, around pivot (0, 10, -3): base 0-3, roof 4-7, barrel 8-11, mast 12-13
_UV = np.array([
    (-7, 0, -7), (7, 0, -7), (7, 0, 8), (-7, 0, 8),
    (-5, 5, -5), (5, 5, -5), (5, 5, 5), (-5, 5, 5),
    (-1.2, 2.5, 8), (1.2, 2.5, 8), (-1.2, 2.5, 30), (1.2, 2.5, 30),
    (0, 5, -3), (0, 10, -3),
], dtype=np.float64) * 0.72
_UE = [(0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4), (0, 4), (1, 5), (2, 6), (3, 7),
       (8, 10), (9, 11), (10, 11), (12, 13)]

_PYR_E = [(0, 1), (1, 2), (2, 3), (3, 0), (0, 4), (1, 4), (2, 4), (3, 4)]
_BOX_E = [(0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4), (0, 4), (1, 5), (2, 6), (3, 7)]

_S = {}


# ------------------------------------------------------------- geometry ---
def _to_world(local, ox, oz, h, oy=0.0):
    c, s = math.cos(h), math.sin(h)
    X = ox + local[:, 0] * c + local[:, 2] * s
    Z = oz - local[:, 0] * s + local[:, 2] * c
    return X, local[:, 1] + oy, Z


def _to_view(X, Y, Z):
    p = _S["player"]
    dx, dz = X - p["x"], Z - p["z"]
    c, s = math.cos(p["heading"]), math.sin(p["heading"])
    return dx * c - dz * s, Y, dx * s + dz * c


def _proj(rx, y, rz):
    return CX + rx * F / rz, HOR + (CAMH - y) * F / rz


def _depth_col(rz, base=GREEN_HI):
    k = max(0.22, min(1.0, 1.25 - rz / 260.0))
    return scale(base, k)


def _draw_edges(d, rx, ry, rz, edges, base, shake=(0, 0)):
    ox, oy = shake
    for a, b in edges:
        za, zb = rz[a], rz[b]
        if za < NEAR and zb < NEAR:
            continue
        xa, ya, xb, yb = rx[a], ry[a], rx[b], ry[b]
        if za < NEAR:
            t = (NEAR - za) / (zb - za)
            xa, ya, za = xa + (xb - xa) * t, ya + (yb - ya) * t, NEAR
        elif zb < NEAR:
            t = (NEAR - zb) / (za - zb)
            xb, yb, zb = xb + (xa - xb) * t, yb + (ya - yb) * t, NEAR
        pa = _proj(xa, ya, za)
        pb = _proj(xb, yb, zb)
        if max(pa[0], pb[0]) < -20 or min(pa[0], pb[0]) > 260:
            continue
        d.line([(pa[0] + ox, pa[1] + oy), (pb[0] + ox, pb[1] + oy)], fill=_depth_col((za + zb) * 0.5, base))


# ------------------------------------------------------------- world ---
def _relative(o):
    p = _S["player"]
    dx, dz = o["x"] - p["x"], o["z"] - p["z"]
    h = p["heading"]
    return dx * math.cos(h) - dz * math.sin(h), dx * math.sin(h) + dz * math.cos(h)


def _turn_toward(current, target, max_step):
    diff = (target - current + math.pi) % (2 * math.pi) - math.pi
    return current + max(-max_step, min(max_step, diff))


def _new_tank(ahead=True):
    """Spawn a tank in front of the player (or anywhere) heading roughly at them."""
    p = _S["player"]
    spread = SPAWN_ARC if ahead else math.pi
    ang = p["heading"] + _rng.uniform(-spread, spread)
    dist = _rng.uniform(110, 200)
    x = p["x"] + dist * math.sin(ang)
    z = p["z"] + dist * math.cos(ang)
    return {"x": x, "z": z, "heading": math.atan2(p["x"] - x, p["z"] - z) + _rng.uniform(-0.8, 0.8),
            "speed": _rng.uniform(0.3, 0.6), "turret_angle": _rng.uniform(0, math.pi * 2),
            "orbit": _rng.choice((-1, 1)), "cool": _rng.uniform(3.0, 6.0), "flash": 0.0,
            "id": _rng.randint(10, 99)}


def _new_obstacle(ahead):
    p = _S["player"]
    ang = p["heading"] + (_rng.uniform(-0.9, 0.9) if ahead else _rng.uniform(-math.pi, math.pi))
    dist = _rng.uniform(200, 340) if ahead else _rng.uniform(60, 340)
    x = p["x"] + dist * math.sin(ang)
    z = p["z"] + dist * math.cos(ang)
    kind = _rng.choice(("pyr", "pyr", "box", "tall"))
    if kind == "pyr":
        s, h = _rng.uniform(10, 14), _rng.uniform(18, 26)
        v = np.array([(-s, 0, -s), (s, 0, -s), (s, 0, s), (-s, 0, s), (0, h, 0)], dtype=np.float64)
        e = _PYR_E
    else:
        w = _rng.uniform(8, 12)
        h = w * (2.2 if kind == "tall" else 1.0)
        v = np.array([(-w, 0, -w), (w, 0, -w), (w, 0, w), (-w, 0, w),
                      (-w, h, -w), (w, h, -w), (w, h, w), (-w, h, w)], dtype=np.float64)
        e = _BOX_E
    X, Y, Z = _to_world(v, x, z, _rng.uniform(0, math.pi))
    return {"x": x, "z": z, "X": X, "Y": Y, "Z": Z, "e": e}


def _new_game(t):
    _S["player"] = {"x": 0.0, "z": 0.0, "heading": 0.0, "speed": 0.5}
    _S["tanks"] = [_new_tank(), _new_tank(), _new_tank(ahead=False)]
    _S["obst"] = [_new_obstacle(False) for _ in range(11)]
    _S.update(shells=[], eshells=[], frags=[], sparks=[], score=0, lives=3, last_shot=t - 1.5,
              hit_t=None, cracks=[], state="play", t_state=t, enemy_gate=t + 6.0, kills=0, recoil=0.0, msg=None)
    _S["ground"] = [[_rng.uniform(-300, 300), _rng.uniform(-300, 300)] for _ in range(70)]


def _reset(t):
    _S.clear()
    _S["hi"] = _rng.choice((48000, 61500, 75000))
    _S["games"] = 1
    _new_game(t)
    # mountain ridge (bearing, height) at infinity
    n = 96
    pts = []
    for i in range(n):
        a = i * 2 * math.pi / n
        h = 4 + 7 * abs(math.sin(a * 3.0 + 1.3)) + _rng.uniform(0, 5)
        if i % 7 == 0:
            h += _rng.uniform(10, 24)
        pts.append([a, h])
    vi = _rng.randrange(n)
    _S["volcano"] = pts[vi][0]
    for k in range(-3, 4):
        pts[(vi + k) % n][1] = 36 - abs(k) * 9
    pts[vi][1] = 31  # crater notch
    _S["ridge_a"] = np.array([p[0] for p in pts])
    _S["ridge_h"] = np.array([p[1] for p in pts])
    _S["moon"] = (_S["volcano"] + _rng.choice((-1, 1)) * _rng.uniform(1.4, 2.6)) % (2 * math.pi)
    _S["stars"] = [(_rng.uniform(0, 2 * math.pi), _rng.uniform(34, 60)) for _ in range(34)]
    _S["lava"] = []
    _S["radar_blips"] = {}
    _ph.reset()


def _msg(text, col, t, dur=2.0):
    _S["msg"] = (text, col, t, dur)


# ------------------------------------------------------------- events ---
def _explode_tank(tank, t):
    tv = _TV.copy()
    X, Y, Z = _to_world(tv, tank["x"], tank["z"], tank["heading"])
    for a, b in _TE[::2] + _TE[12:]:
        mx, my, mz = (X[a] + X[b]) / 2, (Y[a] + Y[b]) / 2, (Z[a] + Z[b]) / 2
        hx, hy, hz = (X[b] - X[a]) / 2, (Y[b] - Y[a]) / 2, (Z[b] - Z[a]) / 2
        ang = math.atan2(mx - tank["x"], mz - tank["z"])
        sp = _rng.uniform(0.5, 1.6)
        _S["frags"].append([mx, my, mz, hx, hy, hz, math.sin(ang) * sp, _rng.uniform(1.0, 2.6),
                            math.cos(ang) * sp, _rng.uniform(-0.2, 0.2), 1.0])
    # the turret flies high
    _S["frags"].append([tank["x"], 9, tank["z"], 6, 0, 0, _rng.uniform(-0.5, 0.5), 3.4, _rng.uniform(-0.5, 0.5), 0.3, 1.0])
    _S["frags"].append([tank["x"], 9, tank["z"], 0, 0, 10, _rng.uniform(-0.5, 0.5), 3.0, _rng.uniform(-0.5, 0.5), -0.25, 1.0])
    _S["boom"] = (tank["x"], tank["z"], t)


def _crack(t):
    cx, cy = CX + _rng.uniform(-40, 40), CY + _rng.uniform(-30, 30)
    lines = []
    n = _rng.randint(9, 13)
    for i in range(n):
        a = i * 2 * math.pi / n + _rng.uniform(-0.25, 0.25)
        x, y = cx, cy
        L = _rng.uniform(70, 150)
        seg = 0.0
        while seg < L:
            st = _rng.uniform(8, 18)
            a += _rng.uniform(-0.35, 0.35)
            nx, ny = x + st * math.cos(a), y + st * math.sin(a)
            lines.append((x, y, nx, ny, 1.0 - seg / L * 0.6))
            if _rng.random() < 0.18:
                ba = a + _rng.choice((-1, 1)) * _rng.uniform(0.5, 1.0)
                lines.append((nx, ny, nx + 14 * math.cos(ba), ny + 14 * math.sin(ba), 0.6))
            x, y = nx, ny
            seg += st
    # concentric shatter rings
    for r in (9, 20):
        pts = []
        for i in range(n):
            a = i * 2 * math.pi / n
            rr = r * _rng.uniform(0.8, 1.2)
            pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
        for i in range(n):
            if _rng.random() < 0.8:
                p1, p2 = pts[i], pts[(i + 1) % n]
                lines.append((p1[0], p1[1], p2[0], p2[1], 0.9))
    _S["cracks"] = lines
    _S["crack_c"] = (cx, cy)


def _player_hit(t):
    _S["lives"] -= 1
    _S["hit_t"] = t
    _crack(t)
    if _S["lives"] <= 0:
        _S["state"] = "over"
        _S["msg"] = None
    else:
        _S["state"] = "hit"
        _msg("HULL BREACH", RED, t, 3.0)
    _S["t_state"] = t


# ------------------------------------------------------------- update ---
def _update(k, t):
    st = _S["state"]
    p = _S["player"]

    if st == "hit":
        if t - _S["t_state"] > 3.4:
            # re-emerge: enemies regroup ahead at range, cracks clear
            _S["tanks"] = [_new_tank() for _ in range(len(_S["tanks"]))]
            _S["eshells"] = []
            _S["state"] = "play"
            _S["cracks"] = []
            _S["enemy_gate"] = t + 6.0
            _msg("PERISCOPE RESTORED", GREEN_HI, t)
        _update_particles(k, t)
        return
    if st == "over":
        if t - _S["t_state"] > 7.0:
            _S["hi"] = max(_S["hi"], _S["score"])
            _S["games"] += 1
            _new_game(t)
            _msg("NEW ENGAGEMENT", GREEN_HI, t)
        _update_particles(k, t)
        return

    tanks = _S["tanks"]
    # 1. periscope sweeps toward the nearest tank; halt and fight once it is in range
    near_dist = 1e9
    nearest = None
    if tanks:
        nearest = min(tanks, key=lambda tk: math.hypot(tk["x"] - p["x"], tk["z"] - p["z"]))
        bearing = math.atan2(nearest["x"] - p["x"], nearest["z"] - p["z"])
        p["heading"] = _turn_toward(p["heading"], bearing, 0.012 * k)
        near_dist = math.hypot(nearest["x"] - p["x"], nearest["z"] - p["z"])
        p["speed"] = 0.5 if near_dist > ENGAGE_DIST + 20 else 0.0
    p["heading"] += math.sin(t * 0.3) * 0.004 * k
    p["x"] += math.sin(p["heading"]) * p["speed"] * k
    p["z"] += math.cos(p["heading"]) * p["speed"] * k
    _S["nearest"] = nearest
    _S["near_dist"] = near_dist

    # 2. enemy tanks hunt the player
    in_reticle = None
    for i, tank in enumerate(tanks):
        to_player = math.atan2(p["x"] - tank["x"], p["z"] - tank["z"])
        dist = math.hypot(p["x"] - tank["x"], p["z"] - tank["z"])
        if dist > ENGAGE_DIST:
            desired = to_player
        elif dist > ENGAGE_DIST * 0.6:
            desired = to_player + tank["orbit"] * math.pi / 2
        else:
            desired = to_player + math.pi  # too close — back off
        tank["heading"] = _turn_toward(tank["heading"], desired, 0.02 * k)
        tank["turret_angle"] = _turn_toward(tank["turret_angle"], to_player, 0.03 * k)
        tank["x"] += math.sin(tank["heading"]) * tank["speed"] * k
        tank["z"] += math.cos(tank["heading"]) * tank["speed"] * k
        tank["flash"] = max(0.0, tank["flash"] - 0.1 * k)

        rx, rz = _relative(tank)
        if dist > RECYCLE_DIST or rz < -40.0:
            tanks[i] = tank = _new_tank()
            rx, rz = _relative(tank)
        if rz > 5.0 and abs(rx * F / rz) < 25:
            in_reticle = tank

        # enemy gunnery: turret aligned and within range
        tank["cool"] -= k / 30.0
        aligned = abs((to_player - tank["turret_angle"] + math.pi) % (2 * math.pi) - math.pi) < 0.08
        if tank["cool"] <= 0 and aligned and dist < 140 and not _S["eshells"] and t > _S["enemy_gate"]:
            tank["cool"] = _rng.uniform(7.0, 13.0)
            tank["flash"] = 1.0
            _S["enemy_gate"] = t + _rng.uniform(10.0, 16.0)
            ta = tank["turret_angle"]
            bx, bz = tank["x"] + math.sin(ta) * 20, tank["z"] + math.cos(ta) * 20
            miss = 0.0 if _rng.random() < 0.28 else _rng.uniform(9, 18) * _rng.choice((-1, 1))
            ux, uz = p["x"] - bx, p["z"] - bz
            ul = math.hypot(ux, uz) or 1.0
            tx = p["x"] + uz / ul * miss
            tz = p["z"] - ux / ul * miss
            _S["fired"] = _S.get("fired", 0) + 1
            L = math.hypot(tx - bx, tz - bz) or 1.0
            _S["eshells"].append({"x": bx, "z": bz, "y": 9.0, "vx": (tx - bx) / L * 5.0,
                                  "vz": (tz - bz) / L * 5.0, "vy": (CAMH - 3 - 9.0) / L * 5.0, "life": L / 5.0 + 20})

    _S["in_reticle"] = in_reticle

    # 3. our gun: fires when a tank is in the reticle (or the occasional speculative round)
    if (in_reticle is not None or _rng.random() < 0.01 * k) and (t - _S["last_shot"] > 3.0):
        _S["last_shot"] = t
        _S["recoil"] = 1.0
        _S["shells"].append({"x": p["x"] + math.sin(p["heading"]) * 10, "z": p["z"] + math.cos(p["heading"]) * 10,
                             "h": p["heading"], "d": 10.0})

    keep = []
    for sh in _S["shells"]:
        step = 12.0 * k
        sh["x"] += math.sin(sh["h"]) * step
        sh["z"] += math.cos(sh["h"]) * step
        sh["d"] += step
        hit = None
        for tank in tanks:
            if math.hypot(sh["x"] - tank["x"], sh["z"] - tank["z"]) < 18.0:
                hit = tank
                break
        if hit is not None:
            _S["score"] += 1500
            _S["kills"] += 1
            _explode_tank(hit, t)
            tanks.remove(hit)
            tanks.append(_new_tank())
            _msg(f"TARGET {hit['id']} DESTROYED", AMBER, t)
            if _S["kills"] % 5 == 0 and len(tanks) < 4:
                tanks.append(_new_tank())
                _msg("ENEMY REINFORCEMENTS", RED, t, 2.4)
        elif sh["d"] < 260.0:
            keep.append(sh)
    _S["shells"] = keep

    keep = []
    for es in _S["eshells"]:
        es["x"] += es["vx"] * k
        es["z"] += es["vz"] * k
        es["y"] += es["vy"] * k
        es["life"] -= k
        dd = math.hypot(es["x"] - p["x"], es["z"] - p["z"])
        if dd < 6.0:
            _player_hit(t)
            _S["eshells"] = []
            return
        if es["life"] > 0:
            keep.append(es)
        else:
            _msg("ROUND WIDE", GREEN_MID, t, 1.2)
    _S["eshells"] = keep

    # 4. obstacles recycle ahead
    for i, o in enumerate(_S["obst"]):
        rx, rz = _relative(o)
        if rz < -60 or math.hypot(o["x"] - p["x"], o["z"] - p["z"]) > 360:
            _S["obst"][i] = _new_obstacle(True)
    for g in _S["ground"]:
        dx, dz = g[0] - p["x"], g[1] - p["z"]
        if dx * dx + dz * dz > 300 * 300:
            a = p["heading"] + _rng.uniform(-1.0, 1.0)
            r = _rng.uniform(150, 290)
            g[0], g[1] = p["x"] + r * math.sin(a), p["z"] + r * math.cos(a)
    _S["recoil"] = max(0.0, _S["recoil"] - 0.12 * k)
    _update_particles(k, t)


def _update_particles(k, t):
    keep = []
    for f in _S["frags"]:
        f[0] += f[6] * k
        f[1] += f[7] * k
        f[2] += f[8] * k
        f[7] -= 0.12 * k
        c, s = math.cos(f[9] * k), math.sin(f[9] * k)
        f[3], f[4] = f[3] * c - f[4] * s, f[3] * s + f[4] * c
        if f[1] < 0:
            f[1] = 0
            f[7] = -f[7] * 0.3
            f[6] *= 0.6
            f[8] *= 0.6
        f[10] -= 0.012 * k
        if f[10] > 0:
            keep.append(f)
    _S["frags"] = keep
    # volcano ejecta (bearing offset, height, v_bearing, v_height, life)
    if _rng.random() < 0.35 * k:
        _S["lava"].append([0.0, 33.0, _rng.uniform(-0.004, 0.004), _rng.uniform(0.6, 1.3), 1.0])
    keep = []
    for l in _S["lava"]:
        l[0] += l[2] * k
        l[1] += l[3] * k
        l[3] -= 0.035 * k
        l[4] -= 0.012 * k
        if l[1] > 24 and l[4] > 0:
            keep.append(l)
    _S["lava"] = keep


# ------------------------------------------------------------- drawing ---
def _bearing_x(rel):
    return CX + math.tan(rel) * F


def _draw_scenery(d, sh):
    p = _S["player"]
    head = p["heading"]
    ox, oy = sh
    # stars
    for a, e in _S["stars"]:
        rel = (a - head + math.pi) % (2 * math.pi) - math.pi
        if abs(rel) < 0.75:
            d.point((_bearing_x(rel) + ox, HOR - e + oy), fill=GREEN_DIM)
    # moon (crescent)
    rel = (_S["moon"] - head + math.pi) % (2 * math.pi) - math.pi
    if abs(rel) < 0.8:
        mx, my = _bearing_x(rel) + ox, HOR - 50 + oy
        d.arc([mx - 9, my - 9, mx + 9, my + 9], 77, 283, fill=GREEN_HI)
        d.arc([mx - 5, my - 9, mx + 13, my + 9], 103, 257, fill=GREEN_MID)
    # ridge
    rel = (_S["ridge_a"] - head + math.pi) % (2 * math.pi) - math.pi
    order = np.argsort(rel)
    rel_s = rel[order]
    h_s = _S["ridge_h"][order]
    vis = np.abs(rel_s) < 0.9
    xs = CX + np.tan(rel_s[vis]) * F + ox
    ys = HOR - h_s[vis] + oy
    pts = list(zip(xs.tolist(), ys.tolist()))
    if len(pts) > 1:
        d.line(pts, fill=GREEN)
        # secondary ridge-lines for depth
        for i in range(0, len(pts) - 1, 2):
            x0, y0 = pts[i]
            if y0 < HOR - 10:
                d.line([(x0, y0), (x0 + 6, HOR - (HOR - y0) * 0.45)], fill=GREEN_DIM)
    # volcano ejecta
    rel = (_S["volcano"] - head + math.pi) % (2 * math.pi) - math.pi
    if abs(rel) < 0.85:
        vx = _bearing_x(rel) + ox
        for l in _S["lava"]:
            x = vx + l[0] * F * 3
            y = HOR - l[1] + oy
            d.point((x, y), fill=AMBER if l[4] > 0.75 else scale(GREEN_HI, l[4]))
    d.line([(0, HOR + oy), (240, HOR + oy)], fill=GREEN_MID)


def _draw_world(d, sh):
    p = _S["player"]
    # ground rubble dots for motion parallax
    for g in _S["ground"]:
        dx, dz = g[0] - p["x"], g[1] - p["z"]
        c, s = math.cos(p["heading"]), math.sin(p["heading"])
        rx, rz = dx * c - dz * s, dx * s + dz * c
        if rz > 10:
            x, y = _proj(rx, 0.0, rz)
            if 0 <= x < 240:
                d.point((x + sh[0], y + sh[1]), fill=GREEN_DIM if rz < 120 else GREEN_FAINT)
    # obstacles
    for o in _S["obst"]:
        rx, ry, rz = _to_view(o["X"], o["Y"], o["Z"])
        if rz.max() < NEAR:
            continue
        _draw_edges(d, rx, ry, rz, o["e"], GREEN, sh)
    # tanks
    for tank in _S["tanks"]:
        rx0, rz0 = _relative(tank)
        if rz0 < -30:
            continue
        X, Y, Z = _to_world(_TV, tank["x"], tank["z"], tank["heading"])
        rx, ry, rz = _to_view(X, Y, Z)
        _draw_edges(d, rx, ry, rz, _TE, GREEN_HI, sh)
        # turret pivot (0,10,-3) in hull frame
        c, s = math.cos(tank["heading"]), math.sin(tank["heading"])
        px, pz = tank["x"] + (-2.2) * s, tank["z"] + (-2.2) * c
        UX, UY, UZ = _to_world(_UV, px, pz, tank["turret_angle"], oy=7.2)
        rx, ry, rz = _to_view(UX, UY, UZ)
        _draw_edges(d, rx, ry, rz, _UE, GREEN_HI, sh)
        if tank["flash"] > 0 and rz[10] > NEAR:
            fx, fy = _proj((rx[10] + rx[11]) / 2, ry[10], rz[10])
            r = 3 + 6 * tank["flash"]
            for q in range(6):
                a = q * math.pi / 3
                d.line([(fx + sh[0], fy + sh[1]), (fx + r * math.cos(a) + sh[0], fy + r * math.sin(a) + sh[1])], fill=AMBER)
    # fragments
    for f in _S["frags"]:
        xs = np.array([f[0] - f[3], f[0] + f[3]])
        ys = np.array([f[1] - f[4], f[1] + f[4]])
        zs = np.array([f[2] - f[5], f[2] + f[5]])
        rx, ry, rz = _to_view(xs, ys, zs)
        _draw_edges(d, rx, ry, rz, [(0, 1)], scale(GREEN_HI, f[10]), sh)
    # explosion flash ring on the ground
    boom = _S.get("boom")
    if boom is not None:
        bx, bz, bt = boom
        age = _S["now"] - bt
        if age < 0.9:
            R = 6 + age * 60
            pts = []
            for q in range(14):
                a = q * 2 * math.pi / 14
                pts.append((bx + R * math.cos(a), bz + R * math.sin(a)))
            ex = np.array([q[0] for q in pts])
            ez = np.array([q[1] for q in pts])
            rx, ry, rz = _to_view(ex, np.full(14, 1.0), ez)
            _draw_edges(d, rx, ry, rz, [(q, (q + 1) % 14) for q in range(14)], scale(AMBER, 1 - age / 0.9), sh)
    # our shells
    for s_ in _S["shells"]:
        dd = s_["d"]
        y = 8 + dd * 0.02
        x, yy = CX, HOR + (CAMH - y) * F / dd
        r = max(1.0, 18 / dd * 4)
        d.polygon([(x + sh[0], yy - r + sh[1]), (x + r + sh[0], yy + sh[1]), (x + sh[0], yy + r + sh[1]),
                   (x - r + sh[0], yy + sh[1])], outline=GREEN_HI)
    # enemy shells
    for es in _S["eshells"]:
        rx, rz = _relative(es)
        if rz > NEAR:
            x, y = _proj(rx, es["y"], rz)
            r = max(1.0, min(9.0, 60 / rz))
            d.ellipse([x - r + sh[0], y - r + sh[1], x + r + sh[0], y + r + sh[1]], outline=AMBER)
            d.point((x + sh[0], y + sh[1]), fill=GREEN_HI)


def _draw_radar(d, t):
    rcx, rcy, R = CX, 36, 21
    d.ellipse([rcx - R, rcy - R, rcx + R, rcy + R], outline=GREEN_MID)
    d.ellipse([rcx - R / 2, rcy - R / 2, rcx + R / 2, rcy + R / 2], outline=GREEN_FAINT)
    # field-of-view wedge
    for sgn in (-1, 1):
        d.line([(rcx, rcy), (rcx + sgn * R * 0.6, rcy - R * 0.8)], fill=GREEN_DIM)
    sweep = (t * 2.6) % (2 * math.pi)
    d.line([(rcx, rcy), (rcx + R * math.sin(sweep), rcy - R * math.cos(sweep))], fill=GREEN)
    for q in range(1, 5):
        a = sweep - q * 0.12
        d.line([(rcx, rcy), (rcx + R * math.sin(a), rcy - R * math.cos(a))], fill=scale(GREEN_DIM, 1 - q / 5))
    blips = _S["radar_blips"]
    for tank in _S["tanks"]:
        rx, rz = _relative(tank)
        a = math.atan2(rx, rz) % (2 * math.pi)
        dist = math.hypot(rx, rz)
        if (sweep - a) % (2 * math.pi) < 0.25:
            blips[id(tank)] = (rx, rz, t)
    for key in list(blips):
        rx, rz, t0 = blips[key]
        age = t - t0
        if age > 2.4:
            del blips[key]
            continue
        dd = math.hypot(rx, rz)
        k = min(1.0, (R - 2) / max(dd * 0.09, 1e-3))
        bx, by = rcx + rx * 0.09 * min(1.0, k), rcy - rz * 0.09 * min(1.0, k)
        d.rectangle([bx - 1, by - 1, bx + 1, by + 1], fill=scale(GREEN_HI, 1 - age / 2.4))
    d.point((rcx, rcy), fill=GREEN_HI)


def _draw_reticle(d, t):
    lock = _S.get("in_reticle") is not None
    col = AMBER if lock else GREEN
    g = 4 if lock else 10
    y0, y1 = CY - 26, CY + 26
    d.line([(CX, y0 - 8), (CX, CY - g - 6)], fill=col)
    d.line([(CX - 16, y0), (CX + 16, y0)], fill=col)
    d.line([(CX - 16, y0), (CX - 16, y0 + 4)], fill=col)
    d.line([(CX + 16, y0), (CX + 16, y0 + 4)], fill=col)
    d.line([(CX, y1 + 8), (CX, CY + g + 6)], fill=col)
    d.line([(CX - 16, y1), (CX + 16, y1)], fill=col)
    d.line([(CX - 16, y1), (CX - 16, y1 - 4)], fill=col)
    d.line([(CX + 16, y1), (CX + 16, y1 - 4)], fill=col)
    if lock and int(t * 6) % 2 == 0:
        _txt(d, CX, y1 + 5, "TARGET LOCK", AMBER, 9, "c")


def _draw_hud(d, t):
    _txt(d, CX - 30, 22, "SCORE", GREEN_MID, 9, "r")
    _txt(d, CX - 30, 33, f"{_S['score']:06d}", AMBER, 9, "r")
    _txt(d, CX + 30, 22, "HI", GREEN_MID, 9, "l")
    _txt(d, CX + 30, 33, f"{max(_S['hi'], _S['score']):06d}", GREEN, 9, "l")
    # lives as tiny tank icons
    for i in range(max(0, _S["lives"])):
        x, y = CX + 34 + i * 12, 50
        d.line([(x - 4, y), (x + 4, y), (x + 3, y - 2), (x - 3, y - 2), (x - 4, y)], fill=GREEN)
        d.rectangle([x - 1, y - 4, x + 1, y - 2], outline=GREEN)
        d.line([(x + 1, y - 3), (x + 5, y - 3)], fill=GREEN)
    _txt(d, CX - 34, 45, f"K {_S['kills']:02d}", GREEN_MID, 9, "r")

    st = _S["state"]
    if st == "play":
        nd = _S.get("near_dist", 1e9)
        near = _S.get("nearest")
        if near is not None:
            rx, rz = _relative(near)
            off = rz <= 5 or abs(rx / max(rz, 1e-3)) > 0.72
            if off and int(t * 3) % 2 == 0:
                _txt(d, CX, 64, "ENEMY TO " + ("LEFT" if rx < 0 else "RIGHT"), RED, 9, "c")
            elif nd < 150 and not off and int(t * 2) % 3 != 0:
                _txt(d, CX, 64, "ENEMY IN RANGE", RED, 9, "c")
    hdg = int(math.degrees(_S["player"]["heading"]) % 360)
    rng = int(min(_S.get("near_dist", 999), 999))
    _txt(d, CX - 56, 180, f"HDG {hdg:03d}", GREEN_MID, 9, "l")
    _txt(d, CX + 56, 180, f"RNG {rng:03d}", GREEN_MID, 9, "r")
    _txt(d, CX, 194, "COG-BATTLEZONE", GREEN_DIM, 9, "c")
    spd = "ADVANCE" if _S["player"]["speed"] > 0 else "HALT - ENGAGE"
    _txt(d, CX, 205, spd, GREEN_DIM if _S["player"]["speed"] > 0 else GREEN_MID, 9, "c")

    m = _S["msg"]
    if m is not None:
        text, col, t0, dur = m
        age = t - t0
        if age < dur:
            if age > 0.3 or int(age * 16) % 2 == 0:
                _txt(d, CX, 166, text, col, 9, "c")
        else:
            _S["msg"] = None


def _draw_cracks(d, t):
    age = t - (_S["hit_t"] or t)
    if age < 0.12:
        d.rectangle([0, 0, 239, 239], fill=scale(GREEN_MID, 0.45))
    k = 1.0 if _S["state"] == "over" else max(0.0, 1.0 - max(0.0, age - 2.2) / 1.2)
    if k <= 0:
        return
    for x0, y0, x1, y1, b in _S["cracks"]:
        d.line([(x0, y0), (x1, y1)], fill=scale(GREEN_HI, b * k))
    if _S["state"] == "over":
        d.rectangle([CX - 52, CY - 12, CX + 52, CY + 24], fill=(0, 0, 0), outline=RED)
        _txt(d, CX, CY - 8, "GAME OVER", scale(RED, 0.6 + 0.4 * math.sin(age * 5)), 16, "c")
        _txt(d, CX, CY + 12, f"FINAL {_S['score']:06d}", AMBER, 9, "c")


def render(bezel, mask, now: float) -> Image.Image:
    if _session.fresh(now) or not _S:
        _reset(now)
        _S["prev"] = now
    k = max(0.0, min(3.0, (now - _S["prev"]) * 30.0))
    _S["prev"] = now
    _S["now"] = now
    _update(k, now)

    img = blank()
    d = ImageDraw.Draw(img)
    shake = (0, 0)
    if _S["recoil"] > 0:
        shake = (0, int(round(_S["recoil"] * 3)))
    if _S["state"] in ("hit", "over") and _S["hit_t"] is not None and now - _S["hit_t"] < 0.6:
        a = (0.6 - (now - _S["hit_t"])) * 10
        shake = (int(_rng.uniform(-a, a)), int(_rng.uniform(-a, a)))
    _draw_scenery(d, shake)
    _draw_world(d, shake)
    _draw_radar(d, now)
    if _S["state"] == "play":
        _draw_reticle(d, now)
    if _S["recoil"] > 0.6:
        for q in range(5):
            a = math.pi + q * math.pi / 4
            d.line([(CX, 200), (CX + 18 * math.cos(a) * _S["recoil"], 200 + 12 * math.sin(a) * _S["recoil"])], fill=GREEN_HI)
    _draw_hud(d, now)
    if _S["cracks"]:
        _draw_cracks(d, now)
    return _ph.compose(img)
