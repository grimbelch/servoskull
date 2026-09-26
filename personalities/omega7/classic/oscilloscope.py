"""Cogitator oscilloscope – multi-channel phosphor scope.

A real 8x8-division graticule with a beam that is rendered by dwell time
(fast edges dim, slow sweeps bright). The scope auto-cycles through modes:
Y-T dual trace (sine + ringing square, with the odd captured glitch), Y-T quad
(sine / square / sawtooth / noise), X-Y Lissajous figures with long
afterglow, and an FFT spectrum with dB scale and peak marker. Channel labels,
V/div, timebase, trigger markers and measurements are all read out.
"""

from __future__ import annotations

import math
import random

import numpy as np
from PIL import Image, ImageDraw

from ..lore._common import CX, CY, Session, font, scale
from ._phosphor import (AMBER, GREEN, GREEN_DIM, GREEN_FAINT, GREEN_HI, GREEN_MID, RED,
                        Phosphor)

NAME = "oscilloscope"

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
_ph = Phosphor(decay=0.5, bloom=0.7)

DIV = 18
X0, X1 = CX - 4 * DIV, CX + 4 * DIV
Y0, Y1 = CY - 4 * DIV, CY + 4 * DIV
RX0 = RY0 = X0 - 6                # beam buffer covers the graticule plus a margin
RW = X1 - X0 + 13


def _lut(c_lo, c_hi):
    lut = np.zeros((256, 3), dtype=np.float32)
    for i in range(256):
        k = i / 255.0
        if k < 0.6:
            q = k / 0.6
            lut[i] = [c_lo[j] * q for j in range(3)]
        else:
            q = (k - 0.6) / 0.4
            lut[i] = [c_lo[j] * (1 - q) + c_hi[j] * q for j in range(3)]
    return lut.astype(np.uint8)


_LUT_A = _lut(GREEN, (215, 255, 225))
_LUT_B = _lut((30, 170, 120), (170, 255, 220))
_LUT_C = _lut(GREEN_MID, GREEN)

MODES = [("YT2", 32.0), ("XY", 34.0), ("YT4", 28.0), ("FFT", 30.0)]
MODE_NAME = {"YT2": "Y-T DUAL", "YT4": "Y-T QUAD", "XY": "X-Y LISSAJOUS", "FFT": "FFT SPECTRUM"}
RATIOS = [(1, 1), (1, 2), (2, 3), (3, 4), (3, 5), (5, 4), (1, 3)]

_S = {}


def _build_graticule():
    img = Image.new("RGB", (240, 240), (0, 0, 0))
    d = ImageDraw.Draw(img)
    for i in range(9):
        x = X0 + i * DIV
        y = Y0 + i * DIV
        for q in range(Y0, Y1 + 1, 3):
            d.point((x, q), fill=GREEN_FAINT)
        for q in range(X0, X1 + 1, 3):
            d.point((q, y), fill=GREEN_FAINT)
    d.rectangle([X0, Y0, X1, Y1], outline=GREEN_DIM)
    for k in range(0, 8 * 5 + 1):
        x = X0 + k * DIV / 5
        y = Y0 + k * DIV / 5
        L = 2
        d.line([(x, CY - L), (x, CY + L)], fill=GREEN_DIM)
        d.line([(CX - L, y), (CX + L, y)], fill=GREEN_DIM)
    return np.asarray(img, dtype=np.uint8).copy()


def _reset(t):
    _S.clear()
    start = _rng.randrange(len(MODES))
    _S.update(mi=start, mode=MODES[start][0], mode_t=t, grat=_build_graticule(), glitch=None,
              glitch_next=t + _rng.uniform(10, 18), roll=None, roll_next=t + _rng.uniform(14, 24),
              ratio_i=_rng.randrange(len(RATIOS)), ratio_t=t, fft_hold=None, autoset=t,
              f1=_rng.choice((1.0, 2.0, 5.0)), phase_x=0.0)
    _ph.reset()
    _ph.decay = 0.78 if _S["mode"] == "XY" else 0.5


# ------------------------------------------------------------- beam ---
def _beam(acc, xs, ys, w=1.0):
    """Accumulate a beam path into acc by dwell time (sub-sampled per segment)."""
    dx = np.diff(xs)
    dy = np.diff(ys)
    L = np.hypot(dx, dy)
    n = np.maximum(1, np.ceil(L / 0.8)).astype(np.int64)
    idx = np.repeat(np.arange(len(dx)), n)
    starts = np.cumsum(n) - n
    offs = np.arange(int(n.sum())) - np.repeat(starts, n)
    tt = offs / n[idx]
    px = xs[:-1][idx] + dx[idx] * tt
    py = ys[:-1][idx] + dy[idx] * tt
    wt = (w / n ** 0.72)[idx]
    ix = np.clip(px.astype(np.int32) - RX0, 0, RW - 1)
    iy = np.clip(py.astype(np.int32) - RY0, 0, RW - 1)
    acc += np.bincount(iy * RW + ix, weights=wt, minlength=RW * RW).reshape(RW, RW).astype(np.float32)


_ESTEP = 64.0
_ELUT = {g: np.clip((1.0 - np.exp(-np.arange(512) / _ESTEP * g)) * 255, 0, 255).astype(np.uint8)
         for g in (0.9, 1.3)}


def _colorize(acc, lut, gain):
    # soften into a 2px beam (cross-shaped blur via slices), then saturate through a LUT
    a = acc
    b = a.copy()
    b[1:] += 0.3 * a[:-1]
    b[:-1] += 0.3 * a[1:]
    b[:, 1:] += 0.3 * a[:, :-1]
    b[:, :-1] += 0.3 * a[:, 1:]
    b *= _ESTEP
    np.minimum(b, 511, out=b)
    return lut[_ELUT[gain][b.astype(np.int32)]]


# ------------------------------------------------------------- signals ---
def _square(ph, ring=True):
    s = np.where(np.mod(ph, 2 * np.pi) < np.pi, 1.0, -1.0)
    if ring:
        # damped ringing after each edge
        tt = np.mod(ph, np.pi)
        s = s + 0.22 * np.exp(-tt * 9.0) * np.sin(tt * 55.0) * s
    return s


def _saw(ph):
    return (np.mod(ph, 2 * np.pi) / np.pi) - 1.0


def _mode_yt2(t, accA, accB, hud):
    xs = np.linspace(X0, X1, 290)
    u = (xs - X0) / (X1 - X0)                    # 0..1 across the screen
    cycles = 2.5
    trig_off = 0.0 if _S["roll"] is None else (t - _S["roll"]) * 2.3
    ph = 2 * np.pi * (u * cycles - 0.25) + trig_off + _nrng.normal(0, 0.004)
    am = 1.0 + 0.18 * math.sin(t * 0.7)
    y1 = CY - DIV * 1.8 - DIV * 1.6 * am * np.sin(ph)
    sq = _square(ph * 2)
    g = _S["glitch"]
    if g is not None:
        gx = g["u"]
        sq = sq + np.where(np.abs(u - gx) < 0.012, -1.3 * np.sign(sq), 0.0)
    y2 = CY + DIV * 1.8 - DIV * 1.3 * sq + _nrng.normal(0, 0.35, len(xs))
    _beam(accA, xs, y1)
    _beam(accB, xs, y2)
    hud["ch"] = [("1", CY - DIV * 1.8, GREEN_HI), ("2", CY + DIV * 1.8, (120, 255, 200))]
    hud["trig"] = CY - DIV * 1.8
    hud["top"] = [("CH1 2V", GREEN_HI), ("CH2 1V", (120, 255, 200))]
    f = _S["f1"]
    hud["meas"] = f"F1 {f:.3f}kHz  VPP {6.4 * am:.2f}V"
    hud["tb"] = f"TB {int(250 / f)}us"
    if g is not None:
        hud["glitch_x"] = X0 + g["u"] * (X1 - X0)


def _mode_yt4(t, accA, accB, hud):
    xs = np.linspace(X0, X1, 290)
    u = (xs - X0) / (X1 - X0)
    ph = 2 * np.pi * (u * 3.0) + _nrng.normal(0, 0.003)
    base = [CY - DIV * 3, CY - DIV, CY + DIV, CY + DIV * 3]
    y1 = base[0] - DIV * 0.8 * np.sin(ph)
    y2 = base[1] - DIV * 0.75 * _square(ph * 1.5, ring=False)
    y3 = base[2] - DIV * 0.75 * _saw(ph * 2 + t * 0.5)
    n = _nrng.normal(0, 1, len(xs))
    n = np.convolve(n, np.ones(3) / 3, mode="same")
    y4 = base[3] - DIV * 0.35 * n - DIV * 0.3 * np.sin(ph * 0.5 + t)
    _beam(accA, xs, y1)
    _beam(accB, xs, y2)
    _beam(accA, xs, y3)
    _beam(accB, xs, y4)
    hud["ch"] = [("1", base[0], GREEN_HI), ("2", base[1], (120, 255, 200)),
                 ("3", base[2], GREEN_HI), ("4", base[3], (120, 255, 200))]
    hud["trig"] = base[0]
    hud["top"] = [("SIN", GREEN_HI), ("SQR", (120, 255, 200)), ("SAW", GREEN_HI), ("NSE", (120, 255, 200))]
    hud["meas"] = f"F1 {_S['f1']:.3f}kHz  DUTY 50.0%"
    hud["tb"] = f"TB {int(330 / _S['f1'])}us"


def _mode_xy(t, accA, accB, hud):
    if t - _S["ratio_t"] > 5.5:
        _S["ratio_t"] = t
        _S["ratio_i"] = (_S["ratio_i"] + 1) % len(RATIOS)
    a, b = RATIOS[_S["ratio_i"]]
    _S["phase_x"] += 0.018
    s = np.linspace(0, 2 * np.pi, 900)
    amp = DIV * 3.4 * min(1.0, (t - _S["ratio_t"]) * 1.6 + 0.2)
    xs = CX + amp * np.sin(a * s + _S["phase_x"])
    ys = CY - amp * np.sin(b * s)
    _beam(accA, xs, ys, 1.4)
    hud["ch"] = []
    hud["trig"] = None
    hud["top"] = [("X=CH1", GREEN_HI), ("Y=CH2", (120, 255, 200))]
    deg = int(math.degrees(_S["phase_x"])) % 360
    hud["meas"] = f"RATIO {a}:{b}  PHASE {deg:03d}"
    hud["tb"] = "XY MODE"


def _mode_fft(t, accA, accB, hud):
    nb = 145
    f = np.linspace(0, 10, nb)                     # kHz
    f0 = 1.2 + 0.8 * (0.5 + 0.5 * math.sin(t * 0.25))
    spec = np.full(nb, -72.0) + _nrng.normal(0, 2.5, nb)
    for h in range(1, 12, 2):                        # odd harmonics of a square wave
        fh = f0 * h
        if fh > 10:
            break
        lvl = -4 - 20 * math.log10(h)
        spec = np.maximum(spec, lvl - ((f - fh) / 0.09) ** 2 * 3 + _nrng.normal(0, 0.6, nb))
    # a wandering spur
    fs = 7.5 + 1.8 * math.sin(t * 0.61)
    spec = np.maximum(spec, -38 - ((f - fs) / 0.07) ** 2 * 4)
    hold = _S["fft_hold"]
    if hold is None or len(hold) != nb:
        hold = spec.copy()
    hold = np.maximum(hold - 0.25, spec)
    _S["fft_hold"] = hold
    xs = np.linspace(X0, X1, nb)
    to_y = lambda db: Y0 + (-np.clip(db, -80, 0)) / 80.0 * (Y1 - Y0)
    _beam(accA, xs, to_y(spec), 1.0)
    _beam(accB, xs, to_y(hold), 0.35)
    k = int(np.argmax(spec))
    hud["peak"] = (xs[k], float(to_y(spec[k])))
    hud["ch"] = []
    hud["trig"] = None
    hud["top"] = [("REF 0dB", GREEN_HI), ("10dB/DIV", GREEN_MID)]
    hud["meas"] = f"MKR {f[k]:.2f}kHz {spec[k]:5.1f}dB"
    hud["tb"] = "SPAN 10kHz"
    hud["db"] = True


def render(bezel, mask, now: float) -> Image.Image:
    if _session.fresh(now) or not _S:
        _reset(now)
    t = now
    # --- mode cycling
    mode, dur = MODES[_S["mi"]]
    if t - _S["mode_t"] > dur:
        _S["mi"] = (_S["mi"] + 1) % len(MODES)
        _S["mode"] = MODES[_S["mi"]][0]
        _S["mode_t"] = t
        _S["autoset"] = t
        _S["fft_hold"] = None
        _S["f1"] = _rng.choice((1.0, 2.0, 2.5, 5.0))
        _ph.decay = 0.78 if _S["mode"] == "XY" else 0.5
    mode = _S["mode"]
    # --- events
    if mode == "YT2":
        if _S["glitch"] is None and t > _S["glitch_next"]:
            _S["glitch"] = {"u": _rng.uniform(0.55, 0.8), "t0": t}
        if _S["glitch"] is not None and t - _S["glitch"]["t0"] > 3.5:
            _S["glitch"] = None
            _S["glitch_next"] = t + _rng.uniform(12, 20)
        if _S["roll"] is None and t > _S["roll_next"]:
            _S["roll"] = t
        if _S["roll"] is not None and t - _S["roll"] > 2.5:
            _S["roll"] = None
            _S["roll_next"] = t + _rng.uniform(15, 25)
    else:
        _S["glitch"] = None
        _S["roll"] = None

    accA = np.zeros((RW, RW), dtype=np.float32)
    accB = np.zeros((RW, RW), dtype=np.float32)
    hud = {}
    autoset = t - _S["autoset"]
    if autoset < 1.1:
        # AUTOSET: flat traces while the cogitator hunts for a trigger
        xs = np.linspace(X0, X1, 120)
        k = autoset / 1.1
        _beam(accA, xs, CY + np.sin(xs * 0.3 + t * 30) * 20 * (1 - k) * _nrng.random(120), 1.0)
        hud = {"ch": [], "trig": None, "top": [("AUTOSET", AMBER)], "meas": "SEEKING TRIGGER", "tb": "--"}
    elif mode == "YT2":
        _mode_yt2(t, accA, accB, hud)
    elif mode == "YT4":
        _mode_yt4(t, accA, accB, hud)
    elif mode == "XY":
        _mode_xy(t, accA, accB, hud)
    else:
        _mode_fft(t, accA, accB, hud)

    gain = 1.3 if mode != "XY" else 0.9
    frame = _S["grat"].copy()
    reg = frame[RY0:RY0 + RW, RX0:RX0 + RW]
    np.maximum(reg, _colorize(accA, _LUT_A, gain), out=reg)
    np.maximum(reg, _colorize(accB, _LUT_B, gain), out=reg)
    img = Image.fromarray(frame)
    # readouts refresh at 4 Hz like a real scope's measurement panel
    if now - _S.get("meas_t", -9) > 0.25 or _S.get("meas_mode") != (mode, autoset < 1.1):
        _S["meas_t"] = now
        _S["meas_mode"] = (mode, autoset < 1.1)
        _S["meas"] = hud.get("meas", "")
    d = ImageDraw.Draw(img)

    # ---- HUD
    _txt(d, CX, 18, MODE_NAME[mode] if autoset >= 1.1 else "AUTOSET", GREEN_HI, 9, "c")
    tops = hud.get("top", [])
    if tops:
        widths = [_mask(s, 9).width for s, _ in tops]
        total = sum(widths) + 8 * (len(tops) - 1)
        x = CX - total / 2
        for (s, col), w in zip(tops, widths):
            _txt(d, x, 32, s, col, 9, "l")
            x += w + 8
    for label, y, col in hud.get("ch", []):
        d.polygon([(X0 - 9, y - 3), (X0 - 4, y), (X0 - 9, y + 3)], fill=col)
        _txt(d, X0 - 17, y - 6, label, col, 9, "l")
    if hud.get("trig") is not None:
        ty = hud["trig"]
        d.polygon([(X1 + 9, ty - 3), (X1 + 4, ty), (X1 + 9, ty + 3)], fill=AMBER)
        _txt(d, X1 + 10, ty - 6, "T", AMBER, 9, "l")
        tx = X0 + (X1 - X0) * 0.1
        d.polygon([(tx - 3, Y0 - 7), (tx + 3, Y0 - 7), (tx, Y0 - 2)], fill=AMBER)
    if hud.get("db"):
        for i in range(0, 9, 2):
            _txt(d, X0 - 4, Y0 + i * DIV - 6, f"{-10 * i}", GREEN_DIM, 9, "r")
        px, py = hud["peak"]
        d.polygon([(px - 3, py - 8), (px + 3, py - 8), (px, py - 3)], fill=AMBER)
    gx = hud.get("glitch_x")
    if gx is not None and int(t * 5) % 2 == 0:
        d.rectangle([gx - 5, CY + DIV * 0.2, gx + 5, CY + DIV * 3.4], outline=AMBER)
    status = "TRIG'D"
    scol = GREEN_MID
    if _S["roll"] is not None and mode == "YT2":
        status, scol = "AUTO ROLL", AMBER
    elif _S["glitch"] is not None:
        status, scol = "GLITCH CAPTURED", AMBER
    elif mode in ("XY", "FFT"):
        status = "RUN"
    _txt(d, CX, 196, f"{hud.get('tb', '')}  {status}", scol, 9, "c")
    _txt(d, CX, 208, _S["meas"], GREEN, 9, "c")
    return _ph.compose(img)
