"""Lexmechanic Ledger - a lexmechanic's calculating engine at work.

A ledger table (REF / ITEM / QTY / VALUE / flag) scrolls through the eye.
Each new entry is computed in place - digits churn and settle left to right -
then added into the running total by hand-style column addition: the addend
sits over the sum, digits roll like an odometer from right to left, and
carries hop to the next column in amber.  A bar chart of category subtotals
grows as entries post.  Some entries are flagged in amber, audited, and
reconciled.  The footer cycles between probability calculations typed out
digit by digit and reconciliation tallies.
"""

from __future__ import annotations

import math
import random

from PIL import Image, ImageDraw

from ..lore._common import CX, CY, Session, font
from ._phosphor import AMBER, GREEN, GREEN_DIM, GREEN_HI, GREEN_MID, RED, Phosphor, blank

NAME = "lexmechanic_ledger"

_rng = random.Random()
_session = Session()
_ph = Phosphor(decay=0.25, bloom=0.5, flicker=0.03)

_CATS = [("MUNIT", "MUN"), ("PROMT", "PRM"), ("RATIO", "RAT"), ("OIL-S", "OIL"), ("TITHE", "TTH")]
_RH = 12
_Y_ROWS = 58
_NROWS = 6
_XREF, _XITEM, _XQTY, _XVAL, _XFLAG = 38, 68, 136, 180, 185
_ND = 8               # odometer digits
_DP = 9               # odometer digit pitch
_OX1 = 182            # right edge of odometer
_DH = 15              # odometer digit cell height

_TXT: dict = {}
_DIG: dict = {}


def _tmask(s, size):
    k = (s, size)
    m = _TXT.get(k)
    if m is None:
        f = font(size)
        m = Image.new("L", (int(math.ceil(f.getlength(s))) + 2, size + 5), 0)
        ImageDraw.Draw(m).text((0, 0), s, fill=255, font=f)
        if len(_TXT) > 500:
            _TXT.clear()
        _TXT[k] = m
    return m


def _txt(img, x, y, s, col, size=10):
    if s:
        img.paste(col, (int(x), int(y)), _tmask(s, size))


def _txt_r(img, xr, y, s, col, size=10):
    if s:
        m = _tmask(s, size)
        img.paste(col, (int(xr - (m.width - 2)), int(y)), m)


def _txt_c(img, y, s, col, size=10):
    m = _tmask(s, size)
    img.paste(col, (int(CX - (m.width - 2) / 2), int(y)), m)


def _digit(dg, size=14):
    k = (dg, size)
    m = _DIG.get(k)
    if m is None:
        f = font(size)
        top = f.getbbox("0")[1]
        m = Image.new("L", (_DP, _DH), 0)
        w = f.getlength(str(dg))
        ImageDraw.Draw(m).text(((_DP - w) / 2, 1 - top), str(dg), fill=255, font=f)
        _DIG[k] = m
    return m


def _mix(a, b, k):
    k = max(0.0, min(1.0, k))
    return tuple(int(a[i] + (b[i] - a[i]) * k) for i in range(3))


# --------------------------------------------------------------------- state

_S: dict = {}


def _new_entry():
    ci = _rng.randrange(len(_CATS))
    qty = int(_rng.choice((_rng.uniform(1, 99), _rng.uniform(10, 999), _rng.uniform(100, 9999))))
    unit = _rng.choice((1, 2, 3, 5, 7, 12, 25, 40))
    val = qty * unit
    flag = _rng.random() < 0.16
    _S["ref"] += _rng.randint(1, 9)
    e = {"ref": "%04d" % (_S["ref"] % 10000), "cat": ci, "qty": qty, "val": val, "flag": flag,
         "true": val + (_rng.randint(1, 9) * 10 ** _rng.randint(0, 2) if flag else 0),
         "state": "new", "t0": 0.0}
    return e


def _reset(t):
    _S.clear()
    total = _rng.randint(800000, 4000000)
    _S.update(t0=t, ref=_rng.randint(100, 3000), rows=[], total=total,
              digits=[(total // 10 ** p) % 10 for p in range(_ND)],
              cats=[_rng.uniform(0.2, 0.6) for _ in _CATS], scroll=0.0,
              phase="compute", p0=t, cur=None, add=None, carries={},
              posted=0, flags=0, recon=0, foot=None, next_foot=t + 6.0,
              folio=_rng.randint(0x10, 0xFF), audit=None)
    for _ in range(_NROWS - 1):
        e = _new_entry()
        e["state"] = "done"
        if e["flag"]:
            e["flag"] = False
            e["true"] = e["val"]
        _S["rows"].append(e)
    _start_entry(t)


def _start_entry(t):
    e = _new_entry()
    e["state"] = "compute"
    e["t0"] = t
    _S["rows"].append(e)
    _S["scroll"] += _RH
    if len(_S["rows"]) > _NROWS + 2:
        del _S["rows"][0]
    _S["cur"] = e
    _S["phase"] = "compute"
    _S["p0"] = t


def _start_add(t, amount, label):
    """Column-wise addition of amount into the total, right to left with carries."""
    digits = [(amount // 10 ** p) % 10 for p in range(_ND)]
    _S["add"] = {"amt": amount, "d": digits, "t0": t, "label": label, "step": 0.16,
                 "start": list(_S["digits"])}
    # precompute per-column roll amount including carries
    carry = 0
    rolls = []
    carries = []
    for p in range(_ND):
        s = _S["digits"][p] + digits[p] + carry
        rolls.append(digits[p] + carry)
        carry = 1 if s >= 10 else 0
        carries.append(carry)
    _S["add"]["rolls"] = rolls
    _S["add"]["carries"] = carries
    top = max([p for p in range(_ND) if digits[p]] + [0])
    last = max(top, max([p + 1 for p in range(_ND) if carries[p]] + [0]))
    _S["add"]["n"] = min(_ND, last + 1)


def _add_state(t):
    a = _S["add"]
    if a is None:
        return None
    u = (t - a["t0"]) / a["step"]
    return u


def _finish_add():
    a = _S["add"]
    _S["total"] = (_S["total"] + a["amt"]) % (10 ** _ND)
    _S["digits"] = [(_S["total"] // 10 ** p) % 10 for p in range(_ND)]
    _S["add"] = None


def _update(t):
    s = _S
    e = s["cur"]
    u = t - s["p0"]
    if s["phase"] == "compute":
        if u >= 1.0:
            e["state"] = "flag" if e["flag"] else "done"
            if e["flag"]:
                s["flags"] += 1
            s["phase"] = "add"
            s["p0"] = t
            _start_add(t, e["val"], "ADD")
    elif s["phase"] == "add":
        a = s["add"]
        if a is not None and (t - a["t0"]) / a["step"] >= a["n"] + 1.5:
            _finish_add()
            s["cats"][e["cat"]] = min(1.0, s["cats"][e["cat"]] + 0.02 + e["val"] / 400000.0)
            s["posted"] += 1
            s["phase"] = "rest"
            s["p0"] = t
            # every so often audit a flagged entry that is still on screen
            for r in s["rows"]:
                if r["state"] == "flag" and r is not e and _rng.random() < 0.8:
                    s["audit"] = r
                    break
    elif s["phase"] == "rest":
        if s["audit"] is not None and u >= 0.4:
            s["phase"] = "audit"
            s["p0"] = t
            s["audit"]["state"] = "audit"
            s["audit"]["t0"] = t
        elif u >= 0.7:
            _start_entry(t)
    elif s["phase"] == "audit":
        r = s["audit"]
        if u >= 1.4 and s["add"] is None and r["state"] == "audit":
            r["state"] = "recon"
            r["t0"] = t
            diff = r["true"] - r["val"]
            r["old"] = r["val"]
            r["val"] = r["true"]
            s["recon"] += 1
            _start_add(t, diff, "ADJ")
        a = s["add"]
        if r["state"] == "recon" and a is not None and (t - a["t0"]) / a["step"] >= a["n"] + 1.5:
            _finish_add()
            s["audit"] = None
            s["phase"] = "rest"
            s["p0"] = t
    # rows scrolled off can no longer be audited
    if s["audit"] is not None and s["audit"] not in s["rows"]:
        s["audit"] = None
        if s["phase"] == "audit":
            s["phase"] = "rest"
            s["p0"] = t
            if s["add"] is not None:
                _finish_add()
    # footer events
    if t >= s["next_foot"]:
        kind = _rng.choice(("prob", "prob", "recon", "mean"))
        n = _rng.randint(6, 30)
        pr = _rng.choice((0.97, 0.98, 0.95, 0.99, 0.93))
        if kind == "prob":
            res = 1 - pr ** n
            s["foot"] = {"t0": t, "a": "P=1-%.2f^%d" % (pr, n), "b": "=%.3f" % res,
                         "warn": res > 0.5}
        elif kind == "mean":
            m = _rng.uniform(80, 9000)
            s["foot"] = {"t0": t, "a": "MEAN/ENTRY", "b": "=%.1f" % m, "warn": False}
        else:
            s["foot"] = {"t0": t, "a": "RECONCILED", "b": " %d/%d" % (s["recon"], max(s["flags"], s["recon"])),
                         "warn": s["flags"] > s["recon"]}
        s["next_foot"] = t + _rng.uniform(6, 10)


# --------------------------------------------------------------------- drawing

def _draw_table(img, d, t):
    s = _S
    _txt(img, _XREF, 44, "REF", GREEN_MID, 9)
    _txt(img, _XITEM, 44, "ITEM", GREEN_MID, 9)
    _txt_r(img, _XQTY, 44, "QTY", GREEN_MID, 9)
    _txt_r(img, _XVAL, 44, "VALUE", GREEN_MID, 9)
    d.line([(36, 56), (204, 56)], fill=(10, 80, 32))
    for x in (_XITEM - 5, _XQTY + 4, _XVAL + 3):
        d.line([(x, 46), (x, 131)], fill=(5, 40, 16))
    rows = s["rows"]
    n = len(rows)
    for i, e in enumerate(rows):
        y = _Y_ROWS + (_NROWS - (n - i)) * _RH + s["scroll"]
        if y < _Y_ROWS - 8 or y > _Y_ROWS + _NROWS * _RH:
            continue
        fade = min(1.0, (y - (_Y_ROWS - 8)) / 10.0)
        st = e["state"]
        base = (30, 190, 80)
        if st == "compute":
            base = GREEN_HI
        elif st in ("flag", "audit"):
            base = AMBER
        col = tuple(int(c * fade) for c in base)
        yi = int(y)
        if st == "audit":
            if int(t * 6) % 2 == 0:
                d.rectangle([34, yi - 1, 204, yi + _RH - 2], outline=AMBER)
        if st == "recon":
            k = min(1.0, (t - e["t0"]) / 1.2)
            d.rectangle([34, yi - 1, 204, yi + _RH - 2], fill=_mix((0, 50, 20), (0, 0, 0), k))
            col = _mix(GREEN_HI, (30, 190, 80), k)
        _txt(img, _XREF, yi, e["ref"], tuple(int(c * 0.75) for c in col), 9)
        _txt(img, _XITEM, yi, _CATS[e["cat"]][0], col, 9)
        if st == "compute":
            u = t - e["t0"]
            q = "%d" % e["qty"]
            v = "%d" % e["val"]
            nq = int(u * 14)
            nv = int(max(0.0, u - 0.3) * 14)
            q = "".join(ch if i2 < nq else str(_rng.randint(0, 9)) for i2, ch in enumerate(q))
            v = "".join(ch if i2 < nv else str(_rng.randint(0, 9)) for i2, ch in enumerate(v))
            _txt_r(img, _XQTY, yi, q, col, 9)
            _txt_r(img, _XVAL, yi, v, col, 9)
            d.polygon([(28, yi + 2), (32, yi + 5), (28, yi + 8)], fill=GREEN_HI)
        else:
            _txt_r(img, _XQTY, yi, "%d" % e["qty"], col, 9)
            _txt_r(img, _XVAL, yi, "%d" % e["val"], col, 9)
        if st in ("flag", "audit"):
            _txt(img, _XFLAG, yi, "!!", AMBER if int(t * 3) % 2 == 0 or st == "flag" else RED, 9)
        elif st == "recon":
            _txt(img, _XFLAG, yi, "RC", GREEN_HI, 9)
        elif st == "done":
            d.line([(_XFLAG + 2, yi + 6), (_XFLAG + 4, yi + 8), (_XFLAG + 8, yi + 3)], fill=tuple(int(c * fade) for c in GREEN_MID))
    d.line([(36, 132), (204, 132)], fill=(10, 80, 32))


def _draw_sum(img, d, t):
    s = _S
    a = s["add"]
    x0 = _OX1 - _ND * _DP
    ya, ys = 135, 151
    # addend row
    if a is not None:
        u = (t - a["t0"]) / a["step"]
        _txt(img, 50, ya + 2, a["label"], AMBER if a["label"] == "ADJ" else GREEN_MID, 9)
        top = max([p for p in range(_ND) if a["d"][p]] + [0])
        for p in range(top + 1):
            x = _OX1 - (p + 1) * _DP
            active = p <= u < p + 1
            c = GREEN_HI if active else ((20, 110, 45) if u > p + 1 else GREEN)
            img.paste(c, (int(x), ya), _digit(a["d"][p], 11))
        _txt(img, x0 - 10, ya + 1, "+", GREEN, 11)
    d.line([(x0 - 12, ys - 2), (_OX1 + 2, ys - 2)], fill=GREEN_MID)
    _txt(img, 50, ys + 3, "SUM", GREEN_MID, 9)
    # odometer total: build the rolling digits on a small mask
    m = Image.new("L", (_ND * _DP, _DH), 0)
    fr_all = []
    lead = True
    for p in range(_ND - 1, -1, -1):
        dg = s["digits"][p]
        fr = 0.0
        if a is not None:
            u = (t - a["t0"]) / a["step"]
            roll = a["rolls"][p]
            k = max(0.0, min(1.0, u - p))
            k = k * k * (3 - 2 * k)
            pos = a["start"][p] + roll * k
            dg = int(pos) % 10
            fr = pos - int(pos)
        fr_all.append(fr)
        if lead and dg == 0 and fr == 0 and p > 0:
            continue
        lead = False
        x = (_ND - 1 - p) * _DP
        if fr > 0.001:
            off = int(fr * _DH)
            m.paste(_digit(dg), (x, -off))
            m.paste(_digit((dg + 1) % 10), (x, _DH - off))
        else:
            m.paste(_digit(dg), (x, 0))
    img.paste(GREEN_HI, (x0, ys), m)
    # thousands separators
    for p in (3, 6):
        x = _OX1 - p * _DP
        d.point((x, ys + _DH - 2), fill=GREEN_MID)
    # carry marks
    if a is not None:
        u = (t - a["t0"]) / a["step"]
        for p in range(_ND - 1):
            if a["carries"][p] and p + 0.5 <= u < p + 2.2:
                x = _OX1 - (p + 2) * _DP
                hop = min(1.0, (u - p - 0.5) / 0.5)
                cx = x + _DP / 2 + (1 - hop) * _DP
                cy = ys - 4 - 4 * math.sin(hop * math.pi)
                _txt(img, cx - 2, cy - 8, "1", AMBER, 9)
    d.rectangle([x0 - 3, ys - 1, _OX1 + 2, ys + _DH], outline=(8, 60, 24))


def _draw_bars(img, d, t):
    s = _S
    cur = s["cur"]["cat"] if s["cur"] is not None else -1
    n = len(_CATS)
    pitch = 24
    x0 = CX - (n - 1) * pitch / 2
    yb = 188
    for i, (name, short) in enumerate(_CATS):
        x = x0 + i * pitch
        h = int(16 * s["cats"][i])
        on = i == cur and s["phase"] in ("add", "compute")
        c = GREEN_HI if on else GREEN
        d.rectangle([x - 5, yb - 17, x + 5, yb], outline=(5, 40, 16))
        d.rectangle([x - 4, yb - h, x + 4, yb - 1], fill=c if on else (24, 150, 62))
        d.line([(x - 4, yb - h), (x + 4, yb - h)], fill=GREEN_HI)
        m = _tmask(short, 9)
        img.paste(GREEN_HI if on else (20, 120, 50), (int(x - (m.width - 2) / 2), yb + 1), m)
    # slow decay of the category bars keeps them moving over a showing
    for i in range(n):
        s["cats"][i] = max(0.1, s["cats"][i] - 0.00025)


def _draw_footer(img, d, t):
    f = _S["foot"]
    y = 203
    if f is None:
        _txt_c(img, y, "POSTED %d" % _S["posted"], (14, 100, 40), 9)
        return
    u = t - f["t0"]
    a, b = f["a"], f["b"]
    full = a + b
    n = int(u * 12)
    shown = full[:n]
    col = AMBER if (f["warn"] and n >= len(full)) else GREEN
    m = _tmask(full, 9)
    x = CX - (m.width - 2) / 2
    _txt(img, x, y, shown, col, 9)
    if n < len(full) and int(t * 6) % 2 == 0:
        xc = x + font(9).getlength(shown) + 1
        d.rectangle([xc, y + 2, xc + 4, y + 10], fill=GREEN_HI)
    if u > 5.5:
        _S["foot"] = None


def render(bezel, mask, now: float) -> Image.Image:
    if _session.fresh(now) or not _S:
        _reset(now)
        _ph.reset()
    t = now
    _update(t)
    _S["scroll"] = max(0.0, _S["scroll"] * 0.8 - 0.2)

    img = blank()
    d = ImageDraw.Draw(img)
    _txt_c(img, 20, "LEXMECHANICUS", GREEN_MID, 9)
    _txt_c(img, 30, "FOLIO %02X   ENTRY %d" % (_S["folio"], _S["ref"] % 10000), (20, 130, 55), 9)
    _draw_table(img, d, t)
    _draw_sum(img, d, t)
    _draw_bars(img, d, t)
    _draw_footer(img, d, t)
    return _ph.compose(img)
