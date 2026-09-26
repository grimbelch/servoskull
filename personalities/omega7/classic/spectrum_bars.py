"""VOX-CANTICLE ANALYSER – spectrum analyser for the servo-skull's vox-grille.

Synthesises smooth "music" (kick, snare, hats, bass, choir pads, arpeggios)
in genre-like phases with builds, breaks and drops, and shows it either as a
segmented 36-band linear analyser with falling peak caps above a scrolling
waterfall spectrogram, or as a mirrored radial analyser around a beat-pulse
hub. dB scale, band labels, BPM and stereo levels are read out.
"""

from __future__ import annotations

import math
import random

import numpy as np
from PIL import Image, ImageDraw

from ..lore._common import CX, CY, Session, font, scale
from ._phosphor import (AMBER, GREEN, GREEN_DIM, GREEN_FAINT, GREEN_HI, GREEN_MID, RED,
                        Phosphor)

NAME = "spectrum_bars"

# ------------------------------------------------------------- cached text ---
_TXT = {}


def _mask(text, size):
    key = (text, size)
    m = _TXT.get(key)
    if m is None:
        if len(_TXT) > 300:
            _TXT.clear()
        f = font(size)
        box = f.getbbox(text)
        m = Image.new("L", (max(1, int(box[2]) + 2), max(1, int(box[3]) + 2)), 0)
        ImageDraw.Draw(m).text((0, 0), text, fill=255, font=f)
        _TXT[key] = m
    return m


def _txt(d, x, y, text, fill, size=9, align="l"):
    m = _mask(text, size)
    if align == "c":
        x -= m.width / 2
    elif align == "r":
        x -= m.width
    d.bitmap((int(round(x)), int(round(y))), m, fill=fill)


# ------------------------------------------------------------- constants ---
_rng = random.Random()
_nrng = np.random.default_rng()
_session = Session()
_ph = Phosphor(decay=0.35, bloom=0.6)

NB = 36
BW = 4
LX0 = CX - NB * BW // 2          # 48
BASE = 138                        # bar baseline
BH = 84                           # max bar height
WF0, WFH = 152, 40                # waterfall top / height
_bins = np.arange(NB, dtype=np.float32)

# bar gradient (row 0 = top of bar area)
_GRAD = np.zeros((BH, 3), dtype=np.float32)
for _r in range(BH):
    k = 1 - _r / (BH - 1)             # 1 at top
    if k > 0.86:
        c = AMBER
    elif k > 0.6:
        q = (k - 0.6) / 0.26
        c = tuple(GREEN[i] * (1 - q) + GREEN_HI[i] * q for i in range(3))
    else:
        q = k / 0.6
        c = tuple(GREEN_MID[i] * (1 - q) + GREEN[i] * q for i in range(3))
    _GRAD[_r] = c
_ROWS = np.arange(BH)[:, None]
_SEGROW = ((np.arange(BH) % 3) != 2)[:, None]
_COLGAP = ((np.arange(NB * BW) % BW) != BW - 1)[None, :]

_WF_LUT = np.zeros((256, 3), dtype=np.uint8)
for _i in range(256):
    k = _i / 255
    if k < 0.5:
        c = tuple(GREEN_FAINT[j] + (GREEN_MID[j] - GREEN_FAINT[j]) * k / 0.5 for j in range(3))
    elif k < 0.85:
        c = tuple(GREEN_MID[j] + (GREEN_HI[j] - GREEN_MID[j]) * (k - 0.5) / 0.35 for j in range(3))
    else:
        c = tuple(GREEN_HI[j] + (AMBER[j] - GREEN_HI[j]) * (k - 0.85) / 0.15 for j in range(3))
    _WF_LUT[_i] = [int(v) for v in c]
_WF_LUT[:18] = 0

GENRES = [
    {"name": "MARTIAL CANTICLE", "bpm": 118, "kick": 1.0, "snare": 0.8, "hat": 0.6, "bass": 0.8, "pad": 0.5, "arp": 0.0},
    {"name": "LITANY CHOIR", "bpm": 68, "kick": 0.0, "snare": 0.0, "hat": 0.1, "bass": 0.5, "pad": 1.0, "arp": 0.0},
    {"name": "FORGE HAMMER", "bpm": 140, "kick": 1.2, "snare": 1.0, "hat": 0.9, "bass": 1.0, "pad": 0.2, "arp": 0.0},
    {"name": "BINARIC CHANT", "bpm": 100, "kick": 0.6, "snare": 0.3, "hat": 0.7, "bass": 0.5, "pad": 0.3, "arp": 1.0},
]
SCALE = [0, 3, 5, 7, 10, 12, 15, 17]
PROG = [0, 5, 3, 7]

_S = {}


def _gauss(center, width, amp):
    return amp * np.exp(-((_bins - center) / width) ** 2)


def _reset(t):
    _S.clear()
    order = GENRES[:]
    _rng.shuffle(order)
    _S.update(order=order, gi=0, g_t=t, prev_g=None, beat0=t, beats_prev=-1, view=_rng.choice(("LIN", "RAD")),
              view_t=t, morph=0.0, level=np.zeros(NB, np.float32), peak=np.zeros(NB, np.float32),
              peak_hold=np.zeros(NB, np.float32), peak_v=np.zeros(NB, np.float32),
              wf=np.zeros((WFH, NB * BW, 3), np.uint8), wf_tick=0, kick_env=0.0, drop=None, arp_note=0,
              lvl_lr=[0.0, 0.0], root=_rng.randrange(5))
    _ph.reset()


def _genre_spectrum(g, t, beats, env):
    """Target energy per band for one genre at musical time `beats`."""
    e = 0.06 + 0.04 * _nrng.random(NB).astype(np.float32)
    beat = beats % 1.0
    bar = int(beats // 4)
    in_bar = beats % 4
    cycle = bar % 12
    brk = cycle in (8, 9) and g["kick"] > 0
    riser = cycle == 9 and g["kick"] > 0
    kick = g["kick"] * math.exp(-beat * 9.0) * (0 if brk else 1)
    env["kick"] = max(env["kick"], kick)
    e += _gauss(1.5, 2.2, kick * 1.0)
    # snare on 2 and 4
    sb = (in_bar - 1) % 2
    snare = g["snare"] * math.exp(-sb * 7.0) * (0 if brk else 1) if in_bar >= 1 else 0.0
    e += _gauss(14, 9, snare * 0.55) + snare * 0.12 * _nrng.random(NB).astype(np.float32)
    # hats on eighths
    hb = (beats * 2) % 1.0
    hat = g["hat"] * math.exp(-hb * 16.0)
    e += _gauss(31, 4.5, hat * 0.5)
    # bass follows the chord root
    chord = PROG[bar % 4] + _S["root"]
    bass_bin = 3 + (chord % 12) * 0.35
    e += _gauss(bass_bin, 1.2, g["bass"] * (0.55 + 0.25 * math.exp(-beat * 3)))
    # pads: chord tones with harmonics, slow swell
    swell = 0.6 + 0.4 * math.sin(beats * math.pi / 8)
    for iv in (0, 3, 7):
        nb = 10 + ((chord + iv) % 12) * 0.9
        for h, a in ((0, 1.0), (7, 0.5), (12, 0.3)):
            e += _gauss(nb + h, 1.4, g["pad"] * swell * 0.45 * a)
    # arpeggio: a bright narrow tone stepping on sixteenths
    if g["arp"] > 0:
        step = int(beats * 4)
        note = SCALE[(step * 3 + bar) % len(SCALE)] + chord
        ab = 16 + (note % 24) * 0.7
        e += _gauss(ab, 0.9, g["arp"] * 0.7 * math.exp(-((beats * 4) % 1.0) * 3))
    if riser:
        pos = in_bar / 4
        e += _gauss(6 + pos * 28, 3.0, 0.4 + 0.5 * pos) + pos * 0.25
    return np.clip(e, 0, 1.25), cycle


def _update(t, dt):
    g = _S["order"][_S["gi"]]
    if t - _S["g_t"] > 50.0:
        _S["prev_g"] = (g, t)
        _S["gi"] = (_S["gi"] + 1) % len(_S["order"])
        _S["g_t"] = t
        _S["beat0"] = t
        _S["root"] = _rng.randrange(5)
        g = _S["order"][_S["gi"]]
    beats = (t - _S["beat0"]) * g["bpm"] / 60.0
    env = {"kick": 0.0}
    target, cycle = _genre_spectrum(g, t, beats, env)
    pg = _S["prev_g"]
    if pg is not None:
        k = (t - pg[1]) / 2.5
        if k >= 1:
            _S["prev_g"] = None
        else:
            pb = (t - _S["beat0"]) * pg[0]["bpm"] / 60.0 + 7
            ptarget, _ = _genre_spectrum(pg[0], t, pb, env)
            target = ptarget * (1 - k) + target * k
    # drop moment: first beat of bar 10 in the 12-bar cycle
    bar_now = int(beats // 4)
    if cycle == 10 and g["kick"] > 0 and (_S["drop"] is None or _S["drop"][1] != bar_now):
        _S["drop"] = (t, bar_now)
        target = np.maximum(target, 1.1)
    _S["kick_env"] = env["kick"]
    _S["beats"] = beats
    _S["genre"] = g

    lvl = _S["level"]
    up = target > lvl
    lvl[up] += (target[up] - lvl[up]) * 0.65
    lvl[~up] += (target[~up] - lvl[~up]) * 0.16
    # peak caps: hold then fall with gravity
    pk = _S["peak"]
    ph = _S["peak_hold"]
    pv = _S["peak_v"]
    rise = lvl >= pk
    pk[rise] = lvl[rise]
    ph[rise] = 0.45
    pv[rise] = 0.0
    fall = ~rise
    ph[fall] -= dt
    falling = fall & (ph <= 0)
    pv[falling] += dt * 1.6
    pk[falling] -= pv[falling] * dt
    np.maximum(pk, lvl, out=pk)

    # stereo levels
    tot = float(np.mean(lvl))
    _S["lvl_lr"] = [tot * (1 + 0.1 * math.sin(t * 1.3)), tot * (1 + 0.1 * math.cos(t * 1.1))]

    # waterfall: one row every other frame
    _S["wf_tick"] += 1
    if _S["wf_tick"] % 2 == 0:
        wf = _S["wf"]
        wf[1:] = wf[:-1]
        row = np.clip((lvl * 1.35 - 0.08) * 290, 0, 255).astype(np.uint8)
        wf[0] = _WF_LUT[np.repeat(row, BW)]
        wf[0, BW - 1::BW] = 0

    # view switching with a collapse/expand morph
    vt = t - _S["view_t"]
    if vt > 42.0:
        _S["view"] = "RAD" if _S["view"] == "LIN" else "LIN"
        _S["view_t"] = t
        vt = 0.0
    _S["morph"] = min(1.0, vt / 0.8) * min(1.0, max(0.0, (42.0 - vt) / 0.6))


def _db(v):
    return 20 * math.log10(max(1e-3, v))


def _draw_linear(frame, d, t):
    m = _S["morph"]
    lvl = np.clip(_S["level"] * m * 1.3, 0, 1)
    pk = np.clip(_S["peak"] * m * 1.3, 0, 1)
    h = (lvl * BH).astype(np.int32)
    hcol = np.repeat(h, BW)[None, :]
    lit = (_ROWS >= BH - hcol) & _SEGROW & _COLGAP
    block = lit[..., None] * _GRAD[:, None, :]
    # faint unlit segments give the analyser its LED-panel texture
    ghost = (~lit & _SEGROW & _COLGAP)[..., None] * np.array(GREEN_FAINT, np.float32) * 0.8
    region = frame[BASE - BH:BASE, LX0:LX0 + NB * BW]
    np.maximum(region, block + ghost, out=region)
    # peak caps
    py = (BASE - 1 - pk * BH).astype(np.int32)
    for i in range(NB):
        y = py[i]
        if y < BASE - 2:
            x0 = LX0 + i * BW
            frame[y, x0:x0 + BW - 1] = GREEN_HI if pk[i] < 0.86 else AMBER
    # waterfall
    frame[WF0:WF0 + WFH, LX0:LX0 + NB * BW] = np.maximum(frame[WF0:WF0 + WFH, LX0:LX0 + NB * BW], _S["wf"])


def _draw_linear_hud(d, t):
    d.line([(LX0 - 2, BASE + 1), (LX0 + NB * BW, BASE + 1)], fill=GREEN_MID)
    for db, frac in ((0, 1.0), (-6, 0.5), (-12, 0.25), (-24, 0.063)):
        y = BASE - frac * BH
        d.line([(LX0 - 5, y), (LX0 - 2, y)], fill=GREEN_MID)
        _txt(d, LX0 - 6, y - 5, f"{db}", GREEN_DIM, 9, "r")
    for label, b in (("63", 1), ("250", 8), ("1K", 16), ("4K", 25), ("16K", 33)):
        _txt(d, LX0 + b * BW + 1, BASE + 3, label, GREEN_DIM, 9, "c")
    d.rectangle([LX0 - 1, WF0 - 1, LX0 + NB * BW, WF0 + WFH], outline=GREEN_DIM)


def _draw_radial(d, t):
    m = _S["morph"]
    lvl = _S["level"] * m
    pk = _S["peak"] * m
    kick = _S["kick_env"]
    r0 = 44 + 3 * kick
    # hub
    hr = 26 + 6 * kick
    d.ellipse([CX - hr, CY - hr, CX + hr, CY + hr], outline=scale(GREEN_HI, 0.4 + 0.6 * kick))
    d.ellipse([CX - r0 + 3, CY - r0 + 3, CX + r0 - 3, CY + r0 - 3], outline=GREEN_DIM)
    # waveform ring between hub and bars
    n = 90
    ang = np.linspace(0, 2 * np.pi, n + 1)
    wave = np.zeros(n + 1)
    for i in range(0, NB, 5):
        wave += lvl[i] * np.sin(ang * (2 + i // 3) + t * (3 + i * 0.2))
    rr = 36 + 3.0 * wave / max(1.0, np.max(np.abs(wave)) or 1.0)
    pts = list(zip((CX + rr * np.sin(ang)).tolist(), (CY + rr * np.cos(ang)).tolist()))
    d.line(pts, fill=GREEN_MID)
    for side in (-1, 1):
        for i in range(NB):
            a = math.pi - side * (i + 0.5) / NB * math.pi   # bass at the bottom, treble at the top
            sa, ca = math.sin(a), math.cos(a)
            L = 4 + float(lvl[i]) * 50
            col = AMBER if lvl[i] > 0.9 else (GREEN_HI if lvl[i] > 0.6 else GREEN)
            d.line([(CX + r0 * sa, CY - r0 * ca), (CX + (r0 + L) * sa, CY - (r0 + L) * ca)], fill=col, width=2)
            pr = r0 + 6 + float(pk[i]) * 50
            d.point((CX + pr * sa, CY - pr * ca), fill=GREEN_HI)
    g = _S["genre"]
    _txt(d, CX, CY - 9, f"{g['bpm']}", GREEN_HI, 12, "c")
    _txt(d, CX, CY + 5, "BPM", GREEN_MID, 9, "c")
    # beat pips (4 per bar)
    b = int(_S["beats"]) % 4
    for i in range(4):
        x = CX - 9 + i * 6
        d.rectangle([x, CY + 17, x + 3, CY + 18], fill=GREEN_HI if i == b else GREEN_DIM)


def render(bezel, mask, now: float) -> Image.Image:
    if _session.fresh(now) or not _S:
        _reset(now)
        _S["prev"] = now
    dt = max(0.0, min(0.1, now - _S["prev"]))
    _S["prev"] = now
    _update(now, dt)

    frame = np.zeros((240, 240, 3), dtype=np.float32)
    view = _S["view"]
    if view == "LIN":
        _draw_linear(frame, None, now)
    img = Image.fromarray(frame.astype(np.uint8))
    d = ImageDraw.Draw(img)
    g = _S["genre"]
    if view == "LIN":
        _draw_linear_hud(d, now)
        _txt(d, CX, 26, "VOX-CANTICLE ANALYSER", GREEN_MID, 9, "c")
        _txt(d, CX, 38, f"{g['name']}  {g['bpm']}BPM", GREEN_HI, 9, "c")
        # stereo meters
        for j, (lab, y) in enumerate((("L", 197), ("R", 204))):
            v = min(1.0, _S["lvl_lr"][j] * 1.9)
            _txt(d, CX - 62, y - 3, lab, GREEN_MID, 9, "l")
            for s in range(20):
                x = CX - 54 + s * 5
                on = s < v * 20
                col = (AMBER if s >= 17 else GREEN) if on else GREEN_FAINT
                d.rectangle([x, y, x + 3, y + 3], fill=col)
        peak_db = _db(float(np.max(_S["level"])) / 1.1)
        _txt(d, CX, 211, f"PEAK {peak_db:+5.1f}dB", AMBER if peak_db > -1 else GREEN_MID, 9, "c")
    else:
        _draw_radial(d, now)
        _txt(d, CX, 14, "VOX-CANTICLE", GREEN_MID, 9, "c")
        _txt(d, CX, 216, g["name"], GREEN_HI, 9, "c")
        peak_db = _db(float(np.max(_S["level"])) / 1.1)
        _txt(d, CX, 204, f"PEAK {peak_db:+5.1f}dB", GREEN_DIM, 9, "c")

    drop = _S["drop"]
    if drop is not None and now - drop[0] < 1.6:
        age = now - drop[0]
        k = 1 - age / 1.6
        y = 92 if view == "LIN" else 58
        if int(age * 10) % 2 == 0 or age > 0.6:
            w = _mask("// DROP //", 12).width
            d.rectangle([CX - w / 2 - 4, y - 2, CX + w / 2 + 4, y + 15], fill=(0, 0, 0), outline=scale(AMBER, k * 0.6))
            _txt(d, CX, y, "// DROP //", scale(AMBER, k), 12, "c")
    elif _S["prev_g"] is not None:
        _txt(d, CX, 92 if view == "LIN" else 58, "RETUNING VOX", GREEN_MID, 9, "c")
    else:
        beats = _S["beats"]
        bar = int(beats // 4) % 12
        if bar in (8, 9) and g["kick"] > 0 and int(now * 3) % 2 == 0:
            _txt(d, CX, 92 if view == "LIN" else 58, "BUILD", GREEN_MID, 9, "c")
    return _ph.compose(img)
