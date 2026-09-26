"""Archeotech Vault - a multi-ring cryptographic lock on a sealed STC vault.

Four concentric cipher rings covered in binary glyphs turn at their own pace.
Ring by ring, from the outside in, the cogitator attacks the cipher: the ring
spins wildly while the key-attempt counter races and the ring's entropy
meter drains, then it decelerates and seats its key glyph in the gate at
twelve o'clock (sometimes a counter-cipher throws it back out first).  With
all four keys seated the rings retract, the core opens on a rotating STC
fragment wireframe, and then the vault reseals behind a fresh lock.
"""

from __future__ import annotations

import math
import random

import numpy as np
from PIL import Image, ImageDraw

from ..lore._common import CX, Session, font, scale
from ._phosphor import (AMBER, GREEN, GREEN_DIM, GREEN_FAINT, GREEN_HI, GREEN_MID, RED,
                        Phosphor, blank)

NAME = "archeotech_vault"

_rng = random.Random()
_session = Session()
_ph = Phosphor(decay=0.7, bloom=0.6, flicker=0.03)

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


# -------------------------------------------------------------- layout ---
VX, VY = CX, 108.0
RINGS = [79.0, 63.0, 47.0, 31.0]      # mid radius of each ring
RW = 6.5                              # half-width of a ring band
GLYPHS = [30, 24, 18, 12]
GATE = -math.pi / 2                   # key seats at twelve o'clock
ROMAN = ["I", "II", "III", "IV"]

_STC = ["LAND RAIDER HULL", "PLASMA COIL", "DATA-CRYSTAL", "RHINO CHASSIS",
        "GELLER NODE", "LAS-FOCUS ARRAY", "MACHINE SPIRIT CORE"]
_VAULTS = ["VAULT SIGMA-7", "VAULT OMICRON", "CRYPT MU-12", "VAULT EXCELSIS",
           "RELIQUARY XI", "VAULT THETA-3"]

T_INTRO = 3.0

_S: dict = {}


# ----------------------------------------------------------- ring glyphs ---
def _glyph_points(r_mid, n, key_idx, pr):
    rs, ths, key = [], [], []
    dth = 2 * math.pi / n
    for g in range(n):
        th0 = g * dth
        is_key = g == key_idx
        if is_key:
            # diamond-in-bars key glyph
            strokes = [((-0.5, 0.0), (0.0, 0.8)), ((0.0, 0.8), (0.5, 0.0)),
                       ((0.5, 0.0), (0.0, -0.8)), ((0.0, -0.8), (-0.5, 0.0)),
                       ((-0.95, -0.9), (-0.95, 0.9)), ((0.95, -0.9), (0.95, 0.9))]
        else:
            bits = int(pr.integers(1, 64))
            strokes = []
            opts = [((-0.7, -0.8), (-0.7, 0.8)), ((0.0, -0.8), (0.0, 0.8)), ((0.7, -0.8), (0.7, 0.8)),
                    ((-0.7, -0.8), (0.7, -0.8)), ((-0.7, 0.0), (0.7, 0.0)), ((-0.7, 0.8), (0.7, 0.8))]
            for b in range(6):
                if bits >> b & 1:
                    strokes.append(opts[b])
        for (a0, b0), (a1, b1) in strokes:
            for u in np.linspace(0, 1, 5):
                a = a0 + (a1 - a0) * u      # tangential (-1..1)
                b = b0 + (b1 - b0) * u      # radial (-1..1)
                rs.append(r_mid + b * (RW - 1.5))
                ths.append(th0 + a * dth * 0.34 * (31.0 / r_mid) ** 0.0)
                key.append(is_key)
    return (np.array(rs, np.float32), np.array(ths, np.float32), np.array(key, bool))


def _new_lock(t0):
    s = _S
    s["t0"] = t0
    pr = np.random.default_rng(_rng.getrandbits(32))
    s["glyph"] = []
    s["keyang"] = []
    for i, (r, n) in enumerate(zip(RINGS, GLYPHS)):
        k = _rng.randrange(n)
        s["glyph"].append(_glyph_points(r, n, k, pr))
        s["keyang"].append(k * 2 * math.pi / n)
    s["rot"] = [_rng.uniform(0, 6.28) for _ in RINGS]
    s["drift"] = [_rng.choice((-1, 1)) * _rng.uniform(0.08, 0.2) for _ in RINGS]
    s["vel"] = [0.0] * 4
    s["state"] = ["idle"] * 4
    s["entropy"] = [1.0] * 4
    s["cur"] = 0
    s["crack_t"] = T_INTRO
    s["dur"] = [_rng.uniform(6.5, 9.0) for _ in RINGS]
    s["reject"] = [_rng.random() < 0.3 for _ in RINGS]
    s["rejected"] = [False] * 4
    s["lock_t"] = [None] * 4
    s["attempts"] = _rng.randint(0x1000, 0x8000)
    s["open_t"] = None
    s["stc"] = _rng.choice(_STC)
    s["vault"] = _rng.choice(_VAULTS)
    s["integ"] = _rng.randint(18, 94)
    s["model"] = _stc_model(s["stc"])
    s["data"] = ["EPOCH M%d" % _rng.randint(18, 25), "MASS %.1fT" % _rng.uniform(0.2, 40),
                 "FIDEL %d%%" % _rng.randint(40, 99), "NODES %d" % _rng.randint(100, 999),
                 "HASH %04X" % _rng.getrandbits(16), "SEALED %dK" % _rng.randint(4, 12)]
    s["msg"] = None
    s["msg_t"] = -10.0


def _stc_model(name):
    """A small wireframe (points, edges) for the recovered fragment."""
    if name in ("DATA-CRYSTAL", "MACHINE SPIRIT CORE"):
        p = (1 + 5 ** 0.5) / 2
        v = []
        for a in (-1, 1):
            for b in (-p, p):
                v += [(0, a, b), (a, b, 0), (b, 0, a)]
        v = np.array(v, np.float32)
        e = [(i, j) for i in range(12) for j in range(i + 1, 12)
             if abs(np.linalg.norm(v[i] - v[j]) - 2.0) < 0.01]
        return v * 12, e
    if name in ("PLASMA COIL", "GELLER NODE", "LAS-FOCUS ARRAY"):
        pts, e = [], []
        n = 14
        for ring, (rr, y) in enumerate(((26, -10), (26, 10), (14, -16), (14, 16))):
            for k in range(n):
                a = 2 * math.pi * k / n
                pts.append((rr * math.cos(a), y, rr * math.sin(a)))
                e.append((ring * n + k, ring * n + (k + 1) % n))
        for k in range(0, n, 2):
            e += [(k, n + k), (k, 2 * n + k), (n + k, 3 * n + k)]
        return np.array(pts, np.float32), e
    # hull: a tapered box with track boxes
    v = np.array([(-16, -10, -30), (16, -10, -30), (16, -10, 28), (-16, -10, 28),
                  (-20, 8, -34), (20, 8, -34), (20, 8, 32), (-20, 8, 32),
                  (-10, -18, -10), (10, -18, -10), (10, -18, 14), (-10, -18, 14)], np.float32)
    e = [(0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4), (0, 4), (1, 5), (2, 6), (3, 7),
         (8, 9), (9, 10), (10, 11), (11, 8), (8, 0), (9, 1), (10, 2), (11, 3)]
    return v * 0.8, e


def _reset():
    _S.clear()
    _ph.reset()
    _S["bg"] = _static_bg()
    _S["prev"] = None
    _new_lock(0.0)


def _static_bg():
    img = Image.new("RGB", (240, 240), (0, 0, 0))
    d = ImageDraw.Draw(img)
    for i in range(48):
        a = 2 * math.pi * i / 48
        r0 = 90 if i % 4 else 88
        d.line([(VX + r0 * math.cos(a), VY + r0 * math.sin(a)),
                (VX + 93 * math.cos(a), VY + 93 * math.sin(a))], fill=GREEN_DIM)
    return img


def _msg(text, col, t):
    _S["msg"], _S["msg_col"], _S["msg_t"] = text, col, t


def _wrap(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


def _update(lt, dt):
    s = _S
    for i in range(4):
        st = s["state"][i]
        if st == "idle":
            s["rot"][i] += s["drift"][i] * dt
        elif st == "crack":
            age = lt - s["crack_t"]
            dur = s["dur"][i]
            s["entropy"][i] = max(0.0, min(s["entropy"][i], 1 - age / dur))
            if age < dur - 1.6:
                # frantic search: varying spin with reversals
                target_v = 5.0 * math.sin(age * 1.7 + i) + 2.5 * math.sin(age * 4.3)
                s["vel"][i] += (target_v - s["vel"][i]) * min(1.0, dt * 4)
                s["rot"][i] += s["vel"][i] * dt
                s["attempts"] += _rng.randint(900, 5000)
            else:
                # home in on the gate
                target = GATE - s["keyang"][i]
                err = _wrap(target - s["rot"][i])
                s["rot"][i] += err * min(1.0, dt * 5.0)
                s["attempts"] += _rng.randint(20, 300)
                if age >= dur and abs(err) < 0.02:
                    if s["reject"][i] and not s["rejected"][i]:
                        s["rejected"][i] = True
                        s["crack_t"] = lt
                        s["dur"][i] = _rng.uniform(4.5, 6.0)
                        s["entropy"][i] = 0.6
                        s["vel"][i] = -6.0
                        _msg("COUNTER-CIPHER! RETRY", AMBER, lt)
                    else:
                        s["rot"][i] = GATE - s["keyang"][i]
                        s["state"][i] = "locked"
                        s["lock_t"][i] = lt
                        s["entropy"][i] = 0.0
                        _msg("KEY %s ACCEPTED" % ROMAN[i], GREEN_HI, lt)
                        if i < 3:
                            s["state"][i + 1] = "crack"
                            s["crack_t"] = lt + 0.8
                            s["cur"] = i + 1
                        else:
                            s["open_t"] = lt + 1.0
    if s["state"][0] == "idle" and lt >= T_INTRO:
        s["state"][0] = "crack"
        s["crack_t"] = lt


def render(bezel, mask, now: float) -> Image.Image:
    if _session.fresh(now) or not _S:
        _reset()
    s = _S
    tt = _session.t(now)
    dt = 1 / 30.0 if s["prev"] is None else max(0.0, min(0.2, tt - s["prev"]))
    s["prev"] = tt
    lt = tt - s["t0"]
    blink = int(tt * 4) % 2 == 0

    # unlock / reveal / reseal timing
    op = s["open_t"]
    oa = lt - op if op is not None else -1.0
    if op is not None and oa > 20.0:
        _new_lock(tt)
        lt, oa, op = 0.0, -1.0, None
    if op is None or oa < 0:
        _update(lt, dt)

    # ring spread factor: 1 closed, >1 retracted
    if oa < 0:
        spread, rfade = 1.0, 1.0
    elif oa < 2.5:
        u = oa / 2.5
        spread, rfade = 1.0 + 0.9 * u * u, 1.0 - u
    elif oa < 16.0:
        spread, rfade = 1.9, 0.0
    else:
        u = min(1.0, (oa - 16.0) / 3.0)
        spread, rfade = 1.9 - 0.9 * (1 - (1 - u) ** 2), u
    intro = min(1.0, lt / T_INTRO)

    img = s["bg"].copy()
    arr = np.asarray(img).copy()

    # ---------------- glyph rings (numpy point scatter)
    if rfade > 0.01:
        for i in range(4):
            rs, ths, key = s["glyph"][i]
            rot = s["rot"][i] + (oa * (1 if i % 2 else -1) * 0.6 if oa > 0 else 0.0)
            r = rs * spread if i < 3 else rs * (1 + (spread - 1) * 2.2)
            th = ths + rot
            x = (VX + r * np.cos(th)).astype(np.int32)
            y = (VY + r * np.sin(th)).astype(np.int32)
            ok = (x >= 0) & (x < 240) & (y >= 0) & (y < 240)
            st = s["state"][i]
            if st == "locked":
                base = GREEN_HI if lt - (s["lock_t"][i] or 0) < 0.5 else GREEN
            elif st == "crack":
                base = GREEN if blink else GREEN_MID
            else:
                base = GREEN_MID
            k = rfade * (intro if i >= 0 else 1)
            c = np.array(scale(base, k), np.uint8)
            kc = np.array(scale(AMBER if st != "locked" else GREEN_HI, k), np.uint8)
            m = ok & ~key
            arr[y[m], x[m]] = c
            m = ok & key
            arr[y[m], x[m]] = kc
    img = Image.fromarray(arr)
    d = ImageDraw.Draw(img)

    # ring edges
    if rfade > 0.01:
        for i, r in enumerate(RINGS):
            sp = spread if i < 3 else 1 + (spread - 1) * 2.2
            st = s["state"][i]
            col = GREEN_MID if st == "locked" else GREEN_DIM
            if st == "locked" and lt - (s["lock_t"][i] or 0) < 0.6:
                col = GREEN_HI
            col = scale(col, rfade * intro)
            for rr in (r - RW, r + RW):
                rr *= sp
                d.ellipse([VX - rr, VY - rr, VX + rr, VY + rr], outline=col)
        # gate channel
        top = VY - (RINGS[0] + RW + 3) * spread
        gc = scale(GREEN_MID, rfade)
        d.line([(VX - 7, top), (VX - 7, VY - (RINGS[3] - RW) * spread)], fill=gc)
        d.line([(VX + 7, top), (VX + 7, VY - (RINGS[3] - RW) * spread)], fill=gc)
        cur = s["cur"]
        if s["state"][cur] == "crack":
            ry = VY - RINGS[cur] * spread
            ac = AMBER if blink else GREEN_HI
            d.polygon([(VX - 14, ry - 4), (VX - 9, ry), (VX - 14, ry + 4)], fill=ac)
            d.polygon([(VX + 14, ry - 4), (VX + 9, ry), (VX + 14, ry + 4)], fill=ac)

    # ---------------- core readout / reveal
    if oa < 0.5 or oa > 18.5:
        core_r = RINGS[3] - RW - 3
        nlock = sum(1 for v in s["state"] if v == "locked")
        _txtc(d, VY - 14, "KEY %d/4" % nlock, GREEN_HI if nlock == 4 else GREEN, 9, x=VX)
        _txtc(d, VY - 2, "%06X" % (s["attempts"] & 0xFFFFFF), GREEN_HI if s["state"][s["cur"]] == "crack" else GREEN_MID, 10, x=VX)
    elif oa >= 1.0:
        # STC fragment wireframe
        grow = min(1.0, (oa - 1.0) / 2.0) if oa < 16 else max(0.0, 1 - (oa - 16.0) / 2.5)
        v, e = s["model"]
        a = tt * 0.7
        ca, sa = math.cos(a), math.sin(a)
        cb, sb = math.cos(0.45), math.sin(0.45)
        R = np.array([[ca, 0, sa], [0, 1, 0], [-sa, 0, ca]], np.float32)
        R = np.array([[1, 0, 0], [0, cb, -sb], [0, sb, cb]], np.float32) @ R
        q = v @ R.T * (1.7 * grow)
        f = 200.0 / (q[:, 2] + 200.0)
        xs = (VX + q[:, 0] * f).tolist()
        ys = (VY + q[:, 1] * f).tolist()
        zs = q[:, 2].tolist()
        for (i0, i1) in e:
            z = (zs[i0] + zs[i1]) / 2
            col = GREEN_HI if z < -6 else (GREEN if z < 8 else GREEN_MID)
            d.line([(xs[i0], ys[i0]), (xs[i1], ys[i1])], fill=col)
        # scan line over the fragment
        if 3.0 < oa < 16:
            sy = VY - 45 + ((oa * 40) % 90)
            d.line([(VX - 50, sy), (VX + 50, sy)], fill=GREEN_MID)
        # opening flash
        if oa < 1.6:
            rr = (oa - 1.0) * 150
            d.ellipse([VX - rr, VY - rr, VX + rr, VY + rr], outline=GREEN_HI, width=2)

    # ---------------- entropy meters (bottom-left / bottom-right arcs)
    if rfade > 0.01:
        for i in range(4):
            e = s["entropy"][i]
            x0 = CX - 46 + i * 24
            y0 = 196
            col = GREEN_HI if s["state"][i] == "locked" else (AMBER if s["state"][i] == "crack" else GREEN_MID)
            d.rectangle([x0, y0, x0 + 20, y0 + 4], outline=scale(GREEN_DIM, rfade))
            if e > 0:
                d.rectangle([x0 + 1, y0 + 1, x0 + 1 + 18 * e, y0 + 3], fill=scale(col, rfade))
            _txtc(d, y0 + 6, ROMAN[i], scale(col, rfade), 9, x=x0 + 10)

    # ---------------- header / status
    if op is None or oa < 0:
        m = s["msg"]
        if m and lt - s["msg_t"] < 2.5:
            col = s["msg_col"]
            if col == AMBER and not blink:
                col = RED
            _txtc(d, 184, m, col, 9)
        elif lt < T_INTRO:
            _txtc(d, 184, s["vault"] + " SEALED", GREEN_MID, 9)
        else:
            _txtc(d, 184, "CRACKING CIPHER %s" % ROMAN[s["cur"]], GREEN, 9)
    else:
        if oa < 2.5:
            _txtc(d, 184, "VAULT UNSEALING", GREEN_HI if blink else GREEN, 10)
        elif oa < 16.0:
            _txtc(d, 22, "STC FRAGMENT", GREEN_HI, 11)
            _txtc(d, 36, s["stc"], AMBER, 9)
            _txtc(d, 176, "INTEGRITY %d%%" % s["integ"], GREEN, 9)
            _txtc(d, 189, "PRAISE THE OMNISSIAH", GREEN_MID, 9)
            data = s["data"]
            nshow = int((oa - 2.5) / 0.5)
            for j in range(min(3, nshow)):
                _txt(d, 22, 92 + j * 13, data[j], GREEN_MID, 9)
            for j in range(3, min(6, nshow)):
                x = 218 - _tlen(data[j], 9)
                _txt(d, x, 92 + (j - 3) * 13, data[j], GREEN_MID, 9)
            b = 58 + 3 * math.sin(tt * 3)
            for sxn, syn in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
                cx_, cy_ = VX + sxn * b, VY + syn * b * 0.8
                d.line([(cx_, cy_), (cx_ - sxn * 8, cy_)], fill=GREEN)
                d.line([(cx_, cy_), (cx_, cy_ - syn * 8)], fill=GREEN)
        else:
            _txtc(d, 184, "VAULT RESEALING", AMBER, 10)
    return _ph.compose(img)
