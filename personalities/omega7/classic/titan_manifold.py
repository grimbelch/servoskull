"""Titan Manifold - the princeps' own systems manifold, read from the Moderati's
command throne.

A 3D wireframe of the Titan strides at the centre (legs swinging, body
bobbing, slowly yawing), ringed by four void-shield generators drawn as
segmented arcs.  Incoming fire flares on the shields and knocks segments out;
a collapsed generator lets hits through and the struck body location lights
amber/red with a damage callout.  Weapon mounts charge and fire, the reactor
heat bar climbs until the plasma is vented, and a stride indicator ticks off
footfalls.  Each engagement ends with repair crews restoring the systems.
"""

from __future__ import annotations

import math
import random

import numpy as np
from PIL import Image, ImageDraw

from ..lore._common import CX, CY, Session, font, lerp_color, scale
from ._phosphor import (AMBER, GREEN, GREEN_DIM, GREEN_FAINT, GREEN_HI, GREEN_MID, RED,
                        Phosphor, blank)

NAME = "titan_manifold"

_rng = random.Random()
_session = Session()
_ph = Phosphor(decay=0.66, bloom=0.55, flicker=0.03)

# ------------------------------------------------------------------ text ---
_TXT: dict = {}
_LEN: dict = {}


def _dyn(text):
    return any(c.isdigit() for c in text)


def _tlen(text, size):
    """Text width; strings with digits are measured per character (see _txt)."""
    k = (text, size)
    w = _LEN.get(k)
    if w is None:
        if _dyn(text) and len(text) > 1:
            return sum(_tlen(c, size) for c in text)
        if len(_LEN) > 500:
            _LEN.clear()
        w = _LEN[k] = font(size).getlength(text)
    return w


def _txt(d, x, y, text, fill, size=10):
    k = (text, size)
    m = _TXT.get(k)
    if m is None and len(text) > 1 and _dyn(text):
        # changing numeric readouts: blit cached glyphs one by one instead of
        # rasterising a new string every frame
        for c in text:
            _txt(d, x, y, c, fill, size)
            x += _tlen(c, size)
        return
    if m is None:
        if len(_TXT) > 500:
            _TXT.clear()
        f = font(size)
        b = f.getbbox(text)
        m = Image.new("L", (max(1, int(b[2]) + 2), max(1, int(b[3]) + 2)), 0)
        ImageDraw.Draw(m).text((0, 0), text, fill=255, font=f)
        _TXT[k] = m
    d.bitmap((int(round(x)), int(round(y))), m, fill=fill)


def _txtc(d, y, text, fill, size=10, x=CX):
    _txt(d, x - _tlen(text, size) / 2, y, text, fill, size)


def _txtr(d, x, y, text, fill, size=10):
    _txt(d, x - _tlen(text, size), y, text, fill, size)


# ------------------------------------------------------------- the model ---
MX, MY = CX, 110.0        # model anchor on screen
PARTS = ["HEAD", "CARAPACE", "L ARM", "R ARM", "L LEG", "R LEG"]
_BOX_EDGES = [(0, 1), (1, 3), (3, 2), (2, 0), (4, 5), (5, 7), (7, 6), (6, 4),
              (0, 4), (1, 5), (2, 6), (3, 7)]


def _box(c, s):
    cx, cy, cz = c
    sx, sy, sz = s[0] / 2, s[1] / 2, s[2] / 2
    return [(cx + a * sx, cy + b * sy, cz + e * sz) for a in (-1, 1) for b in (-1, 1) for e in (-1, 1)]


def _model(phase):
    """Returns list of (points[8 or 2], edges, part index)."""
    items = []
    bob = 1.5 * abs(math.sin(phase))
    sway = 0.03 * math.sin(phase)
    by = bob
    # static-ish body
    items.append((_box((0, -50 + by, -6), (12, 10, 12)), 0))                 # head
    items.append((_box((0, -33 + by, 0), (46, 20, 28)), 1))                  # carapace
    items.append((_box((-12, -47 + by, 6), (12, 6, 12)), 1))                 # missile pods
    items.append((_box((12, -47 + by, 6), (12, 6, 12)), 1))
    items.append((_box((0, -17 + by, 0), (20, 10, 16)), 1))                  # waist
    # arm weapons
    items.append((_box((-31, -35 + by, 0), (14, 10, 14)), 2))                # L shoulder
    items.append((_box((-32, -18 + by, -6), (12, 22, 12)), 2))               # L weapon body
    items.append((_box((-32, -4 + by, -12), (8, 8, 20)), 2))                 # L barrel
    items.append((_box((31, -35 + by, 0), (14, 10, 14)), 3))
    items.append((_box((32, -18 + by, -6), (13, 22, 13)), 3))
    items.append((_box((32, -5 + by, -12), (10, 10, 16)), 3))
    # legs (walking)
    for side, part in ((-1, 4), (1, 5)):
        sw = math.sin(phase + (0 if side < 0 else math.pi))
        lift = max(0.0, math.cos(phase + (0 if side < 0 else math.pi))) * 5
        hip = (side * 11, -12 + by, 0)
        knee = (side * 14, 8 + by - lift * 0.5, -6 + sw * 9)
        ankle = (side * 13, 32 - lift, 2 + sw * 12)
        for a, b, w in ((hip, knee, 5), (knee, ankle, 4)):
            items.append(([(a[0] - w, a[1], a[2]), (b[0] - w, b[1], b[2]),
                           (a[0] + w, a[1], a[2]), (b[0] + w, b[1], b[2])], part))
        items.append((_box((ankle[0], ankle[1] + 3, ankle[2] - 2), (14, 5, 20)), part))
    return items, sway


def _limb_edges(n):
    return _BOX_EDGES if n == 8 else [(0, 1), (2, 3), (0, 2), (1, 3)]


# ---------------------------------------------------------------- data ---
_NAMES = ["IMPERIUS DOMINATUS", "INVIGILATA", "MORTIS VULT", "LEX IMPERIALIS",
          "PRAETORIAN ULTIMA", "FIDES PROMETHEUS", "IRA DEI", "VULPINE VIGILANS"]
_CLASSES = ["WARLORD", "REAVER", "WARLORD", "WARBRINGER"]
_LEGIO = ["LEGIO IGNATUM", "LEGIO METALICA", "LEGIO GRYPHONICUS", "LEGIO TEMPESTUS",
          "LEGIO ASTORUM", "LEGIO SOLARIA"]
_WEAPONS = [("VOLCANO", 0.09), ("MACRO GAT", 0.28), ("MISSILES", 0.14)]  # name, charge/s
_WEAPONS_R = [("PLASMA", 0.08), ("MELTA", 0.16), ("LASER BL", 0.12)]

_S: dict = {}


def _new_engagement(t0):
    s = _S
    s["t0"] = t0
    s["name"] = _rng.choice(_NAMES)
    s["cls"] = _rng.choice(_CLASSES)
    s["legio"] = _rng.choice(_LEGIO)
    s["shield"] = [1.0, 1.0, 1.0, 1.0]
    s["down_t"] = [None] * 4
    s["dmg"] = [0.0] * 6
    s["dmg_t"] = [-10.0] * 6
    s["wl"] = _rng.choice(_WEAPONS)
    s["wr"] = _rng.choice(_WEAPONS_R)
    s["charge"] = [0.6, 0.3, 0.8]
    s["fire_t"] = [-10.0, -10.0, -10.0]
    s["heat"] = 0.25
    s["vent_t"] = None
    s["hits"] = []
    s["next_hit"] = 18.0
    s["alerts"] = []
    s["len"] = _rng.uniform(78, 92)
    s["eng0"] = _rng.uniform(12, 16)
    s["eng1"] = s["len"] - _rng.uniform(22, 26)


def _reset():
    _S.clear()
    _ph.reset()
    s = _S
    s["bg"] = _static_bg()
    s["phase"] = 0.0
    s["prev"] = None
    s["steps"] = 0
    _new_engagement(0.0)


def _static_bg():
    img = Image.new("RGB", (240, 240), (0, 0, 0))
    d = ImageDraw.Draw(img)
    # range rings and crosshair ticks behind the Titan
    for r in (48, 72):
        d.arc([MX - r, MY - r, MX + r, MY + r], 0, 360, fill=GREEN_FAINT)
    for i in range(24):
        a = math.radians(i * 15)
        d.line([(CX + 93 * math.cos(a), CY + 93 * math.sin(a)),
                (CX + 96 * math.cos(a), CY + 96 * math.sin(a))], fill=GREEN_DIM)
    return img


def _alert(text, col, t):
    s = _S
    s["alerts"].append((t, text, col))
    if len(s["alerts"]) > 3:
        s["alerts"].pop(0)


def _quad_of(angle_deg):
    return int(((angle_deg + 45) % 360) // 90)   # 0=right 1=bottom 2=left 3=top


_QUAD_PARTS = {0: [3, 5, 1], 1: [4, 5], 2: [2, 4, 1], 3: [0, 1]}
_QNAME = ["DEXTER", "INFERIOR", "SINISTER", "SUPERIOR"]


def _update(lt, dt):
    s = _S
    engaged = s["eng0"] <= lt < s["eng1"]
    s["walk"] = 0.9 if lt < s["eng0"] else (0.55 if engaged else 0.75)
    # incoming fire
    if engaged and lt >= s["next_hit"]:
        ang = _rng.uniform(0, 360)
        if _rng.random() < 0.5:
            ang = _rng.choice((0, 180)) + _rng.uniform(-40, 40)
        q = _quad_of(ang)
        s["hits"].append((lt, ang))
        if s["shield"][q] > 0:
            s["shield"][q] = max(0.0, s["shield"][q] - _rng.uniform(0.14, 0.3))
            if s["shield"][q] <= 0:
                s["down_t"][q] = lt
                _alert("VOID %s COLLAPSED" % _QNAME[q], RED, lt)
        else:
            p = _rng.choice(_QUAD_PARTS[q])
            s["dmg"][p] = min(1.0, s["dmg"][p] + _rng.uniform(0.3, 0.55))
            s["dmg_t"][p] = lt
            _alert("%s HIT - %s" % (PARTS[p], "CRITICAL" if s["dmg"][p] > 0.7 else "DAMAGED"),
                   RED if s["dmg"][p] > 0.7 else AMBER, lt)
        s["next_hit"] = lt + _rng.uniform(0.7, 2.6)
    s["hits"] = [h for h in s["hits"] if lt - h[0] < 1.2]
    # shield regeneration
    for q in range(4):
        if s["down_t"][q] is not None:
            if lt - s["down_t"][q] > (6.0 if engaged else 2.0):
                s["down_t"][q] = None
                _alert("VOID %s RESTORED" % _QNAME[q], GREEN_HI, lt)
        else:
            s["shield"][q] = min(1.0, s["shield"][q] + dt * (0.03 if engaged else 0.12))
            if 0 < s["shield"][q] < 0.02:
                pass
    # weapons
    rates = [s["wl"][1], s["wr"][1], 0.1]
    for i in range(3):
        s["charge"][i] = min(1.0, s["charge"][i] + dt * rates[i])
        if engaged and s["charge"][i] >= 1.0 and s["vent_t"] is None and _rng.random() < 0.02:
            s["charge"][i] = 0.0
            s["fire_t"][i] = lt
            s["heat"] += (0.12, 0.14, 0.08)[i]
    # reactor
    s["heat"] += dt * (0.004 * s["walk"] - 0.006)
    if s["vent_t"] is None and s["heat"] > 0.95:
        s["vent_t"] = lt
        _alert("REACTOR SURGE - VENTING", RED, lt)
    if s["vent_t"] is not None:
        s["heat"] -= dt * 0.18
        if lt - s["vent_t"] > 3.5:
            s["vent_t"] = None
            _alert("PLASMA VENTED", GREEN_HI, lt)
    s["heat"] = max(0.15, min(1.0, s["heat"]))
    # repairs after the engagement
    if lt >= s["eng1"]:
        for p in range(6):
            if s["dmg"][p] > 0:
                s["dmg"][p] = max(0.0, s["dmg"][p] - dt * 0.06)


def _part_col(s, p, lt, blink):
    dm = s["dmg"][p]
    if dm > 0.7:
        return RED if blink else AMBER
    if dm > 0.25:
        return AMBER
    if lt - s["dmg_t"][p] < 0.4:
        return GREEN_HI
    return None


def render(bezel, mask, now: float) -> Image.Image:
    if _session.fresh(now) or not _S:
        _reset()
    s = _S
    tt = _session.t(now)
    dt = 1 / 30.0 if s["prev"] is None else max(0.0, min(0.2, tt - s["prev"]))
    s["prev"] = tt
    lt = tt - s["t0"]
    if lt >= s["len"]:
        _new_engagement(tt)
        lt = 0.0
    _update(lt, dt)
    blink = int(tt * 4) % 2 == 0

    old = s["phase"]
    s["phase"] += dt * 2.6 * s["walk"]
    if int(old / math.pi) != int(s["phase"] / math.pi):
        s["steps"] += 1
        s["foot_t"] = tt
    ph = s["phase"]

    img = s["bg"].copy()
    d = ImageDraw.Draw(img)

    # ---------------- Titan wireframe
    items, sway = _model(ph)
    yaw = 0.55 * math.sin(tt * 0.19) + 0.25
    pitch = -0.18
    cyw, syw = math.cos(yaw), math.sin(yaw)
    cp, sp = math.cos(pitch), math.sin(pitch)
    R = np.array([[cyw, 0, syw], [0, 1, 0], [-syw, 0, cyw]], np.float32)
    R = np.array([[1, 0, 0], [0, cp, -sp], [0, sp, cp]], np.float32) @ R
    allp = np.array([p for it in items for p in it[0]], np.float32)
    q = allp @ R.T
    f = 250.0 / (q[:, 2] + 250.0) * 1.02
    sx = (MX + q[:, 0] * f).tolist()
    sy = (MY + q[:, 1] * f).tolist()
    zz = q[:, 2].tolist()
    k = 0
    damaged_pos = {}
    for pts, part in items:
        n = len(pts)
        pc = _part_col(s, part, lt, blink)
        for a, b in _limb_edges(n):
            ia, ib = k + a, k + b
            z = (zz[ia] + zz[ib]) * 0.5
            if pc is not None:
                col = pc
            else:
                col = GREEN_HI if z < -12 else (GREEN if z < 0 else (GREEN_MID if z < 10 else GREEN_DIM))
            d.line([(sx[ia], sy[ia]), (sx[ib], sy[ib])], fill=col)
        if pc is not None and part not in damaged_pos and s["dmg"][part] > 0.25:
            damaged_pos[part] = (sum(sx[k:k + n]) / n, sum(sy[k:k + n]) / n)
        k += n

    # damage callouts
    for part, (px, py) in damaged_pos.items():
        col = RED if s["dmg"][part] > 0.7 else AMBER
        rr = 11 + 2 * math.sin(tt * 6)
        for sxn, syn in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
            cx_, cy_ = px + sxn * rr, py + syn * rr
            d.line([(cx_, cy_), (cx_ - sxn * 4, cy_)], fill=col)
            d.line([(cx_, cy_), (cx_, cy_ - syn * 4)], fill=col)

    # ---------------- void shield generators (segmented arcs)
    r0, r1 = 101, 106
    hitq = {}
    for (ht, ang) in s["hits"]:
        hitq[_quad_of(ang)] = max(hitq.get(_quad_of(ang), 0.0), 1 - (lt - ht) / 1.2)
    for qd in range(4):
        base = qd * 90 - 45
        st = s["shield"][qd]
        lit = int(math.ceil(st * 9 - 1e-6))
        down = s["down_t"][qd] is not None
        for j in range(9):
            a0 = base + 3 + j * 9.4
            if down:
                col = RED if (blink and lt - s["down_t"][qd] < 3) else scale(RED, 0.35)
            elif j < lit:
                col = GREEN if st > 0.45 else AMBER
                if qd in hitq:
                    col = lerp_color(col, GREEN_HI, hitq[qd])
            else:
                col = GREEN_FAINT
            d.arc([CX - r1, CY - r1, CX + r1, CY + r1], a0, a0 + 7.4, fill=col, width=4)
    # impact flares
    for (ht, ang) in s["hits"]:
        age = lt - ht
        a = math.radians(ang)
        rr = 99 - age * 12
        x, y = CX + rr * math.cos(a), CY + rr * math.sin(a)
        rad = 3 + age * 10
        c = scale(GREEN_HI, 1 - age / 1.2)
        d.arc([x - rad, y - rad, x + rad, y + rad], ang + 110, ang + 250, fill=c, width=2)
        x2, y2 = CX + 120 * math.cos(a), CY + 120 * math.sin(a)
        if age < 0.25:
            d.line([(x2, y2), (CX + 104 * math.cos(a), CY + 104 * math.sin(a))], fill=AMBER, width=2)

    # ---------------- weapon mounts
    wnames = [s["wl"][0], s["wr"][0], "CARAPACE"]
    for i, (xa, ya, right) in enumerate(((30, 80, False), (210, 80, True), (30, 118, False))):
        ch = s["charge"][i]
        ready = ch >= 1.0
        fired = lt - s["fire_t"][i] < 0.5
        col = GREEN_HI if fired else (GREEN if ready else GREEN_MID)
        name = wnames[i]
        if right:
            _txtr(d, xa, ya, name, col, 9)
            bx0 = xa - 40
        else:
            _txt(d, xa, ya, name, col, 9)
            bx0 = xa
        d.rectangle([bx0, ya + 12, bx0 + 40, ya + 16], outline=GREEN_DIM)
        d.rectangle([bx0 + 1, ya + 13, bx0 + 1 + 38 * ch, ya + 15], fill=GREEN if not ready else GREEN_HI)
        tag = "FIRE" if fired else ("READY" if ready else "%d%%" % int(ch * 100))
        tcol = AMBER if fired else (GREEN_HI if ready else GREEN_DIM)
        if right:
            _txtr(d, xa, ya + 18, tag, tcol, 9)
        else:
            _txt(d, xa, ya + 18, tag, tcol, 9)
    # muzzle flashes
    for i, side in ((0, -1), (1, 1)):
        age = lt - s["fire_t"][i]
        if age < 0.35:
            x0 = MX + side * 40
            y0 = MY + 6
            L = 20 + age * 120
            d.line([(x0, y0), (x0 + side * L * 0.3, y0 + 4), (x0 + side * L * 0.5, y0 - L)], fill=GREEN_HI)
    if lt - s["fire_t"][2] < 0.6:
        age = lt - s["fire_t"][2]
        for m in (-1, 1):
            x0, y0 = MX + m * 12, MY - 60 - age * 60
            d.line([(x0, y0), (x0, y0 + 8)], fill=GREEN_HI)

    # right column: princeps / stride
    _txtr(d, 210, 120, "STRIDE", GREEN_DIM, 9)
    spd = s["walk"] * 4.8
    _txtr(d, 210, 130, "%.1f KPH" % (spd * 3.6), GREEN, 9)
    ft = tt - s.get("foot_t", -10)
    lf = s["steps"] % 2 == 0
    for j, on in enumerate((lf, not lf)):
        x = 184 + j * 14
        c = GREEN_HI if (on and ft < 0.3) else (GREEN_MID if on else GREEN_DIM)
        d.rectangle([x, 143, x + 9, 148], fill=c if on else None, outline=c)

    # ---------------- reactor heat bar
    heat = s["heat"]
    yb = 172
    w = 110
    x0 = CX - w / 2
    venting = s["vent_t"] is not None
    _txt(d, x0, yb - 11, "VENTING" if venting else "REACTOR", (AMBER if blink else GREEN_MID) if venting else GREEN_MID, 9)
    _txtr(d, x0 + w, yb - 11, "%d%%" % int(heat * 100), GREEN if heat < 0.7 else (AMBER if heat < 0.9 else RED), 9)
    segs = 22
    lit = int(heat * segs)
    for j in range(segs):
        c = GREEN if j < segs * 0.65 else (AMBER if j < segs * 0.85 else RED)
        if j >= lit:
            c = GREEN_FAINT
        xx = x0 + j * w / segs
        d.rectangle([xx, yb, xx + w / segs - 2, yb + 5], fill=c)

    # ---------------- header
    _txtc(d, 27, s["name"], GREEN_HI, 9)
    vs = sum(1 for q_ in range(4) if s["down_t"][q_] is None)
    _txtc(d, 41, "VOID %d/4  %d%%" % (vs, int(25 * sum(s["shield"]))), GREEN if vs == 4 else AMBER, 9)

    # ---------------- status / alerts
    ya = 188
    if s["alerts"] and lt - s["alerts"][-1][0] < 3.0:
        at, text, col = s["alerts"][-1]
        if col in (RED, AMBER) and not blink and lt - at < 1.2:
            col = GREEN_HI
        _txtc(d, ya, text, col, 10)
    else:
        if lt < s["eng0"]:
            msg, c = s["cls"] + " - " + s["legio"], GREEN_MID
        elif lt < s["eng1"]:
            msg, c = "ENGAGED - MAINTAIN FIRE", GREEN
        else:
            nd = sum(1 for v in s["dmg"] if v > 0.02)
            msg, c = ("ENGINSEERS REPAIRING" if nd else "ALL SYSTEMS NOMINAL"), GREEN_MID
        _txtc(d, ya, msg, c, 9)
    # compact damage summary
    for i, p in enumerate(PARTS):
        dm = s["dmg"][i]
        c = GREEN_MID if dm < 0.02 else (AMBER if dm < 0.7 else RED)
        x = CX - 30 + i * 11
        d.rectangle([x, 206, x + 7, 210], outline=c, fill=c if dm >= 0.02 else None)
    return _ph.compose(img)
