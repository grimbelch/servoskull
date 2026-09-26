"""Magos Biologis - gene-seed comparator.

Two gene sequences scroll side by side: the chapter's reference gene-seed on
the left and the specimen on the right, codon by codon.  Every row passes
through a comparator window where matching codons are bridged and divergent
bases flare amber.  A ring gauge tracks scan progress and the match
percentage climbs, a genome map collects the mutation loci, and at the end
the Magos rules: GENE-SEED PURE, MUTATION DETECTED or XENOS TAINT.  Then the
next aspirant is sequenced.
"""

from __future__ import annotations

import math
import random

from PIL import Image, ImageDraw

from ..lore._common import CX, CY, Session, font, scale
from ._phosphor import (AMBER, GREEN, GREEN_DIM, GREEN_FAINT, GREEN_HI, GREEN_MID, RED,
                        Phosphor, blank)

NAME = "magos_biologis"

_rng = random.Random()
_session = Session()
_ph = Phosphor(decay=0.55, bloom=0.5, flicker=0.03)

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


_CODON: dict = {}


def _codon(cod):
    """Cached mask of a three-letter codon at fixed letter spacing."""
    m = _CODON.get(cod)
    if m is None:
        f = font(10)
        m = Image.new("L", (3 * LSP + 8, 14), 0)
        dd = ImageDraw.Draw(m)
        for p, ch in enumerate(cod):
            dd.text((p * LSP, 0), ch, fill=255, font=f)
        _CODON[cod] = m
    return m


# -------------------------------------------------------------- layout ---
RH = 11.0                 # row height
LX = 78                   # left strand codon x
RX = 142                  # right strand codon x
LSP = 7                   # letter spacing
WIN_Y = 116.0             # comparator window centre
Y_TOP, Y_BOT = 52.0, 172.0
NROWS = 72
SPEED = 2.0               # rows per second
T_LOAD = 3.0
T_SCAN = NROWS / SPEED + (WIN_Y - Y_TOP) / RH / SPEED
T_VERDICT = 10.0
T_WIPE = 2.0

BASES = "ACGT"
_CHAPTERS = ["ULTRAMARINES", "BLOOD ANGELS", "DARK ANGELS", "SPACE WOLVES",
             "IMPERIAL FISTS", "WHITE SCARS", "RAVEN GUARD", "SALAMANDERS",
             "IRON HANDS", "WORLD EATERS?"]
_SUBJECTS = ["ASPIRANT 0417", "NEOPHYTE K-22", "PROGENOID VII", "SUBJECT TR-9",
             "ASPIRANT 1138", "INITIATE 88-C", "SCOUT M-310", "SAMPLE XR-5"]

_S: dict = {}


def _new_specimen(t0):
    s = _S
    s["t0"] = t0
    s["chapter"] = _rng.choice(_CHAPTERS[:-1])
    s["subject"] = _rng.choice(_SUBJECTS)
    roll = _rng.random()
    nmut = 0 if roll < 0.35 else (_rng.randint(1, 2) if roll < 0.55 else
                                  (_rng.randint(3, 7) if roll < 0.9 else _rng.randint(10, 16)))
    ref = ["".join(_rng.choice(BASES) for _ in range(3)) for _ in range(NROWS)]
    smp = list(ref)
    mut = set(_rng.sample(range(4, NROWS - 2), nmut))
    diff = {}
    for i in mut:
        p = _rng.randrange(3)
        c = _rng.choice([b for b in BASES if b != ref[i][p]])
        smp[i] = ref[i][:p] + c + ref[i][p + 1:]
        diff[i] = p
    s["ref"], s["smp"], s["diff"] = ref, smp, diff
    s["nmut"] = nmut
    s["bars"] = [(_rng.randint(4, 20), _rng.randint(4, 20)) for _ in range(NROWS)]
    s["found"] = []
    s["compared"] = 0
    s["flash"] = {}


def _reset():
    _S.clear()
    _ph.reset()
    _S["bg"] = _static_bg()
    _new_specimen(0.0)


def _static_bg():
    img = Image.new("RGB", (240, 240), (0, 0, 0))
    d = ImageDraw.Draw(img)
    # strand spines
    for x in (LX - 5, LX + 3 * LSP + 3, RX - 5, RX + 3 * LSP + 3):
        d.line([(x, Y_TOP), (x, Y_BOT)], fill=GREEN_FAINT)
    # gauge track
    r = 104
    d.arc([CX - r, CY - r, CX + r, CY + r], 135, 405, fill=GREEN_FAINT, width=3)
    for k in range(11):
        a = math.radians(135 + 27 * k)
        d.line([(CX + 98 * math.cos(a), CY + 98 * math.sin(a)),
                (CX + 101 * math.cos(a), CY + 101 * math.sin(a))], fill=GREEN_DIM)
    return img


def _verdict(s):
    n = s["nmut"]
    if n <= 2:
        return "GENE-SEED PURE", GREEN_HI, "ASPIRANT ACCEPTED"
    if n <= 8:
        return "MUTATION DETECTED", AMBER, "REFER TO APOTHECARION"
    return "XENOS TAINT", RED, "PURGE SPECIMEN"


def render(bezel, mask, now: float) -> Image.Image:
    if _session.fresh(now) or not _S:
        _reset()
    s = _S
    tt = _session.t(now)
    lt = tt - s["t0"]
    total = T_LOAD + T_SCAN + T_VERDICT + T_WIPE
    if lt >= total:
        _new_specimen(tt)
        lt = 0.0
    blink = int(tt * 4) % 2 == 0

    scan_t = min(max(0.0, lt - T_LOAD), T_SCAN)
    scroll = scan_t * SPEED * RH           # px scrolled
    verdict = lt >= T_LOAD + T_SCAN
    v_age = lt - T_LOAD - T_SCAN
    wipe = lt >= T_LOAD + T_SCAN + T_VERDICT
    w_age = lt - T_LOAD - T_SCAN - T_VERDICT
    fade = 1.0
    if lt < T_LOAD:
        fade = lt / T_LOAD
    if wipe:
        fade = max(0.0, 1 - w_age / T_WIPE)

    img = s["bg"].copy()
    d = ImageDraw.Draw(img)

    # ---------------- comparator window
    wy0, wy1 = WIN_Y - RH * 0.5 - 3, WIN_Y + RH * 0.5 + 3
    d.line([(LX - 22, wy0), (RX + 3 * LSP + 22, wy0)], fill=GREEN_MID)
    d.line([(LX - 22, wy1), (RX + 3 * LSP + 22, wy1)], fill=GREEN_MID)
    for x, sg in ((LX - 22, 1), (RX + 3 * LSP + 22, -1)):
        d.line([(x, wy0), (x, wy1)], fill=GREEN_MID)
        d.polygon([(x - sg * 6, WIN_Y - 4), (x - sg * 1, WIN_Y), (x - sg * 6, WIN_Y + 4)], fill=GREEN)
    if not verdict and lt > T_LOAD:
        ly = WIN_Y + (RH * 0.5 + 1) * math.sin(tt * 7)
        d.line([(LX - 8, ly), (RX + 3 * LSP + 8, ly)], fill=scale(GREEN_HI, 0.6))

    # ---------------- rows
    base_y = Y_BOT - 4 - scroll         # row 0 starts near the bottom and rises
    k0 = max(0, int((Y_TOP - 2 - base_y) / RH))
    k1 = min(NROWS - 1, int((Y_BOT - base_y) / RH) + 1)
    for k in range(k0, k1 + 1):
        y = base_y + k * RH
        if y < Y_TOP - 2 or y > Y_BOT:
            continue
        dist = abs(y - WIN_Y)
        edge = min(1.0, (y - Y_TOP + 2) / 18.0, (Y_BOT - y) / 18.0)
        inwin = dist < RH * 0.6
        passed = y < WIN_Y - RH * 0.5
        # comparison bookkeeping as the row crosses the window centre
        if y <= WIN_Y and k >= s["compared"] and not verdict:
            s["compared"] = k + 1
            if k in s["diff"]:
                s["found"].append(k)
                s["flash"][k] = lt
        ismut = k in s["diff"]
        known = passed or inwin
        lvl = (1.0 if inwin else (0.55 if passed else 0.4)) * edge * fade
        base_c = GREEN_HI if inwin else GREEN
        ref, smp = s["ref"][k], s["smp"][k]
        yy = y - 6
        c = scale(base_c, lvl)
        d.bitmap((LX, int(yy)), _codon(ref), fill=c)
        if ismut and known:
            for p in range(3):
                c2 = c
                if s["diff"][k] == p:
                    c2 = scale(AMBER if not inwin or blink else RED, max(0.5, lvl))
                _txt(d, RX + p * LSP, yy, smp[p], c2, 10)
        else:
            d.bitmap((RX, int(yy)), _codon(smp), fill=c)
        # barcode bars on the outer sides
        bl, br = s["bars"][k]
        bc = scale(GREEN_MID, lvl * 0.8)
        d.line([(LX - 8 - bl, y), (LX - 8, y)], fill=bc)
        d.line([(RX + 3 * LSP + 6, y), (RX + 3 * LSP + 6 + br, y)], fill=bc)
        # links across the gap
        gx0, gx1 = LX + 3 * LSP + 4, RX - 6
        if known:
            if ismut:
                cx_ = (gx0 + gx1) / 2
                mc = scale(AMBER, max(0.6, lvl))
                d.line([(cx_ - 3, y - 3), (cx_ + 3, y + 3)], fill=mc)
                d.line([(cx_ - 3, y + 3), (cx_ + 3, y - 3)], fill=mc)
                if inwin:
                    d.rectangle([RX - 3, y - 6, RX + 3 * LSP + 1, y + 6], outline=AMBER)
            else:
                lc = scale(GREEN_HI if inwin else GREEN_DIM, lvl if inwin else 1.0 * fade * edge)
                d.line([(gx0, y), (gx1, y)], fill=lc)

    # ---------------- specimen headers
    _txtc(d, 22, "GENE-SEED", GREEN_MID, 9)
    _txtc(d, 32, s["chapter"], GREEN_HI, 9)
    _txt(d, LX + 1, 40, "REF", GREEN_MID, 9)
    _txt(d, RX + 1, 40, "SMP", GREEN_MID, 9)

    # ---------------- gauges
    comp = min(NROWS, s["compared"])
    prog = comp / NROWS
    nf = len(s["found"])
    match = 100.0 * (comp - nf) / comp if comp else 100.0
    r = 104
    if prog > 0:
        d.arc([CX - r, CY - r, CX + r, CY + r], 135, 135 + 270 * prog, fill=GREEN_MID, width=3)
    r2 = 109
    mcol = GREEN if nf <= 2 else (AMBER if nf <= 8 else RED)
    if comp:
        d.arc([CX - r2, CY - r2, CX + r2, CY + r2], 135, 135 + 270 * prog * match / 100.0, fill=mcol, width=2)
    # head of progress arc
    a = math.radians(135 + 270 * prog)
    hx, hy = CX + r * math.cos(a), CY + r * math.sin(a)
    d.ellipse([hx - 2.5, hy - 2.5, hx + 2.5, hy + 2.5], fill=GREEN_HI)

    # ---------------- genome map (bottom strip)
    mx0, mw, my = CX - 50, 100, 198
    d.line([(mx0, my), (mx0 + mw, my)], fill=GREEN_DIM)
    d.line([(mx0, my), (mx0 + mw * prog, my)], fill=GREEN_MID)
    for kf in s["found"]:
        x = mx0 + mw * (kf + 0.5) / NROWS
        age = lt - s["flash"].get(kf, -10)
        c = GREEN_HI if age < 0.3 else (AMBER if nf <= 8 else RED)
        d.line([(x, my - 4), (x, my + 3)], fill=c)

    # ---------------- readouts / verdict
    if not verdict:
        if lt < T_LOAD:
            _txtc(d, 184, "SEQUENCING " + s["subject"], GREEN if blink else GREEN_MID, 9)
        else:
            _txtc(d, 176, "%.1f%%" % match, mcol if nf else GREEN_HI, 14)
        _txt(d, 30, 138, "LOCI", GREEN_DIM, 9)
        _txt(d, 30, 148, "%02d/%d" % (comp, NROWS), GREEN_MID, 9)
        _txtr(d, 212, 138, "MUT", GREEN_DIM, 9)
        _txtr(d, 212, 148, "%d" % nf, AMBER if nf else GREEN_MID, 9)
        _txtc(d, 204, s["subject"], GREEN_DIM, 9)
    else:
        title, col, sub = _verdict(s)
        if v_age < T_VERDICT:
            # banner over the strands
            bw = max(_tlen(title, 13), _tlen(sub, 9)) + 14
            by0, by1 = WIN_Y - 20, WIN_Y + 20
            d.rectangle([CX - bw / 2, by0, CX + bw / 2, by1], fill=(0, 0, 0), outline=col)
            if v_age < 0.4:
                d.rectangle([CX - bw / 2 - 3, by0 - 3, CX + bw / 2 + 3, by1 + 3], outline=GREEN_HI)
            tc = col if (blink or col == GREEN_HI or v_age > 2.0) else GREEN_HI
            _txtc(d, by0 + 5, title, tc, 13)
            _txtc(d, by0 + 22, sub, GREEN_MID, 9)
            _txtc(d, 179, "MATCH %.1f%%" % match, mcol, 11)
            if s["found"]:
                loci = ",".join("%d" % k for k in s["found"][:6]) + ("+" if nf > 6 else "")
                _txtc(d, 204, "LOCI " + loci, AMBER if nf <= 8 else RED, 9)
            else:
                _txtc(d, 204, "NO DEVIATION", GREEN_MID, 9)
    return _ph.compose(img)
