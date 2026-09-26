"""Linguis Technis - a lingua-technis decoder turning binharic cant into Gothic.

A stream of binharic pulses scrolls across a waveform trace towards the read
head.  Each bit that passes the head is latched into an 8-bit register, and
the decoder ring of glyphs narrows its candidates bit by bit (a visible binary
search), rotating the surviving glyphs up to the pointer until one letter
remains and is struck into the centre.  Letters build a High Gothic phrase;
low-confidence glyphs waver in amber between two readings before settling.
Completed phrases are stamped TRANSLATED and archived to a scrolling log.
"""

from __future__ import annotations

import math
import random

from PIL import Image, ImageDraw

from ..lore._common import CX, CY, Session, font
from ._phosphor import AMBER, GREEN, GREEN_DIM, GREEN_HI, GREEN_MID, RED, Phosphor, blank

NAME = "linguis_technis"

_rng = random.Random()
_session = Session()
_ph = Phosphor(decay=0.22, bloom=0.6, flicker=0.03)

_PHRASES = ["PRAISE THE OMNISSIAH", "THE SPIRIT IS WILLING", "OIL THE THIRD VALVE",
            "SEVEN RITES REMAIN", "AWAIT THE MAGOS", "THE FORGE BURNS", "BLESSED BE THE COG",
            "KNOWLEDGE IS POWER", "THE MACHINE ABIDES", "FLESH IS WEAK", "MARS SENDS WORD",
            "CHANT THE LITANY", "ENGINE AWAKENS", "SEAL THE VAULT", "OBEY THE CODE",
            "NO FAULT FOUND", "THE COG TURNS", "GLORY TO MARS"]
_SYMS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ "
_NS = len(_SYMS)
_RATE = 15.0          # bits per second
_BW = 7               # waveform pixels per bit
_PRE = 16             # preamble bits
_RCX, _RCY, _RR = CX, 131, 38
_WY = 46              # waveform baseline centre

_TXT: dict = {}


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


def _txt_at(img, cx, y, s, col, size):
    m = _tmask(s, size)
    img.paste(col, (int(cx - (m.width - 2) / 2), int(y)), m)


def _txt(img, x, y, s, col, size):
    img.paste(col, (int(x), int(y)), _tmask(s, size))


def _mix(a, b, k):
    k = max(0.0, min(1.0, k))
    return tuple(int(a[i] + (b[i] - a[i]) * k) for i in range(3))


def _sc(c, k):
    k = max(0.0, min(1.0, k))
    return (int(c[0] * k), int(c[1] * k), int(c[2] * k))


# --------------------------------------------------------------------- state

_S: dict = {}


def _new_phrase(t):
    s = _S
    order = s["order"]
    if not order:
        order[:] = _rng.sample(_PHRASES, len(_PHRASES))
    text = order.pop()
    bits = [1, 0] * 6 + [1, 1, 1, 1]
    confs = []
    for ch in text:
        c = ord(ch)
        bits += [(c >> (7 - i)) & 1 for i in range(8)]
        r = _rng.random()
        confs.append(_rng.uniform(0.38, 0.58) if r < 0.12 else _rng.uniform(0.74, 0.99))
    s["ph"] = {"text": text, "bits": bits, "t0": t, "conf": confs,
               "end": t + len(bits) / _RATE}
    s["snr"] = _rng.uniform(0.55, 0.95)


def _reset(t):
    _S.clear()
    _S.update(t0=t, order=[], log=[], log_t=-10.0, ring=0.0, flash=-10.0, n_done=0)
    _new_phrase(t + 0.6)


def _cands(code_bits, nb):
    """Indices of symbols consistent with the first nb received bits."""
    if nb <= 0:
        return list(range(_NS))
    out = []
    shift = 8 - nb
    want = 0
    for i in range(nb):
        want = (want << 1) | code_bits[i]
    for i, ch in enumerate(_SYMS):
        if (ord(ch) >> shift) == want:
            out.append(i)
    return out


# --------------------------------------------------------------------- drawing

def _waveform(img, d, t, ph, n_f):
    bits = ph["bits"]
    x_lo, x_hi = 42, 198
    noise = 1.0 - _S["snr"]
    hi_y, lo_y = _WY - 6, _WY + 6
    # grid ticks
    for gx in range(x_lo, x_hi + 1, _BW * 4):
        d.line([(gx, _WY + 10), (gx, _WY + 12)], fill=GREEN_DIM)
    d.line([(x_lo, _WY + 11), (x_hi, _WY + 11)], fill=(6, 50, 20))
    k0 = int(n_f) - int((CX - x_lo) / _BW) - 2
    k1 = int(n_f) + int((x_hi - CX) / _BW) + 2
    prev = None
    for k in range(k0, k1 + 1):
        b = bits[k] if 0 <= k < len(bits) else 0
        xa = CX + (k - n_f) * _BW
        xb = xa + _BW
        if xb < x_lo or xa > x_hi:
            continue
        xa, xb = max(x_lo, xa), min(x_hi, xb)
        y = hi_y if b else lo_y
        if noise > 0.2:
            y += _rng.uniform(-noise, noise) * 3
        decoded = xb <= CX + 0.5
        if decoded:
            age = (CX - xb) / (CX - x_lo)
            col = _mix(GREEN_HI, (10, 90, 36), age * 1.3)
        else:
            col = (14, 110, 44)
        if prev is not None and abs(prev[1] - y) > 0.5:
            d.line([(xa, prev[1]), (xa, y)], fill=col)
        d.line([(xa, y), (xb, y)], fill=col)
        prev = (xb, y)
    # read head
    d.line([(CX, _WY - 12), (CX, _WY + 12)], fill=AMBER if _S.get("amb") else GREEN_HI)
    d.polygon([(CX - 3, _WY - 15), (CX + 3, _WY - 15), (CX, _WY - 11)], fill=GREEN_HI)


def _register(img, d, t, ph, n):
    """8-bit latch below the waveform."""
    j_bits = n - _PRE
    y = 61
    if j_bits < 0:
        _txt_at(img, CX, y, "SYNC %s" % ("." * (1 + int(t * 4) % 3)), GREEN_MID, 10)
        return
    nb = j_bits % 8
    j = j_bits // 8
    bits = ph["bits"][_PRE + j * 8:_PRE + j * 8 + 8]
    pitch = 8
    x0 = CX - 4 * pitch - 2
    for i in range(8):
        x = x0 + i * pitch + (4 if i >= 4 else 0)
        if i < nb:
            _txt(img, x, y, str(bits[i]), GREEN_HI if i == nb - 1 else GREEN, 11)
        else:
            d.line([(x + 1, y + 12), (x + 5, y + 12)], fill=GREEN_DIM)


def _ring(img, d, t, ph, n, dt):
    j_bits = n - _PRE
    text = ph["text"]
    if 0 <= j_bits < len(text) * 8:
        j = j_bits // 8
        nb = j_bits % 8
        code = [(ord(text[j]) >> (7 - i)) & 1 for i in range(8)]
        cands = _cands(code, nb)
    else:
        cands = list(range(_NS))
        nb = 0
    # rotate so the candidate centroid sits under the pointer at the top
    step = 2 * math.pi / _NS
    if len(cands) < _NS:
        sx = sum(math.cos(i * step) for i in cands)
        sy = sum(math.sin(i * step) for i in cands)
        mean = math.atan2(sy, sx)
        target = -math.pi / 2 - mean
        diff = (target - _S["ring"] + math.pi) % (2 * math.pi) - math.pi
        _S["ring"] += diff * min(1.0, dt * 6.0)
    else:
        _S["ring"] += dt * 0.35
    rot = _S["ring"]
    cs = set(cands)
    # outer lattice
    d.ellipse([_RCX - _RR - 9, _RCY - _RR - 9, _RCX + _RR + 9, _RCY + _RR + 9], outline=(6, 55, 22))
    d.ellipse([_RCX - _RR + 9, _RCY - _RR + 9, _RCX + _RR - 9, _RCY + _RR - 9], outline=(6, 55, 22))
    for i, ch in enumerate(_SYMS):
        a = rot + i * step
        x = _RCX + _RR * math.cos(a)
        y = _RCY + _RR * math.sin(a)
        if i in cs:
            col = GREEN_HI if len(cands) <= 2 else GREEN
        else:
            col = (8, 60, 24)
        _txt_at(img, x, y - 7, ch if ch != " " else "_", col, 9)
        # lattice spokes to surviving candidates
        if i in cs and len(cands) < 8:
            d.line([(_RCX + (_RR - 9) * math.cos(a), _RCY + (_RR - 9) * math.sin(a)),
                    (_RCX + 18 * math.cos(a), _RCY + 18 * math.sin(a))], fill=(10, 90, 36))
    # pointer at the top
    py = _RCY - _RR - 10
    d.polygon([(CX - 4, py - 5), (CX + 4, py - 5), (CX, py)], fill=GREEN_HI)
    return cands, nb


def _centre(img, d, t, ph, n):
    """Big glyph of the most recently completed letter, or '?' while decoding."""
    j_done = (n - _PRE) // 8 if n >= _PRE else -1
    text = ph["text"]
    _S["amb"] = False
    d.ellipse([_RCX - 17, _RCY - 17, _RCX + 17, _RCY + 17], outline=(10, 80, 32))
    if j_done <= 0 and n < _PRE + 8:
        _txt_at(img, _RCX, _RCY - 10, "?", GREEN_MID, 16)
        return
    j = min(j_done, len(text)) - 1
    ch = text[j]
    t_done = ph["t0"] + (_PRE + (j + 1) * 8) / _RATE
    u = t - t_done
    conf = ph["conf"][j]
    if conf < 0.6 and u < 0.9:
        _S["amb"] = True
        alt = _SYMS[(_SYMS.index(ch) + 1 + (j % 3)) % _NS]
        show = ch if int(u * 10) % 2 == 0 else alt
        _txt_at(img, _RCX, _RCY - 10, show if show != " " else "_", AMBER, 16)
        _txt_at(img, _RCX, _RCY + 6, "AMBIG", AMBER, 9)
        return
    k = min(1.0, max(0.0, u - (0.9 if conf < 0.6 else 0.0)) / 0.5)
    col = _mix(GREEN_HI, GREEN, k)
    _txt_at(img, _RCX, _RCY - 10, ch if ch != " " else "_", col, 16)
    _txt_at(img, _RCX, _RCY + 6, "0x%02X" % ord(ch), GREEN_MID, 9)
    if u < 0.25:
        r = 17 + u * 60
        d.ellipse([_RCX - r, _RCY - r, _RCX + r, _RCY + r], outline=_sc(GREEN_HI, 1 - u / 0.25))


def _meters(img, d, t, ph, n):
    j_bits = n - _PRE
    text = ph["text"]
    if j_bits >= 8:
        j = min(len(text), j_bits // 8) - 1
        conf = ph["conf"][j]
    else:
        conf = 0.0
    # smooth the confidence needle
    _S["cs"] = _S.get("cs", 0.0) + (conf - _S.get("cs", 0.0)) * 0.15
    cv = _S["cs"]
    r = _RR + 16
    box = [_RCX - r, _RCY - r, _RCX + r, _RCY + r]
    # left arc: confidence (fills upward from the bottom)
    d.arc(box, 130, 230, fill=(5, 40, 16), width=4)
    col = AMBER if 0.05 < cv < 0.6 and conf > 0 else GREEN
    if cv > 0.01:
        d.arc(box, 230 - 100 * cv, 230, fill=col, width=4)
    # right arc: signal-to-noise
    snr = _S["snr"] + 0.03 * math.sin(t * 5)
    d.arc(box, 310, 410, fill=(5, 40, 16), width=4)
    d.arc(box, 310, 310 + 100 * snr, fill=GREEN_MID, width=4)
    _txt_at(img, _RCX - r - 15, _RCY - 12, "CONF", GREEN_MID, 9)
    _txt_at(img, _RCX - r - 15, _RCY - 1, "%d%%" % int(cv * 100) if conf > 0 else "--", col, 9)
    _txt_at(img, _RCX + r + 15, _RCY - 12, "SNR", GREEN_MID, 9)
    _txt_at(img, _RCX + r + 15, _RCY - 1, "%.1f" % (snr * 20), GREEN_MID, 9)


def _phrase_line(img, d, t, ph, n):
    text = ph["text"]
    j_done = max(0, (n - _PRE) // 8) if n >= _PRE else 0
    j_done = min(j_done, len(text))
    y = 184
    shown = text[:j_done]
    done = j_done >= len(text)
    size = 11
    m = _tmask(text, size)
    w = m.width - 2
    x0 = CX - w / 2
    f = font(size)
    if shown:
        if done:
            u = t - ph["end"]
            col = GREEN_HI if int(u * 6) % 2 == 0 and u < 0.8 else GREEN
            _txt(img, x0, y, shown, col, size)
        else:
            _txt(img, x0, y, shown[:-1], GREEN, size)
            xl = x0 + f.getlength(shown[:-1])
            _txt(img, xl, y, shown[-1], GREEN_HI, size)
    if not done and int(t * 3) % 2 == 0:
        cx = x0 + (f.getlength(shown) if shown else 0)
        d.line([(cx + 1, y + 13), (cx + 6, y + 13)], fill=GREEN_HI)
    if done:
        u = t - ph["end"]
        if u > 0.5:
            k = min(1.0, (u - 0.5) / 0.3)
            s = "TRANSLATED"
            mm = _tmask(s, 9)
            ww = (mm.width - 2) / 2 + 4
            d.rectangle([CX - ww * k, 198, CX + ww * k, 210], outline=GREEN_MID)
            if k >= 1:
                _txt_at(img, CX, 199, s, GREEN_MID, 9)


def _log(img, d, t):
    log = _S["log"]
    if not log:
        return
    u = min(1.0, (t - _S["log_t"]) / 0.5)
    off = (1 - u) * 11
    for i, s in enumerate(reversed(log[-2:])):
        y = 199 + i * 11 + off
        if i == 0 and u < 1:
            col = _sc((20, 140, 56), u)
        else:
            col = (14, 100, 40) if i == 0 else (8, 60, 24)
        _txt_at(img, CX, y, s[:22], col, 9)


def render(bezel, mask, now: float) -> Image.Image:
    if _session.fresh(now) or not _S:
        _reset(now)
        _ph.reset()
    t = now
    dt = max(0.0, min(0.1, t - _S.get("last", t)))
    _S["last"] = t
    ph = _S["ph"]
    n_f = (t - ph["t0"]) * _RATE
    n = max(0, min(len(ph["bits"]), int(n_f)))
    # phrase complete: hold, archive, start the next one
    if t > ph["end"] + 3.2:
        _S["log"].append(ph["text"])
        _S["log"] = _S["log"][-6:]
        _S["log_t"] = t
        _S["n_done"] += 1
        _new_phrase(t + 0.4)
        ph = _S["ph"]
        n_f = (t - ph["t0"]) * _RATE
        n = max(0, int(n_f))

    img = blank()
    d = ImageDraw.Draw(img)
    _txt_at(img, CX, 20, "LINGUA-TECHNIS  %02d" % (_S["n_done"] % 100), GREEN_MID, 9)
    _centre(img, d, t, ph, n)
    _waveform(img, d, t, ph, n_f)
    _register(img, d, t, ph, n)
    _ring(img, d, t, ph, n, dt)
    _meters(img, d, t, ph, n)
    in_log = t > ph["end"] + 0.5 and n >= len(ph["bits"])
    if not in_log:
        _log(img, d, t)
    _phrase_line(img, d, t, ph, n)
    return _ph.compose(img)
