"""Astronomican Pulse - a Navigator's beacon-scope.

The Astronomican burns gold at the centre of the instrument. Rhythmic psychic
pulses expand outward as rings (every fourth a strong choir-surge); where they
strike a warp storm they cast shadow cones and echo rings that interfere with
the next pulse. Star systems flare as each pulse passes. Our voidship's line of
sight to Terra is tracked: when a swirling warp storm drifts across it the
signal fails (LIGHT OCCLUDED) until the storm passes and the beacon is
reacquired. Signal strength and distance from Terra are read out.
"""

from __future__ import annotations

import math
import random

import numpy as np
from PIL import Image, ImageDraw

from ..lore._common import CX, CY, Session, font
from ._phosphor import AMBER, GREEN, GREEN_DIM, GREEN_FAINT, GREEN_HI, GREEN_MID, RED, Phosphor, blank

NAME = "astronomican_pulse"

_rng = random.Random()
_session = Session()
_ph = Phosphor(decay=0.5, bloom=0.5)
_S: dict = {}

HR = 80
SC = 240 // HR
PULSE_V = 36.0          # px / s
PULSE_T = 1.7           # s between pulses
GOLD = (255, 205, 110)
SYSTEMS = ["CADIA", "BAAL", "FENRIS", "MACRAGGE", "RYZA", "CATACHAN", "NOCTURNE", "ARMAGEDDON", "VALHALLA", "MORDIAN"]

_hy, _hx = np.mgrid[0:HR, 0:HR].astype(np.float32)
_X = (_hx + 0.5) * SC - CX
_Y = (_hy + 0.5) * SC - CY
_R = np.sqrt(_X * _X + _Y * _Y)
_TH = np.arctan2(_Y, _X)
_GLOW = (0.55 * np.exp(-_R / 16.0) + 0.12 * np.exp(-_R / 60.0)).astype(np.float32)
_RAMP = np.zeros((256, 3), np.uint8)
for _i in range(256):
    _v = _i / 255.0
    _RAMP[_i] = (int(min(255, 40 * _v + 200 * max(0, _v - 0.75) * 4)),
                 int(min(255, 235 * _v ** 0.9)),
                 int(min(255, 90 * _v + 120 * max(0, _v - 0.7) * 3)))

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


def _angdiff(a, b):
    return (a - b + math.pi) % (2 * math.pi) - math.pi


def _reset():
    _S.clear()
    _S["last"] = None
    stars = []
    for i in range(46):
        a = _rng.uniform(0, 6.283)
        r = 20 + 88 * math.sqrt(_rng.random())
        stars.append((r * math.cos(a), r * math.sin(a), _rng.uniform(0.15, 0.45)))
    _S["stars"] = np.array(stars, np.float32)
    names = _rng.sample(SYSTEMS, 4)
    ok = [i for i, (x, y, _b) in enumerate(stars) if abs(y) < 45 and 25 < abs(x) < 72]
    while len(ok) < 4:
        i = len(stars)
        stars.append((_rng.choice((-1, 1)) * _rng.uniform(30, 70), _rng.uniform(-40, 40), 0.3))
        ok.append(i)
    _S["stars"] = np.array(stars, np.float32)
    _S["named"] = [(i, names[k]) for k, i in enumerate(_rng.sample(ok, 4))]
    ship_a = _rng.uniform(-2.6, -2.1) if _rng.random() < 0.5 else _rng.uniform(-1.05, -0.55)
    _S["ship_a"] = ship_a
    _S["ship_r"] = 84.0
    # storm A is set to cross the line of sight around t=40s; B drifts elsewhere
    wA = 0.07 * _rng.choice((-1, 1))
    _S["storms"] = [
        {"d": 50.0, "a0": ship_a - wA * 40, "w": wA, "rad": 19.0, "ph": _rng.uniform(0, 6)},
        {"d": 72.0, "a0": ship_a + math.pi * 0.9, "w": -0.03, "rad": 14.0, "ph": _rng.uniform(0, 6)},
    ]
    _S["dist"] = _rng.uniform(22000, 48000)
    _S["sig"] = 0.8
    _S["occluded"] = False
    _S["reacq"] = -10.0
    _S["lost_t"] = -10.0
    _S["bg"] = _build_bg()
    _ph.reset()


def _build_bg():
    m1 = Image.new("L", (240, 240), 0)
    m2 = Image.new("L", (240, 240), 0)
    d1, d2 = ImageDraw.Draw(m1), ImageDraw.Draw(m2)
    for k in range(72):
        a = k * math.pi / 36
        r0 = 102 if k % 6 else 97
        (d1 if k % 6 else d2).line([(CX + r0 * math.cos(a), CY + r0 * math.sin(a)),
                                    (CX + 107 * math.cos(a), CY + 107 * math.sin(a))], fill=255)
    return m1, m2


def render(bezel, mask, now: float) -> Image.Image:
    if _session.fresh(now):
        _reset()
    S = _S
    ta = _session.t(now)
    dt = 1 / 30 if S["last"] is None else min(0.1, max(0.0, now - S["last"]))
    S["last"] = now

    # storms (positions, breathing radius)
    storms = []
    for st in S["storms"]:
        a = st["a0"] + st["w"] * ta
        rad = st["rad"] * (1 + 0.18 * math.sin(ta * 0.4 + st["ph"]))
        storms.append((st["d"], a, rad, st["ph"]))

    # ── field (half res) ──
    sdist = []
    for (sd, sa, srad, _p) in storms:
        ex, ey = sd * math.cos(sa), sd * math.sin(sa)
        sdist.append(np.sqrt((_X - ex) ** 2 + (_Y - ey) ** 2))
    F = _GLOW * (0.85 + 0.15 * math.sin(ta * 5.0))
    n0 = int(ta / PULSE_T)
    ship_a = S["ship_a"] + 0.08 * math.sin(ta * 0.01)
    ship_r = S["ship_r"]
    for n in range(n0, n0 - 5, -1):
        if n < 0:
            break
        age = ta - n * PULSE_T
        Rp = age * PULSE_V
        if Rp > 150:
            break
        strong = n % 4 == 0 or (ta - S["reacq"] < 3 and n == int(S["reacq"] / PULSE_T) + 1)
        amp = (1.0 if strong else 0.55) * max(0.0, 1 - Rp / 150)
        w = 3.4 if strong else 2.6
        m = np.abs(_R - Rp) < w * 3
        if m.any():
            F[m] += amp * np.exp(-((_R[m] - Rp) / w) ** 2)
        # echo rings from storms (interference)
        for (sd, sa, srad, _p), Re in zip(storms, sdist):
            er = Rp - sd
            if 0 < er < 60:
                me = (np.abs(Re - er) < 6.0) & (Re > srad)
                if me.any():
                    F[me] += 0.35 * amp * (1 - er / 60) * np.exp(-((Re[me] - er) / 2.0) ** 2)
    # interference fringe texture
    F *= 0.85 + 0.15 * np.cos(_R * 0.9 - ta * 6.0)
    # storm shadows + dark cores
    shade = np.ones_like(F)
    for (sd, sa, srad, _p), dd in zip(storms, sdist):
        half = math.asin(min(0.99, srad / sd))
        dth = np.abs((_TH - sa + math.pi) % (2 * math.pi) - math.pi)
        cone = np.clip((half - dth) / (half * 0.35), 0, 1) * np.clip((_R - sd) / 6.0, 0, 1)
        shade *= 1 - 0.85 * cone
        shade *= np.clip((dd - srad * 0.5) / (srad * 0.6), 0.05, 1)
    F *= shade
    idx = np.clip(F * 230, 0, 255).astype(np.uint8)
    col = _RAMP[idx]
    img = Image.fromarray(col).resize((240, 240), Image.BILINEAR)
    img.paste(GREEN_DIM, (0, 0), S["bg"][0])
    img.paste(GREEN_MID, (0, 0), S["bg"][1])
    d = ImageDraw.Draw(img)

    # ── beacon core (gold) ──
    pulse_ph = (ta % PULSE_T) / PULSE_T
    cr = 5 + 2.5 * math.exp(-pulse_ph * 6)
    d.ellipse([CX - cr - 3, CY - cr - 3, CX + cr + 3, CY + cr + 3], outline=_col(GOLD, 0.6))
    d.ellipse([CX - cr, CY - cr, CX + cr, CY + cr], fill=GOLD)
    d.ellipse([CX - 2, CY - 2, CX + 2, CY + 2], fill=(255, 250, 230))
    for k in range(4):
        a = k * math.pi / 2 + math.pi / 4
        d.line([(CX + 9 * math.cos(a), CY + 9 * math.sin(a)), (CX + 14 * math.cos(a), CY + 14 * math.sin(a))],
               fill=_col(GOLD, 0.7))

    # ── stars ──
    st = S["stars"]
    sxi = np.clip(((st[:, 0] + CX) / SC).astype(np.int32), 0, HR - 1)
    syi = np.clip(((st[:, 1] + CY) / SC).astype(np.int32), 0, HR - 1)
    fv = F[syi, sxi]
    br = np.clip(st[:, 2] + 1.4 * np.clip(fv - _GLOW[syi, sxi] * 0.9, 0, 1), 0, 1.3) * shade[syi, sxi]
    xs = (st[:, 0] + CX).tolist()
    ys = (st[:, 1] + CY).tolist()
    brl = br.tolist()
    for i in range(len(xs)):
        b = brl[i]
        x, y = xs[i], ys[i]
        if b > 0.75:
            c = GREEN_HI
            d.line([(x - 2, y), (x + 2, y)], fill=c)
            d.line([(x, y - 2), (x, y + 2)], fill=c)
        else:
            d.rectangle([x, y, x + 1, y + 1], fill=_col(GREEN, 0.35 + b))
    for i, nm in S["named"]:
        b = brl[i]
        x, y = xs[i], ys[i]
        d.rectangle([x - 2, y - 2, x + 2, y + 2], outline=_col(GREEN, 0.4 + 0.6 * min(1.0, b)))
        lx = x + 5 if x < CX + 30 else x - 5
        _text(img, lx, y - 5, nm, _col(GREEN_MID, 0.6 + 0.6 * min(1.0, b)), 9, "l" if x < CX + 30 else "r")

    # ── warp storm swirls ──
    for (sd, sa, srad, ph) in storms:
        ex, ey = CX + sd * math.cos(sa), CY + sd * math.sin(sa)
        rot = ta * 0.9 + ph
        for arm in range(3):
            pts = []
            for k in range(9):
                u = k / 8
                a = rot + arm * 2.094 + u * 3.2
                r = srad * (0.2 + 0.9 * u)
                pts.append((ex + r * math.cos(a), ey + r * math.sin(a)))
            d.line(pts, fill=_col(GREEN_MID, 0.75))
        d.ellipse([ex - 1.5, ey - 1.5, ex + 1.5, ey + 1.5], fill=_col(RED, 0.8))

    # ── our ship + line of sight ──
    sx_, sy_ = CX + ship_r * math.cos(ship_a), CY + ship_r * math.sin(ship_a)
    occluded = False
    for (sd, sa, srad, _p) in storms:
        if sd < ship_r and abs(_angdiff(ship_a, sa)) < math.asin(min(0.99, srad / sd)) * 0.8:
            occluded = True
    if occluded and not S["occluded"]:
        S["lost_t"] = ta
    if not occluded and S["occluded"]:
        S["reacq"] = ta
    S["occluded"] = occluded
    los_c = _col(AMBER, 0.6) if occluded else _col(GREEN, 0.45)
    for k in range(14):
        u0, u1 = (k + 0.2) / 14, (k + 0.6) / 14
        if u0 * ship_r < 16:
            continue
        d.line([(CX + (sx_ - CX) * u0, CY + (sy_ - CY) * u0), (CX + (sx_ - CX) * u1, CY + (sy_ - CY) * u1)], fill=los_c)
    hd = ship_a + math.pi  # heading toward Terra
    c = AMBER if occluded else GREEN_HI
    tri = [(sx_ + 6 * math.cos(hd), sy_ + 6 * math.sin(hd)),
           (sx_ + 4 * math.cos(hd + 2.4), sy_ + 4 * math.sin(hd + 2.4)),
           (sx_ + 4 * math.cos(hd - 2.4), sy_ + 4 * math.sin(hd - 2.4))]
    d.polygon(tri, outline=c)
    # received pulse at ship
    recv = float(F[min(HR - 1, max(0, int(sy_ / SC))), min(HR - 1, max(0, int(sx_ / SC)))])
    target = (0.78 + 0.2 * min(1.0, recv * 2.0) - 0.08 * (S["dist"] > 40000)) * (0.06 if occluded else 1.0)
    S["sig"] += (target - S["sig"]) * min(1.0, dt * 2.5)
    sig = S["sig"]
    if recv > 0.35 and not occluded:
        rr = 8
        d.ellipse([sx_ - rr, sy_ - rr, sx_ + rr, sy_ + rr], outline=GREEN)

    # ── HUD ──
    S["dist"] -= dt * 0.9
    _text(img, CX, 18, "ASTRONOMICAN", _col(GOLD, 0.85), 10)
    if occluded:
        lab = "LIGHT OCCLUDED"
        c = RED if int(ta * 3) % 2 else AMBER
    elif ta - S["reacq"] < 4:
        lab, c = "BEACON REACQUIRED", GREEN_HI
    elif any(abs(_angdiff(ship_a, s[1])) < 0.6 and s[0] < ship_r for s in storms):
        lab, c = "WARP STORM CLOSING", AMBER
    else:
        lab, c = "BEACON LOCK", GREEN
    _text(img, CX, 30, lab, c, 10)
    # signal bar
    x0, x1, y0 = CX - 42, CX + 42, 196
    d.rectangle([x0, y0, x1, y0 + 5], outline=GREEN_DIM)
    fill_w = (x1 - x0 - 2) * max(0.0, min(1.0, sig))
    d.rectangle([x0 + 1, y0 + 1, x0 + 1 + fill_w, y0 + 4], fill=GREEN if sig > 0.4 else AMBER)
    _text(img, CX, 182, f"SIGNAL {int(sig * 100):02d}%", GREEN_HI if sig > 0.4 else AMBER, 10)
    _text(img, CX, 205, f"TERRA {int(S['dist']):,} LY".replace(",", "."), GREEN_MID, 9)
    return _ph.compose(img)
