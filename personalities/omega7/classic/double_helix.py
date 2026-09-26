"""Double Helix - a Magos Biologis gene-sequencer readout.

A 3D double helix turns and scrolls up through a fixed sequencing bar. Strands
and base-pair rungs are depth-shaded (front bright, back dim). As each rung
crosses the bar its bases are read out (A/T/G/C) and appended to a scrolling
sequence line. The showing alternates SEQUENCING, SEEK (fast-forward to the
next gene locus) and LOCUS LOCK; now and then a mutated base pair (amber)
reaches the bar, halts the sequencer and is repaired.
"""

from __future__ import annotations

import math
import random

import numpy as np
from PIL import Image, ImageDraw

from ..lore._common import CX, CY, Session, font
from ._phosphor import AMBER, GREEN, GREEN_DIM, GREEN_FAINT, GREEN_HI, GREEN_MID, RED, Phosphor, blank

NAME = "double_helix"

_rng = random.Random()
_session = Session()
_ph = Phosphor(decay=0.55, bloom=0.5)
_S: dict = {}

HR = 38.0          # helix radius
SP = 9.0           # rung spacing (world units)
TW = 2 * math.pi / (10.5 * SP)   # twist per unit (10.5 bp per turn)
YMAX = 64.0
SCAN_Y = 0.0       # world y of sequencing bar
FOV, CAM = 240.0, 250.0
PAIR = {"A": "T", "T": "A", "G": "C", "C": "G"}
LOCI = ["GS-PROGENOID", "OSSMODULA", "BISCOPEA", "OOLITIC KID", "MUCRANOID", "BETCHER GL",
        "CATALEPSEAN", "LARRAMAN", "SUS-AN MEMB", "OMOPHAGEA", "HAEMASTAMEN", "MELANOCHROME"]

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


# depth-shade palette: index 0 = far back, 7 = nearest front
_SHADE = [_col(GREEN, 0.18 + 0.12 * i) if i < 6 else (GREEN if i == 6 else GREEN_HI) for i in range(8)]


def _base(k):
    seq = _S["seq"]
    b = seq.get(k)
    if b is None:
        if len(seq) > 400:
            seq.clear()
        b = seq[k] = _rng.choice("ATGC")
    return b


def _build_bg():
    img = blank()
    d = ImageDraw.Draw(img)
    d.ellipse([CX - 109, CY - 109, CX + 109, CY + 109], outline=GREEN_FAINT)
    for k in range(-8, 9):
        y = CY + k * 10
        d.line([(CX - 96 + abs(k) * 2, y), (CX - 90 + abs(k) * 2, y)], fill=GREEN_DIM if k % 5 else GREEN_MID)
    _text(img, CX, 17, "GENE-SEED SEQUENCER", GREEN_MID, 10)
    return img


def _reset():
    _S.clear()
    _S["bg"] = _build_bg()
    _S["seq"] = {}
    _S["nmut"] = 0
    _S["scroll"] = -YMAX       # world offset: rung k sits at y = k*SP - scroll
    _S["rot"] = _rng.uniform(0, 6.28)
    _S["last"] = None
    _S["read"] = []            # (letter, status) status: 0 ok, 1 mutant, 2 repaired
    _S["last_k"] = None
    _S["mut"] = {}             # rung k -> state ('pending' | 'halt' | 'fixed', t)
    _S["next_mut"] = _rng.uniform(14, 24)
    _S["halt"] = None
    _S["locus"] = _rng.randrange(len(LOCI))
    _S["bp"] = _rng.randrange(1000, 90000)
    _ph.reset()


def _phase(ta):
    c = ta % 60.0
    if c < 38:
        return "SEQ", c
    if c < 46:
        return "SEEK", c - 38
    return "LOCK", c - 46


def render(bezel, mask, now: float) -> Image.Image:
    if _session.fresh(now):
        _reset()
    S = _S
    ta = _session.t(now)
    dt = 1 / 30 if S["last"] is None else min(0.1, max(0.0, now - S["last"]))
    S["last"] = now
    phase, pt = _phase(ta)
    if phase == "SEEK" and pt < dt * 1.5:
        S["locus"] = (S["locus"] + _rng.randrange(1, len(LOCI))) % len(LOCI)

    # speed (world units / s)
    speed = {"SEQ": 7.0, "SEEK": 7.0 + 60.0 * math.sin(min(1.0, pt / 8) * math.pi), "LOCK": 4.0}[phase]
    halt = S["halt"]
    if halt is not None:
        hk, h0 = halt
        if ta - h0 < 4.2:
            speed = 0.0 if ta - h0 < 3.6 else 3.0
        else:
            S["halt"] = None
    S["scroll"] += speed * dt
    S["rot"] += dt * (0.55 + speed * 0.02)
    scroll, rot = S["scroll"], S["rot"]

    # schedule mutations on upcoming rungs below the bar
    if ta > S["next_mut"] and phase == "SEQ":
        k = int((scroll + SCAN_Y + 60) / SP)
        S["mut"][k] = ["pending", ta]
        S["next_mut"] = ta + _rng.uniform(26, 40)

    img = S["bg"].copy()
    d = ImageDraw.Draw(img)

    tilt = 0.18 * math.sin(ta * 0.11)
    ct, st = math.cos(tilt), math.sin(tilt)

    def proj(x, y, z):
        y2 = y * ct - z * st
        z2 = y * st + z * ct
        f = FOV / (z2 + CAM)
        return CX + x * f, CY + y2 * f, z2

    # strands: fine sample along y
    ys = np.arange(-YMAX, YMAX + 0.1, 3.0, dtype=np.float32)
    s = ys + scroll
    seg_front, seg_back = [], []
    for off in (0.0, math.pi * 0.78):          # minor/major groove offset
        a = s * TW + rot + off
        x, z = np.cos(a) * HR, np.sin(a) * HR
        sx, sy, sz = proj(x, ys, z)
        shade = np.clip(((-sz / HR) * 0.5 + 0.5) * 7.99, 0, 7).astype(np.int32)
        fade = np.clip((YMAX - np.abs(ys)) / 14.0, 0, 1)
        shade = np.minimum(shade, (fade * 7.99).astype(np.int32))
        sxl, syl, shl, szl = sx.tolist(), sy.tolist(), shade.tolist(), sz.tolist()
        for i in range(len(sxl) - 1):
            seg = ((sxl[i], syl[i]), (sxl[i + 1], syl[i + 1]), shl[i])
            (seg_front if szl[i] < 0 else seg_back).append(seg)

    for p0, p1, sh in seg_back:
        d.line([p0, p1], fill=_SHADE[sh])

    # rungs
    k0 = int(math.floor((scroll - YMAX) / SP)) + 1
    k1 = int(math.floor((scroll + YMAX) / SP))
    scan_s = scroll + SCAN_Y
    front_rungs = []
    cur_k = int(round(scan_s / SP))
    for k in range(k0, k1 + 1):
        y = k * SP - scroll
        sk = k * SP
        a1 = sk * TW + rot
        a2 = a1 + math.pi * 0.78
        p1 = proj(HR * math.cos(a1), y, HR * math.sin(a1))
        p2 = proj(HR * math.cos(a2), y, HR * math.sin(a2))
        mid = ((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2)
        depth = (p1[2] + p2[2]) / 2
        fade = max(0.0, min(1.0, (YMAX - abs(y)) / 14.0))
        b = (0.25 + 0.45 * (0.5 - depth / HR / 2)) * fade
        mu = S["mut"].get(k)
        near = math.exp(-((y - SCAN_Y) / 4.5) ** 2)
        if mu is not None and mu[0] != "fixed":
            c1 = c2 = _col(AMBER, 0.45 + 0.55 * fade)
            if mu[0] == "halt" and int(ta * 6) % 2:
                c1 = c2 = RED
        elif mu is not None and mu[0] == "fixed" and ta - mu[1] < 3:
            c1 = c2 = GREEN_HI
        else:
            c1 = _col(GREEN, b + 0.9 * near)
            c2 = _col(GREEN_MID, b * 1.3 + 0.9 * near)
        item = (p1[:2], p2[:2], mid, c1, c2, near)
        if depth < 0:
            front_rungs.append(item)
        else:
            _draw_rung(d, item)

        # reading at the bar
        if k == cur_k and S["last_k"] != k and abs(y - SCAN_Y) < SP * 0.5:
            S["last_k"] = k
            S["bp"] += 1
            letter = _base(k)
            if mu is not None and mu[0] == "pending":
                mu[0], mu[1] = "halt", ta
                S["halt"] = (k, ta)
                S["nmut"] += 1
                S["read"].append([letter, 1, k])
            else:
                S["read"].append([letter, 0, k])
            if len(S["read"]) > 40:
                del S["read"][:-20]

    # mutation repair completes after the halt
    for k, mu in S["mut"].items():
        if mu[0] == "halt" and ta - mu[1] > 3.4:
            mu[0], mu[1] = "fixed", ta
            for r in S["read"]:
                if r[2] == k:
                    r[1] = 2
    if len(S["mut"]) > 8:
        for k in sorted(S["mut"])[:-4]:
            del S["mut"][k]

    for p0, p1, sh in seg_front:
        d.line([p0, p1], fill=_SHADE[sh], width=2 if sh >= 6 else 1)
    for item in front_rungs:
        _draw_rung(d, item)
        p1, p2 = item[0], item[1]
        for p in (p1, p2):
            d.ellipse([p[0] - 1.5, p[1] - 1.5, p[0] + 1.5, p[1] + 1.5], fill=GREEN)

    # sequencing bar
    by = CY + SCAN_Y
    halted = S["halt"] is not None
    bc = AMBER if halted else GREEN_HI
    sweep = 0.5 + 0.5 * math.sin(ta * 3)
    d.line([(CX - 66, by), (CX + 66, by)], fill=_col(bc, 0.55 + 0.3 * sweep))
    d.line([(CX - 70, by - 6), (CX - 70, by + 6)], fill=bc)
    d.line([(CX - 70, by - 6), (CX - 65, by - 6)], fill=bc)
    d.line([(CX - 70, by + 6), (CX - 65, by + 6)], fill=bc)
    d.line([(CX + 70, by - 6), (CX + 70, by + 6)], fill=bc)
    d.line([(CX + 65, by - 6), (CX + 70, by - 6)], fill=bc)
    d.line([(CX + 65, by + 6), (CX + 70, by + 6)], fill=bc)
    # base letters of the current pair
    if S["read"]:
        letter, status, _k = S["read"][-1]
        lc = AMBER if status == 1 else GREEN_HI
        _text(img, CX - 84, by - 7, letter, lc, 13)
        _text(img, CX + 84, by - 7, PAIR[letter], lc, 13)

    # gene locus bracket on the right during LOCK
    if phase == "LOCK":
        a = min(1.0, pt / 1.5)
        top, bot = CY - 58, CY + 30
        c = _col(GREEN, a)
        d.line([(CX + 50, top), (CX + 56, top), (CX + 56, bot), (CX + 50, bot)], fill=c)
        d.line([(CX + 56, CY - 40), (CX + 62, CY - 40)], fill=c)
        _text(img, CX + 64, CY - 52, "LOCUS", _col(GREEN_MID, a), 9, "l")
        _text(img, CX + 64, CY - 41, f"{S['locus'] + 1:02d}q-{(S['locus'] * 7) % 31 + 2}", _col(GREEN_HI, a), 11, "l")

    # HUD top
    if halted:
        hk, h0 = S["halt"]
        if ta - h0 < 1.8:
            lab, c = "MUTATION DETECTED", (RED if int(ta * 5) % 2 else AMBER)
        else:
            lab, c = "REPAIRING BASE PAIR", AMBER
    elif phase == "SEEK":
        lab, c = "SEEKING LOCUS", GREEN
    elif phase == "LOCK":
        lab, c = f"LOCUS {LOCI[S['locus']]}", GREEN_HI
    else:
        recent_fix = any(m[0] == "fixed" and ta - m[1] < 3 for m in S["mut"].values())
        lab, c = ("REPAIR COMPLETE", GREEN_HI) if recent_fix else ("SEQUENCING", GREEN)
    _text(img, CX, 30, lab, c, 11)

    # sequence line (monospaced from per-letter sprites), newest at right edge of the window
    n = 13
    cw = 9
    seq = S["read"][-n:]
    y0 = 186
    x0 = CX - (n * cw) / 2
    frac = 0.0
    if speed > 0 and S["last_k"] is not None:
        frac = max(0.0, min(1.0, ((scan_s / SP) - S["last_k"] + 0.5)))
    for i, (letter, status, _k) in enumerate(seq):
        x = x0 + (n - len(seq) + i) * cw - frac * cw * 0.0
        age = len(seq) - 1 - i
        if status == 1:
            c = AMBER
        elif status == 2:
            c = GREEN_HI if age < 6 else GREEN
        else:
            c = GREEN_HI if age == 0 else _col(GREEN, 1.0 - age * 0.05)
        _text(img, x + cw / 2, y0, letter, c, 11)
    d.line([(x0, y0 + 14), (x0 + n * cw, y0 + 14)], fill=GREEN_DIM)
    bp = f"{S['bp']:06d} BP   MUT {S['nmut']:02d}"
    _text(img, CX, 203, bp, GREEN_MID, 9)
    return _ph.compose(img)


def _draw_rung(d, item):
    p1, p2, mid, c1, c2, near = item
    d.line([p1, mid], fill=c1, width=2 if near > 0.5 else 1)
    d.line([mid, p2], fill=c2, width=2 if near > 0.5 else 1)
