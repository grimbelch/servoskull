"""Fabricator Matrix - production schematic of a forge-world manufactorum line.

A node graph of stations (ORE -> SMELT -> PRESS -> ASSEMBLY -> BLESSING ->
MUNITORUM) drawn as extruded phosphor boxes joined by animated conveyor links.
Items flow along the links, changing form at each station (ore, ingot, plate,
component, sanctified part).  Each station shows its utilisation and input
queue; the slowest one backs up into an amber bottleneck until a Rite of
Hastening is applied.  Machine spirits occasionally balk, a quota bar fills
through each shift, and shift changes pause the line.
"""

from __future__ import annotations

import math
import random

from PIL import Image, ImageDraw

from ..lore._common import CX, Session, font, scale
from ._phosphor import (AMBER, GREEN, GREEN_DIM, GREEN_FAINT, GREEN_HI, GREEN_MID, RED,
                        Phosphor, blank)

NAME = "fabricator_matrix"

_rng = random.Random()
_session = Session()
_ph = Phosphor(decay=0.6, bloom=0.5, flicker=0.03)

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


# -------------------------------------------------------------- layout ---
BW, BH = 46, 22
ROW1, ROW2 = 70, 138
NODES = [("ORE", 58, ROW1), ("SMELT", 120, ROW1), ("PRESS", 182, ROW1),
         ("ASSEM", 182, ROW2), ("BLESS", 120, ROW2), ("OUT", 58, ROW2)]
DEPTH = (4, -4)       # extrusion offset for the 3D boxes


def _link_pts(i):
    _, x0, y0 = NODES[i]
    _, x1, y1 = NODES[i + 1]
    if y0 == y1:
        sgn = 1 if x1 > x0 else -1
        return [(x0 + sgn * BW / 2, y0), (x1 - sgn * BW / 2, y1)]
    return [(x0, y0 + BH / 2), (x1, y1 - BH / 2)]


LINKS = [_link_pts(i) for i in range(5)]
TRAVEL = [1.5, 1.5, 1.8, 1.5, 1.5]

_SHIFTS = ["PRIMUS", "SECUNDUS", "TERTIUS", "QUARTUS", "QUINTUS", "SEXTUS", "SEPTIMUS"]
_PRODUCTS = ["LASGUN MK IV", "BOLT SHELLS", "LEMAN RUSS PLATE", "SERVO LIMBS",
             "LAS-CELLS", "CHIMERA TRACKS", "FRAG GRENADES", "AUSPEX UNITS"]
_SHIFT_LEN = 80.0

_S: dict = {}


def _new_shift(t0, n):
    s = _S
    s["t0"] = t0
    s["shift"] = n
    s["product"] = _rng.choice(_PRODUCTS)
    base = [0.0, 1.2, 1.25, 1.2, 1.0, 0.0]
    slow = _rng.choice((1, 2, 3, 4))
    base[slow] = _rng.uniform(1.65, 1.95)
    s["proc"] = base
    s["haste"] = [1.0] * 6
    s["src_rate"] = _rng.uniform(1.25, 1.4)
    s["next_src"] = 0.5
    s["queue"] = [0] * 6
    s["busy"] = [None] * 6        # finish time of item in process
    s["util"] = [0.0] * 6
    s["transit"] = []             # (link, start)
    s["made"] = 0
    s["quota"] = _rng.randint(36, 44)
    s["hist"] = [0] * 40
    s["last_hist"] = 0.0
    s["bneck"] = None
    s["bneck_t"] = None
    s["rite_t"] = -10.0
    s["stall"] = None
    s["stall_t"] = -10.0
    s["next_stall"] = _rng.uniform(25, 45)
    s["quota_t"] = None
    s["msg"] = None


def _reset():
    _S.clear()
    _ph.reset()
    _S["bg"] = _static_bg()
    _S["prev"] = None
    _new_shift(0.0, _rng.randrange(len(_SHIFTS)))


def _static_bg():
    img = Image.new("RGB", (240, 240), (0, 0, 0))
    d = ImageDraw.Draw(img)
    for x in range(16, 225, 12):
        for y in range(16, 225, 12):
            if (x - 120) ** 2 + (y - 120) ** 2 < 104 ** 2:
                d.point((x, y), fill=GREEN_FAINT)
    # link rails
    for pts in LINKS:
        (x0, y0), (x1, y1) = pts
        if y0 == y1:
            d.line([(x0, y0 - 3), (x1, y1 - 3)], fill=GREEN_DIM)
            d.line([(x0, y0 + 3), (x1, y1 + 3)], fill=GREEN_DIM)
        else:
            d.line([(x0 - 3, y0), (x1 - 3, y1)], fill=GREEN_DIM)
            d.line([(x0 + 3, y0), (x1 + 3, y1)], fill=GREEN_DIM)
    # extruded box backs
    for name, x, y in NODES:
        x0, y0, x1, y1 = x - BW / 2, y - BH / 2, x + BW / 2, y + BH / 2
        ox, oy = DEPTH
        d.line([(x0 + ox, y0 + oy), (x1 + ox, y0 + oy), (x1 + ox, y1 + oy)], fill=GREEN_DIM)
        d.line([(x0, y0), (x0 + ox, y0 + oy)], fill=GREEN_DIM)
        d.line([(x1, y0), (x1 + ox, y0 + oy)], fill=GREEN_DIM)
        d.line([(x1, y1), (x1 + ox, y1 + oy)], fill=GREEN_DIM)
    return img


def _pos_on(link, u):
    (x0, y0), (x1, y1) = LINKS[link]
    return x0 + (x1 - x0) * u, y0 + (y1 - y0) * u


def _update(lt, dt):
    s = _S
    paused = lt < 3.0 or lt > _SHIFT_LEN - 5.0
    # source
    if not paused and lt >= s["next_src"]:
        s["transit"].append((0, lt))
        s["next_src"] = lt + s["src_rate"] * _rng.uniform(0.75, 1.25)
    # transit arrivals
    keep = []
    for (ln, st) in s["transit"]:
        if lt - st >= TRAVEL[ln]:
            s["queue"][ln + 1] += 1
        else:
            keep.append((ln, st))
    s["transit"] = keep
    # stations
    for i in range(1, 6):
        stalled = s["stall"] == i
        if s["busy"][i] is not None and lt >= s["busy"][i] and not stalled:
            s["busy"][i] = None
            if i < 5:
                s["transit"].append((i, lt))
        if i == 5:
            while s["queue"][5] > 0:
                s["queue"][5] -= 1
                s["made"] += 1
            continue
        if s["busy"][i] is None and s["queue"][i] > 0 and not paused and not stalled:
            s["queue"][i] -= 1
            s["busy"][i] = lt + s["proc"][i] * s["haste"][i] * _rng.uniform(0.85, 1.15)
        on = 1.0 if (s["busy"][i] is not None and not stalled) else 0.0
        s["util"][i] += (on - s["util"][i]) * min(1.0, dt * 0.35)
    s["util"][0] += ((0.0 if paused else 0.8) - s["util"][0]) * min(1.0, dt * 0.5)
    # bottleneck detection and the rite of hastening
    worst = max(range(1, 5), key=lambda i: s["queue"][i])
    if s["queue"][worst] >= 4:
        if s["bneck"] != worst:
            s["bneck"], s["bneck_t"] = worst, lt
        elif lt - s["bneck_t"] > 7.0 and s["haste"][worst] == 1.0:
            s["haste"][worst] = 0.55
            s["rite_t"] = lt
    elif s["queue"][worst] <= 1:
        s["bneck"] = None
    # machine spirit stalls
    if s["stall"] is None and lt >= s["next_stall"] and not paused:
        s["stall"] = _rng.choice((1, 2, 3, 4))
        s["stall_t"] = lt
    if s["stall"] is not None and lt - s["stall_t"] > 6.0:
        s["stall"] = None
        s["next_stall"] = lt + _rng.uniform(30, 50)
    if s["quota_t"] is None and s["made"] >= s["quota"]:
        s["quota_t"] = lt
    # throughput history
    if lt - s["last_hist"] >= 2.0:
        s["last_hist"] = lt
        s["hist"].append(s["made"])
        s["hist"].pop(0)


def _item(d, x, y, stage, col):
    if stage == 0:
        d.ellipse([x - 2, y - 2, x + 2, y + 2], fill=col)
    elif stage == 1:
        d.rectangle([x - 3, y - 1.5, x + 3, y + 1.5], fill=col)
    elif stage == 2:
        d.rectangle([x - 3, y - 3, x + 3, y + 3], outline=col)
    elif stage == 3:
        d.rectangle([x - 3, y - 3, x + 3, y + 3], fill=col)
        d.point((x, y), fill=(0, 0, 0))
    else:
        d.polygon([(x, y - 4), (x + 4, y), (x, y + 4), (x - 4, y)], fill=col)


def render(bezel, mask, now: float) -> Image.Image:
    if _session.fresh(now) or not _S:
        _reset()
    s = _S
    tt = _session.t(now)
    dt = 1 / 30.0 if s["prev"] is None else max(0.0, min(0.2, tt - s["prev"]))
    s["prev"] = tt
    lt = tt - s["t0"]
    if lt >= _SHIFT_LEN:
        _new_shift(tt, s["shift"] + 1)
        lt = 0.0
    _update(lt, dt)
    blink = int(tt * 4) % 2 == 0
    changing = lt > _SHIFT_LEN - 5.0 or lt < 3.0

    img = s["bg"].copy()
    d = ImageDraw.Draw(img)

    # ---------------- conveyor links (moving dashes)
    off = (tt * 14) % 8
    for ln, pts in enumerate(LINKS):
        (x0, y0), (x1, y1) = pts
        L = abs(x1 - x0) + abs(y1 - y0)
        sg = 1 if (x1 - x0 + y1 - y0) > 0 else -1
        col = GREEN_DIM if changing else GREEN_MID
        p = off
        while p < L:
            u0, u1 = p / L, min(L, p + 3) / L
            a, b = _pos_on(ln, u0), _pos_on(ln, u1)
            d.line([a, b], fill=col)
            p += 8
        # arrow head at the far end
        ex, ey = x1, y1
        if y0 == y1:
            d.polygon([(ex, ey), (ex - sg * 4, ey - 3), (ex - sg * 4, ey + 3)], fill=col)
        else:
            d.polygon([(ex, ey), (ex - 3, ey - sg * 4), (ex + 3, ey - sg * 4)], fill=col)

    # ---------------- items in transit
    for (ln, st) in s["transit"]:
        u = min(1.0, (lt - st) / TRAVEL[ln])
        x, y = _pos_on(ln, u)
        _item(d, x, y, ln, GREEN_HI if ln == 4 else GREEN)

    # ---------------- stations
    for i, (name, x, y) in enumerate(NODES):
        x0, y0, x1, y1 = x - BW / 2, y - BH / 2, x + BW / 2, y + BH / 2
        q = s["queue"][i] if i < 5 else 0
        is_b = s["bneck"] == i
        is_st = s["stall"] == i
        col = GREEN
        if is_b:
            col = AMBER
        if is_st:
            col = RED if blink else AMBER
        if changing:
            col = GREEN_MID
        busy = s["busy"][i] is not None and not is_st
        if i in (0, 5):
            busy = not changing
        d.rectangle([x0, y0, x1, y1], fill=(0, 0, 0), outline=col)
        _txt(d, x0 + 3, y0 + 1, name, GREEN_HI if busy else GREEN_MID, 9)
        # utilisation bar
        ut = s["util"][i] if i < 5 else min(1.0, s["made"] / max(1, s["quota"]))
        d.rectangle([x0 + 3, y1 - 6, x1 - 3, y1 - 3], outline=GREEN_DIM)
        d.rectangle([x0 + 4, y1 - 5, x0 + 4 + (BW - 8) * ut, y1 - 4],
                    fill=AMBER if (is_b and ut > 0.9) else GREEN)
        # activity lamp (spinning when busy)
        if busy:
            a = tt * 8 + i
            lx, ly = x1 - 5, y0 + 6
            d.line([(lx - 3 * math.cos(a), ly - 3 * math.sin(a)), (lx + 3 * math.cos(a), ly + 3 * math.sin(a))],
                   fill=GREEN_HI)
        # input queue pips above/below box
        if 0 < i < 5 and q > 0:
            py = y0 - 6 if y == ROW1 else y1 + 3
            for k in range(min(q, 7)):
                px = x0 + 2 + k * 6
                d.rectangle([px, py, px + 3, py + 3], fill=AMBER if q >= 4 else GREEN_MID)
            if q > 7:
                _txt(d, x0 + 44, py - 4, "+", AMBER, 9)
        # rite of hastening flash
        if i == s["bneck"] or (lt - s["rite_t"] < 1.0 and s["haste"][i] < 1):
            pass
        if s["haste"][i] < 1 and lt - s["rite_t"] < 0.8:
            rr = 14 + (lt - s["rite_t"]) * 40
            d.ellipse([x - rr, y - rr, x + rr, y + rr], outline=GREEN_HI)

    # ---------------- throughput graph (between the rows)
    gx0, gy0, gw, gh = 76, 92, 88, 26
    h = s["hist"]
    raw = [max(0, h[k] - h[k - 1]) for k in range(1, len(h))]
    rates = [sum(raw[max(0, k - 2):k + 1]) / len(raw[max(0, k - 2):k + 1]) for k in range(len(raw))]
    mx = 2.5
    d.line([(gx0, gy0 + gh), (gx0 + gw, gy0 + gh)], fill=GREEN_DIM)
    pts = [(gx0 + k * gw / (len(rates) - 1), gy0 + gh - min(1.0, r / mx) * (gh - 4)) for k, r in enumerate(rates)]
    d.line(pts, fill=GREEN)
    _txt(d, gx0, gy0 - 2, "OUTPUT", GREEN_DIM, 9)
    _txtr(d, gx0 + gw, gy0 - 2, "%.1f/M" % (sum(raw[-6:]) * 5.0), GREEN_MID, 9)

    # ---------------- header
    _txtc(d, 18, "FORGE MANUFACTORUM", GREEN_MID, 9)
    _txtc(d, 29, "SHIFT " + _SHIFTS[s["shift"] % len(_SHIFTS)], GREEN_HI, 10)
    _txtc(d, 41, s["product"], GREEN, 9)

    # ---------------- quota bar
    yq = 166
    w = 120
    x0 = CX - w / 2
    frac = min(1.0, s["made"] / s["quota"])
    met = s["quota_t"] is not None
    _txt(d, x0, yq, "QUOTA", GREEN_MID, 9)
    _txtr(d, x0 + w, yq, "%d/%d" % (s["made"], s["quota"]), GREEN_HI if met else GREEN, 9)
    segs = 24
    for k in range(segs):
        xx = x0 + k * w / segs
        c = (GREEN_HI if met else GREEN) if k < int(frac * segs) else GREEN_FAINT
        d.rectangle([xx, yq + 12, xx + w / segs - 2, yq + 17], fill=c)
    # expected-progress marker
    exp = min(1.0, lt / (_SHIFT_LEN - 8))
    mxp = x0 + exp * w
    d.line([(mxp, yq + 10), (mxp, yq + 19)], fill=AMBER)

    # ---------------- status line
    ys = 190
    if lt < 3.0:
        _txtc(d, ys, "SHIFT CHANGE - SERVITORS CYCLE", GREEN_HI if blink else GREEN_MID, 9)
    elif lt > _SHIFT_LEN - 5.0:
        _txtc(d, ys, "END OF SHIFT", GREEN_HI, 10)
        _txtc(d, ys + 12, ("QUOTA MET" if met else "QUOTA SHORTFALL"), GREEN_HI if met else AMBER, 9)
    elif s["stall"] is not None:
        _txtc(d, ys, NODES[s["stall"]][0] + " SPIRIT UNRESPONSIVE", RED if blink else AMBER, 9)
        _txtc(d, ys + 12, "APPLYING SACRED UNGUENTS", GREEN_MID, 9)
    elif lt - s["rite_t"] < 3.0:
        _txtc(d, ys, "RITE OF HASTENING APPLIED", GREEN_HI, 9)
    elif s["bneck"] is not None:
        _txtc(d, ys, "BOTTLENECK: " + NODES[s["bneck"]][0], AMBER if blink else GREEN_MID, 10)
    elif met and lt - s["quota_t"] < 4.0:
        _txtc(d, ys, "QUOTA MET - OMNISSIAH PLEASED", GREEN_HI, 9)
    else:
        _txtc(d, ys, "PRODUCTION NOMINAL", GREEN_MID, 9)
    if met and lt - s["quota_t"] < 0.5:
        k = 1 - (lt - s["quota_t"]) / 0.5
        d.rectangle([x0 - 3, yq + 9, x0 + w + 3, yq + 20], outline=scale(GREEN_HI, k))
    return _ph.compose(img)
