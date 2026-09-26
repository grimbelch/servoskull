"""Neural Net - the Cogitation Lattice.

A layered network (input -> hidden -> hidden -> output) hangs in 3D and sways
slowly for parallax. Edge brightness shows weight magnitude. Each cycle begins
with TRAINING: forward passes ripple signal pulses through the lattice, backward
passes return gradients, weights drift toward their trained values and a loss
curve is plotted as it falls. On convergence the lattice switches to
INFERENCE: sample inputs propagate forward and the winning output is named
with its confidence. Then the lattice is reseeded and trained again.
"""

from __future__ import annotations

import math
import random

import numpy as np
from PIL import Image, ImageDraw

from ..lore._common import CX, CY, Session, font
from ._phosphor import AMBER, GREEN, GREEN_DIM, GREEN_FAINT, GREEN_HI, GREEN_MID, RED, Phosphor, blank

NAME = "neural_net"

_rng = random.Random()
_nrng = np.random.default_rng()
_session = Session()
_ph = Phosphor(decay=0.6, bloom=0.55)
_S: dict = {}

LAYERS = [5, 7, 7, 3]
LX = 52.0
LY = 15.0
FOV, CAM = 300.0, 320.0
CYCLE = 100.0
T_TRAIN = 58.0
CLASSES = ["SERVITOR", "HERETEK", "XENOS", "PSYKER", "PILGRIM", "OGRYN"]

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


# node world positions
_POS = []
_LIDX = []
for _l, _n in enumerate(LAYERS):
    idx = []
    for _i in range(_n):
        x = (_l - (len(LAYERS) - 1) / 2) * LX
        y = (_i - (_n - 1) / 2) * LY
        z = 10.0 * math.sin(_i * 1.7 + _l)
        idx.append(len(_POS))
        _POS.append((x, y, z))
    _LIDX.append(idx)
_POS = np.array(_POS, np.float32)
_EDGES = []  # (layer, i_local, j_local, src_global, dst_global)
for _l in range(len(LAYERS) - 1):
    for _i in range(LAYERS[_l]):
        for _j in range(LAYERS[_l + 1]):
            _EDGES.append((_l, _i, _j, _LIDX[_l][_i], _LIDX[_l + 1][_j]))
_ESRC = np.array([e[3] for e in _EDGES])
_EDST = np.array([e[4] for e in _EDGES])
_ELAY = np.array([e[0] for e in _EDGES])


def _build_bg():
    img = blank()
    d = ImageDraw.Draw(img)
    d.ellipse([CX - 110, CY - 110, CX + 110, CY + 110], outline=GREEN_FAINT)
    for k in range(24):
        a = k * math.pi / 12
        d.line([(CX + 104 * math.cos(a), CY + 104 * math.sin(a)),
                (CX + 109 * math.cos(a), CY + 109 * math.sin(a))], fill=GREEN_DIM)
    _text(img, CX, 18, "COGITATION LATTICE", GREEN_MID, 10)
    # loss plot frame
    x0, x1, y0, y1 = CX - 52, CX + 52, 166, 192
    d.line([(x0, y0), (x0, y1), (x1, y1)], fill=GREEN_DIM)
    for k in range(1, 4):
        d.point([(x0 + k * 26, y1 - 1), (x0 + 1, y0 + k * 6.5)], fill=GREEN_DIM)
    return img


def _new_cycle(t0):
    S = _S
    S["c0"] = t0
    S["W0"] = _nrng.normal(0, 0.9, len(_EDGES)).astype(np.float32)
    S["W1"] = _nrng.normal(0, 1.0, len(_EDGES)).astype(np.float32)
    S["W1"] *= (np.abs(S["W1"]) > 0.35)  # trained lattice is sparser / crisper
    S["loss0"] = _rng.uniform(1.8, 2.6)
    S["kl"] = _rng.uniform(3.5, 5.0)
    S["hist"] = []
    S["pass_n"] = -1
    S["inp"] = _nrng.uniform(0, 1, LAYERS[0]).astype(np.float32)
    S["cls"] = _rng.sample(CLASSES, 3)
    S["result"] = None


def _reset():
    _S.clear()
    _S["bg"] = _build_bg()
    _S["last"] = None
    _new_cycle(0.0)
    _ph.reset()


def _forward(W, inp):
    """Returns per-layer display activations in 0..1 (hidden units are tanh internally)."""
    acts = [inp]
    a = inp * 2 - 1
    for l in range(len(LAYERS) - 1):
        m = _ELAY == l
        w = W[m].reshape(LAYERS[l], LAYERS[l + 1])
        z = a @ w
        if l < len(LAYERS) - 2:
            a = np.tanh(z)
            acts.append((a * 0.5 + 0.5).astype(np.float32))
        else:
            z = z * 1.6
            e = np.exp(z - z.max())
            acts.append((e / e.sum()).astype(np.float32))
    return acts


def render(bezel, mask, now: float) -> Image.Image:
    if _session.fresh(now):
        _reset()
    S = _S
    ta = _session.t(now)
    if ta - S["c0"] >= CYCLE:
        _new_cycle(ta)
    tc = ta - S["c0"]
    training = tc < T_TRAIN
    prog = min(1.0, tc / T_TRAIN)
    learn = 1 - math.exp(-4.0 * prog)

    # passes
    pdur = 1.8 if training else 2.6
    pn = int(tc / pdur)
    pu = (tc % pdur) / pdur
    if pn != S["pass_n"]:
        S["pass_n"] = pn
        if not training:
            want = pn % LAYERS[-1]
            cand = _nrng.uniform(0, 1, (16, LAYERS[0])).astype(np.float32)
            Wc = S["W1"]
            pick = cand[0]
            for c_ in cand:
                if int(np.argmax(_forward(Wc, c_)[-1])) == want:
                    pick = c_
                    break
            S["inp"] = pick
        else:
            S["inp"] = _nrng.uniform(0, 1, LAYERS[0]).astype(np.float32)
            loss = S["loss0"] * math.exp(-S["kl"] * prog) + 0.04 + _rng.uniform(-0.06, 0.06) * (1.2 - prog)
            S["hist"].append(max(0.02, loss))
    W = S["W0"] * (1 - learn) + S["W1"] * learn
    if training:
        W = W + _nrng.normal(0, 0.06 * (1 - prog), len(W)).astype(np.float32)
    acts = _forward(W, S["inp"])
    act_all = np.concatenate(acts)

    # forward progress in layer units: 0..3 during first part of pass
    nL = len(LAYERS) - 1
    if training:
        fwd = min(nL + 0.3, pu / 0.55 * (nL + 0.3))
        bwd = max(0.0, (pu - 0.6) / 0.4) * nL if pu > 0.6 else -1.0
    else:
        fwd = min(nL + 0.3, pu / 0.6 * (nL + 0.3))
        bwd = -1.0

    # projection (sway)
    yaw = 0.5 * math.sin(ta * 0.09)
    pitch = 0.18 + 0.08 * math.sin(ta * 0.13)
    cyw, syw, cp, sp = math.cos(yaw), math.sin(yaw), math.cos(pitch), math.sin(pitch)
    x, y, z = _POS[:, 0], _POS[:, 1], _POS[:, 2]
    x2 = x * cyw + z * syw
    z2 = -x * syw + z * cyw
    y2 = y * cp - z2 * sp
    z3 = y * sp + z2 * cp
    f = FOV / (z3 + CAM)
    sx = CX - 8 + x2 * f
    sy = CY - 14 + y2 * f
    sxl, syl, fl = sx.tolist(), sy.tolist(), f.tolist()

    img = S["bg"].copy()
    d = ImageDraw.Draw(img)

    # edges
    aw = np.abs(W)
    eb = np.clip(aw / 1.8, 0, 1)
    src_act = act_all[_ESRC]
    lit_l = np.floor(fwd).astype(int) if fwd >= 0 else -1
    Wl = W.tolist()
    ebl = eb.tolist()
    sal = src_act.tolist()
    pulses_hi, pulses_lo = [], []
    for k, (l, i, j, s, t) in enumerate(_EDGES):
        b = ebl[k]
        active = l < fwd
        c = _col(GREEN, 0.12 + 0.55 * b * (1.4 if active else 1.0))
        if Wl[k] < 0:
            c = _col(c, 0.6)
        d.line([(sxl[s], syl[s]), (sxl[t], syl[t])], fill=c, width=2 if b > 0.75 else 1)
        # forward pulse
        u = fwd - l
        if 0 <= u <= 1 and sal[k] * b > 0.2:
            px = sxl[s] + (sxl[t] - sxl[s]) * u
            py = syl[s] + (syl[t] - syl[s]) * u
            (pulses_hi if sal[k] * b > 0.45 else pulses_lo).append((px, py))
        # backward gradient pulse
        if bwd >= 0:
            ub = bwd - (nL - 1 - l)
            if 0 <= ub <= 1 and b > 0.4:
                px = sxl[t] + (sxl[s] - sxl[t]) * ub
                py = syl[t] + (syl[s] - syl[t]) * ub
                pulses_lo.append((px, py))
    for px, py in pulses_lo:
        d.rectangle([px - 1, py - 1, px + 1, py + 1], fill=GREEN_MID)
    for px, py in pulses_hi:
        d.ellipse([px - 2, py - 2, px + 2, py + 2], fill=GREEN_HI)

    # nodes
    best = int(np.argmax(acts[-1]))
    fwd_done = fwd >= nL
    for l, idx in enumerate(_LIDX):
        reached = l <= fwd
        for i, g in enumerate(idx):
            a = float(acts[l][i])
            r = 3.2 * fl[g] + 1.0
            xg, yg = sxl[g], syl[g]
            if reached:
                glow = 0.35 + 0.75 * a
                if l == len(LAYERS) - 1 and not training and fwd_done and i == best:
                    c = GREEN_HI
                    d.ellipse([xg - r - 4, yg - r - 4, xg + r + 4, yg + r + 4], outline=GREEN)
                else:
                    c = _col(GREEN, glow)
                d.ellipse([xg - r, yg - r, xg + r, yg + r], fill=c, outline=GREEN_HI if a > 0.8 else c)
            else:
                d.ellipse([xg - r, yg - r, xg + r, yg + r], fill=(0, 18, 7), outline=GREEN_MID)

    # output class tags
    if not training:
        for i, g in enumerate(_LIDX[-1]):
            win = fwd_done and i == best
            _text(img, sxl[g] + 9, syl[g] - 6, S["cls"][i][:3], GREEN_HI if win else GREEN_DIM, 9, "l")

    # layer labels
    lab_y = CY - 14 + (max(LAYERS) / 2 + 0.6) * LY
    for l, lab in enumerate(("IN", "H1", "H2", "OUT")):
        g = _LIDX[l][-1]
        _text(img, sxl[g], syl[g] + 7, lab, GREEN_DIM, 9)

    # ── HUD ──
    ep = int(tc / 1.8 * 7) if training else int(T_TRAIN / 1.8 * 7)
    hist = S["hist"]
    if training:
        if tc < 3:
            lab, c = "LATTICE RESEEDED", AMBER
        else:
            lab, c = "TRAINING", GREEN
    elif tc < T_TRAIN + 3:
        lab, c = "CONVERGENCE ACHIEVED", GREEN_HI
    else:
        lab, c = "INFERENCE", GREEN
    _text(img, CX, 30, lab, c, 11)

    # loss curve
    x0, x1, y0, y1 = CX - 52, CX + 52, 166, 192
    if len(hist) > 1:
        top = S["loss0"] * 1.1
        n = len(hist)
        nmax = max(n, int(T_TRAIN / 1.8) + 1)
        pts = [(x0 + 1 + (x1 - x0 - 2) * i / (nmax - 1), y1 - 2 - (y1 - y0 - 4) * min(1.0, v / top))
               for i, v in enumerate(hist)]
        d.line(pts, fill=GREEN if training else GREEN_MID)
        if training:
            d.ellipse([pts[-1][0] - 2, pts[-1][1] - 2, pts[-1][0] + 2, pts[-1][1] + 2], fill=GREEN_HI)
    loss_now = hist[-1] if hist else S["loss0"]
    if training or tc < T_TRAIN + 3:
        _text(img, CX, 196, f"EPOCH {ep:04d}  LOSS {loss_now:.3f}", GREEN_MID, 9)
    else:
        if fwd_done:
            conf = float(acts[-1][best])
            _text(img, CX, 196, f"{S['cls'][best]}  {conf * 100:4.1f}%", GREEN_HI, 11)
        else:
            _text(img, CX, 196, "PROPAGATING", GREEN_MID, 9)
    _text(img, x0 - 4, y0 - 2, "L", GREEN_DIM, 9, "r")
    return _ph.compose(img)
