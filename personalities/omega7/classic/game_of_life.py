"""Cellular Cogitation – Conway's Life on a 60x60 toroidal grid.

numpy-vectorised Life with age-shaded cells (newborns flare, elders dim),
phosphor ghosts of dying cells, a library of classic genomes (Gosper gun,
pulsars, R-pentomino, acorn, diehard, glider fleets, HighLife replicators) and
symmetric/random soups. Generation and population readouts with a population
sparkline; stagnation is detected and the grid is re-seeded behind a
"GENOME RESEQUENCED" scan-wipe.
"""

from __future__ import annotations

import math
import random
from collections import deque

import numpy as np
from PIL import Image, ImageDraw

from ..lore._common import CX, CY, Session, font, scale
from ._phosphor import (AMBER, GREEN, GREEN_DIM, GREEN_FAINT, GREEN_HI, GREEN_MID, RED,
                        Phosphor)

NAME = "game_of_life"

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
_ph = Phosphor(decay=0.5, bloom=0.6)

N = 60
CELL = 4

# colour by age (0 = newborn)
_AGE_LUT = np.zeros((64, 3), dtype=np.float32)
for _a in range(64):
    if _a == 0:
        c = GREEN_HI
    elif _a < 3:
        c = tuple(int(GREEN_HI[i] * (1 - _a / 3) + GREEN[i] * (_a / 3)) for i in range(3))
    elif _a < 24:
        k = (_a - 3) / 21
        c = tuple(int(GREEN[i] * (1 - k) + GREEN_MID[i] * k) for i in range(3))
    else:
        k = min(1.0, (_a - 24) / 30)
        c = tuple(int(GREEN_MID[i] * (1 - k * 0.45) + GREEN_DIM[i] * k * 0.45) for i in range(3))
    _AGE_LUT[_a] = c
_GHOST = np.array(GREEN_DIM, dtype=np.float32) * 1.3

_yy, _xx = np.mgrid[0:240, 0:240]
_GAP = ((_xx % CELL == CELL - 1) | (_yy % CELL == CELL - 1))
_CELLMASK = (~_GAP).astype(np.float32)[..., None]
_rad = np.sqrt((_xx - CX + 0.5) ** 2 + (_yy - CY + 0.5) ** 2)
# faint lattice dots at every 5th cell corner
_LATTICE = np.zeros((240, 240, 3), dtype=np.float32)
_LATTICE[((_xx % 20) == 19) & ((_yy % 20) == 19)] = GREEN_FAINT
# HUD bands are dimmed so readouts stay legible over the colony
_DIM = np.ones((240, 1, 1), dtype=np.float32)
_DIM[12:44] = 0.22
_DIM[176:214] = 0.22
_LAT8 = (_LATTICE * _DIM).astype(np.uint8)
_CM8 = (~_GAP).astype(np.uint8)[..., None]
_CDIM = np.ones((N, 1, 1), dtype=np.float32)
_CDIM[3:11] = 0.22
_CDIM[44:54] = 0.22


def _pat(rows):
    return np.array([[1 if ch == "O" else 0 for ch in r] for r in rows], dtype=np.uint8)


GUN = _pat([
    "........................O...........",
    "......................O.O...........",
    "............OO......OO............OO",
    "...........O...O....OO............OO",
    "OO........O.....O...OO..............",
    "OO........O...O.OO....O.O...........",
    "..........O.....O.......O...........",
    "...........O...O....................",
    "............OO......................",
])
PULSAR = _pat([
    "..OOO...OOO..", ".............", "O....O.O....O", "O....O.O....O", "O....O.O....O",
    "..OOO...OOO..", ".............", "..OOO...OOO..", "O....O.O....O", "O....O.O....O",
    "O....O.O....O", ".............", "..OOO...OOO..",
])
PENTA = _pat(["..O....O..", "OO.OOOO.OO", "..O....O.."])
RPENT = _pat([".OO", "OO.", ".O."])
ACORN = _pat([".O.....", "...O...", "OO..OOO"])
DIEHARD = _pat(["......O.", "OO......", ".O...OOO"])
GLIDER = _pat([".O.", "..O", "OOO"])
LWSS = _pat([".O..O", "O....", "O...O", "OOOO."])
REPL = _pat(["..OOO", ".O..O", "O...O", "O..O.", "OOO.."])

CONWAY = ((3,), (2, 3), "B3/S23")
HIGHLIFE = ((3, 6), (2, 3), "B36/S23")

_S = {}


def _stamp(g, p, r, c):
    h, w = p.shape
    rr = (np.arange(h) + r) % N
    cc = (np.arange(w) + c) % N
    g[np.ix_(rr, cc)] |= p


def _seed(kind):
    g = np.zeros((N, N), dtype=np.uint8)
    rule = CONWAY
    c0 = N // 2
    if kind == "GOSPER GUN":
        _stamp(g, GUN, 12, 12)
        _stamp(g, np.flipud(np.fliplr(GUN)), 38, 12)
    elif kind == "PULSAR ARRAY":
        for (r, c) in ((8, 8), (8, 39), (39, 8), (39, 39)):
            _stamp(g, PULSAR, r, c)
        _stamp(g, PENTA.T, 25, 29)
        _stamp(g, PENTA, 29, 25)
    elif kind == "R-PENTOMINO":
        _stamp(g, RPENT, c0 - 1, c0 - 1)
    elif kind == "ACORN":
        _stamp(g, ACORN, c0 - 1, c0 - 3)
    elif kind == "DIEHARD":
        _stamp(g, DIEHARD, c0 - 1, c0 - 4)
    elif kind == "GLIDER FLEET":
        for i in range(10):
            p = GLIDER
            for _ in range(_rng.randrange(4)):
                p = np.rot90(p)
            _stamp(g, p, _rng.randrange(N), _rng.randrange(N))
        for i in range(3):
            _stamp(g, LWSS, 10 + i * 16, 5 + i * 6)
    elif kind == "SYMMETRIC SOUP":
        q = (np.random.default_rng(_rng.randrange(1 << 30)).random((14, 14)) < 0.38).astype(np.uint8)
        blk = np.block([[q, np.fliplr(q)], [np.flipud(q), np.flipud(np.fliplr(q))]])
        _stamp(g, blk, c0 - 14, c0 - 14)
    elif kind == "HIGHLIFE BLOOM":
        rule = HIGHLIFE
        rr = np.random.default_rng(_rng.randrange(1 << 30)).random((N, N))
        yy, xx = np.mgrid[0:N, 0:N]
        g = ((rr < 0.18) & ((yy - c0) ** 2 + (xx - c0) ** 2 < 14 ** 2)).astype(np.uint8)
        for (r, c) in ((c0 - 18, c0 - 3), (c0 + 14, c0 - 3), (c0 - 3, c0 - 18), (c0 - 3, c0 + 14)):
            _stamp(g, REPL, r, c)
    else:  # PRIMORDIAL SOUP
        rr = np.random.default_rng(_rng.randrange(1 << 30)).random((N, N))
        yy, xx = np.mgrid[0:N, 0:N]
        circ = (yy - c0) ** 2 + (xx - c0) ** 2 < 24 ** 2
        g = ((rr < 0.33) & circ).astype(np.uint8)
    return g, rule


_KINDS = ["PRIMORDIAL SOUP", "GOSPER GUN", "R-PENTOMINO", "SYMMETRIC SOUP", "PULSAR ARRAY",
          "ACORN", "GLIDER FLEET", "HIGHLIFE BLOOM", "DIEHARD"]
_MIN_T = {"PULSAR ARRAY": 14.0, "GOSPER GUN": 24.0, "DIEHARD": 13.0, "HIGHLIFE BLOOM": 16.0}


def _load(kind, t):
    g, rule = _seed(kind)
    _S.update(grid=g, age=np.zeros((N, N), dtype=np.int16), ghost=np.zeros((N, N), dtype=np.float32),
              rule=rule, kind=kind, gen=0, epoch_t=t, hashes=deque(maxlen=48), pop_hist=deque(maxlen=120),
              acc=0.0, peak=int(g.sum()), births=0, deaths=0)
    _S["pop_hist"].append(int(g.sum()))
    _S["age"][g == 1] = 0


def _reset(t):
    _S.clear()
    order = _KINDS[:]
    _rng.shuffle(order)
    order.remove("PRIMORDIAL SOUP")
    order.insert(0, "PRIMORDIAL SOUP")
    _S["order"] = order
    _S["oi"] = 0
    _S["trans"] = None
    _S["epochs"] = 1
    _load(order[0], t)
    _ph.reset()


def _step():
    g = _S["grid"]
    n = (np.roll(g, 1, 0) + np.roll(g, -1, 0) + np.roll(g, 1, 1) + np.roll(g, -1, 1)
         + np.roll(np.roll(g, 1, 0), 1, 1) + np.roll(np.roll(g, 1, 0), -1, 1)
         + np.roll(np.roll(g, -1, 0), 1, 1) + np.roll(np.roll(g, -1, 0), -1, 1))
    born_set, surv_set, _ = _S["rule"]
    lb = np.zeros(9, dtype=bool)
    lb[list(born_set)] = True
    ls = np.zeros(9, dtype=bool)
    ls[list(surv_set)] = True
    alive = g == 1
    born = lb[n] & ~alive
    surv = ls[n] & alive
    new = (born | surv).astype(np.uint8)
    died = (g == 1) & (new == 0)
    age = _S["age"]
    age[surv] += 1
    np.minimum(age, 63, out=age)
    age[born] = 0
    gh = _S["ghost"]
    gh *= 0.72
    gh[died] = 1.0
    gh[new == 1] = 0.0
    _S["grid"] = new
    _S["gen"] += 1
    _S["births"] = int(born.sum())
    _S["deaths"] = int(died.sum())
    pop = int(new.sum())
    _S["pop_hist"].append(pop)
    _S["peak"] = max(_S["peak"], pop)
    h = hash(np.packbits(new).tobytes())
    periodic = h in _S["hashes"]
    _S["hashes"].append(h)
    return periodic, pop


def _stagnant(periodic, pop, t):
    age = t - _S["epoch_t"]
    if pop == 0:
        return age > 3.0
    min_t = _MIN_T.get(_S["kind"], 9.0)
    if age < min_t:
        return False
    if periodic:
        return True
    ph = _S["pop_hist"]
    if len(ph) >= 110 and max(ph) - min(ph) <= max(4, int(0.03 * pop)):
        return True
    return age > 60.0


def _start_transition(t, reason):
    _S["oi"] = (_S["oi"] + 1) % len(_S["order"])
    nk = _S["order"][_S["oi"]]
    g, rule = _seed(nk)
    _S["trans"] = {"t0": t, "new_kind": nk, "new": g, "rule": rule, "reason": reason}


def _render_cells(t):
    g = _S["grid"]
    age = _S["age"]
    cols = _AGE_LUT[np.minimum(age, 63)] * g[..., None]
    gh = _S["ghost"][..., None] * _GHOST
    cols = np.maximum(cols, gh)
    tr = _S["trans"]
    if tr is not None:
        # scan-wipe: rows above the scanline show the new genome
        prog = min(1.0, (t - tr["t0"]) / 1.6)
        row = int(prog * N)
        if row > 0:
            ng = tr["new"][:row]
            cols[:row] = _AGE_LUT[0] * 0.6 * ng[..., None]
        _S["scan_row"] = row
    cols *= _CDIM
    c8 = cols.astype(np.uint8)
    big = np.repeat(np.repeat(c8, CELL, axis=0), CELL, axis=1)
    big *= _CM8
    np.maximum(big, _LAT8, out=big)
    return big


def _sparkline(d, t):
    ph = list(_S["pop_hist"])
    if len(ph) < 2:
        return
    x0, x1, y0, y1 = CX - 58, CX + 58, 182, 198
    lo, hi = min(ph), max(ph)
    rng_ = max(1, hi - lo)
    n = len(ph)
    pts = []
    for i, v in enumerate(ph):
        x = x1 - (n - 1 - i) * (x1 - x0) / 119
        y = y1 - (v - lo) / rng_ * (y1 - y0)
        pts.append((x, y))
    d.line([(x0, y1 + 1), (x1, y1 + 1)], fill=GREEN_DIM)
    for i in range(0, len(pts), 3):
        d.line([(pts[i][0], y1), pts[i]], fill=GREEN_FAINT)
    d.line(pts, fill=GREEN)
    d.rectangle([pts[-1][0] - 1, pts[-1][1] - 1, pts[-1][0] + 1, pts[-1][1] + 1], fill=GREEN_HI)
    _txt(d, x0 - 3, y0 - 4, f"{hi}", GREEN_DIM, 9, "r")
    _txt(d, x0 - 3, y1 - 8, f"{lo}", GREEN_DIM, 9, "r")


def render(bezel, mask, now: float) -> Image.Image:
    if _session.fresh(now) or not _S:
        _reset(now)
        _S["prev"] = now
    dt = max(0.0, min(0.1, now - _S["prev"]))
    _S["prev"] = now

    tr = _S["trans"]
    if tr is None:
        rate = 11.0 if _S["kind"] not in ("PULSAR ARRAY",) else 8.0
        _S["acc"] += dt * rate
        steps = 0
        while _S["acc"] >= 1.0 and steps < 3:
            _S["acc"] -= 1.0
            steps += 1
            periodic, pop = _step()
            if _stagnant(periodic, pop, now):
                if pop == 0:
                    reason = "EXTINCTION"
                elif periodic:
                    reason = "OSCILLATOR LOCK"
                elif now - _S["epoch_t"] > 59.0:
                    reason = "EPOCH LIMIT"
                else:
                    reason = "STASIS DETECTED"
                _start_transition(now, reason)
                break
    else:
        if now - tr["t0"] > 2.8:
            _S["epochs"] += 1
            _load(tr["new_kind"], now)
            _S["trans"] = None

    big = _render_cells(now)
    img = Image.fromarray(big)
    d = ImageDraw.Draw(img)

    tr = _S["trans"]
    # ---- HUD
    rule = _S["rule"][2] if tr is None else tr["rule"][2]
    kind = _S["kind"] if tr is None else tr["new_kind"]
    _txt(d, CX, 15, f"GENOME: {kind}", GREEN_MID, 9, "c")
    pop = _S["pop_hist"][-1]
    _txt(d, CX - 6, 28, f"GEN {_S['gen']:05d}", GREEN_HI, 9, "r")
    _txt(d, CX + 6, 28, f"POP {pop:04d}", GREEN_HI, 9, "l")
    _txt(d, CX - 58, 201, f"+{_S['births']:03d}", GREEN, 9, "l")
    _txt(d, CX + 58, 201, f"-{_S['deaths']:03d}", GREEN_MID, 9, "r")
    _txt(d, CX, 201, f"RULE {rule}", GREEN_DIM, 9, "c")
    _sparkline(d, now)

    if tr is not None:
        age = now - tr["t0"]
        row = _S.get("scan_row", 0)
        y = row * CELL
        if age < 1.7:
            d.line([(0, y), (239, y)], fill=GREEN_HI)
            d.line([(0, y - 2), (239, y - 2)], fill=GREEN_MID)
        # banner
        k = min(1.0, age * 4)
        w = 150
        d.rectangle([CX - w / 2, CY - 20, CX + w / 2, CY + 22], fill=(0, 0, 0), outline=scale(GREEN_HI, k))
        d.line([(CX - w / 2 + 3, CY - 17), (CX + w / 2 - 3, CY - 17)], fill=scale(GREEN_DIM, k))
        _txt(d, CX, CY - 14, tr["reason"], scale(AMBER if tr["reason"] != "EXTINCTION" else RED, k), 9, "c")
        on = int(age * 5) % 2 == 0 or age > 1.6
        _txt(d, CX, CY - 2, "GENOME RESEQUENCED", scale(GREEN_HI if on else GREEN_MID, k), 9, "c")
        _txt(d, CX, CY + 10, f"EPOCH {_S['epochs'] + 1:02d}", scale(GREEN_MID, k), 9, "c")
    elif now - _S["epoch_t"] < 2.0 and _S["epochs"] > 1:
        _txt(d, CX, 40, "SEQUENCE ACCEPTED", GREEN_MID if int(now * 6) % 2 else GREEN, 9, "c")

    return _ph.compose(img)
