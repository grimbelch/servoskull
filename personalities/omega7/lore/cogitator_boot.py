"""Cogitator Boot Sequence - a long, staged power-up of a Mechanicus cogitator.

CRT power-on, a BIOS-style mnemonic core test with a counting progress bar and
subsystem checks, a machine-spirit handshake (packets exchanged between the
cogitator and its spirit), the Omnissiah cog-skull glyph traced line by line
as vectors, then a live diagnostic dashboard of sparklines, gauges and bars.
Sometimes the spirit is displeased: the screen glitches, an error box flashes
and a litany is recited amid incense until it is placated.  Then the cogitator
reboots and the cycle begins again with different hardware and phosphor.
"""

from __future__ import annotations

import math
import random

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter

from ._common import CX, CY, H, W, Session, font, lerp_color, safe_half_width, scale

NAME = "cogitator_boot"

_rng = random.Random()
_session = Session()

_THEMES = [
    ((80, 255, 130), (255, 200, 60), (255, 60, 50)),    # green phosphor
    ((255, 180, 60), (255, 240, 150), (255, 60, 40)),   # amber phosphor
    ((110, 220, 255), (255, 210, 90), (255, 70, 60)),   # cold blue lumen
]
_SUBSYS = ["LOGIS ENGINE", "AUSPEX BUS", "VOX-LINK", "NOOSPHERIC NODE", "SERVO-MOTORS",
           "LUMEN BANK", "RITE-CACHE", "MACHINE CANT", "CENSER VALVE", "DATA-SLATE PORT",
           "GELLER FIELD", "SANCTUS WARD"]
_HAND = [
    [("> INVOKE 0x7F3A", "< THE SPIRIT STIRS"), ("> OFFER LITANY VII", "< LITANY ACCEPTED"),
     ("> REQUEST COMMUNION", "< COMMUNION GRANTED")],
    [("> KNOCK x3 ON CASING", "< WHO DISTURBS ME"), ("> A HUMBLE ACOLYTE", "< STATE THY PURPOSE"),
     ("> TO SERVE THE OMNISSIAH", "< PROCEED, ACOLYTE")],
    [("> BINARIC HAIL 0110", "< 1001 1011"), ("> OFFER SACRED OIL", "< OIL IS ACCEPTABLE"),
     ("> BIND TO NOOSPHERE", "< BINDING COMPLETE")],
]
_LITANY = ["O SPIRIT OF THE MACHINE", "FORGIVE THIS INTRUSION", "ACCEPT THIS INCENSE",
           "AND BE APPEASED"]
_DASH_LABELS = [("LOGIS LOAD", "PLASMA FLUX", "NOOSPHERE TRAFFIC"),
                ("THOUGHT RATE", "COOLANT", "BINARIC CANT"),
                ("RITE CYCLES", "OIL PRESSURE", "DATA-TITHE")]

# scanlines + vignette multiplier and bloom table (built once)
_yy, _xx = np.mgrid[0:H, 0:W].astype(np.float32)
_rr = np.hypot(_xx - CX, _yy - CY)
_m = (np.where((np.arange(H) % 2 == 0)[:, None], 1.0, 0.72) * np.clip(1.25 - _rr / 150.0, 0.35, 1.0))
_SCAN = Image.fromarray((np.repeat(_m[..., None], 3, axis=2) * 255).astype(np.uint8), "RGB")
_BLOOM_LUT = [min(255, int(v * 0.8)) for v in range(256)] * 3
del _yy, _xx, _rr, _m


def _glyph_paths():
    """The Cult Mechanicus cog-skull as polylines (drawn in order)."""
    cx, cy = 120.0, 112.0
    paths = []
    teeth = 12
    pts = []
    for i in range(teeth * 4 + 1):
        a = 2 * math.pi * i / (teeth * 4) - math.pi / 2
        r = 66 if (i % 4) in (1, 2) else 57
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    paths.append(pts)
    paths.append([(cx + 48 * math.cos(2 * math.pi * i / 48), cy + 48 * math.sin(2 * math.pi * i / 48))
                  for i in range(49)])
    # skull outline: cranium arc then jaw
    sk = []
    for i in range(25):
        a = math.radians(150 + 240 * i / 24)
        sk.append((cx + 27 * math.cos(a), cy - 6 + 27 * math.sin(a)))
    sk += [(cx + 22, cy + 17), (cx + 15, cy + 30), (cx - 15, cy + 30), (cx - 22, cy + 17), sk[0]]
    paths.append(sk)
    # organic eye socket (left)
    paths.append([(cx - 10 + 7 * math.cos(2 * math.pi * i / 16), cy - 3 + 7 * math.sin(2 * math.pi * i / 16))
                  for i in range(17)])
    # bionic eye (right)
    paths.append([(cx + 11 + 8 * math.cos(2 * math.pi * i / 16), cy - 3 + 8 * math.sin(2 * math.pi * i / 16))
                  for i in range(17)])
    paths.append([(cx + 11 + 3 * math.cos(2 * math.pi * i / 10), cy - 3 + 3 * math.sin(2 * math.pi * i / 10))
                  for i in range(11)])
    paths.append([(cx + 1, cy - 3), (cx + 22, cy - 3)])
    # nose
    paths.append([(cx, cy + 7), (cx - 4, cy + 14), (cx + 4, cy + 14), (cx, cy + 7)])
    # teeth
    paths.append([(cx - 15, cy + 22), (cx + 15, cy + 22)])
    for x in (-10, -5, 0, 5, 10):
        paths.append([(cx + x, cy + 18), (cx + x, cy + 30)])
    # machine half: circuitry on the cranium
    paths.append([(cx, cy - 33), (cx + 2, cy - 26), (cx - 2, cy - 20), (cx, cy - 13)])
    paths.append([(cx + 6, cy - 30), (cx + 6, cy - 22), (cx + 16, cy - 22), (cx + 20, cy - 16)])
    paths.append([(cx + 12, cy - 30), (cx + 22, cy - 22)])
    # cog spokes
    for k in range(4):
        a = math.pi / 4 + k * math.pi / 2
        paths.append([(cx + 38 * math.cos(a), cy + 38 * math.sin(a)), (cx + 48 * math.cos(a), cy + 48 * math.sin(a))])
    segs = []
    for p in paths:
        for i in range(len(p) - 1):
            L = math.hypot(p[i + 1][0] - p[i][0], p[i + 1][1] - p[i][1])
            segs.append((p[i], p[i + 1], L))
    return segs


_GLYPH = _glyph_paths()
_GLYPH_LEN = sum(s[2] for s in _GLYPH)

_S: dict = {}


# --------------------------------------------------------------------- cycle

def _new_cycle(t):
    s = _S
    s["c0"] = t
    s["theme"] = _rng.choice(_THEMES)
    s["rev"] = _rng.randint(700, 999)
    s["cores"] = _rng.choice((2, 4, 8, 12))
    s["mem"] = _rng.choice((16384, 32768, 65536, 131072))
    subs = _rng.sample(_SUBSYS, 6)
    stat = []
    for name in subs:
        r = _rng.random()
        if name == "GELLER FIELD":
            stat.append((name, "N/A", 1))
        elif r < 0.15:
            stat.append((name, "WEAK", 1))
        else:
            stat.append((name, "OK", 0))
    s["subs"] = stat
    s["hand"] = _rng.choice(_HAND)
    s["labels"] = _rng.choice(_DASH_LABELS)
    s["dash_len"] = _rng.uniform(34, 44)
    s["error"] = _rng.random() < 0.7
    s["err_at"] = _rng.uniform(7, 16)
    s["err_code"] = _rng.randint(0x1000, 0xFFFF)
    s["err_len"] = 15.0 if s["error"] else 0.0
    s["T_BIOS"], s["T_HS"], s["T_GLY"], s["T_DASH"] = 3.0, 21.0, 36.0, 52.0
    s["T_END"] = s["T_DASH"] + s["dash_len"] + s["err_len"]
    s["total"] = s["T_END"] + 4.0
    # log schedule for BIOS phase
    ev = [(0.0, f"OMNISSIAH BIOS REV M41.{s['rev']}", None, 0),
          (0.6, "(C) ADEPTUS MECHANICUS", None, 0),
          (1.2, f"LOGIS ENGINE x{s['cores']} ... SANCTIFIED", None, 0),
          (2.0, "MNEMONIC CORE TEST", "__MEM__", 0)]
    tt = 9.0
    for name, st, lvl in stat:
        ev.append((tt, name, st, lvl))
        tt += 0.95
    ev.append((tt + 0.3, "BOOT RUNE FOUND: SECTOR 0", None, 0))
    ev.append((tt + 1.1, "AWAKENING SPIRIT-CORE...", None, 2))
    s["bios_ev"] = ev
    # dashboard series
    pr = s["np"]
    s["ser"] = [list(0.5 + 0.2 * pr.standard_normal(40)) for _ in range(3)]
    s["ser_t"] = 0.0
    s["bars"] = [0.5, 0.5, 0.5, 0.5]


def _reset(t):
    _S.clear()
    _S["np"] = np.random.default_rng(_rng.getrandbits(32))
    _S["smk"] = {k: np.zeros(220, np.float32) for k in ("x", "y", "vx", "vy", "age", "life")}
    _S["smk"]["age"][:] = 9
    _S["smk_next"] = 0
    _S["last_t"] = t
    _new_cycle(t)


# --------------------------------------------------------------------- drawing helpers

def _txt(d, x, y, s, col, size=10):
    d.text((x, y), s, fill=col, font=font(size))


def _ctext(d, y, s, col, size=10):
    f = font(size)
    w = d.textlength(s, font=f)
    d.text((CX - w / 2, y), s, fill=col, font=f)


def _fit(d, s, width, f):
    if d.textlength(s, font=f) <= width:
        return s
    while s and d.textlength(s + ".", font=f) > width:
        s = s[:-1]
    return s + "."


def _log(d, lines, y0, y1, col_main, dy=12, size=10):
    """Draw log lines bottom-anchored inside the circular text column."""
    f = font(size)
    maxn = int((y1 - y0) // dy)
    lines = lines[-maxn:]
    y = y0
    for text, right, rcol, tcol in lines:
        hw = safe_half_width(y + 5, 10)
        x0, x1 = CX - hw, CX + hw
        rw = d.textlength(right, font=f) if right else 0
        body = _fit(d, text, x1 - x0 - rw - 6, f)
        d.text((x0, y), body, fill=tcol or col_main, font=f)
        if right:
            d.text((x1 - rw, y), right, fill=rcol, font=f)
        y += dy


def _typed(s, u, cps=45.0):
    n = int(max(0.0, u) * cps)
    return s[:n]


def _sparkline(d, box, data, col, label, fsz=9):
    x0, y0, x1, y1 = box
    d.rectangle(box, outline=scale(col, 0.35))
    n = len(data)
    pts = []
    for i, v in enumerate(data):
        v = min(1.0, max(0.0, v))
        pts.append((x0 + 2 + (x1 - x0 - 4) * i / (n - 1), y1 - 3 - (y1 - y0 - 14) * v))
    d.line(pts, fill=col, width=1)
    lx, ly = pts[-1]
    d.ellipse([lx - 1.5, ly - 1.5, lx + 1.5, ly + 1.5], fill=(255, 255, 255))
    f = font(fsz)
    d.text((x0 + 3, y0 + 2), _fit(d, label, x1 - x0 - 6, f), fill=scale(col, 0.7), font=f)


# --------------------------------------------------------------------- phases

def _phase_power(d, u, col):
    # CRT warm-up: a line opens into the raster
    if u < 0.35:
        w = 20 + 180 * (u / 0.35)
        d.rectangle([CX - w / 2, CY - 1, CX + w / 2, CY + 1], fill=(255, 255, 255))
    else:
        k = (u - 0.35) / 0.65
        h = 2 + 100 * k
        d.rectangle([CX - 100, CY - h, CX + 100, CY + h], fill=scale(col, 0.12 * (1 - k)))
        d.line([(CX - 100, CY), (CX + 100, CY)], fill=scale((255, 255, 255), 1 - k))
        if k > 0.4:
            _ctext(d, CY - 8, "+ ++ +++ ++ +", col, 12)


def _phase_bios(d, u, s, col, warn, t):
    ev = s["bios_ev"]
    lines = []
    for i, (et, text, right, lvl) in enumerate(ev):
        if u < et:
            break
        nxt = ev[i + 1][0] if i + 1 < len(ev) else 99
        age = u - et
        tcol = col if lvl < 2 else lerp_color(col, (255, 255, 255), 0.5 + 0.5 * math.sin(t * 8))
        if right == "__MEM__":
            k = min(1.0, age / 6.0)
            val = int(s["mem"] * k) // 64 * 64
            lines.append((_typed(text, age), f"{val:06d}K", col if k < 1 else col, tcol))
            s["_memk"] = k
            continue
        typed = _typed(text, age)
        rr = right if (right and age > 0.45) else ""
        rcol = col if lvl == 0 else warn
        lines.append((typed, rr, rcol, tcol))
    _ctext(d, 22, "COGITATOR BOOT", scale(col, 0.8), 10)
    d.line([(60, 36), (180, 36)], fill=scale(col, 0.4))
    _log(d, lines, 42, 170, col)
    # progress bar for memory test / overall boot
    k = s.get("_memk", 0.0) if u < 9.0 else min(1.0, (u - 9.0) / 8.0)
    label = "MNEMONIC SCAN" if u < 9.0 else "SUBSYSTEM RITES"
    _ctext(d, 174, label, scale(col, 0.6), 9)
    x0, x1 = 50, 190
    d.rectangle([x0, 187, x1, 195], outline=col)
    fillw = (x1 - x0 - 4) * k
    nblk = int(fillw // 6)
    for i in range(nblk):
        bx = x0 + 2 + i * 6
        d.rectangle([bx, 189, bx + 4, 193], fill=col)
    if int(t * 2) % 2 == 0 and k < 1:
        d.rectangle([x0 + 2 + nblk * 6, 189, x0 + 6 + nblk * 6, 193], fill=scale(col, 0.5))


def _phase_hand(d, u, s, col, hot, t):
    _ctext(d, 22, "SPIRIT HANDSHAKE", scale(col, 0.8), 10)
    L, R = (62, 76), (178, 76)
    per = 2.3
    idx = int(u // (per * 2))
    sub = u % (per * 2)
    sending_right = sub < per
    # link with binaric cant waveform
    pts = []
    for i in range(41):
        x = L[0] + 18 + (R[0] - L[0] - 36) * i / 40
        bit = int(((x * 0.2) - t * 9)) & 3
        y = L[1] + (-4 if bit in (0, 3) else 4)
        pts.append((x, y))
    d.line(pts, fill=scale(col, 0.45))
    for (x, y), lab, ph in ((L, "COGITATOR", 0), (R, "SPIRIT", 1)):
        pulse = 0.5 + 0.5 * math.sin(t * 4 + ph * 2)
        d.ellipse([x - 16, y - 16, x + 16, y + 16], outline=col, width=2)
        r = 6 + 3 * pulse
        d.ellipse([x - r, y - r, x + r, y + r], fill=scale(hot if ph else col, 0.4 + 0.5 * pulse))
        f9 = font(9)
        w = d.textlength(lab, font=f9)
        d.text((x - w / 2, y + 19), lab, fill=scale(col, 0.8), font=f9)
    # packet
    if idx < len(s["hand"]):
        k = (sub % per) / (per * 0.45)
        if k < 1.0:
            a, b = (L, R) if sending_right else (R, L)
            for j in range(3):
                kk = min(1.0, max(0.0, k - j * 0.08))
                px = a[0] + (b[0] - a[0]) * kk
                py = a[1] - 14 * math.sin(math.pi * kk)
                sz = 3 - j
                d.rectangle([px - sz, py - sz, px + sz, py + sz], fill=scale(hot, 1.0 - j * 0.3))
    # exchange log
    lines = []
    for i, (q, a) in enumerate(s["hand"]):
        base = i * per * 2
        if u >= base + per * 0.45:
            lines.append((_typed(q, u - base - per * 0.45), "", None, col))
        if u >= base + per * 1.45:
            lines.append((_typed(a, u - base - per * 1.45), "", None, hot))
    if u > len(s["hand"]) * per * 2 - 0.6:
        lines.append(("HANDSHAKE SEALED", "", None, lerp_color(col, (255, 255, 255), 0.5)))
    _log(d, lines, 114, 200, col, dy=12)


def _phase_glyph(d, u, col, hot, t):
    draw_t = 11.0
    k = min(1.0, u / draw_t)
    target = k * _GLYPH_LEN
    acc = 0.0
    pen = None
    glow = scale(col, 0.3)
    bright = col
    if k >= 1.0:
        p = 0.5 + 0.5 * math.sin((u - draw_t) * 5)
        bright = lerp_color(col, (255, 255, 255), 0.4 * p)
        glow = scale(col, 0.35 + 0.3 * p)
    for a, b, L in _GLYPH:
        if acc >= target:
            break
        if acc + L <= target:
            e = b
        else:
            f = (target - acc) / L
            e = (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)
            pen = e
        d.line([a, e], fill=glow, width=3)
        d.line([a, e], fill=bright, width=1)
        acc += L
    if pen is not None:
        r = 2.5 + 1.5 * math.sin(t * 30)
        d.ellipse([pen[0] - r, pen[1] - r, pen[0] + r, pen[1] + r], fill=(255, 255, 255))
        d.line([(CX, 200), pen], fill=scale(col, 0.18))
    _ctext(d, 22, "SANCTIFIED GLYPH", scale(col, 0.8), 10)
    if k < 1.0:
        _ctext(d, 190, f"VECTOR {int(k * 100):03d}%", scale(col, 0.7), 10)
    else:
        _ctext(d, 188, "PRAISE THE OMNISSIAH", hot, 10)


def _phase_dash(d, u, s, col, hot, warn, t, dt, err_state):
    pr = s["np"]
    frozen = err_state is not None
    # advance data
    if not frozen:
        s["ser_t"] += dt
        while s["ser_t"] > 0.12:
            s["ser_t"] -= 0.12
            for j, ser in enumerate(s["ser"]):
                last = ser[-1]
                v = last + 0.12 * pr.standard_normal() + 0.08 * (0.55 - last)
                if j == 1:
                    v = 0.5 + 0.35 * math.sin(t * 1.3) + 0.08 * pr.standard_normal()
                ser.append(min(1.0, max(0.0, v)))
                del ser[0]
            s["bars"] = [min(1.0, max(0.05, b + 0.08 * pr.standard_normal() + 0.05 * (0.6 - b)))
                         for b in s["bars"]]
    c = col if not frozen else warn
    labs = s["labels"]
    _ctext(d, 22, "DIAGNOSTIC ORACULUM", scale(col, 0.8), 10)
    _sparkline(d, (46, 40, 117, 86), s["ser"][0], c, labs[0])
    _sparkline(d, (123, 40, 194, 86), s["ser"][1], c, labs[1])
    # spirit gauge
    gx, gy, gr = 76, 122, 26
    d.arc([gx - gr, gy - gr, gx + gr, gy + gr], 150, 390, fill=scale(c, 0.6), width=2)
    for i in range(9):
        a = math.radians(150 + 240 * i / 8)
        d.line([(gx + (gr - 5) * math.cos(a), gy + (gr - 5) * math.sin(a)),
                (gx + gr * math.cos(a), gy + gr * math.sin(a))], fill=c)
    mood = 0.72 + 0.12 * math.sin(t * 0.9) + 0.04 * math.sin(t * 5.1)
    if frozen:
        mood = 0.08 + 0.05 * math.sin(t * 17)
    a = math.radians(150 + 240 * mood)
    d.line([(gx, gy), (gx + (gr - 7) * math.cos(a), gy + (gr - 7) * math.sin(a))], fill=hot, width=2)
    d.ellipse([gx - 3, gy - 3, gx + 3, gy + 3], fill=hot)
    f9 = font(9)
    d.text((gx - 14, gy + 12), "SPIRIT", fill=scale(c, 0.8), font=f9)
    # bars
    for i, (lab, v) in enumerate(zip(("MEM", "AUSP", "VOX", "SERVO"), s["bars"])):
        y = 101 + i * 12
        d.text((110, y - 1), lab, fill=scale(c, 0.8), font=f9)
        x0, x1 = 140, 196
        d.rectangle([x0, y + 1, x1, y + 7], outline=scale(c, 0.4))
        vv = v if not frozen else v * (0.3 + 0.2 * math.sin(t * 13 + i))
        d.rectangle([x0 + 1, y + 2, x0 + 1 + (x1 - x0 - 2) * vv, y + 6], fill=c if vv < 0.85 else warn)
    _sparkline(d, (40, 154, 200, 186), s["ser"][2], c, labs[2])
    up = int(u)
    _ctext(d, 192, f"UPTIME {up // 60:02d}:{up % 60:02d}  +++  SPIRIT CONTENT" if not frozen else
           "+++ COGITATION HALTED +++", scale(c, 0.8), 9)


def _error_overlay(img, d, e, s, col, hot, red, t):
    """e: seconds into the error episode."""
    pr = s["np"]
    if e < 1.8 or (e < 3.0 and pr.random() < 0.3):
        arr = np.asarray(img).copy()
        for _ in range(6):
            y0 = int(pr.integers(20, 210))
            hgt = int(pr.integers(3, 14))
            arr[y0:y0 + hgt] = np.roll(arr[y0:y0 + hgt], int(pr.integers(-25, 25)), axis=1)
        arr[..., 1] = (arr[..., 1] * 0.4).astype(np.uint8)
        arr[..., 2] = (arr[..., 2] * 0.4).astype(np.uint8)
        img = Image.fromarray(arr, "RGB")
        d = ImageDraw.Draw(img)
    if e >= 1.2:
        box = (32, 78, 208, 162)
        flash = int(t * 3) % 2 == 0
        placate = e >= 5.0
        done = e >= 13.0
        border = red if not done else col
        d.rectangle(box, fill=(10, 0, 0) if not done else (0, 8, 4), outline=border, width=2)
        if not placate:
            _ctext(d, 86, "!! MACHINE SPIRIT !!", red if flash else scale(red, 0.6), 10)
            _ctext(d, 100, "DISPLEASED", red, 14)
            _ctext(d, 122, f"FAULT 0x{s['err_code']:04X}", scale(red, 0.8), 10)
            _ctext(d, 138, "COMMENCE PLACATION", hot if flash else scale(hot, 0.5), 9)
        elif not done:
            _ctext(d, 84, "LITANY OF PLACATION", hot, 10)
            for i, line in enumerate(_LITANY):
                lt = e - 5.5 - i * 1.8
                if lt > 0:
                    _ctext(d, 100 + i * 14, _typed(line, lt, 30), lerp_color(hot, (255, 255, 255), 0.3), 9)
        else:
            _ctext(d, 102, "SPIRIT PLACATED", col, 14)
            _ctext(d, 124, "RESUMING COGITATION", scale(col, 0.7), 9)
    return img, d


def _smoke(img, s, dt, emit, t):
    pr = s["np"]
    sm = s["smk"]
    if emit:
        n = 4
        m = sm["x"].shape[0]
        ids = (np.arange(n) + s["smk_next"]) % m
        s["smk_next"] = int((s["smk_next"] + n) % m)
        cxp = CX + 30 * math.sin(t * 1.6)
        sm["x"][ids] = cxp + pr.normal(0, 3, n)
        sm["y"][ids] = 196
        sm["vx"][ids] = pr.normal(0, 6, n)
        sm["vy"][ids] = pr.uniform(-34, -20, n)
        sm["age"][ids] = 0
        sm["life"][ids] = pr.uniform(3.0, 5.0, n)
    live = sm["age"] < sm["life"]
    if not live.any():
        return img
    li = np.nonzero(live)[0]
    sm["vx"][li] += pr.normal(0, 16, li.size) * dt
    sm["x"][li] += sm["vx"][li] * dt
    sm["y"][li] += sm["vy"][li] * dt
    sm["age"][li] += dt
    qx = (sm["x"][li] / 2).astype(np.int32)
    qy = (sm["y"][li] / 2).astype(np.int32)
    wv = (1.0 - sm["age"][li] / sm["life"][li]) * 240.0
    ok = (qx >= 0) & (qx < W // 2) & (qy >= 0) & (qy < H // 2)
    acc = np.bincount(qy[ok] * (W // 2) + qx[ok], weights=wv[ok], minlength=(W // 2) * (H // 2))
    L = Image.fromarray(np.clip(acc, 0, 255).astype(np.uint8).reshape(H // 2, W // 2), "L")
    L = L.filter(ImageFilter.GaussianBlur(2)).resize((W, H), Image.BILINEAR)
    return ImageChops.add(img, Image.merge("RGB", (L, L, L)))


# --------------------------------------------------------------------- main

def render(bezel, mask, now: float) -> Image.Image:
    if _session.fresh(now) or not _S:
        _reset(0.0)
    t = _session.t(now)
    s = _S
    dt = max(0.0, min(0.1, t - s["last_t"]))
    s["last_t"] = t
    tc = t - s["c0"]
    if tc >= s["total"]:
        _new_cycle(t)
        tc = 0.0
    col, hot, red = s["theme"]
    warn = (255, 170, 40) if col[0] < 200 else (255, 90, 50)

    img = Image.new("RGB", (W, H), scale(col, 0.04))
    d = ImageDraw.Draw(img)

    err_state = None
    if tc < s["T_BIOS"]:
        _phase_power(d, tc / s["T_BIOS"], col)
    elif tc < s["T_HS"]:
        _phase_bios(d, tc - s["T_BIOS"], s, col, warn, t)
    elif tc < s["T_GLY"]:
        _phase_hand(d, tc - s["T_HS"], s, col, hot, t)
    elif tc < s["T_DASH"]:
        _phase_glyph(d, tc - s["T_GLY"], col, hot, t)
    elif tc < s["T_END"]:
        u = tc - s["T_DASH"]
        e = None
        if s["error"] and s["err_at"] <= u < s["err_at"] + s["err_len"]:
            e = u - s["err_at"]
            err_state = e
        _phase_dash(d, u, s, col, hot, warn, t, dt, err_state if (e is not None and e < 13.0) else None)
        if e is not None:
            img, d = _error_overlay(img, d, e, s, col, hot, red, t)
    else:
        u = (tc - s["T_END"]) / 4.0
        if u < 0.45:
            _ctext(d, 100, "COGITATION CYCLE", col, 10)
            _ctext(d, 116, "COMPLETE", col, 12)
            _ctext(d, 136, _typed("REBOOTING...", u * 4.0, 8), scale(col, 0.7), 10)
        else:
            k = (u - 0.45) / 0.55
            h = max(1.0, 60 * (1 - k * 1.6))
            w = 180 * (1 - k) if k > 0.6 else 180
            d.rectangle([CX - w / 2, CY - h / 2, CX + w / 2, CY + h / 2], fill=scale(col, 0.25))
            d.line([(CX - w / 2, CY), (CX + w / 2, CY)], fill=(255, 255, 255))

    emit = err_state is not None and 5.0 <= err_state < 12.5
    if emit:
        # swinging censer below the litany box
        cxp = CX + 30 * math.sin(t * 1.6)
        d.line([(CX, 170), (cxp, 192)], fill=scale(hot, 0.6))
        d.ellipse([cxp - 6, 190, cxp + 6, 202], fill=scale(hot, 0.5), outline=hot)
        d.line([(cxp - 4, 196), (cxp + 4, 196)], fill=(255, 120, 40))
    if emit or s["smk"]["age"].min() < 6:
        img = _smoke(img, s, dt, emit, t)

    # CRT bloom + scanlines
    glow = img.resize((80, 80), Image.BOX).filter(ImageFilter.GaussianBlur(1.5)).resize((W, H), Image.BILINEAR)
    img = ImageChops.add(img, glow.point(_BLOOM_LUT))
    img = ImageChops.multiply(img, _SCAN)
    return img
