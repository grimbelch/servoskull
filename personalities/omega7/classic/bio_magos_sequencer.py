"""Bio-Magos Sequencer - a Magos Biologis culture dish under the bio-auspex.

Colonies grow organically in a graduated culture dish (a numpy Gray-Scott
reaction-diffusion simulation, drawn as phosphor contours over a dim fill).
A scanning reticle hops between growths and posts classification cards, a
biomass graph plots the growth rate, containment warnings climb through amber,
and when the culture breaches tolerance the dish is purged in a flash and a
new strain is inoculated.
"""

from __future__ import annotations

import math
import random

import numpy as np
from PIL import Image, ImageDraw

from ..lore._common import CX, Session, font, scale
from ._phosphor import (AMBER, GREEN, GREEN_DIM, GREEN_FAINT, GREEN_HI, GREEN_MID, RED,
                        Phosphor, blank)

NAME = "bio_magos_sequencer"

_rng = random.Random()
_session = Session()
_ph = Phosphor(decay=0.62, bloom=0.5, flicker=0.03)

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


# ------------------------------------------------------------ simulation ---
N = 68                  # grid cells across
SC = 2                  # pixels per cell
DR = 31.5               # dish radius in cells
DX, DY = CX - N * SC // 2, 108 - N * SC // 2     # top-left of the field on screen
DCX, DCY = CX, 108      # dish centre on screen

_gy, _gx = np.mgrid[0:N, 0:N].astype(np.float32)
_grr = np.hypot(_gx - (N - 1) / 2, _gy - (N - 1) / 2)
_DISH = (_grr < DR).astype(np.float32)
_DISH_N = float(_DISH.sum())

_STRAINS = [
    # name, F, k, iterations per frame
    ("MITOS", 0.0367, 0.0649, 3),
    ("CORAL", 0.0545, 0.0620, 2),
    ("VERMI", 0.0580, 0.0650, 3),
    ("LABYR", 0.0290, 0.0570, 2),
    ("SPORE", 0.0300, 0.0620, 3),
]
_GENUS = ["XENOS-GAMMA", "TYRANIC SP.", "NURGLOID", "VIRIDIS MUT.", "LACRIMA SP.",
          "GENESTEALER", "FUNGOID ORK", "PLAGUE-BACIL", "HRUD-SPORE", "LICTOR TISS."]
_ORIGIN = ["CATACHAN II", "MIRAL PRIME", "ICHAR IV", "BALECATH", "VOIDWRECK 9", "GRYPHONNE",
           "HIVE FLEET KRAK", "UNKNOWN"]
_THREAT = [("MINIMAL", GREEN), ("LOW", GREEN), ("MODERATE", AMBER), ("HIGH", AMBER),
           ("EXTREMIS", RED)]
_NUMERALS = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII"]

_S: dict = {}


def _new_culture(t0):
    s = _S
    s["t0"] = t0
    name, F, k, it = _rng.choice(_STRAINS)
    s["strain"], s["F"], s["k"], s["it"] = name, F, k, it
    s["id"] = "CULTURE %s-%s" % (_rng.choice(_NUMERALS), _rng.choice("ABGDEZ"))
    s["origin"] = _rng.choice(_ORIGIN)
    U = np.ones((N, N), np.float32)
    V = np.zeros((N, N), np.float32)
    seeds = []
    for _ in range(_rng.randint(3, 6)):
        a = _rng.uniform(0, 2 * math.pi)
        r = _rng.uniform(0, DR * 0.7)
        seeds.append(((N - 1) / 2 + r * math.cos(a), (N - 1) / 2 + r * math.sin(a)))
    s["seeds"] = seeds
    s["U"], s["V"] = U, V
    s["seeded"] = 0
    s["hist"] = []
    s["cov"] = 0.0
    s["phase"] = "grow"
    s["purge_t"] = None
    s["ret"] = [float(DCX), float(DCY)]
    s["tgt"] = None
    s["tgt_t"] = -10.0
    s["card"] = None
    s["nspec"] = 0
    s["gen"] = 0
    s["sat"] = 0
    s["temp"] = _rng.uniform(36.2, 38.4)


def _reset():
    _S.clear()
    _ph.reset()
    _S["bg"] = _static_bg()
    _new_culture(0.0)


def _static_bg():
    img = Image.new("RGB", (240, 240), (0, 0, 0))
    d = ImageDraw.Draw(img)
    r = DR * SC
    # dish grid
    for g in range(-4, 5):
        o = g * 16
        h = math.sqrt(max(0.0, r * r - o * o))
        d.line([(DCX + o, DCY - h), (DCX + o, DCY + h)], fill=GREEN_FAINT)
        d.line([(DCX - h, DCY + o), (DCX + h, DCY + o)], fill=GREEN_FAINT)
    d.ellipse([DCX - r - 2, DCY - r - 2, DCX + r + 2, DCY + r + 2], outline=GREEN_MID)
    d.ellipse([DCX - r - 6, DCY - r - 6, DCX + r + 6, DCY + r + 6], outline=GREEN_DIM)
    for i in range(60):
        a = math.radians(i * 6)
        r0 = r + 6
        r1 = r + (11 if i % 5 == 0 else 8)
        d.line([(DCX + r0 * math.cos(a), DCY + r0 * math.sin(a)),
                (DCX + r1 * math.cos(a), DCY + r1 * math.sin(a))],
               fill=GREEN_MID if i % 5 == 0 else GREEN_DIM)
    return img


def _step(n, F, k, feed_mask=None):
    s = _S
    U, V = s["U"], s["V"]
    for _ in range(n):
        Up = np.pad(U, 1, mode="edge")
        Vp = np.pad(V, 1, mode="edge")
        lu = Up[:-2, 1:-1] + Up[2:, 1:-1] + Up[1:-1, :-2] + Up[1:-1, 2:] - 4 * U
        lv = Vp[:-2, 1:-1] + Vp[2:, 1:-1] + Vp[1:-1, :-2] + Vp[1:-1, 2:] - 4 * V
        uvv = U * V * V
        U += 0.16 * lu - uvv + F * (1 - U)
        V += 0.08 * lv + uvv - (F + k) * V
        V *= _DISH
        U[_DISH == 0] = 1.0
    s["gen"] += n


def _seed(i):
    s = _S
    x, y = s["seeds"][i]
    xi, yi = int(x), int(y)
    s["U"][yi - 2:yi + 3, xi - 2:xi + 3] = 0.5
    s["V"][yi - 2:yi + 3, xi - 2:xi + 3] = 0.25 + 0.1 * _rng.random()


def _field_masks(V):
    v = np.clip(V * 3.2, 0, 1)
    gx = np.abs(np.diff(v, axis=1, append=0))
    gy = np.abs(np.diff(v, axis=0, append=0))
    edge = np.clip((gx + gy) * 2.6, 0, 1)
    fill = (v * 70).astype(np.uint8)
    edge = (edge * 255).astype(np.uint8)
    fm = Image.fromarray(fill, "L").resize((N * SC, N * SC), Image.BILINEAR)
    em = Image.fromarray(edge, "L").resize((N * SC, N * SC), Image.BILINEAR)
    return fm, em


def _pick_target():
    s = _S
    V = s["V"]
    ys, xs = np.nonzero(V > 0.22)
    if len(xs) == 0:
        return None
    j = _rng.randrange(len(xs))
    return (DX + xs[j] * SC + 1.0, DY + ys[j] * SC + 1.0)


def _new_card():
    s = _S
    s["nspec"] += 1
    th = _THREAT[min(len(_THREAT) - 1, int(s["cov"] * 7 + _rng.random() * 1.5))]
    return {"id": "SPECIMEN %02d" % s["nspec"], "genus": _rng.choice(_GENUS),
            "threat": th, "div": "%.1fM/S" % _rng.uniform(0.4, 9.9)}


def render(bezel, mask, now: float) -> Image.Image:
    if _session.fresh(now) or not _S:
        _reset()
    s = _S
    tt = _session.t(now)
    lt = tt - s["t0"]
    blink = int(tt * 4) % 2 == 0

    # ---------------- simulation / phases
    nseeds = len(s["seeds"])
    while s["seeded"] < nseeds and lt > 0.6 + s["seeded"] * 0.7:
        _seed(s["seeded"])
        s["seeded"] += 1
    if s["phase"] == "grow":
        _step(s["it"], s["F"], s["k"])
        if int(lt * 30) % 6 == 0:
            s["cov"] = float(((s["V"] > 0.15) * _DISH).sum() / _DISH_N)
            s["hist"].append(s["cov"])
            if len(s["hist"]) > 64:
                s["hist"].pop(0)
            if len(s["hist"]) > 30 and s["hist"][-1] - s["hist"][-30] < 0.01 and s["cov"] > 0.2:
                s["sat"] += 1
        if (s["cov"] > 0.6 or s["sat"] > 12 or lt > 80) and lt > 20:
            s["phase"] = "purge"
            s["purge_t"] = lt
    elif s["phase"] == "purge":
        pa = lt - s["purge_t"]
        if pa < 3.0:
            _step(max(2, s["it"] // 2), s["F"], s["k"])
        else:
            # sterilising sweep from the rim inward
            rr = DR * (1 - (pa - 3.0) / 1.6)
            kill = _grr > rr
            s["V"][kill] = 0.0
            s["U"][kill] = 1.0
            if pa > 4.8:
                s["phase"] = "sterile"
                s["V"][:] = 0
                s["cov"] = 0.0
        if pa > 3.0:
            s["cov"] = float(((s["V"] > 0.15) * _DISH).sum() / _DISH_N)
    else:
        if lt - s["purge_t"] > 8.5:
            _new_culture(tt)
            lt = 0.0

    img = s["bg"].copy()
    d = ImageDraw.Draw(img)
    box = (DX, DY, DX + N * SC, DY + N * SC)

    cov = s["cov"]
    warn = cov > 0.3 and s["phase"] == "grow"
    purge_age = lt - s["purge_t"] if s["purge_t"] is not None else -1

    # ---------------- culture field
    if s["phase"] != "sterile":
        fm, em = _field_masks(s["V"])
        img.paste(GREEN_MID, box, fm)
        col = GREEN_HI
        if s["phase"] == "purge" and purge_age < 3.0 and blink:
            col = AMBER
        img.paste(col, box, em)

    # rim tint on warning
    r = DR * SC
    if warn or (s["phase"] == "purge" and purge_age < 3.0):
        c = AMBER if s["sat"] < 4 else (RED if blink else AMBER)
        a0 = (tt * 40) % 360
        for k in range(6):
            d.arc([DCX - r - 4, DCY - r - 4, DCX + r + 4, DCY + r + 4],
                  a0 + k * 60, a0 + k * 60 + 30, fill=c, width=2)
    # purge sweep ring + flash
    if s["phase"] == "purge" and purge_age >= 3.0:
        pr = r * max(0.0, 1 - (purge_age - 3.0) / 1.6)
        if pr > 0:
            d.ellipse([DCX - pr, DCY - pr, DCX + pr, DCY + pr], outline=GREEN_HI, width=3)
        if purge_age < 3.35:
            k = 1 - (purge_age - 3.0) / 0.35
            d.ellipse([DCX - r, DCY - r, DCX + r, DCY + r], fill=scale(GREEN_HI, k * 0.9))

    # ---------------- scanning reticle + classification card
    if s["phase"] == "grow" and lt > 5:
        if s["tgt"] is None or lt - s["tgt_t"] > 5.5:
            p = _pick_target()
            if p is not None:
                s["tgt"], s["tgt_t"] = p, lt
                s["card"] = _new_card()
        if s["tgt"] is not None:
            rx, ry = s["ret"]
            tx, ty = s["tgt"]
            rx += (tx - rx) * 0.12
            ry += (ty - ry) * 0.12
            s["ret"] = [rx, ry]
            age = lt - s["tgt_t"]
            rr = 11 - 4 * min(1.0, age / 1.2)
            d.ellipse([rx - rr, ry - rr, rx + rr, ry + rr], outline=GREEN_HI)
            for (ax, ay) in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                d.line([(rx + ax * (rr + 2), ry + ay * (rr + 2)), (rx + ax * (rr + 8), ry + ay * (rr + 8))],
                       fill=GREEN_HI)
            # scan beam from rim marker
            if age > 1.2:
                card = s["card"]
                cw, ch = 88, 38
                cx0 = rx + 14 if rx < CX else rx - 14 - cw
                cy0 = min(max(ry - ch / 2, 42), 150)
                cx0 = min(max(cx0, 26), 214 - cw)
                reveal = min(4, int((age - 1.2) / 0.25))
                d.rectangle([cx0, cy0, cx0 + cw, cy0 + ch], fill=(0, 0, 0), outline=GREEN)
                d.line([(rx, ry), (cx0 if cx0 > rx else cx0 + cw, cy0 + ch / 2)], fill=GREEN_MID)
                lines = [(card["id"], GREEN_HI), (card["genus"], GREEN),
                         ("THREAT " + card["threat"][0], card["threat"][1]),
                         ("DIV " + card["div"], GREEN_MID)]
                for j in range(reveal):
                    _txt(d, cx0 + 3, cy0 + 1 + j * 9, lines[j][0], lines[j][1], 9)

    # ---------------- HUD
    _txtc(d, 16, "BIOLOGIS", GREEN_MID, 9)
    _txtc(d, 26, s["id"], GREEN_HI, 10)
    # left column
    _txt(d, 12, 86, "STRAIN", GREEN_DIM, 9)
    _txt(d, 12, 96, s["strain"], GREEN, 9)
    _txt(d, 12, 112, "GEN", GREEN_DIM, 9)
    _txt(d, 12, 122, "%05d" % (s["gen"] // 10), GREEN, 9)
    _txt(d, 12, 138, "TEMP", GREEN_DIM, 9)
    _txt(d, 12, 148, "%.1f" % (s["temp"] + 0.2 * math.sin(tt * 0.7)), GREEN, 9)
    # right column
    _txtr(d, 228, 86, "MASS", GREEN_DIM, 9)
    _txtr(d, 228, 96, "%d%%" % int(cov * 100), AMBER if warn else GREEN, 9)
    h = s["hist"]
    rate = (h[-1] - h[-6]) * 100 if len(h) > 6 else 0.0
    _txtr(d, 228, 112, "RATE", GREEN_DIM, 9)
    _txtr(d, 228, 122, "%+.1f" % rate, GREEN, 9)
    _txtr(d, 228, 138, "CONT", GREEN_DIM, 9)
    lvl = 0 if cov < 0.3 else (1 if s["sat"] < 4 and cov < 0.5 else 2)
    cont = ("SEALED", "STRAIN", "BREACH")[lvl]
    _txtr(d, 228, 148, cont, (GREEN, AMBER, RED)[lvl], 9)

    # growth-rate graph
    gx0, gy0, gw, gh = CX - 40, 192, 80, 16
    d.rectangle([gx0 - 1, gy0 - 1, gx0 + gw + 1, gy0 + gh + 1], outline=GREEN_DIM)
    ty = gy0 + gh - 0.62 * gh
    for x in range(gx0, gx0 + gw, 4):
        d.point((x, ty), fill=AMBER)
    if len(h) > 1:
        pts = [(gx0 + i * gw / 63, gy0 + gh - min(1.0, v) * gh) for i, v in enumerate(h)]
        d.line(pts, fill=GREEN_HI)
    # status
    if s["phase"] == "grow":
        if lt < 5:
            _txtc(d, 212, "INOCULATING", GREEN_HI if blink else GREEN_MID, 9)
        elif warn:
            _txtc(d, 212, "CONTAINMENT WARNING", AMBER if blink else GREEN_MID, 9)
        else:
            _txtc(d, 212, "INCUBATING", GREEN_MID, 9)
    elif s["phase"] == "purge":
        if purge_age < 3.0:
            _txtc(d, 150, "PURGE IN %d" % (3 - int(purge_age)), RED if blink else AMBER, 14)
            _txtc(d, 212, "PURGE PROTOCOL", RED, 9)
        else:
            _txtc(d, 212, "PROMETHIUM FLUSH", AMBER, 9)
    else:
        _txtc(d, 100, "DISH STERILE", GREEN_HI, 13)
        _txtc(d, 116, "PRAISE THE OMNISSIAH", GREEN_MID, 9)
        if lt - s["purge_t"] > 5.5:
            _txtc(d, 130, "NEW SAMPLE", GREEN if blink else GREEN_DIM, 9)
        _txtc(d, 212, "STERILE", GREEN_MID, 9)
    return _ph.compose(img)
