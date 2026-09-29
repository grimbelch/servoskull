"""Chaos Corruption Spread – the warp gnaws at a cogitator's data-lattice.

A 60x60 numpy cellular field of corruption sits over a green-phosphor lattice of
data tiles (aquila, cog, skull, Inquisitorial I, circuit traces). Warp breaches,
each aligned to one of the Ruinous Powers, send out wandering tendrils; a noisy
growth rule fills the gaps into glitching blocks of corrupted data that burn
through the monochrome screen in the god's own impossible colour, and the lattice
near the front shears under an animated displacement field. Consecrated firewall
wards slam down with a phosphor shockwave and push the corruption back. A
feedback controller keeps the tug-of-war balanced but random; each ~100 s
"engagement" ends with a verdict (held or lost) and a fresh lattice.
"""

from __future__ import annotations

import math
import random

import numpy as np
from PIL import Image, ImageChops, ImageDraw

from ..classic._phosphor import (AMBER, GREEN, GREEN_DIM, GREEN_FAINT, GREEN_HI, GREEN_MID,
                                 RED as ALARM, Phosphor)
from ._common import CX, CY, Session, font, safe_half_width

NAME = "chaos_corruption"

_rng = random.Random()
_session = Session()
_ph = Phosphor(decay=0.3, bloom=0.45, flicker=0.03)

G = 60            # simulation grid
CELL = 4          # px per cell
GODS = [                          # warp light: the only colours a phosphor screen shouldn't show
    ("KHORNE", (230, 30, 20)),
    ("TZEENTCH", (140, 70, 255)),
    ("NURGLE", (190, 190, 30)),
    ("SLAANESH", (240, 60, 200)),
    ("UNDIVIDED", (200, 20, 110)),
]
_GODCOL = np.array([c for _, c in GODS], np.float32)

_gy, _gx = np.mgrid[0:G, 0:G].astype(np.float32)
_GDIST = np.sqrt((_gx - (G - 1) / 2) ** 2 + (_gy - (G - 1) / 2) ** 2)
_INSIDE = (_GDIST <= 27.5).astype(np.float32)
_NIN = float(_INSIDE.sum())
_py, _px = np.mgrid[0:240, 0:240]
_PXF = _px.astype(np.float32)
_PYF = _py.astype(np.float32)
_rr = np.sqrt((_PXF - 119.5) ** 2 + (_PYF - 119.5) ** 2)
_band = np.maximum(np.clip(1 - np.abs(_PYF - 32) / 17, 0, 1), np.clip(1 - np.abs(_PYF - 204) / 15, 0, 1))
_PXFL = _PXF.ravel()
_CELLIDX = ((_py // CELL) * G + (_px // CELL)).ravel()
_PYFL = _PYF.ravel()
_VIGN = ((1 - 0.6 * np.clip((_rr - 88) / 24, 0, 1)) * (1 - 0.62 * _band ** 0.7)).astype(np.float32)[..., None]
_VIGNF = _VIGN.reshape(-1, 1)


# ── helpers ─────────────────────────────────────────────────────────────────
_TXT: dict = {}


def _tsprite(text, size):
    key = (text, size)
    m = _TXT.get(key)
    if m is None:
        if len(_TXT) > 300:
            _TXT.clear()
        f = font(size)
        l, t, r, b = f.getbbox(text)
        im = Image.new("L", (max(1, int(r)) + 2, max(1, int(b)) + 2), 0)
        ImageDraw.Draw(im).text((0, 0), text, fill=255, font=f)
        m = _TXT[key] = (im, f.getlength(text))
    return m


def _fit(img, y, text, fill, size, shadow=None):
    hw = safe_half_width(y + size * 0.6, 4)
    while size > 9 and _tsprite(text, size)[1] > 2 * hw:
        size -= 1
    m, w = _tsprite(text, size)
    x = int(CX - w / 2)
    if shadow is not None:
        for ox, oy in ((1, 1), (-1, 0), (1, 0), (0, -1)):
            img.paste(shadow, (x + ox, int(y) + oy), m)
    img.paste(fill, (x, int(y)), m)


def _smooth_noise(h, w, cells, rng):
    base = np.array([[rng.random() for _ in range(cells)] for _ in range(cells)], np.float32)
    im = Image.fromarray(base).resize((w, h), Image.BICUBIC)
    a = np.asarray(im)
    return (a - a.min()) / max(1e-6, float(a.max() - a.min()))


def _build_tiles(rng):
    """The cogitator's data-lattice: 12x12 phosphor tiles, each with a sacred glyph."""
    img = Image.new("RGB", (240, 240), (0, 0, 0))
    d = ImageDraw.Draw(img)
    T = 20
    for j in range(12):
        for i in range(12):
            x0, y0 = i * T, j * T
            d.rectangle([x0 + 1, y0 + 1, x0 + T - 2, y0 + T - 2], outline=GREEN_FAINT)
            ink = GREEN_MID if rng.random() < 0.35 else GREEN_DIM
            k = rng.random()
            cx, cy = x0 + 10, y0 + 10
            if k < 0.22:      # aquila wings
                d.line([(cx - 6, cy - 2), (cx, cy + 1), (cx + 6, cy - 2)], fill=ink)
                d.line([(cx - 5, cy + 1), (cx, cy + 3), (cx + 5, cy + 1)], fill=ink)
                d.point([(cx - 1, cy - 2), (cx + 1, cy - 2)], fill=ink)
            elif k < 0.40:    # cog
                d.ellipse([cx - 4, cy - 4, cx + 4, cy + 4], outline=ink)
                for a in range(0, 360, 45):
                    r = math.radians(a)
                    d.point((cx + round(math.cos(r) * 6), cy + round(math.sin(r) * 6)), fill=ink)
            elif k < 0.52:    # skull
                d.ellipse([cx - 4, cy - 5, cx + 4, cy + 2], outline=ink)
                d.point([(cx - 2, cy - 2), (cx + 2, cy - 2)], fill=ink)
                d.line([(cx - 2, cy + 4), (cx + 2, cy + 4)], fill=ink)
            elif k < 0.64:    # inquisitorial I
                d.line([(cx, cy - 6), (cx, cy + 6)], fill=ink)
                for yy in (-5, 0, 5):
                    d.line([(cx - 3, cy + yy), (cx + 3, cy + yy)], fill=ink)
            else:             # data circuit
                d.line([(x0 + 4, cy), (cx, cy), (cx, y0 + 16)], fill=ink)
                d.point((x0 + 4, cy), fill=GREEN_HI)
    return np.asarray(img).astype(np.float32)


def _build_seal():
    """A consecrated firewall ward (RGBA): a ringed cog with the Inquisitorial I."""
    W = H = 30
    s = 3
    im = Image.new("RGBA", (W * s, H * s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    c = W * s / 2
    hi, mid = GREEN_HI + (255,), GREEN + (255,)
    d.ellipse([c - 13 * s, c - 13 * s, c + 13 * s, c + 13 * s], outline=mid, width=s)
    for a in range(0, 360, 30):                               # cog teeth
        r = math.radians(a)
        d.line([(c + math.cos(r) * 10 * s, c + math.sin(r) * 10 * s),
                (c + math.cos(r) * 13 * s, c + math.sin(r) * 13 * s)], fill=mid, width=2 * s)
    d.ellipse([c - 8 * s, c - 8 * s, c + 8 * s, c + 8 * s], fill=(0, 0, 0, 255), outline=hi, width=s)
    d.line([(c, c - 6 * s), (c, c + 6 * s)], fill=hi, width=s)
    for yy in (-5, 0, 5):
        d.line([(c - 3 * s, c + yy * s), (c + 3 * s, c + yy * s)], fill=hi, width=s)
    return im.resize((W, H), Image.LANCZOS)


_SEAL = _build_seal()
_SEAL_SCALED = [(k, _SEAL.resize((max(1, int(_SEAL.width * k)), max(1, int(_SEAL.height * k))), Image.BILINEAR))
                for k in (2.4, 2.0, 1.7, 1.45, 1.25, 1.1, 1.0)]
_SEAL_FADE = [(_SEAL, _SEAL.getchannel("A").point(lambda v, a=a: int(v * a))) for a in (0.8, 0.6, 0.4, 0.2)]

_S: dict = {}
_GODS_STORM = (190, 80, 255)

STATUS_BREACH = ["WARP BREACH DETECTED", "HERESY IN THE LATTICE", "DAEMONIC INCURSION", "REALITY FAILING"]
STATUS_SEAL = ["FIREWALL WARD DEPLOYED", "LATTICE CONSECRATED", "LITANY OF PURITY", "BY HIS WILL: PURGE"]


def _new_cycle(t0):
    rng = _rng
    tiles = _build_tiles(rng)
    n1 = _smooth_noise(G, G, 7, rng) * 2 * math.pi
    n2 = _smooth_noise(G, G, 9, rng) * 2 * math.pi
    fine = _smooth_noise(240, 240, 40, rng)
    veins = _smooth_noise(240, 240, 18, rng)
    veins = np.clip(1.0 - np.abs(veins - 0.5) * 14.0, 0, 1)  # ridged network
    _S.clear()
    _S.update(t0=t0, c=np.zeros((G, G), np.float32), god=np.zeros((G, G), np.int16),
              pur=np.zeros((G, G), np.float32), tips=[], seals=[], rifts=[], last=None,
              tiles8=tiles.astype(np.uint8).reshape(-1, 3), tiles_v=np.clip(tiles * _VIGN, 0, 255).astype(np.uint8), ph1=n1.astype(np.float32), ph2=n2.astype(np.float32),
              thr=(0.42 + 0.22 * fine).astype(np.float32).ravel(), veins=(1 - 0.55 * veins).astype(np.float32).reshape(-1, 1),
              next_seal=rng.uniform(9, 14), next_rift=0.5, storm=0.0, msg=("CATHEDRAL LATTICE SECURE", 0.0),
              length=rng.uniform(95, 120), verdict=None, hist=[], sector=f"{rng.randint(1, 99):02d}-{rng.choice('ABGKMTX')}")


def _reset():
    _new_cycle(0.0)


def _spawn_rift(t, strong=False):
    a = _rng.uniform(0, 2 * math.pi)
    r = _rng.uniform(0, 22)
    x, y = 29.5 + math.cos(a) * r, 29.5 + math.sin(a) * r
    god = _rng.randrange(len(GODS))
    _S["rifts"].append(dict(x=x, y=y, god=god, t0=t, life=_rng.uniform(10, 18) * (1.4 if strong else 1.0)))
    for _ in range(_rng.randint(3, 5)):
        _S["tips"].append([x, y, _rng.uniform(0, 2 * math.pi), god, _rng.randint(60, 140)])
    _S["msg"] = (f"{GODS[god][0]} STIRS" if _rng.random() < 0.5 else _rng.choice(STATUS_BREACH), t)


def _drop_seal(t):
    c = _S["c"]
    # target the densest corruption (coarse box blur, then argmax)
    k = c.copy()
    for ax in (0, 1):
        k = k + np.roll(k, 3, ax) + np.roll(k, -3, ax)
    k *= (_GDIST < 22)
    j = int(np.argmax(k + np.random.default_rng(_rng.randrange(1 << 30)).random(k.shape) * 0.5))
    y, x = divmod(j, G)
    _S["seals"].append(dict(x=x + 0.5, y=y + 0.5, t0=t, life=_rng.uniform(12, 17), rmax=_rng.uniform(12, 17)))
    if _S.get("verdict") is None:
        _S["msg"] = (_rng.choice(STATUS_SEAL), t)


def _step(t, dt):
    S = _S
    c, god, pur = S["c"], S["god"], S["pur"]
    # rifts pump corruption
    alive = []
    for r in S["rifts"]:
        age = t - r["t0"]
        if age < r["life"]:
            alive.append(r)
            xi, yi = int(r["x"]), int(r["y"])
            c[max(0, yi - 1):yi + 2, max(0, xi - 1):xi + 2] = 1.0
            god[max(0, yi - 1):yi + 2, max(0, xi - 1):xi + 2] = r["god"]
            if _rng.random() < 0.08 and len(S["tips"]) < 70:
                S["tips"].append([r["x"], r["y"], _rng.uniform(0, 2 * math.pi), r["god"], _rng.randint(50, 120)])
    S["rifts"] = alive
    # tendrils
    tips = []
    for tp in S["tips"]:
        x, y, a, g, life = tp
        a += _rng.uniform(-0.45, 0.45)
        sp = 0.28 * (1.6 if S["storm"] > 0 else 1.0)
        x += math.cos(a) * sp
        y += math.sin(a) * sp
        xi, yi = int(x), int(y)
        if not (0 <= xi < G and 0 <= yi < G) or _GDIST[yi, xi] > 27.5 or pur[yi, xi] > 0.45:
            continue
        c[yi, xi] = 1.0
        god[yi, xi] = g
        life -= 1
        if life > 0:
            tips.append([x, y, a, g, life])
            if _rng.random() < 0.03 and len(tips) < 70:
                tips.append([x, y, a + _rng.choice([-1, 1]) * _rng.uniform(0.6, 1.2), g, int(life * 0.7)])
    S["tips"] = tips
    # organic growth: lobed by an animated phase field
    m = (np.roll(c, 1, 0) + np.roll(c, -1, 0) + np.roll(c, 1, 1) + np.roll(c, -1, 1)) * 0.25
    lobes = (0.5 + 0.5 * np.sin(S["ph1"] + t * 0.7) * np.cos(S["ph2"] - t * 0.45)) ** 2
    rate = 0.9 * (1.8 if S["storm"] > 0 else 1.0)
    grow = dt * rate * np.clip(m - 0.18, 0, None) * lobes * (1.0 - np.minimum(1.0, pur * 2.5))
    c += grow
    # god-alignment propagates with the growth front
    for ax, sh in ((0, 1), (0, -1), (1, 1), (1, -1)):
        rc = np.roll(c, sh, ax)
        take = rc > c + 0.25
        if take.any():
            god[take] = np.roll(god, sh, ax)[take]
    # purity pushes back, then decays
    c -= dt * 2.2 * pur
    np.clip(c, 0, 1, out=c)
    c *= _INSIDE
    pur *= max(0.0, 1.0 - 0.09 * dt)
    # seals: expanding consecrated ring
    alive = []
    for s in S["seals"]:
        age = t - s["t0"]
        if age > s["life"]:
            continue
        alive.append(s)
        if age < 0.35:
            continue
        r = min(s["rmax"], (age - 0.35) * 7.0)
        dd = np.sqrt((_gx - s["x"]) ** 2 + (_gy - s["y"]) ** 2)
        band = np.abs(dd - r) < 1.6
        inner = dd < r
        if r < s["rmax"]:
            c[band] *= 0.15
        np.maximum(pur, inner * (0.9 if age < s["life"] - 3 else 0.3), out=pur)
    S["seals"] = alive


def render(bezel, mask, now: float) -> Image.Image:
    if _session.fresh(now):
        _reset()
        _ph.reset()
    ta = _session.t(now)
    S = _S
    if S.get("pending"):
        _new_cycle(ta)
        S = _S
    t = ta - S["t0"]
    dt = 1 / 30 if S["last"] is None else min(0.1, max(0.0, now - S["last"]))
    S["last"] = now
    c = S["c"]
    P = float((c * _INSIDE).sum() / _NIN)

    # ── the tug-of-war controller ──
    if S["verdict"] is None:
        if t >= S["next_rift"] and (P < 0.35 or _rng.random() < 0.01):
            _spawn_rift(t, strong=P < 0.1)
            S["next_rift"] = t + _rng.uniform(3, 7)
        if t >= S["next_seal"] and P > _rng.uniform(0.3, 0.62):
            burst = 3 if P > 0.6 else (2 if P > 0.45 else 1)
            for _ in range(burst):
                _drop_seal(t + _rng.uniform(0, 0.4))
            S["next_seal"] = t + _rng.uniform(4, 9)
        if S["storm"] <= 0 and _rng.random() < 0.0015 and t > 20:
            S["storm"] = _rng.uniform(5, 8)
            S["msg"] = ("WARP STORM SURGES", t)
        if t > S["length"]:
            S["verdict"] = ("SECTOR LOST TO THE WARP" if P > 0.5 else "SECTOR HOLDS. FOR NOW.", t, P)
            S["msg"] = (S["verdict"][0], t)
            if P <= 0.5:
                for _ in range(4):
                    _drop_seal(t + _rng.uniform(0, 0.6))
    S["storm"] = max(0.0, S["storm"] - dt)
    _step(t, dt)

    # ── compose (only pixels touched by corruption / purity are recomputed) ──
    out = S["tiles_v"].copy()
    of = out.reshape(-1, 3)
    cs = np.asarray(Image.fromarray(c).resize((240, 240), Image.BILINEAR)).ravel()
    idx = np.flatnonzero(cs > 0.02)
    if idx.size:
        csi = cs[idx]
        # animated warp displacement for the tile mosaic
        wx = (np.sin(S["ph1"] * 2 + t * 1.9) * c).astype(np.float32)
        wy = (np.cos(S["ph2"] * 2 - t * 1.6) * c).astype(np.float32)
        wx = np.asarray(Image.fromarray(wx).resize((240, 240), Image.BILINEAR)).ravel()[idx]
        wy = np.asarray(Image.fromarray(wy).resize((240, 240), Image.BILINEAR)).ravel()[idx]
        sx = np.clip((_PXFL[idx] + wx * 12.0).astype(np.intp), 0, 239)
        sy = np.clip((_PYFL[idx] + wy * 12.0).astype(np.intp), 0, 239)
        tiles = S["tiles8"][sy * 240 + sx]
        # flesh colour per cell (god hue, pulsing), upscaled
        pulse = 0.55 + 0.45 * np.sin(S["ph1"] * 3 + t * 3.3 + c * 5)
        glitch = np.random.default_rng().random((G, G)).astype(np.float32)   # per-block data noise
        gc = _GODCOL[S["god"]]
        flesh_c = gc * ((0.6 + 0.4 * pulse) * (0.12 + 0.88 * glitch ** 2.5))[..., None]  # sparse bright blocks
        ci = _CELLIDX[idx]
        flesh = np.asarray(Image.fromarray(np.clip(flesh_c, 0, 255).astype(np.uint8)).resize((240, 240), Image.NEAREST)
                           ).reshape(-1, 3)[idx] * S["veins"][idx]
        rim_col = gc.reshape(-1, 3)[ci] * 0.6 + 110
        thr = S["thr"][idx]
        tint = np.minimum(csi * 1.6, 1.0)[:, None] * 0.55
        o = tiles * (1 - tint) + (flesh * 0.8) * tint
        dcs = (csi - thr)[:, None]
        o = np.where(dcs > 0, flesh, o)
        o = np.where(np.abs(dcs) < 0.035, rim_col, o)
        o = np.where((dcs > -0.09) & (dcs < -0.035), o * 0.45, o)
        o *= _VIGNF[idx]
        of[idx] = np.clip(o, 0, 255)
    img = Image.fromarray(out)
    # consecrated ground shimmer (additive gold glow, computed per cell)
    pur = S["pur"]
    if pur.max() > 0.02:
        k = (0.07 + 0.04 * math.sin(t * 5)) * pur * _INSIDE
        glow = np.clip(k[..., None] * np.array(GREEN, np.float32), 0, 255).astype(np.uint8)
        img = ImageChops.add(img, Image.fromarray(glow).resize((240, 240), Image.BILINEAR))
    d = ImageDraw.Draw(img)

    # seals + shockwaves
    for s in S["seals"]:
        age = t - s["t0"]
        px, py = s["x"] * CELL, s["y"] * CELL
        if age < 0:
            continue
        if age >= 0.35:
            r = min(s["rmax"], (age - 0.35) * 7.0) * CELL
            if r < s["rmax"] * CELL:
                a = 1 - r / (s["rmax"] * CELL)
                col = tuple(int(h * a + m * (1 - a)) for h, m in zip(GREEN_HI, GREEN_DIM))
                d.ellipse([px - r, py - r, px + r, py + r], outline=col, width=2)
            if age < 0.6:
                fr = 12 * (1 - (age - 0.35) / 0.25)
                d.ellipse([px - fr, py - fr, px + fr, py + fr], fill=GREEN_HI)
        if age < 0.35:
            k = min(len(_SEAL_SCALED) - 1, int(age / 0.35 * len(_SEAL_SCALED)))
            spr = _SEAL_SCALED[k][1]
            img.paste(spr, (int(px - spr.width / 2), int(py - spr.width / 2 + 4)), spr)
        else:
            rem = s["life"] - age
            spr = _SEAL
            m = spr
            if rem < 2.0:
                m = _SEAL_FADE[min(3, int((2.0 - rem) / 0.5))][1]
            img.paste(spr, (int(px - spr.width / 2), int(py - 13)), m)

    # ── HUD ──
    rim_r = 108
    box = [CX - rim_r, CY - rim_r, CX + rim_r, CY + rim_r]
    a0, a1 = 212, 328
    d.arc(box, a0, a1, fill=GREEN_FAINT, width=7)
    meter = GREEN if P < 0.4 else (AMBER if P < 0.6 else ALARM)
    d.arc(box, a0, a0 + (a1 - a0) * P, fill=meter, width=5)
    for k in range(6):
        a = math.radians(a0 + (a1 - a0) * k / 5)
        d.line([(CX + math.cos(a) * 100, CY + math.sin(a) * 100), (CX + math.cos(a) * 104, CY + math.sin(a) * 104)],
               fill=GREEN_MID)
    pc = int(round(P * 100))
    _fit(img, 22, f"CORRUPTION {pc}%", GREEN_HI if P < 0.4 else meter, 11)
    _fit(img, 36, f"LATTICE SECTOR {S['sector']}", GREEN_MID, 9)
    msg, mt = S["msg"]
    if t - mt < 5.0 or S["verdict"] is not None:
        if (t - mt) > 0.6 or int((t - mt) * 8) % 2 == 0:
            big = S["verdict"] is not None
            good = any(w in msg for w in ("WARD", "PURITY", "HOLDS", "PURGE", "CONSECRATED", "SECURE"))
            if big:                                           # the verdict gets an alarm box
                d.rectangle([CX - 104, 104, CX + 104, 130], fill=(0, 0, 0),
                            outline=GREEN_HI if good else ALARM, width=2)
            _fit(img, 200 if not big else 110, msg, GREEN_HI if good else AMBER if not big else ALARM,
                 10 if not big else 14)
    if S["storm"] > 0 and int(t * 4) % 2 == 0:
        _fit(img, 186, "WARP STORM", _GODS_STORM, 10)
    if S["verdict"] is not None and t - S["verdict"][1] > 7.0:
        S["pending"] = True
    return _ph.compose(img)
