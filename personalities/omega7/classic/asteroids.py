"""COG-ASTEROIDS – vector arcade, green-phosphor cogitator edition.

A servitor-piloted ship hunts rocks with lead-computed shots, dodges incoming
debris (or warps out through hyperspace), fights occasional xenos raiders and
clears waves of ever-faster asteroids. The play field is circular and wraps
edge-to-opposite-edge so everything stays on the round eye.
"""

from __future__ import annotations

import math
import random

from PIL import Image, ImageDraw

from ..lore._common import CX, CY, Session, font, scale
from ._phosphor import (AMBER, GREEN, GREEN_DIM, GREEN_FAINT, GREEN_HI, GREEN_MID, RED,
                        Phosphor, blank)

NAME = "asteroids"

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


# ------------------------------------------------------------- state ---
_rng = random.Random()
_session = Session()
_ph = Phosphor(decay=0.55, bloom=0.75)

RA = 108.0                      # arena radius (wraps to the opposite side)
SIZES = {3: 16.0, 2: 9.0, 1: 5.0}
POINTS = {3: 20, 2: 50, 1: 100}
BULLET_SPD = 230.0
TURN = 5.5

_S = {}


def _wrap(o):
    x, y = o["x"] - CX, o["y"] - CY
    r = math.hypot(x, y)
    if r > RA:
        k = (RA - 1.0) / r
        o["x"], o["y"] = CX - x * k, CY - y * k


def _rock_poly(r):
    n = _rng.randint(8, 11)
    pts = []
    for i in range(n):
        a = i * 2 * math.pi / n + _rng.uniform(-0.15, 0.15)
        rr = r * _rng.uniform(0.72, 1.18)
        pts.append((rr * math.cos(a), rr * math.sin(a)))
    return pts


def _new_rock(size, x, y, spd, materialise=0.0):
    a = _rng.uniform(0, 2 * math.pi)
    return {"x": x, "y": y, "vx": math.cos(a) * spd, "vy": math.sin(a) * spd, "size": size,
            "r": SIZES[size], "rot": _rng.uniform(0, 6.3), "spin": _rng.uniform(-1.4, 1.4),
            "poly": _rock_poly(SIZES[size]), "mat": materialise}


def _new_ship():
    return {"x": CX, "y": CY, "vx": 0.0, "vy": 0.0, "a": -math.pi / 2, "thrust": 0.0,
            "inv": 2.5, "alive": True}


def _reset_game(t):
    _S.update(score=0, lives=3, wave=0, next_life=10000, ship=_new_ship(), rocks=[], bullets=[],
              ubullets=[], sparks=[], debris=[], rings=[], ufo=None, state="wave_in", t_state=t,
              last_shot=0.0, respawn_at=None, hyper_cd=0.0, msg=None, ufo_next=t + _rng.uniform(22, 35),
              hits=0, shots=0)


def _reset(t):
    _S.clear()
    _S["hi"] = _rng.choice((7450, 9820, 12040, 15530))
    _S["game"] = 1
    _S["stars"] = [(_rng.uniform(-1, 1), _rng.uniform(-1, 1), _rng.choice((0.15, 0.35))) for _ in range(46)]
    _S["star_off"] = [0.0, 0.0]
    _reset_game(t)
    _ph.reset()


def _msg(text, col, t, dur=2.2):
    _S["msg"] = (text, col, t, dur)


def _start_wave(t):
    _S["wave"] += 1
    w = _S["wave"]
    n = min(3 + w, 8)
    spd = 16 + 4 * min(w, 8)
    rocks = []
    ship = _S["ship"]
    for i in range(n):
        a = i * 2 * math.pi / n + _rng.uniform(-0.3, 0.3)
        r = _rng.uniform(70, 96)
        x, y = CX + r * math.cos(a), CY + r * math.sin(a)
        if math.hypot(x - ship["x"], y - ship["y"]) < 45:
            x, y = CX - (x - CX), CY - (y - CY)
        rocks.append(_new_rock(3, x, y, spd * _rng.uniform(0.7, 1.3), materialise=1.0 + i * 0.12))
    _S["rocks"] = rocks
    _msg(f"WAVE {w:02d}", GREEN_HI, t, 2.0)


def _burst(x, y, n, spd, col=GREEN_HI, life=1.0):
    for _ in range(n):
        a = _rng.uniform(0, 2 * math.pi)
        s = _rng.uniform(0.2, 1.0) * spd
        _S["sparks"].append([x, y, math.cos(a) * s, math.sin(a) * s, life * _rng.uniform(0.6, 1.0), col])


def _debris_from_poly(o, pts, col, spd=35.0):
    n = len(pts)
    for i in range(n):
        p1, p2 = pts[i], pts[(i + 1) % n]
        mx, my = (p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2
        hx, hy = (p2[0] - p1[0]) / 2, (p2[1] - p1[1]) / 2
        a = math.atan2(my - o["y"], mx - o["x"])
        s = _rng.uniform(0.4, 1.0) * spd
        _S["debris"].append([mx, my, hx, hy, o.get("vx", 0) * 0.4 + math.cos(a) * s,
                             o.get("vy", 0) * 0.4 + math.sin(a) * s, _rng.uniform(-4, 4), 1.0, col])


def _rock_world(rk):
    c, s = math.cos(rk["rot"]), math.sin(rk["rot"])
    return [(rk["x"] + px * c - py * s, rk["y"] + px * s + py * c) for px, py in rk["poly"]]


def _add_score(n, t):
    _S["score"] += n
    if _S["score"] >= _S["next_life"]:
        _S["next_life"] += 10000
        _S["lives"] = min(6, _S["lives"] + 1)
        _msg("BLESSED REPAIR +1", AMBER, t)
    _S["hi"] = max(_S["hi"], _S["score"])


def _kill_rock(rk, t, from_ship=True):
    if rk in _S["rocks"]:
        _S["rocks"].remove(rk)
    if from_ship:
        _add_score(POINTS[rk["size"]], t)
    _debris_from_poly(rk, _rock_world(rk), GREEN, 30 + 10 * (4 - rk["size"]))
    _burst(rk["x"], rk["y"], 6 + 3 * rk["size"], 70)
    if rk["size"] > 1:
        spd = math.hypot(rk["vx"], rk["vy"]) * 1.35 + 8
        for _ in range(2):
            _S["rocks"].append(_new_rock(rk["size"] - 1, rk["x"] + _rng.uniform(-3, 3),
                                         rk["y"] + _rng.uniform(-3, 3), spd))


def _kill_ship(t):
    sh = _S["ship"]
    sh["alive"] = False
    _debris_from_poly(sh, _ship_pts(sh), GREEN_HI, 28)
    _burst(sh["x"], sh["y"], 26, 90, GREEN_HI, 1.4)
    _burst(sh["x"], sh["y"], 8, 60, AMBER, 1.0)
    _S["rings"].append((sh["x"], sh["y"], t, 1))
    _S["lives"] -= 1
    if _S["lives"] <= 0:
        _S["state"] = "over"
        _S["t_state"] = t
        _msg("GAME OVER", RED, t, 6.0)
    else:
        _S["respawn_at"] = t + 2.6
        _msg("SERVITOR LOST", RED, t)


def _ship_pts(sh):
    a = sh["a"]
    x, y = sh["x"], sh["y"]
    return [(x + 9 * math.cos(a), y + 9 * math.sin(a)),
            (x + 7 * math.cos(a + 2.45), y + 7 * math.sin(a + 2.45)),
            (x + 3.5 * math.cos(a + math.pi), y + 3.5 * math.sin(a + math.pi)),
            (x + 7 * math.cos(a - 2.45), y + 7 * math.sin(a - 2.45))]


def _angdiff(a, b):
    return (a - b + math.pi) % (2 * math.pi) - math.pi


def _ai(dt, t):
    sh = _S["ship"]
    sh["thrust"] = 0.0
    rocks = [r for r in _S["rocks"] if r["mat"] <= 0]
    targets = list(rocks)
    ufo = _S["ufo"]
    # --- danger assessment: closest approach within 1.2 s
    danger = None
    for o in rocks + ([ufo] if ufo else []):
        rx, ry = o["x"] - sh["x"], o["y"] - sh["y"]
        vx, vy = o["vx"] - sh["vx"], o["vy"] - sh["vy"]
        vv = vx * vx + vy * vy
        tc = -(rx * vx + ry * vy) / vv if vv > 1e-6 else 0.0
        tc = max(0.0, tc)
        if tc > 1.2:
            continue
        cx, cy = rx + vx * tc, ry + vy * tc
        miss = math.hypot(cx, cy)
        rad = o.get("r", 8) + 10
        if miss < rad and (danger is None or tc < danger[1]):
            danger = (o, tc, rx, ry, vx, vy)
    for ub in _S["ubullets"]:
        if math.hypot(ub[0] - sh["x"], ub[1] - sh["y"]) < 22:
            danger = danger or ({"x": ub[0], "y": ub[1], "r": 2}, 0.1, ub[0] - sh["x"], ub[1] - sh["y"], ub[2], ub[3])

    if danger is not None and danger[1] < 0.35 and _S["hyper_cd"] <= 0 and math.hypot(danger[2], danger[3]) < danger[0].get("r", 5) + 16:
        _hyperspace(t)
        return
    if danger is not None:
        o, tc, rx, ry, vx, vy = danger
        # thrust perpendicular to the threat's approach, away from its line
        pa = math.atan2(vy, vx) + math.pi / 2
        if math.cos(pa) * rx + math.sin(pa) * ry > 0:
            pa += math.pi
        diff = _angdiff(pa, sh["a"])
        sh["a"] += max(-TURN * dt, min(TURN * dt, diff))
        if abs(diff) < 0.9:
            sh["thrust"] = 1.0
        # still shoot at the threat if roughly aligned
        tgt = o if o in targets or o is ufo else None
    else:
        tgt = None

    # --- target selection & lead
    if ufo is not None:
        targets.append(ufo)
    best, best_cost, best_aim = None, 1e9, None
    for o in targets:
        rx, ry = o["x"] - sh["x"], o["y"] - sh["y"]
        vx, vy = o["vx"] - sh["vx"] * 0.3, o["vy"] - sh["vy"] * 0.3
        # intercept: |r + v t| = s t
        a = vx * vx + vy * vy - BULLET_SPD ** 2
        b = 2 * (rx * vx + ry * vy)
        c = rx * rx + ry * ry
        disc = b * b - 4 * a * c
        if disc < 0:
            continue
        tt = (-b - math.sqrt(disc)) / (2 * a)
        if tt < 0:
            tt = (-b + math.sqrt(disc)) / (2 * a)
        if tt < 0 or tt > 0.9:
            continue
        aim = math.atan2(ry + vy * tt, rx + vx * tt)
        cost = abs(_angdiff(aim, sh["a"])) * 60 + math.sqrt(c) * 0.5 - (40 if o is ufo else 0) - o.get("size", 0) * 3
        if cost < best_cost:
            best, best_cost, best_aim = o, cost, aim
    _S["target"] = best
    if best is not None:
        diff = _angdiff(best_aim, sh["a"])
        if danger is None:
            sh["a"] += max(-TURN * dt, min(TURN * dt, diff))
        tol = math.atan2(best.get("r", 6) * 0.7, max(10.0, math.hypot(best["x"] - sh["x"], best["y"] - sh["y"])))
        if abs(diff) < tol and t - _S["last_shot"] > 0.17 and len(_S["bullets"]) < 5:
            _fire(t)
    # --- positional drift toward the centre when idle
    if danger is None:
        dc = math.hypot(sh["x"] - CX, sh["y"] - CY)
        near = min((math.hypot(r["x"] - sh["x"], r["y"] - sh["y"]) - r["r"] for r in rocks), default=999)
        if (dc > 60 or near > 80) and best is not None and abs(_angdiff(math.atan2(CY - sh["y"], CX - sh["x"]), sh["a"])) < 0.5:
            sh["thrust"] = 0.6
        elif best is None and rocks:
            ang = math.atan2(rocks[0]["y"] - sh["y"], rocks[0]["x"] - sh["x"])
            sh["a"] += max(-TURN * dt, min(TURN * dt, _angdiff(ang, sh["a"])))
            if near > 60:
                sh["thrust"] = 0.7


def _fire(t):
    sh = _S["ship"]
    _S["last_shot"] = t
    _S["shots"] += 1
    a = sh["a"]
    _S["bullets"].append([sh["x"] + 9 * math.cos(a), sh["y"] + 9 * math.sin(a),
                          sh["vx"] * 0.3 + BULLET_SPD * math.cos(a), sh["vy"] * 0.3 + BULLET_SPD * math.sin(a), 0.85])


def _hyperspace(t):
    sh = _S["ship"]
    _S["rings"].append((sh["x"], sh["y"], t, -1))
    _burst(sh["x"], sh["y"], 10, 50, GREEN_MID)
    for _ in range(20):
        a = _rng.uniform(0, 2 * math.pi)
        r = _rng.uniform(0, 70)
        x, y = CX + r * math.cos(a), CY + r * math.sin(a)
        if all(math.hypot(x - rk["x"], y - rk["y"]) > rk["r"] + 22 for rk in _S["rocks"]):
            break
    sh["x"], sh["y"], sh["vx"], sh["vy"] = x, y, 0.0, 0.0
    sh["inv"] = 0.6
    _S["rings"].append((x, y, t + 0.15, 1))
    _S["hyper_cd"] = 4.0
    _msg("WARP JUMP", GREEN_HI, t, 1.4)


def _update(dt, t):
    st = _S["state"]
    sh = _S["ship"]
    _S["hyper_cd"] -= dt

    if st == "wave_in":
        if not _S["rocks"]:
            _start_wave(t)
        _S["state"] = "play"
    elif st == "clear":
        if t - _S["t_state"] > 3.0:
            _S["state"] = "wave_in"
    elif st == "over":
        if t - _S["t_state"] > 6.0:
            _S["game"] += 1
            _reset_game(t)
            _msg(f"GAME {_S['game']:02d}", GREEN_HI, t)
            return

    # ship
    if sh["alive"]:
        if st == "play":
            _ai(dt, t)
        k = 150.0 * sh["thrust"]
        sh["vx"] += math.cos(sh["a"]) * k * dt
        sh["vy"] += math.sin(sh["a"]) * k * dt
        drag = 0.55 ** dt
        sh["vx"] *= drag
        sh["vy"] *= drag
        sp = math.hypot(sh["vx"], sh["vy"])
        if sp > 110:
            sh["vx"] *= 110 / sp
            sh["vy"] *= 110 / sp
        sh["x"] += sh["vx"] * dt
        sh["y"] += sh["vy"] * dt
        _wrap(sh)
        sh["inv"] = max(0.0, sh["inv"] - dt)
        _S["star_off"][0] -= sh["vx"] * dt * 0.003
        _S["star_off"][1] -= sh["vy"] * dt * 0.003
    elif _S["respawn_at"] is not None and t > _S["respawn_at"]:
        if all(math.hypot(CX - rk["x"], CY - rk["y"]) > rk["r"] + 26 for rk in _S["rocks"]) or t > _S["respawn_at"] + 3:
            _S["ship"] = _new_ship()
            _S["respawn_at"] = None
            _S["rings"].append((CX, CY, t, 1))
            _msg("SERVITOR RE-SANCTIFIED", GREEN_HI, t)
    sh = _S["ship"]

    # rocks
    for rk in _S["rocks"]:
        rk["x"] += rk["vx"] * dt
        rk["y"] += rk["vy"] * dt
        rk["rot"] += rk["spin"] * dt
        rk["mat"] = max(0.0, rk["mat"] - dt)
        _wrap(rk)

    # ufo
    ufo = _S["ufo"]
    if ufo is None and st == "play" and t > _S["ufo_next"] and _S["rocks"]:
        a = _rng.uniform(0, 2 * math.pi)
        x, y = CX + (RA - 2) * math.cos(a), CY + (RA - 2) * math.sin(a)
        head = a + math.pi + _rng.uniform(-0.5, 0.5)
        spd = 38 + 3 * _S["wave"]
        _S["ufo"] = ufo = {"x": x, "y": y, "vx": math.cos(head) * spd, "vy": math.sin(head) * spd, "r": 7,
                           "life": 0.0, "next": t + 1.2, "hx": math.cos(head), "hy": math.sin(head), "spd": spd}
        _msg("XENOS RAIDER DETECTED", AMBER, t)
    if ufo is not None:
        ufo["life"] += dt
        wob = math.sin(ufo["life"] * 2.2) * 0.9
        ufo["vx"] = (ufo["hx"] - ufo["hy"] * wob) * ufo["spd"]
        ufo["vy"] = (ufo["hy"] + ufo["hx"] * wob) * ufo["spd"]
        ufo["x"] += ufo["vx"] * dt
        ufo["y"] += ufo["vy"] * dt
        if math.hypot(ufo["x"] - CX, ufo["y"] - CY) > RA and ufo["life"] > 1.0:
            _S["ufo"] = ufo = None
            _S["ufo_next"] = t + _rng.uniform(25, 45)
        elif t > ufo["next"] and sh["alive"]:
            ufo["next"] = t + _rng.uniform(0.9, 1.6)
            a = math.atan2(sh["y"] - ufo["y"], sh["x"] - ufo["x"]) + _rng.gauss(0, 0.22)
            _S["ubullets"].append([ufo["x"], ufo["y"], math.cos(a) * 120, math.sin(a) * 120, 1.3])

    # bullets
    keep = []
    for b in _S["bullets"]:
        b[0] += b[2] * dt
        b[1] += b[3] * dt
        b[4] -= dt
        o = {"x": b[0], "y": b[1]}
        _wrap(o)
        b[0], b[1] = o["x"], o["y"]
        hit = False
        for rk in _S["rocks"]:
            if rk["mat"] <= 0 and math.hypot(b[0] - rk["x"], b[1] - rk["y"]) < rk["r"]:
                _kill_rock(rk, t)
                _S["hits"] += 1
                hit = True
                break
        if not hit and ufo is not None and math.hypot(b[0] - ufo["x"], b[1] - ufo["y"]) < 8:
            hit = True
            _add_score(500, t)
            _burst(ufo["x"], ufo["y"], 24, 90, AMBER, 1.2)
            _debris_from_poly(ufo, _ufo_pts(ufo), AMBER, 40)
            _S["rings"].append((ufo["x"], ufo["y"], t, 1))
            _msg("RAIDER PURGED +500", AMBER, t)
            _S["ufo"] = ufo = None
            _S["ufo_next"] = t + _rng.uniform(25, 45)
        if not hit and b[4] > 0:
            keep.append(b)
    _S["bullets"] = keep

    keep = []
    for b in _S["ubullets"]:
        b[0] += b[2] * dt
        b[1] += b[3] * dt
        b[4] -= dt
        if sh["alive"] and sh["inv"] <= 0 and math.hypot(b[0] - sh["x"], b[1] - sh["y"]) < 6:
            _kill_ship(t)
            continue
        if b[4] > 0 and math.hypot(b[0] - CX, b[1] - CY) < RA:
            keep.append(b)
    _S["ubullets"] = keep

    # collisions: ship/ufo vs rocks
    if sh["alive"] and sh["inv"] <= 0:
        for rk in _S["rocks"]:
            if rk["mat"] <= 0 and math.hypot(sh["x"] - rk["x"], sh["y"] - rk["y"]) < rk["r"] + 4:
                _kill_rock(rk, t, from_ship=False)
                _kill_ship(t)
                break
    if ufo is not None:
        for rk in _S["rocks"]:
            if rk["mat"] <= 0 and math.hypot(ufo["x"] - rk["x"], ufo["y"] - rk["y"]) < rk["r"] + 6:
                _kill_rock(rk, t, from_ship=False)
                _burst(ufo["x"], ufo["y"], 18, 80, AMBER)
                _S["ufo"] = None
                _S["ufo_next"] = t + _rng.uniform(25, 45)
                break

    if st == "play" and not _S["rocks"] and _S["ufo"] is None:
        _S["state"] = "clear"
        _S["t_state"] = t
        bonus = 250 * _S["wave"]
        _add_score(bonus, t)
        _msg(f"WAVE {_S['wave']:02d} PURGED +{bonus}", AMBER, t, 2.8)

    # particles
    keep = []
    for sp in _S["sparks"]:
        sp[0] += sp[2] * dt
        sp[1] += sp[3] * dt
        sp[4] -= dt * 1.5
        if sp[4] > 0:
            keep.append(sp)
    _S["sparks"] = keep
    keep = []
    for db in _S["debris"]:
        db[0] += db[4] * dt
        db[1] += db[5] * dt
        c, s = math.cos(db[6] * dt), math.sin(db[6] * dt)
        db[2], db[3] = db[2] * c - db[3] * s, db[2] * s + db[3] * c
        db[7] -= dt * 0.8
        if db[7] > 0:
            keep.append(db)
    _S["debris"] = keep
    _S["rings"] = [r for r in _S["rings"] if t - r[2] < 0.9]


def _ufo_pts(u):
    x, y = u["x"], u["y"]
    return [(x - 8, y), (x - 4, y - 3), (x + 4, y - 3), (x + 8, y), (x + 4, y + 3), (x - 4, y + 3)]


# ------------------------------------------------------------- drawing ---
def _draw(d, t):
    # parallax starfield
    ox, oy = _S["star_off"]
    for sx, sy, depth in _S["stars"]:
        x = (sx + ox * depth * 3 + 1) % 2 - 1
        y = (sy + oy * depth * 3 + 1) % 2 - 1
        px, py = CX + x * 110, CY + y * 110
        if (px - CX) ** 2 + (py - CY) ** 2 < 104 ** 2:
            d.point((px, py), fill=GREEN_DIM if depth > 0.2 else GREEN_FAINT)
    # arena rim with bearing ticks
    d.ellipse([CX - RA - 2, CY - RA - 2, CX + RA + 2, CY + RA + 2], outline=GREEN_FAINT)
    for k in range(24):
        a = k * math.pi / 12
        r0 = RA - (4 if k % 6 == 0 else 2)
        d.line([(CX + r0 * math.cos(a), CY + r0 * math.sin(a)),
                (CX + RA * math.cos(a), CY + RA * math.sin(a))], fill=GREEN_DIM)

    # rocks
    tgt = _S.get("target")
    for rk in _S["rocks"]:
        pts = _rock_world(rk)
        if rk["mat"] > 0:
            k = max(0.0, 1.0 - rk["mat"])
            r = rk["r"] * (1 + 1.2 * min(1.0, rk["mat"]))
            d.ellipse([rk["x"] - r, rk["y"] - r, rk["x"] + r, rk["y"] + r], outline=scale(GREEN_MID, 0.4 + 0.6 * k))
            if k > 0:
                d.line(pts + [pts[0]], fill=scale(GREEN, k))
            continue
        d.line(pts + [pts[0]], fill=GREEN, width=1)
        # inner facet for depth
        c = (rk["x"], rk["y"])
        for i in range(0, len(pts), 3):
            p = pts[i]
            d.line([p, (c[0] + (p[0] - c[0]) * 0.45, c[1] + (p[1] - c[1]) * 0.45)], fill=GREEN_DIM)
        if rk is tgt:
            r = rk["r"] + 5
            for q in range(4):
                a = q * math.pi / 2 + math.pi / 4 + t * 2
                ax, ay = rk["x"] + r * math.cos(a), rk["y"] + r * math.sin(a)
                d.line([(ax, ay), (ax + 3 * math.cos(a + 2.2), ay + 3 * math.sin(a + 2.2))], fill=AMBER)

    # ufo
    u = _S["ufo"]
    if u is not None:
        pts = _ufo_pts(u)
        d.line(pts + [pts[0]], fill=AMBER)
        d.line([pts[0], pts[3]], fill=AMBER)
        d.line([(u["x"] - 3, u["y"] - 3), (u["x"] - 2, u["y"] - 6), (u["x"] + 2, u["y"] - 6), (u["x"] + 3, u["y"] - 3)], fill=AMBER)
        if int(t * 8) % 2:
            d.point((u["x"], u["y"] + 1), fill=RED)

    # bullets
    for b in _S["bullets"]:
        sp = math.hypot(b[2], b[3]) or 1
        d.line([(b[0], b[1]), (b[0] - b[2] / sp * 3, b[1] - b[3] / sp * 3)], fill=GREEN_HI, width=2)
    for b in _S["ubullets"]:
        d.rectangle([b[0] - 1, b[1] - 1, b[0] + 1, b[1] + 1], fill=AMBER)

    # debris & sparks
    for db in _S["debris"]:
        d.line([(db[0] - db[2], db[1] - db[3]), (db[0] + db[2], db[1] + db[3])], fill=scale(db[8], db[7]))
    for sp in _S["sparks"]:
        d.point((sp[0], sp[1]), fill=scale(sp[5], min(1.0, sp[4])))
    for (x, y, t0, direction) in _S["rings"]:
        k = (t - t0) / 0.9
        if k < 0:
            continue
        r = 4 + 34 * k if direction > 0 else 30 * (1 - k)
        d.ellipse([x - r, y - r, x + r, y + r], outline=scale(GREEN_HI, 1 - k))

    # ship
    sh = _S["ship"]
    if sh["alive"] and (sh["inv"] <= 0 or int(t * 10) % 2 == 0):
        pts = _ship_pts(sh)
        d.line(pts + [pts[0]], fill=GREEN_HI)
        if sh["thrust"] > 0:
            a = sh["a"] + math.pi
            L = 6 + _rng.uniform(2, 7) * sh["thrust"]
            bx, by = sh["x"] + 3.5 * math.cos(a), sh["y"] + 3.5 * math.sin(a)
            tip = (bx + L * math.cos(a), by + L * math.sin(a))
            w1 = (bx + 2.5 * math.cos(a + 1.6), by + 2.5 * math.sin(a + 1.6))
            w2 = (bx + 2.5 * math.cos(a - 1.6), by + 2.5 * math.sin(a - 1.6))
            d.line([w1, tip, w2], fill=GREEN_HI)
            d.point(((bx + tip[0]) / 2, (by + tip[1]) / 2), fill=AMBER)

    # HUD
    _txt(d, CX, 13, f"{_S['score']:06d}", AMBER, 12, "c")
    _txt(d, CX - 58, 30, f"WAVE {_S['wave']:02d}", GREEN_MID, 9, "l")
    for i in range(min(_S["lives"], 5)):
        x, y = CX + 36 + i * 8, 35
        d.line([(x, y - 4), (x - 3, y + 3), (x, y + 1), (x + 3, y + 3), (x, y - 4)], fill=GREEN)
    _txt(d, CX, 198, "COG-ASTEROIDS", GREEN_DIM, 9, "c")
    _txt(d, CX, 209, f"HI {_S['hi']:06d}", GREEN_DIM, 9, "c")
    acc = _S["hits"] / _S["shots"] * 100 if _S["shots"] else 0
    _txt(d, CX - 70, 184, f"ACC {acc:3.0f}%", GREEN_DIM, 9, "l")
    _txt(d, CX + 70, 184, f"ROCKS {len(_S['rocks']):02d}", GREEN_DIM, 9, "r")

    m = _S["msg"]
    if m is not None:
        text, col, t0, dur = m
        age = t - t0
        if age < dur:
            k = 1.0 if age < dur - 0.5 else (dur - age) / 0.5
            if age > 0.4 or int(age * 16) % 2 == 0:
                _txt(d, CX, 48, text, scale(col, k), 9, "c")
        else:
            _S["msg"] = None
    if _S["state"] == "over":
        age = t - _S["t_state"]
        _txt(d, CX, CY - 16, "GAME OVER", scale(RED, 0.6 + 0.4 * math.sin(age * 6)), 16, "c")
        _txt(d, CX, CY + 6, f"SCORE {_S['score']:06d}", AMBER, 9, "c")
        _txt(d, CX, CY + 18, "RECALIBRATING SERVITOR", GREEN_MID, 9, "c")
    elif _S["state"] == "clear":
        age = t - _S["t_state"]
        r = 20 + age * 30
        d.ellipse([CX - r, CY - r, CX + r, CY + r], outline=scale(GREEN_MID, max(0.0, 1 - age / 3)))


def render(bezel, mask, now: float) -> Image.Image:
    if _session.fresh(now) or not _S:
        _reset(now)
        _S["prev"] = now
    dt = max(0.0, min(0.1, now - _S["prev"]))
    _S["prev"] = now
    _update(dt, now)
    img = blank()
    d = ImageDraw.Draw(img)
    _draw(d, now)
    return _ph.compose(img)
