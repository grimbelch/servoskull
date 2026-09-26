"""Glitch - a cogitator pict-feed suffering signal corruption.

A steady green-phosphor display (the cog-skull emblem, an auspex telemetry
plot, or a noosphere link status page) runs calmly, with the odd one-frame
blip.  Then a fault burst hits: horizontal tearing, wavy line jitter, amber
ghost images, static bands, block corruption and a rolling vertical hold.
Sometimes the carrier drops out entirely into static.  The cogitator re-syncs,
the picture locks back into place and "SIGNAL RESTORED" is declared - until
the next burst.  Red is used only for the brief fault flags.
"""

from __future__ import annotations

import math
import random

import numpy as np
from PIL import Image, ImageDraw

from ..lore._common import CX, CY, Session, font
from ._phosphor import AMBER, GREEN, GREEN_DIM, GREEN_HI, GREEN_MID, RED, Phosphor, blank

NAME = "glitch"

_rng = random.Random()
_nrng = np.random.default_rng()
_session = Session()
_ph = Phosphor(decay=0.3, bloom=0.55, flicker=0.04)

_TXT: dict = {}
_FAULTS = ["tear", "wave", "ghost", "static", "block", "roll"]
_FAULT_NAMES = {"tear": "H-SYNC TEAR", "wave": "LINE JITTER", "ghost": "GHOST ECHO",
                "static": "NOISE BAND", "block": "BLOCK CORRUPT", "roll": "V-HOLD LOST"}
_GREEN_V = np.array([0.24, 1.0, 0.5], dtype=np.float32)
_AMBER_V = np.array([1.0, 0.7, 0.16], dtype=np.float32)


def _tmask(s, size):
    k = (s, size)
    m = _TXT.get(k)
    if m is None:
        f = font(size)
        m = Image.new("L", (int(math.ceil(f.getlength(s))) + 2, size + 5), 0)
        ImageDraw.Draw(m).text((0, 0), s, fill=255, font=f)
        if len(_TXT) > 400:
            _TXT.clear()
        _TXT[k] = m
    return m


def _txt(img, x, y, s, col, size=10):
    img.paste(col, (int(x), int(y)), _tmask(s, size))


def _txt_c(img, y, s, col, size=10):
    m = _tmask(s, size)
    img.paste(col, (int(CX - (m.width - 2) / 2), int(y)), m)


def _tw(s, size):
    return _tmask(s, size).width - 2


# --------------------------------------------------------------------- scenes

def _scene_emblem(img, d, t):
    cx, cy = CX, 110
    rot = t * 0.25
    pts = []
    teeth = 12
    for i in range(teeth * 4):
        a = rot + 2 * math.pi * i / (teeth * 4)
        r = 50 if (i % 4) in (1, 2) else 42
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    d.polygon(pts, outline=GREEN)
    d.ellipse([cx - 33, cy - 33, cx + 33, cy + 33], outline=GREEN_MID)
    for k in range(4):
        a = -rot * 1.7 + k * math.pi / 2
        d.line([(cx + 33 * math.cos(a), cy + 33 * math.sin(a)),
                (cx + 27 * math.cos(a), cy + 27 * math.sin(a))], fill=GREEN_MID)
    # skull
    d.arc([cx - 17, cy - 22, cx + 17, cy + 10], 160, 380, fill=GREEN_HI)
    d.line([(cx - 16, cy - 2), (cx - 12, cy + 10), (cx - 8, cy + 18), (cx + 8, cy + 18),
            (cx + 12, cy + 10), (cx + 16, cy - 2)], fill=GREEN_HI)
    d.rectangle([cx - 11, cy - 7, cx - 4, cy - 1], fill=GREEN)
    blink = 0.5 + 0.5 * math.sin(t * 3)
    d.ellipse([cx + 3, cy - 8, cx + 12, cy + 1], outline=GREEN_HI)
    d.ellipse([cx + 6, cy - 5, cx + 9, cy - 2], fill=(int(255 * blink), int(60 * blink), 40))
    d.line([(cx, cy + 3), (cx - 3, cy + 8), (cx + 3, cy + 8), (cx, cy + 3)], fill=GREEN)
    for x in (-6, -2, 2, 6):
        d.line([(cx + x, cy + 12), (cx + x, cy + 17)], fill=GREEN_MID)
    _txt_c(img, 34, "PICT-FEED 07", GREEN, 11)
    _txt_c(img, 168, "OMNISSIAH VIGILANT", GREEN_MID, 10)
    # carrier waveform
    y0 = 192
    prev = None
    for i in range(0, 121, 3):
        x = 60 + i
        y = y0 + 5 * math.sin(i * 0.15 - t * 6) * math.sin(i * 0.026 + 0.3)
        if prev:
            d.line([prev, (x, y)], fill=GREEN)
        prev = (x, y)


def _scene_telemetry(img, d, t):
    _txt_c(img, 30, "AUSPEX TELEMETRY", GREEN, 11)
    x0, x1, y0, y1 = 42, 198, 56, 150
    for gx in range(x0, x1 + 1, 26):
        d.line([(gx, y0), (gx, y1)], fill=GREEN_DIM)
    for gy in range(y0, y1 + 1, 23):
        d.line([(x0, gy), (x1, gy)], fill=GREEN_DIM)
    d.rectangle([x0, y0, x1, y1], outline=GREEN_MID)
    my = (y0 + y1) / 2
    p1, p2 = [], []
    for i in range(0, x1 - x0 + 1, 3):
        u = i * 0.05 - t * 2.2
        p1.append((x0 + i, my - 30 * math.sin(u) * (0.6 + 0.4 * math.sin(u * 0.31))))
        p2.append((x0 + i, my + 18 * math.sin(u * 1.7 + 1.0)))
    d.line(p2, fill=GREEN_MID)
    d.line(p1, fill=GREEN_HI)
    amp = 0.8 + 0.1 * math.sin(t * 0.7)
    _txt(img, 56, 160, "AMP %.2f" % amp, GREEN, 10)
    _txt(img, 128, 160, "FRQ %4.1f" % (41 + 3 * math.sin(t * 0.4)), GREEN, 10)
    _txt_c(img, 178, "CONTACT BEARING %03d" % (int(t * 7) % 360), GREEN_MID, 10)
    # sweep marker
    sx = x0 + (t * 40) % (x1 - x0)
    d.line([(sx, y0 + 1), (sx, y1 - 1)], fill=GREEN_MID)


_LINK_ROWS = ["VOX RELAY", "LOGIS CORE", "AUSPEX BUS", "RITE CACHE", "SERVO NET", "DATA TITHE"]


def _scene_link(img, d, t):
    _txt_c(img, 30, "NOOSPHERE LINK 3F", GREEN, 11)
    d.line([(52, 46), (188, 46)], fill=GREEN_MID)
    for i, name in enumerate(_LINK_ROWS):
        y = 54 + i * 17
        _txt(img, 50, y, name, GREEN_MID, 10)
        v = (int(t * (1.3 + i * 0.4)) * 37 + i * 91) % 1000
        _txt(img, 124, y, "%03d" % v, GREEN, 10)
        _txt(img, 160, y, "OK", GREEN_HI, 10)
        w = int(18 + 14 * (0.5 + 0.5 * math.sin(t * (0.8 + i * 0.3) + i)))
        d.rectangle([146, y + 4, 146 + w // 3, y + 9], fill=GREEN_DIM)
    y = 160
    _txt(img, 52, y, "> AWAIT PICT", GREEN, 10)
    if int(t * 2.5) % 2 == 0:
        d.rectangle([52 + _tw("> AWAIT PICT", 10) + 3, y + 2, 52 + _tw("> AWAIT PICT", 10) + 9, y + 12], fill=GREEN)
    _txt_c(img, 184, "LINK INTEGRITY %d%%" % (97 + int(t) % 3), GREEN_MID, 10)


_SCENES = [_scene_emblem, _scene_telemetry, _scene_link]

# --------------------------------------------------------------------- timeline

_S: dict = {}


def _reset(t):
    _S.clear()
    _S.update(t0=t, scene=_rng.randrange(len(_SCENES)), cycle=0, blip=t + 2.0,
              blip_until=0.0, faults=0)
    _new_stable(t, first=True)


def _new_stable(t, first=False):
    _S["phase"] = "stable"
    _S["p0"] = t
    _S["p_end"] = t + (_rng.uniform(5, 8) if first else _rng.uniform(7, 12))


def _next_phase(t):
    p = _S["phase"]
    if p == "stable":
        _S["phase"] = "burst"
        _S["p_end"] = t + _rng.uniform(3.0, 5.5)
        k = _rng.randint(2, 4)
        _S["kinds"] = _rng.sample(_FAULTS, k)
        _S["faults"] += 1
        _S["cycle"] += 1
    elif p == "burst":
        if _rng.random() < 0.5 or _S["cycle"] % 3 == 0:
            _S["phase"] = "loss"
            _S["p_end"] = t + _rng.uniform(1.2, 2.2)
        else:
            _S["phase"] = "recover"
            _S["p_end"] = t + 3.0
    elif p == "loss":
        _S["phase"] = "recover"
        _S["p_end"] = t + 3.0
        if _rng.random() < 0.7:
            _S["scene"] = (_S["scene"] + _rng.randint(1, 2)) % len(_SCENES)
    else:
        _new_stable(t)
        return
    _S["p0"] = t


# --------------------------------------------------------------------- faults

def _apply_faults(a, f, kinds, t, roll_off):
    """Corrupt the frame array in place-ish; returns the new array."""
    if f <= 0:
        return a
    if "roll" in kinds and roll_off:
        a = np.roll(a, int(roll_off), axis=0)
        seam = int(roll_off) % 240
        a[max(0, seam - 7):seam + 1] = 0
        if 0 <= seam + 1 < 240:
            a[seam + 1] = (40, 120, 60)
    if "wave" in kinds:
        amp = 3 + 9 * f
        ph = t * 9
        for y in range(0, 240, 6):
            dx = int(amp * math.sin(y * 0.09 + ph) * (0.6 + 0.4 * math.sin(y * 0.023 - ph * 0.3)))
            if dx:
                a[y:y + 6] = np.roll(a[y:y + 6], dx, axis=1)
    if "tear" in kinds:
        for _ in range(1 + int(f * 5)):
            y = _rng.randrange(0, 236)
            h = _rng.randint(2, 4 + int(22 * f))
            dx = _rng.randint(-int(10 + 40 * f), int(10 + 40 * f))
            a[y:y + h] = np.roll(a[y:y + h], dx, axis=1)
    if "ghost" in kinds:
        dx = int(4 + 8 * f)
        g = np.roll(a[..., 1], dx, axis=1).astype(np.float32)
        gh = (g[..., None] * (_AMBER_V * (0.35 + 0.35 * f))).astype(np.uint8)
        a = np.maximum(a, gh)
    if "block" in kinds:
        for _ in range(int(3 + 14 * f)):
            bw, bh = _rng.choice(((8, 8), (16, 8), (24, 4), (8, 16)))
            x = _rng.randrange(30, 210 - bw)
            y = _rng.randrange(30, 210 - bh)
            if _rng.random() < 0.5:
                sx, sy = _rng.randrange(20, 220 - bw), _rng.randrange(20, 220 - bh)
                a[y:y + bh, x:x + bw] = a[sy:sy + bh, sx:sx + bw]
            else:
                m = a[y:y + bh, x:x + bw].mean(axis=(0, 1))
                a[y:y + bh, x:x + bw] = (m * (1.5 + _rng.random())).clip(0, 255).astype(np.uint8)
                a[y, x:x + bw] = (20, 150, 60)
    if "static" in kinds:
        for _ in range(1 + int(f * 3)):
            y = _rng.randrange(0, 230)
            h = _rng.randint(3, 6 + int(18 * f))
            h = min(h, 240 - y)
            n = _nrng.random((h, 240), dtype=np.float32)
            n = n * n * (140 + 110 * f)
            band = (n[..., None] * _GREEN_V).astype(np.uint8)
            a[y:y + h] = np.maximum(a[y:y + h] // 2, band)
    return a


def _static_frame(level):
    n = _nrng.random((120, 120), dtype=np.float32)
    n = (n * n * level)[..., None] * _GREEN_V
    small = n.astype(np.uint8)
    return np.repeat(np.repeat(small, 2, axis=0), 2, axis=1)


# --------------------------------------------------------------------- HUD

def _hud(img, d, t, phase, f, u):
    # signal meter at the top
    lvl = {"stable": 5, "burst": max(1, int(5 - f * 4)), "loss": 0}.get(phase, min(5, int(1 + u * 1.6)))
    x0 = CX - 5 * 7 // 2
    for i in range(5):
        c = GREEN if i < lvl else GREEN_DIM
        if phase == "loss":
            c = (60, 16, 12)
        d.rectangle([x0 + i * 7, 22 - i, x0 + i * 7 + 4, 25], fill=c)
    # fault flag / status at the bottom
    if phase == "burst":
        if int(t * 5) % 2 == 0:
            names = _S["kinds"]
            nm = _FAULT_NAMES[names[int(t * 1.3) % len(names)]]
            s = "! " + nm
            w = _tw(s, 10)
            d.rectangle([CX - w / 2 - 4, 205, CX + w / 2 + 4, 218], fill=(50, 8, 6))
            _txt_c(img, 206, s, RED, 10)
    elif phase == "loss":
        d.rectangle([CX - 46, 104, CX + 46, 132], fill=(0, 0, 0), outline=RED)
        if int(t * 3) % 3 != 2:
            _txt_c(img, 107, "NO CARRIER", RED, 12)
        _txt_c(img, 120, "SEARCHING %d" % (int(t * 30) % 1000), AMBER, 9)
    elif phase == "recover":
        if u < 1.2:
            s = "RE-SYNC"
            _txt_c(img, 206, s, AMBER, 10)
            w = 70
            d.rectangle([CX - w / 2, 219, CX + w / 2, 223], outline=GREEN_MID)
            d.rectangle([CX - w / 2 + 1, 220, CX - w / 2 + 1 + (w - 2) * min(1.0, u / 1.2), 222], fill=GREEN)
        else:
            k = min(1.0, (u - 1.2) / 0.2)
            fade = min(1.0, (3.0 - u) / 0.6)
            s = "SIGNAL RESTORED"
            w = _tw(s, 11)
            c = GREEN_HI if u < 1.6 else GREEN
            c = tuple(int(x * fade) for x in c)
            d.rectangle([CX - w / 2 * k - 6, 203, CX + w / 2 * k + 6, 219], outline=tuple(int(x * fade) for x in GREEN_MID))
            if k >= 1:
                _txt_c(img, 204, s, c, 11)
    else:
        _txt_c(img, 206, "FAULTS %02d" % _S["faults"], (12, 90, 36), 9)


# --------------------------------------------------------------------- render

def render(bezel, mask, now: float) -> Image.Image:
    if _session.fresh(now) or not _S:
        _reset(now)
        _ph.reset()
    t = now
    if t >= _S["p_end"]:
        _next_phase(t)
    phase = _S["phase"]
    u = t - _S["p0"]
    dur = _S["p_end"] - _S["p0"]

    img = blank()
    d = ImageDraw.Draw(img)
    f = 0.0
    kinds = ()
    roll = 0.0
    if phase == "stable":
        if t >= _S["blip"]:
            _S["blip"] = t + _rng.uniform(1.5, 4.0)
            _S["blip_until"] = t + _rng.uniform(0.04, 0.12)
            _S["blip_kind"] = _rng.choice(("tear", "static", "block"))
        if t < _S["blip_until"]:
            f, kinds = 0.25, (_S["blip_kind"],)
    elif phase == "burst":
        ramp = min(1.0, u / (dur * 0.6))
        spike = 0.35 if _rng.random() < 0.15 else 0.0
        f = min(1.0, 0.25 + 0.65 * ramp + spike)
        kinds = _S["kinds"]
        roll = (u * u * 90) if "roll" in kinds else 0.0
    elif phase == "loss":
        f = 1.0
    else:  # recover: roll settles, ghost fades
        f = max(0.0, 0.6 * (1.0 - u / 1.1))
        kinds = ("ghost", "wave") if f > 0 else ()
        if u < 1.1:
            roll = 240 * (1.0 - u / 1.1) ** 2
            kinds = kinds + ("roll",)

    if phase == "loss":
        a = _static_frame(170 + 60 * _rng.random())
        # a ghost of the picture rolls through the static
        _SCENES[_S["scene"]](img, d, t)
        pic = np.asarray(img, dtype=np.uint8)
        a = np.maximum(a, np.roll(pic, int(u * 300) % 240, axis=0) // 4)
        img = Image.fromarray(a)
        d = ImageDraw.Draw(img)
    else:
        _SCENES[_S["scene"]](img, d, t)
        if f > 0 and kinds:
            a = np.array(img, dtype=np.uint8)
            a = _apply_faults(a, f, kinds, t, roll)
            img = Image.fromarray(a)
            d = ImageDraw.Draw(img)
        if phase == "recover" and 1.1 <= u < 1.5:
            # lock flash: a bright scan sweeps down as the picture locks
            y = int((u - 1.1) / 0.4 * 240)
            d.line([(0, y), (239, y)], fill=GREEN_HI)
            d.line([(0, y - 2), (239, y - 2)], fill=GREEN_MID)
    _hud(img, d, t, phase, f, u)
    return _ph.compose(img)
