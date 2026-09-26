"""Hex Grid - a tilted tactical hex map.

The honeycomb lies on a plane tilted away in perspective. Each mission plots an
A* route between two marked hexes around impassable terrain: the search
frontier and closed set spread visibly, the found path lights up and a unit
advances along it, and on arrival the surrounding hexes are claimed and rise.
Enemy-held (amber) hexes grow elsewhere and blink where they border friendly
ground. Auspex pings send ripples of lifted cells across the map.
"""

from __future__ import annotations

import heapq
import math
import random

import numpy as np
from PIL import Image, ImageDraw

from ..lore._common import CX, CY, Session, font
from ._phosphor import AMBER, GREEN, GREEN_DIM, GREEN_FAINT, GREEN_HI, GREEN_MID, RED, Phosphor, blank

NAME = "hex_grid"

_rng = random.Random()
_session = Session()
_ph = Phosphor(decay=0.6, bloom=0.5)
_S: dict = {}

HS = 10.5                     # hex radius (world)
PHI = 0.85                     # plane tilt (rad); pi/2 = face-on
FOV, CAM = 400.0, 420.0
YOFF = 6.0
SECTORS = ["GAMMA", "SIGMA", "TAU", "EPSILON", "KAPPA", "OMICRON"]
_SPH, _CPH = math.sin(PHI), math.cos(PHI)
_DIRS = [(1, 0), (1, -1), (0, -1), (-1, 0), (-1, 1), (0, 1)]

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


def _proj(x, z, h=0.0):
    zc = z * _CPH - h * _SPH
    f = FOV / (zc + CAM)
    return CX + x * f, CY + YOFF - (z * _SPH + h * _CPH) * f, f


# ── build the cell table once ────────────────────────────────────────────────
_CELLS = {}   # (q, r) -> dict(c=(sx,sy), f, pts=[6 corners], up=px per unit height, z)
for _q in range(-9, 10):
    for _r in range(-9, 10):
        if abs(_q + _r) > 12:
            continue
        wx = HS * math.sqrt(3) * (_q + _r / 2)
        wz = -HS * 1.5 * _r
        sx, sy, f = _proj(wx, wz)
        if (sx - CX) ** 2 + (sy - CY) ** 2 > 106 ** 2 or not (44 < sy < 192):
            continue
        pts = []
        for k in range(6):
            a = math.radians(60 * k + 30)
            px, py, _ = _proj(wx + HS * 0.94 * math.cos(a), wz + HS * 0.94 * math.sin(a))
            pts.append((px, py))
        _, sy_up, _ = _proj(wx, wz, 1.0)
        _CELLS[(_q, _r)] = {"c": (sx, sy), "f": f, "pts": pts, "up": sy - sy_up, "z": wz}
_KEYS = list(_CELLS)


def _hdist(a, b):
    dq, dr = a[0] - b[0], a[1] - b[1]
    return (abs(dq) + abs(dr) + abs(dq + dr)) // 2


def _nbrs(c):
    for dq, dr in _DIRS:
        n = (c[0] + dq, c[1] + dr)
        if n in _CELLS:
            yield n


def _astar(start, goal, blocked):
    openh = [(0, 0, start)]
    g = {start: 0}
    came = {}
    push_step = {start: 0}
    close_step = {}
    step = 0
    cnt = 0
    while openh:
        _, _, cur = heapq.heappop(openh)
        if cur in close_step:
            continue
        step += 1
        close_step[cur] = step
        if cur == goal:
            path = [cur]
            while path[-1] in came:
                path.append(came[path[-1]])
            return path[::-1], push_step, close_step, step
        for n in _nbrs(cur):
            if n in blocked or n in close_step:
                continue
            ng = g[cur] + 1
            if ng < g.get(n, 1e9):
                g[n] = ng
                came[n] = cur
                push_step.setdefault(n, step)
                cnt += 1
                heapq.heappush(openh, (ng + _hdist(n, goal) * 0.8, cnt, n))
    return None, push_step, close_step, step


def _grid_layer(blocked):
    img = blank()
    d = ImageDraw.Draw(img)
    for k, c in _CELLS.items():
        f = c["f"]
        b = 0.55 + 0.6 * (f - 0.8)
        if k in blocked:
            d.polygon(c["pts"], fill=(1, 12, 5), outline=_col(GREEN_DIM, b * 0.8))
            p = c["pts"]
            d.line([p[1], p[4]], fill=_col(GREEN_DIM, 0.7))
        else:
            d.polygon(c["pts"], outline=_col(GREEN_DIM, b))
    d.ellipse([CX - 111, CY - 111, CX + 111, CY + 111], outline=GREEN_FAINT)
    return img


def _new_mission(t):
    S = _S
    owner = S["owner"]
    for _ in range(40):
        cand = [k for k in _KEYS if owner.get(k) != 2]
        start = _rng.choice(cand)
        far = [k for k in cand if _hdist(k, start) >= 8]
        if not far:
            continue
        goal = _rng.choice(far)
        blocked = set()
        for _ in range(_rng.randint(6, 9)):   # ridges of impassable terrain
            c = _rng.choice(_KEYS)
            dq, dr = _rng.choice(_DIRS)
            for i in range(_rng.randint(3, 6)):
                blocked.add(c)
                c = (c[0] + dq, c[1] + dr)
                if _rng.random() < 0.3:
                    dq, dr = _rng.choice(_DIRS)
        blocked.discard(start)
        blocked.discard(goal)
        path, push, close, n = _astar(start, goal, blocked)
        if path and len(path) >= 8:
            break
    else:
        # fallback: open ground between two far-apart cells
        start = min(_KEYS, key=lambda k: _CELLS[k]["c"][0])
        goal = max(_KEYS, key=lambda k: _CELLS[k]["c"][0])
        blocked = set()
        path, push, close, n = _astar(start, goal, blocked)
    S["m"] = {"t0": t, "start": start, "goal": goal, "blocked": blocked, "path": path,
              "push": push, "close": close, "nsteps": n, "claimed": False}
    S["grid"] = _grid_layer(blocked)


def _reset():
    _S.clear()
    _S["owner"] = {}
    _S["sector"] = _rng.choice(SECTORS)
    _S["last"] = None
    # seed an enemy-held region
    c = _rng.choice(_KEYS)
    for k in _KEYS:
        if _hdist(k, c) <= 1:
            _S["owner"][k] = 2
    _S["pings"] = []
    _S["next_ping"] = 2.0
    _S["next_grow"] = 6.0
    _new_mission(0.0)
    _ph.reset()


def _cell_poly(d, c, h, fill, outline, side=None):
    up = c["up"] * h
    pts = [(x, y - up) for x, y in c["pts"]]
    if h > 0.3:
        sc = side or outline
        p = c["pts"]
        for i in (2, 3, 4, 5, 0):  # lower (near) corners
            x, y = p[i]
            d.line([(x, y), (x, y - up)], fill=sc)
        d.line([p[2], p[3], p[4], p[5], p[0]], fill=sc)
    d.polygon(pts, fill=fill, outline=outline)


def render(bezel, mask, now: float) -> Image.Image:
    if _session.fresh(now):
        _reset()
    S = _S
    ta = _session.t(now)
    m = S["m"]
    tm = ta - m["t0"]
    owner = S["owner"]

    exp_rate = 10.0
    t_search0 = 2.5
    t_search = m["nsteps"] / exp_rate
    t_path0 = t_search0 + t_search + 0.5
    t_move0 = t_path0 + 2.0
    move_dt = 0.7
    t_arrive = t_move0 + (len(m["path"]) - 1) * move_dt
    t_end = t_arrive + 7.0
    if tm > t_end:
        _new_mission(ta)
        m = S["m"]
        tm = 0.0

    # auspex pings
    if ta > S["next_ping"]:
        S["pings"].append((_rng.choice(_KEYS), ta, 1.0))
        S["next_ping"] = ta + _rng.uniform(5, 9)
    # enemy growth
    if ta > S["next_grow"]:
        S["next_grow"] = ta + _rng.uniform(5, 8)
        enemy = [k for k, v in owner.items() if v == 2]
        if not enemy or len(enemy) < 3:
            c = _rng.choice(_KEYS)
            owner[c] = 2
        else:
            src = _rng.choice(enemy)
            opts = [n for n in _nbrs(src) if owner.get(n) != 2 and n not in m["blocked"]]
            if opts and len(enemy) < 22:
                owner[_rng.choice(opts)] = 2

    # heights from ripples
    heights = {}
    keep = []
    for c0, t0, amp in S["pings"]:
        age = ta - t0
        if age > 4.0:
            continue
        keep.append((c0, t0, amp))
        front = age * 5.0
        for k in _KEYS:
            dd = _hdist(k, c0)
            x = dd - front
            if -1.6 < x < 0.6:
                h = amp * (4.0 * math.exp(-x * x * 2.0)) * max(0.0, 1 - age / 4.0)
                if h > heights.get(k, 0):
                    heights[k] = h
    S["pings"] = keep

    img = S["grid"].copy()
    d = ImageDraw.Draw(img)

    # search state
    step = (tm - t_search0) * exp_rate
    closed, opened = set(), set()
    if tm > t_search0:
        cs = m["close"]
        for k, s in m["push"].items():
            if s <= step:
                if cs.get(k, 1e9) <= step:
                    closed.add(k)
                else:
                    opened.add(k)
    searching = t_search0 < tm < t_search0 + t_search
    fade_search = 1.0 if tm < t_move0 else max(0.25, 1 - (tm - t_move0) / 4)

    # compose draw list: (screen y, cell, h, fill, outline)
    items = {}

    def put(k, h, fill, outline, pri):
        cur = items.get(k)
        if cur is None or pri >= cur[3]:
            items[k] = (h, fill, outline, pri)

    for k, v in owner.items():
        if v == 1:
            put(k, 1.6, _col(GREEN, 0.30), _col(GREEN_MID, 1.0), 1)
        elif v == 2:
            contested = any(owner.get(n) == 1 for n in _nbrs(k))
            if contested and int(ta * 3) % 2:
                put(k, 0.8, _col(AMBER, 0.35), AMBER, 1)
            else:
                put(k, 0.8, _col(AMBER, 0.2), _col(AMBER, 0.55), 1)
    for k in closed:
        put(k, 0.0, _col(GREEN, 0.10 * fade_search), _col(GREEN_MID, fade_search), 2)
    for k in opened:
        put(k, 0.0, None, _col(GREEN, 0.9 * fade_search), 2)

    path = m["path"]
    if tm > t_path0:
        n_show = min(len(path), int((tm - t_path0) / 1.5 * len(path)) + 1)
        for k in path[:n_show]:
            put(k, 0.5, _col(GREEN, 0.12), GREEN_HI, 3)
    for k, h in heights.items():
        cur = items.get(k)
        if cur is not None:
            items[k] = (cur[0] + h, cur[1], cur[2], cur[3])
        else:
            items[k] = (h, (0, 10, 4), _col(GREEN, 0.3 + 0.15 * h), 0)

    for k in sorted(items, key=lambda k: -_CELLS[k]["z"]):
        h, fill, outline, pri = items[k]
        _cell_poly(d, _CELLS[k], h, fill, outline)

    # path line + unit
    pc = [_CELLS[k]["c"] for k in path]
    if tm > t_path0:
        n_show = min(len(path), int((tm - t_path0) / 1.5 * len(path)) + 1)
        if n_show > 1:
            d.line(pc[:n_show], fill=GREEN_HI, width=1)
    if tm > t_move0:
        u = min(len(path) - 1.0, (tm - t_move0) / move_dt)
        i = int(u)
        fr = u - i
        if i >= len(path) - 1:
            ux, uy = pc[-1]
        else:
            ux = pc[i][0] + (pc[i + 1][0] - pc[i][0]) * fr
            uy = pc[i][1] + (pc[i + 1][1] - pc[i][1]) * fr
        d.polygon([(ux, uy - 7), (ux + 4, uy - 1), (ux - 4, uy - 1)], fill=GREEN_HI)
        d.line([(ux, uy - 1), (ux, uy + 2)], fill=GREEN_HI)

    # arrival: claim zone + ping
    if tm > t_arrive and not m["claimed"]:
        m["claimed"] = True
        for k in _KEYS:
            if _hdist(k, m["goal"]) <= 2 and k not in m["blocked"]:
                if owner.get(k) == 2 and _hdist(k, m["goal"]) > 1:
                    continue  # the enemy holds the fringe: contested
                owner[k] = 1
        S["pings"].append((m["goal"], ta, 1.4))
        # cap friendly territory so the map keeps changing
        fr_ = [k for k, v in owner.items() if v == 1]
        if len(fr_) > 45:
            for k in _rng.sample(fr_, len(fr_) - 45):
                del owner[k]

    # start / goal markers
    for k, lab, c in ((m["start"], "S", GREEN_HI), (m["goal"], "G", AMBER if tm < t_arrive else GREEN_HI)):
        x, y = _CELLS[k]["c"]
        r = 7 + 2 * math.sin(ta * 5)
        for sx_, sy_ in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            x0, y0 = x + sx_ * r, y + sy_ * r * 0.8
            d.line([(x0, y0), (x0 - sx_ * 3, y0)], fill=c)
            d.line([(x0, y0), (x0, y0 - sy_ * 3)], fill=c)
        lx = x + r + 2 if x < CX + 40 else x - r - 42
        _text(img, lx, y - r - 6, f"{lab} {k[0] + 10:02d}{k[1] + 10:02d}", c, 9, "l")

    # ── HUD ──
    _text(img, CX, 16, f"SECTOR {S['sector']}", GREEN_MID, 10)
    if tm < t_search0:
        lab, c = "TARGET DESIGNATED", AMBER
    elif searching:
        lab, c = "PLOTTING ROUTE", GREEN
    elif tm < t_move0:
        lab, c = "ROUTE LOCKED", GREEN_HI
    elif tm < t_arrive:
        lab, c = "ADVANCING", GREEN
    else:
        lab, c = "ZONE CLAIMED", GREEN_HI
    _text(img, CX, 28, lab, c, 11)
    nexp = len(closed)
    n_en = sum(1 for v in owner.values() if v == 2)
    n_fr = sum(1 for v in owner.values() if v == 1)
    _text(img, CX, 196, f"NODES {nexp:03d}  PATH {len(path) - 1:02d}", GREEN_MID, 9)
    _text(img, CX - 4, 208, f"HELD {n_fr:02d}", GREEN, 9, "r")
    _text(img, CX + 4, 208, f"HOSTILE {n_en:02d}", AMBER, 9, "l")
    return _ph.compose(img)
