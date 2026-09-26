"""Space Hulk Boarding Auspex – Terminator squad vs Genestealers.

Top-down schematic of a freshly generated derelict (new corridors every
cycle). A five-man Terminator squad advances in file towards its objective
while motion-tracker blips close in from the dark; contacts that enter line of
sight resolve into Genestealers, storm bolters trade with them, and Terminators
can fall in close assault. Ends with "PURGE COMPLETE" or "SIGNAL LOST".
"""

from __future__ import annotations

import math
import random
from collections import deque

import numpy as np
from PIL import Image, ImageChops, ImageDraw

from ._common import CX, CY, Session, font, lerp_color, scale

NAME = "space_hulk_auspex"


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
CELL = 14                # px per grid cell
MAZE = 13                # maze cells per side -> grid of 2*MAZE+1
G = 2 * MAZE + 1
PAD = 130                # world image padding so the camera crop never leaves it

TERM = (150, 225, 255)
TERM_DARK = (20, 50, 70)
STEAL = (225, 80, 255)
BLIP = (120, 255, 140)
AMBER = (255, 190, 60)
RED = (255, 60, 50)
WALL = (60, 165, 175)
WHITE = (255, 255, 255)

_HULKS = ["SIN OF DAMNATION", "FORSAKEN MALICE", "WRATH OF ANCIENTS", "SHROUD OF WOE",
          "CURSED ERRANT", "DAMNED SOULS", "MORTIS VOID", "HAND OF DESPAIR"]
_SQUADS = ["GIDEON", "LORENZO", "VALENCIO", "LEON", "CLAUDIO", "ZAEL", "GOMEZ", "OMNIO",
           "SCIPIO", "NOCTIS", "DEINO", "BELIAL"]
_OBJS = ["PURGE BROOD NEST", "SEAL AIRLOCK", "RECOVER RELIC", "ARM CHARGES", "PURGE LIBRARIUM"]
_DIRS = ((1, 0), (-1, 0), (0, 1), (0, -1))


# ------------------------------------------------------------- map ---

def _gen_grid():
    rnd = _rng
    floor = np.zeros((G, G), bool)
    # maze via DFS on odd cells, biased to keep corridors straight
    start = (rnd.randrange(MAZE), rnd.randrange(MAZE))
    seen = {start}
    stack = [(start, None)]
    floor[2 * start[1] + 1, 2 * start[0] + 1] = True
    while stack:
        (cx, cy), last = stack[-1]
        opts = [(dx, dy) for dx, dy in _DIRS
                if 0 <= cx + dx < MAZE and 0 <= cy + dy < MAZE and (cx + dx, cy + dy) not in seen]
        if not opts:
            stack.pop()
            continue
        if last in opts and rnd.random() < 0.72:
            dx, dy = last
        else:
            dx, dy = rnd.choice(opts)
        nx, ny = cx + dx, cy + dy
        seen.add((nx, ny))
        floor[2 * cy + 1 + dy, 2 * cx + 1 + dx] = True
        floor[2 * ny + 1, 2 * nx + 1] = True
        stack.append(((nx, ny), (dx, dy)))
    # loops
    for _ in range(int(MAZE * MAZE * 0.14)):
        x, y = rnd.randrange(1, G - 1), rnd.randrange(1, G - 1)
        if not floor[y, x] and ((x % 2 == 1 and y % 2 == 0) or (x % 2 == 0 and y % 2 == 1)):
            floor[y, x] = True
    # rooms
    rooms = []
    for _ in range(rnd.randint(3, 5)):
        rx, ry = 2 * rnd.randrange(1, MAZE - 2) + 1, 2 * rnd.randrange(1, MAZE - 2) + 1
        floor[ry - 1:ry + 2, rx - 1:rx + 2] = True
        rooms.append((rx, ry))
    # prune some dead ends to make it read as corridors, not a maze
    for _ in range(2):
        for y in range(1, G - 1):
            for x in range(1, G - 1):
                if floor[y, x] and sum(floor[y + dy, x + dx] for dx, dy in _DIRS) == 1 and rnd.random() < 0.35:
                    floor[y, x] = False
    return floor, rooms


def _bfs(floor, sources):
    dist = np.full(floor.shape, 9999, np.int32)
    q = deque()
    for (x, y) in sources:
        if floor[y, x]:
            dist[y, x] = 0
            q.append((x, y))
    while q:
        x, y = q.popleft()
        dd = dist[y, x] + 1
        for dx, dy in _DIRS:
            nx, ny = x + dx, y + dy
            if 0 <= nx < G and 0 <= ny < G and floor[ny, nx] and dist[ny, nx] > dd:
                dist[ny, nx] = dd
                q.append((nx, ny))
    return dist


def _largest_component(floor):
    cells = list(zip(*np.nonzero(floor)))
    best = None
    seen = np.zeros_like(floor)
    for (y, x) in cells:
        if seen[y, x]:
            continue
        d = _bfs(floor, [(x, y)])
        comp = d < 9999
        seen |= comp
        if best is None or comp.sum() > best.sum():
            best = comp
    return best


def _render_map(floor, obj):
    size = G * CELL + 2 * PAD
    img = Image.new("RGB", (size, size), (2, 5, 7))
    d = ImageDraw.Draw(img)
    ys, xs = np.nonzero(floor)
    for y, x in zip(ys.tolist(), xs.tolist()):
        x0, y0 = PAD + x * CELL, PAD + y * CELL
        d.rectangle([x0, y0, x0 + CELL - 1, y0 + CELL - 1], fill=(12, 30, 36))
        d.point((x0 + CELL // 2, y0 + CELL // 2), fill=(22, 48, 52))
    for y, x in zip(ys.tolist(), xs.tolist()):
        x0, y0 = PAD + x * CELL, PAD + y * CELL
        x1, y1 = x0 + CELL - 1, y0 + CELL - 1
        if not floor[y - 1, x]:
            d.line([(x0, y0), (x1, y0)], fill=WALL)
        if not floor[y + 1, x]:
            d.line([(x0, y1), (x1, y1)], fill=WALL)
        if not floor[y, x - 1]:
            d.line([(x0, y0), (x0, y1)], fill=WALL)
        if not floor[y, x + 1]:
            d.line([(x1, y0), (x1, y1)], fill=WALL)
    # hatch the void between corridors
    for y in range(G):
        for x in range(G):
            if not floor[y, x] and (x + y) % 2 == 0:
                x0, y0 = PAD + x * CELL, PAD + y * CELL
                d.line([(x0 + 3, y0 + CELL - 4), (x0 + CELL - 4, y0 + 3)], fill=(12, 28, 32))
    ox, oy = obj
    x0, y0 = PAD + ox * CELL, PAD + oy * CELL
    d.rectangle([x0 - CELL, y0 - CELL, x0 + 2 * CELL - 1, y0 + 2 * CELL - 1], outline=(120, 90, 20))
    return img


# ------------------------------------------------------------- state ---

class _S:
    pass


_st = _S()
_st.ready = False


class _Term:
    __slots__ = ("name", "x", "y", "alive", "cd", "face", "gun", "flash", "jam")

    def __init__(self, name, gun):
        self.name, self.gun = name, gun
        self.x = self.y = 0.0
        self.alive = True
        self.cd = _rng.uniform(0, 0.5)
        self.face = 0.0
        self.flash = 0.0
        self.jam = 0.0


class _Steal:
    __slots__ = ("x", "y", "tx", "ty", "seen", "ping", "px", "py", "alive", "cd", "speed")

    def __init__(self, x, y):
        self.x, self.y = float(x), float(y)
        self.tx, self.ty = x, y
        self.seen = False
        self.ping = -9.0
        self.px, self.py = self.x, self.y
        self.alive = True
        self.cd = 0.0
        self.speed = _rng.uniform(2.1, 2.8)


def _reset():
    _st.ready = True
    _new_mission(0.0)


def _new_mission(t0):
    st = _st
    st.t0 = t0
    st.sim_t = 0.0
    for _ in range(10):
        floor, rooms = _gen_grid()
        comp = _largest_component(floor)
        floor = floor & comp
        cells = list(zip(*np.nonzero(floor)))
        y, x = cells[_rng.randrange(len(cells))]
        d = _bfs(floor, [(x, y)])
        d[d == 9999] = -1
        yb, xb = np.unravel_index(int(np.argmax(d)), d.shape)
        d2 = _bfs(floor, [(int(xb), int(yb))])
        target = _rng.randint(30, 40)
        cand = np.argwhere((d2 < 9999) & (np.abs(d2 - target) <= 3))
        if len(cand):
            break
    else:
        cand = np.argwhere(d2 == d2[d2 < 9999].max())
    # prefer objective in a room if one is near the target distance
    oy, ox = cand[_rng.randrange(len(cand))]
    for rx, ry in rooms:
        if floor[ry, rx] and abs(d2[ry, rx] - target) <= 6:
            ox, oy = rx, ry
            break
    st.floor = floor
    st.entry = (int(xb), int(yb))
    st.obj = (int(ox), int(oy))
    # path entry -> objective by walking down the distance field from the objective
    dobj = _bfs(floor, [st.obj])
    path = [st.entry]
    cx, cy = st.entry
    while (cx, cy) != st.obj and len(path) < 400:
        best = None
        for dx, dy in _DIRS:
            nx, ny = cx + dx, cy + dy
            if floor[ny, nx] and dobj[ny, nx] < dobj[cy, cx]:
                best = (nx, ny)
                break
        if best is None:
            break
        cx, cy = best
        path.append(best)
    st.path = path
    st.map_img = _render_map(floor, st.obj)
    st.hulk = _rng.choice(_HULKS)
    st.squad = _rng.choice(_SQUADS)
    st.objective = _rng.choice(_OBJS)
    names = ["SGT " + st.squad, "BR. " + _rng.choice(_SQUADS), "BR. " + _rng.choice(_SQUADS),
             "BR. " + _rng.choice(_SQUADS), "BR. " + _rng.choice(_SQUADS)]
    guns = ["hammer", "bolter", "cannon", "bolter", "flamer"]
    st.terms = [_Term(n, g) for n, g in zip(names, guns)]
    st.s = 4.2                      # leader's distance along the path (cells)
    st.cam = None
    st.steals = []
    st.tracers = []   # [x0,y0,x1,y1,life,col]  (cell coords)
    st.splats = []    # (x,y,kind)
    st.events = []
    st.spawn_cd = _rng.uniform(5, 8)
    st.flow = None
    st.flow_cd = 0.0
    st.los_cd = 0.0
    st.kills = 0
    st.ending = None
    st.end_t = 0.0
    st.halt = False
    st.los = None
    st.aggr = _rng.uniform(0.85, 1.35)   # how hard the brood pushes this mission
    _place_squad()
    _event("BOARDING: " + st.hulk, AMBER)


def _event(text, col):
    _st.events.insert(0, [text, 0.0, col])
    del _st.events[3:]


def _path_pos(s):
    p = _st.path
    s = max(0.0, min(len(p) - 1.0, s))
    i = int(s)
    f = s - i
    x0, y0 = p[i]
    x1, y1 = p[min(i + 1, len(p) - 1)]
    return x0 + (x1 - x0) * f, y0 + (y1 - y0) * f


def _place_squad():
    st = _st
    k = 0
    for tm in st.terms:
        if not tm.alive:
            continue
        sk = st.s - k * 1.05
        nx, ny = _path_pos(sk)
        if st.sim_t == 0:
            tm.x, tm.y = nx, ny
        else:
            tm.x += (nx - tm.x) * 0.2
            tm.y += (ny - tm.y) * 0.2
        if not st.halt:
            ax, ay = _path_pos(sk + 1.0)
            if abs(ax - tm.x) + abs(ay - tm.y) > 0.05:
                tm.face = math.atan2(ay - tm.y, ax - tm.x)
        k += 1


# ------------------------------------------------------------- sim ---

def _los_matrix(ax, ay, bx, by, n=16):
    """Boolean LOS for every pair (A_i, B_j) via sampled rays on the grid."""
    fl = _st.floor
    t = np.linspace(0.0, 1.0, n, dtype=np.float32)
    X = ax[:, None, None] + (bx[None, :, None] - ax[:, None, None]) * t
    Y = ay[:, None, None] + (by[None, :, None] - ay[:, None, None]) * t
    xi = np.clip(np.rint(X).astype(np.int32), 0, G - 1)
    yi = np.clip(np.rint(Y).astype(np.int32), 0, G - 1)
    return fl[yi, xi].all(axis=2)


def _step(dt):
    st = _st
    st.sim_t += dt
    t = st.sim_t
    for e in st.events:
        e[1] += dt
    for tr in st.tracers:
        tr[4] -= dt
    st.tracers = [tr for tr in st.tracers if tr[4] > 0]
    if st.ending is not None:
        return
    alive_t = [tm for tm in st.terms if tm.alive]
    live_s = [g for g in st.steals if g.alive]

    # --- flow field toward the squad ---
    st.flow_cd -= dt
    if st.flow_cd <= 0 or st.flow is None:
        st.flow_cd = 0.4
        st.flow = _bfs(st.floor, [(int(round(tm.x)), int(round(tm.y))) for tm in alive_t])

    # --- line of sight / resolve contacts ---
    st.los_cd -= dt
    if st.los_cd <= 0:
        st.los_cd = 0.1
        if live_s and alive_t:
            ax = np.array([tm.x for tm in alive_t], np.float32)
            ay = np.array([tm.y for tm in alive_t], np.float32)
            bx = np.array([g.x for g in live_s], np.float32)
            by = np.array([g.y for g in live_s], np.float32)
            dist = np.hypot(ax[:, None] - bx[None, :], ay[:, None] - by[None, :])
            los = _los_matrix(ax, ay, bx, by) & (dist < 8.5)
            st.los = (alive_t, live_s, los, dist)
            vis = los.any(axis=0)
            for j, g in enumerate(live_s):
                if vis[j] and not g.seen:
                    g.seen = True
                    if st.kills == 0 and not any(o.seen for o in live_s if o is not g):
                        _event("CONTACT: GENESTEALERS", STEAL)
                elif not vis[j] and g.seen:
                    g.seen = False
        else:
            st.los = None
    # --- squad advance / halt on close contacts ---
    close = False
    if getattr(st, "los", None):
        at, ls, los, dist = st.los
        close = bool((los & (dist < 5.0)).any())
    if close and not st.halt:
        _event("OVERWATCH", AMBER)
    st.halt = close
    if not st.halt and alive_t:
        st.s = min(len(st.path) - 1.0, st.s + dt * 0.68)
    _place_squad()
    lead = alive_t[0] if alive_t else None
    if lead and st.s >= len(st.path) - 1.0:
        st.ending = "purge"
        st.end_t = t
        _event("OBJECTIVE REACHED", AMBER)
        return

    # --- spawning ---
    st.spawn_cd -= dt
    if st.spawn_cd <= 0 and lead is not None:
        pressure = min(1.0, t / 70.0)
        st.spawn_cd = _rng.uniform(4.5, 7.5) * (1.3 - 0.6 * pressure) / st.aggr
        if len(live_s) < 12:
            f = st.flow
            cand = np.argwhere((f >= 8) & (f <= 14))
            if len(cand):
                n = _rng.randint(2, 3 + int(pressure * 2))
                y, x = cand[_rng.randrange(len(cand))]
                for _ in range(n):
                    st.steals.append(_Steal(int(x), int(y)))

    # --- genestealer movement ---
    f = st.flow
    for g in live_s:
        if g.cd > 0:
            g.cd -= dt
        dx, dy = g.tx - g.x, g.ty - g.y
        dd = math.hypot(dx, dy)
        if dd < 0.05:
            cx, cy = int(round(g.x)), int(round(g.y))
            best, bv = (cx, cy), f[cy, cx]
            opts = []
            for ddx, ddy in _DIRS:
                nx, ny = cx + ddx, cy + ddy
                if 0 <= nx < G and 0 <= ny < G and st.floor[ny, nx] and f[ny, nx] < bv:
                    opts.append((nx, ny))
            if opts:
                best = _rng.choice(opts)
            g.tx, g.ty = best
        else:
            sp = g.speed * (0.62 if g.seen else 1.0) * dt   # they weave through fire
            if dd <= sp:
                g.x, g.y = g.tx, g.ty
            else:
                g.x += dx / dd * sp
                g.y += dy / dd * sp
        # close assault
        for tm in alive_t:
            if tm.alive and abs(tm.x - g.x) < 0.95 and abs(tm.y - g.y) < 0.95 and g.cd <= 0:
                g.cd = 0.7
                g.seen = True
                st.tracers.append([g.x, g.y, tm.x, tm.y, 0.12, STEAL])
                p_kill = 0.215 * st.aggr if tm.gun != "hammer" else 0.14 * st.aggr
                p_parry = 0.42 if tm.gun == "hammer" else 0.28
                r = _rng.random()
                if r < p_kill:
                    tm.alive = False
                    st.splats.append((tm.x, tm.y, 1))
                    _event(tm.name + " DOWN", RED)
                elif r < p_kill + p_parry:
                    g.alive = False
                    st.kills += 1
                    st.splats.append((g.x, g.y, 0))
                break

    # --- terminator fire ---
    if getattr(st, "los", None):
        at, ls, los, dist = st.los
        for i, tm in enumerate(at):
            tm.flash = max(0.0, tm.flash - dt)
            if not tm.alive:
                continue
            if tm.jam > 0:
                tm.jam -= dt
                continue
            tm.cd -= dt
            cands = [(dist[i, j], j) for j in range(len(ls)) if los[i, j] and ls[j].alive]
            if not cands:
                continue
            dmin, j = min(cands)
            g = ls[j]
            tm.face = math.atan2(g.y - tm.y, g.x - tm.x)
            rng = 2.2 if tm.gun == "flamer" else (1.2 if tm.gun == "hammer" else 8.5)
            if dmin > rng or tm.cd > 0:
                continue
            if tm.gun == "cannon":
                tm.cd, p = 0.3, 0.26
            elif tm.gun == "flamer":
                tm.cd, p = 1.2, 0.75
            elif tm.gun == "hammer":
                tm.cd, p = 0.8, 0.5
            else:
                tm.cd, p = 0.55, 0.30
            p *= max(0.35, 1.1 - dmin / 10.0)
            tm.flash = 0.08
            col = (255, 140, 40) if tm.gun == "flamer" else (255, 230, 120)
            st.tracers.append([tm.x, tm.y, g.x + _rng.uniform(-0.3, 0.3), g.y + _rng.uniform(-0.3, 0.3),
                               0.3 if tm.gun == "flamer" else 0.1, col])
            if tm.gun == "bolter" and _rng.random() < 0.012:
                tm.jam = 2.0
                _event("STORM BOLTER JAMMED", AMBER)
                continue
            if _rng.random() < p:
                g.alive = False
                st.kills += 1
                st.splats.append((g.x, g.y, 0))
    st.steals = [g for g in st.steals if g.alive]
    if len(st.splats) > 80:
        del st.splats[:len(st.splats) - 80]

    if not any(tm.alive for tm in st.terms):
        st.ending = "lost"
        st.end_t = t
        _event("SQUAD OVERRUN", RED)


# ------------------------------------------------------------- draw ---

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
    if st.ending is not None and t - st.end_t > 9.0:
        _new_mission(t_all)
        t = 0.0
    end_age = t - st.end_t if st.ending else 0.0

    # camera follows the squad centroid (in cells)
    alive_t = [tm for tm in st.terms if tm.alive]
    if alive_t:
        fx = sum(tm.x for tm in alive_t) / len(alive_t)
        fy = sum(tm.y for tm in alive_t) / len(alive_t)
    else:
        fx, fy = st.cam if st.cam else (0.0, 0.0)
    if st.cam is None:
        st.cam = (fx, fy)
    cx, cy = st.cam
    st.cam = (cx + (fx - cx) * 0.06, cy + (fy - cy) * 0.06)
    cx, cy = st.cam
    ox = PAD + cx * CELL + CELL / 2 - CX
    oy = PAD + cy * CELL + CELL / 2 - CY
    oxi, oyi = int(round(ox)), int(round(oy))
    img = st.map_img.crop((oxi, oyi, oxi + 240, oyi + 240))

    def sx(x):
        return PAD + x * CELL + CELL / 2 - oxi

    def sy(y):
        return PAD + y * CELL + CELL / 2 - oyi

    # motion-tracker sweep (additive wedge)
    sw = (t * 2.4) % (2 * math.pi)
    wedge = Image.new("RGB", (240, 240), (0, 0, 0))
    wd = ImageDraw.Draw(wedge)
    deg = math.degrees(sw)
    for k in range(5):
        wd.pieslice([CX - 108, CY - 108, CX + 108, CY + 108], deg - 40 + k * 8, deg, fill=(0, 8 + k * 3, 4 + k))
    for r in (36, 72):
        wd.ellipse([CX - r, CY - r, CX + r, CY + r], outline=(0, 40, 20))
    img = ImageChops.add(img, wedge)
    d = ImageDraw.Draw(img)
    d.line([(CX, CY), (CX + math.cos(sw) * 108, CY + math.sin(sw) * 108)], fill=(90, 220, 120))
    f9, f10 = font(9), font(10)

    # objective marker
    ox_, oy_ = sx(st.obj[0]), sy(st.obj[1])
    k = 0.5 + 0.5 * math.sin(t * 4)
    d.rectangle([ox_ - 6, oy_ - 6, ox_ + 6, oy_ + 6], outline=lerp_color((120, 90, 20), AMBER, k))
    d.line([(ox_ - 3, oy_), (ox_ + 3, oy_)], fill=AMBER)
    d.line([(ox_, oy_ - 3), (ox_, oy_ + 3)], fill=AMBER)

    # splats
    for x, y, kind in st.splats:
        px, py = sx(x), sy(y)
        if -5 < px < 245 and -5 < py < 245:
            c = (90, 30, 100) if kind == 0 else (40, 90, 120)
            d.line([(px - 2, py - 2), (px + 2, py + 2)], fill=c)
            d.line([(px - 2, py + 2), (px + 2, py - 2)], fill=c)

    # tracers
    for x0, y0, x1, y1, life, col in st.tracers:
        if col == (255, 140, 40):
            d.line([(sx(x0), sy(y0)), (sx(x1), sy(y1))], fill=scale(col, life / 0.3 + 0.2), width=3)
        else:
            d.line([(sx(x0), sy(y0)), (sx(x1), sy(y1))], fill=scale(col, min(1.0, life * 10)))

    # contacts: blips (motion tracker) or resolved genestealers
    for g in st.steals:
        gx, gy = sx(g.x), sy(g.y)
        if g.seen:
            c = STEAL
            d.ellipse([gx - 3, gy - 3, gx + 3, gy + 3], fill=(70, 10, 80), outline=c)
            for a in (0.6, 2.5, 3.8, 5.7):
                ca = a + math.sin(t * 9 + g.speed * 5) * 0.2
                d.line([(gx + math.cos(ca) * 3, gy + math.sin(ca) * 3), (gx + math.cos(ca) * 6, gy + math.sin(ca) * 6)],
                       fill=c)
        else:
            ang = math.atan2(gy - CY, gx - CX) % (2 * math.pi)
            if (sw - ang) % (2 * math.pi) < 0.25:
                g.ping = t
                g.px, g.py = g.x, g.y
            age = t - g.ping
            if age < 2.2:
                bx, by = sx(g.px), sy(g.py)
                kk = 1.0 - age / 2.2
                r = 3 + age * 2
                d.ellipse([bx - r, by - r, bx + r, by + r], outline=scale(BLIP, kk * 0.6))
                d.ellipse([bx - 2.5, by - 2.5, bx + 2.5, by + 2.5], fill=scale(BLIP, kk))

    # terminators
    for i, tm in enumerate(st.terms):
        if not tm.alive:
            continue
        px, py = sx(tm.x), sy(tm.y)
        c = lerp_color(TERM, WHITE, 1.0 if tm.flash > 0 else 0.0)
        d.rectangle([px - 4, py - 4, px + 4, py + 4], fill=TERM_DARK, outline=c)
        fx_, fy_ = math.cos(tm.face), math.sin(tm.face)
        d.line([(px + fx_ * 2, py + fy_ * 2), (px + fx_ * 7, py + fy_ * 7)], fill=c)
        if i == 0:
            d.point([(px, py), (px - 1, py), (px + 1, py)], fill=AMBER)
        if tm.jam > 0 and int(t * 6) % 2:
            _txt(d, (px + 5, py - 11), "JAM", AMBER, 9)

    # ---- HUD ----
    ttl = "HULK: " + st.hulk
    w = _tlen(ttl, 9)
    d.rectangle([CX - w / 2 - 3, 12, CX + w / 2 + 3, 23], fill=(0, 10, 8))
    _txt(d, (CX - w / 2, 13), ttl, BLIP, 9)
    contacts = len(st.steals)
    s2 = "CONTACTS %02d  PURGED %02d" % (contacts, st.kills)
    w = _tlen(s2, 9)
    d.rectangle([CX - w / 2 - 3, 24, CX + w / 2 + 3, 35], fill=(0, 10, 8))
    _txt(d, (CX - w / 2, 25), s2, STEAL if contacts else scale(BLIP, 0.6), 9)

    # squad status pips
    n_alive = len(alive_t)
    lab = "SQUAD " + st.squad
    w = _tlen(lab, 9)
    d.rectangle([CX - 52, 190, CX + 52, 214], fill=(0, 10, 8))
    _txt(d, (CX - w / 2, 191), lab, TERM, 9)
    for i, tm in enumerate(st.terms):
        x = CX - 26 + i * 13
        if tm.alive:
            d.rectangle([x - 4, 203, x + 4, 210], fill=TERM_DARK, outline=TERM)
        else:
            d.line([(x - 4, 203), (x + 4, 210)], fill=RED)
            d.line([(x - 4, 210), (x + 4, 203)], fill=RED)
    # distance to objective
    rem = max(0, int(len(st.path) - 1 - st.s))
    _txt(d, (CX + 36, 179), "%dM" % (rem * 3), AMBER, 9)
    _txt(d, (CX - 56, 179), "HALT" if st.halt else "ADV", AMBER if st.halt else scale(BLIP, 0.7), 9)
    if st.events and st.ending is None:
        txt, age, col = st.events[0]
        if age < 3.5:
            kk = 1.0 if (age > 0.4 or int(age * 20) % 2) else 0.3
            w = _tlen(txt, 9)
            d.rectangle([CX - w / 2 - 2, 216, CX + w / 2 + 2, 226], fill=(0, 10, 8))
            _txt(d, (CX - w / 2, 216), txt, scale(col, kk), 9)

    # ---- endings ----
    if st.ending == "purge":
        if end_age < 3.0:
            # flamer purge washes over the objective chamber
            r = 6 + end_age * 16
            for k2 in range(3):
                rr = r * (1 - k2 * 0.25)
                d.ellipse([ox_ - rr, oy_ - rr, ox_ + rr, oy_ + rr],
                          outline=scale((255, 120 + k2 * 50, 30), 1 - end_age / 3), width=2)
        if end_age > 1.0:
            _banner(d, "PURGE COMPLETE", st.objective, AMBER, t)
    elif st.ending == "lost":
        if end_age > 1.0:
            noise = np.random.randint(0, 60, (120, 120), dtype=np.uint8)
            n_img = Image.fromarray(noise, "L").resize((240, 240), Image.NEAREST)
            g = Image.merge("RGB", (n_img, n_img, n_img))
            img = Image.blend(img, g, min(1.0, (end_age - 1.0) / 1.5))
            d = ImageDraw.Draw(img)
        if end_age > 1.5:
            _banner(d, "SIGNAL LOST", "SQUAD " + st.squad + " OVERRUN", RED, t)
    return img


def _banner(d, title, sub, col, t):
    f14, f9 = font(14), font(9)
    w = max(_tlen(title, 14), _tlen(sub, 9)) + 18
    d.rectangle([CX - w / 2, 100, CX + w / 2, 138], fill=(2, 8, 8), outline=col)
    d.line([(CX - w / 2 + 3, 103), (CX + w / 2 - 3, 103)], fill=scale(col, 0.5))
    tw = _tlen(title, 14)
    _txt(d, (CX - tw / 2, 105), title, col if int(t * 3) % 4 else scale(col, 0.6), 14)
    sw = _tlen(sub, 9)
    _txt(d, (CX - sw / 2, 124), sub, WHITE, 9)
