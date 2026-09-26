"""Golden Throne EKG - life-support monitor for the Master of Mankind.

Three sweeping phosphor traces: a slow cardiac EKG with a proper PQRST
complex, the psychic output feeding the Astronomican, and the soul-feed intake
(each sacrificed psyker a spike, 1000 per day).  Numeric vitals update per
beat.  Every so often a trace falters - arrhythmia, asystole, a psychic dip or
a stalled feed - the monitor alarms in amber/red, the Tech-Priests intone the
litany, and the vitals stabilise.
"""

from __future__ import annotations

import math
import random

import numpy as np
from PIL import Image, ImageDraw

from ..lore._common import CX, Session, font, scale
from ._phosphor import (AMBER, GREEN, GREEN_DIM, GREEN_FAINT, GREEN_HI, GREEN_MID, RED,
                        Phosphor, blank)

NAME = "golden_throne_ekg"

_rng = random.Random()
_session = Session()
_ph = Phosphor(decay=0.80, bloom=0.55, flicker=0.03)

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


# -------------------------------------------------------------- layout ---
TX0, TW = 30, 132          # trace x start / width
SPEED = 46.0               # px per second
GAP = 9
# channel: (label, centre y, half-height)
CH = [("CARDIAC", 72, 20), ("PSY-OUT", 114, 13), ("SOUL-FEED", 152, 11)]
NX = 170                   # numerics column x

_EVENTS = ["ARRHYTHMIA", "ASYSTOLE", "PSY DIP", "FEED STALL"]
_LITANY = ["LITANY OF SUSTENANCE", "RITE OF QUICKENING", "CANTICLE OF THE THRONE",
           "INVOCATION OF VITALITY"]

_S: dict = {}


def _static_bg():
    img = Image.new("RGB", (240, 240), (0, 0, 0))
    d = ImageDraw.Draw(img)
    for label, cy, hh in CH:
        y0, y1 = cy - hh - 4, cy + hh + 4
        for x in range(TX0, TX0 + TW + 1, 11):
            for y in range(y0, y1 + 1, 4):
                d.point((x, y), fill=GREEN_FAINT)
        for y in range(y0, y1 + 1, 8):
            for x in range(TX0, TX0 + TW + 1, 3):
                d.point((x, y), fill=GREEN_FAINT)
        d.line([(TX0 - 3, y0), (TX0 - 3, y1)], fill=GREEN_DIM)
        d.line([(TX0 + TW + 3, y0), (TX0 + TW + 3, y1)], fill=GREEN_DIM)
        _txt(d, TX0 + TW - 1 - _tlen(label, 9), y0 + 1, label, GREEN_DIM, 9)
    # outer bezel segments
    for i in range(36):
        a0 = i * 10 + 1
        d.arc([6, 6, 234, 234], a0, a0 + 7, fill=GREEN_FAINT, width=2)
    return img


def _reset():
    _S.clear()
    _ph.reset()
    s = _S
    s["bg"] = _static_bg()
    s["buf"] = [np.zeros(TW, np.float32) for _ in CH]
    s["wx"] = 0.0          # write head (px, float, continuous)
    s["hr"] = _rng.uniform(40, 48)
    s["beat_t"] = 0.5      # time of the next beat
    s["last_beat"] = -10.0
    s["beats"] = []        # recent beat times
    s["souls"] = []        # soul arrival times (recent)
    s["next_soul"] = 0.4
    s["fed"] = _rng.randint(100, 900)
    s["ev"] = None
    s["ev_t"] = 0.0
    s["next_ev"] = _rng.uniform(22, 32)
    s["ev_order"] = _rng.sample(_EVENTS, len(_EVENTS))
    s["ev_n"] = 0
    s["litany"] = _rng.choice(_LITANY)
    s["ph"] = [_rng.uniform(0, 6.28) for _ in range(4)]
    s["t_prev"] = 0.0
    s["hr_disp"] = int(s["hr"])
    s["stab_t"] = -10.0
    s["pause"] = False


def _ekg(tau):
    """PQRST complex; tau = seconds since beat start."""
    if tau < 0 or tau > 0.9:
        return 0.0
    g = math.exp
    return (0.13 * g(-((tau - 0.10) / 0.028) ** 2) - 0.12 * g(-((tau - 0.205) / 0.010) ** 2)
            + 1.00 * g(-((tau - 0.225) / 0.014) ** 2) - 0.28 * g(-((tau - 0.250) / 0.012) ** 2)
            + 0.30 * g(-((tau - 0.46) / 0.055) ** 2))


def _ev_active(name, t):
    s = _S
    return s["ev"] == name and 0 <= t - s["ev_t"] < _EV_LEN[name]


_EV_LEN = {"ARRHYTHMIA": 9.0, "ASYSTOLE": 7.5, "PSY DIP": 9.0, "FEED STALL": 8.0}


def _sample(t):
    """Values for the three channels at time t (normalised -1..1)."""
    s = _S
    # cardiac: sum of the beats near t
    v = 0.0
    for bt in s["beats"][-3:]:
        v += _ekg(t - bt)
    v += 0.02 * math.sin(t * 2.1)  # baseline wander
    # psychic output
    ph = s["ph"]
    amp = 1.0
    if s["ev"] == "PSY DIP":
        e = t - s["ev_t"]
        if 0 <= e < 9.0:
            amp = 0.15 + 0.85 * min(1.0, abs(e - 3.5) / 3.5) if e < 7 else 1.0
    p = amp * (0.45 * math.sin(t * 4.2 + ph[0]) + 0.25 * math.sin(t * 9.7 + ph[1])
               + 0.15 * math.sin(t * 23.0 + ph[2])) + 0.12 * (_rng.random() - 0.5)
    # soul feed: decaying spikes
    f = 0.0
    for st in s["souls"][-4:]:
        e = t - st
        if 0 <= e < 0.4:
            f += math.exp(-e * 16) * (1.0 if e > 0.02 else e / 0.02)
    return v, p, min(1.2, f)


def _schedule_beats(t):
    s = _S
    while s["beat_t"] <= t + 0.05:
        bt = s["beat_t"]
        s["beats"].append(bt)
        if len(s["beats"]) > 8:
            s["beats"].pop(0)
        s["last_beat"] = bt
        hr = s["hr"] + 1.5 * math.sin(bt * 0.13)
        if _ev_active("ARRHYTHMIA", bt):
            hr = _rng.uniform(30, 95)
        interval = 60.0 / hr
        nb = bt + interval
        if s["pause"]:
            s["pause"] = False
            nb = max(nb, s["ev_t"] + 5.2)   # the pause
        s["beat_t"] = nb
        s["hr_disp"] = int(hr)


def _schedule_souls(t):
    s = _S
    while s["next_soul"] <= t:
        st = s["next_soul"]
        s["souls"].append(st)
        if len(s["souls"]) > 8:
            s["souls"].pop(0)
        s["fed"] += 1
        rate = 1.3
        if s["ev"] == "FEED STALL":
            e = st - s["ev_t"]
            if 0 <= e < 5.0:
                rate = 0.05
            elif 5.0 <= e < 8.0:
                rate = 6.0        # backlog flushed
        nxt = st + _rng.expovariate(rate) + 0.08
        if s["ev"] == "FEED STALL" and st - s["ev_t"] < 5.0:
            nxt = min(nxt, s["ev_t"] + 5.0)
        s["next_soul"] = nxt


def _draw_trace(d, buf, cy, hh, head, col, headcol):
    vals = cy - np.clip(buf, -1.3, 1.3) * hh
    ys = vals.tolist()
    h = int(head) % TW
    # two segments: after gap to end, start to head
    a0 = h + GAP
    if a0 < TW - 1:
        d.line([(TX0 + i, ys[i]) for i in range(a0, TW)], fill=col)
    if h > 1:
        d.line([(TX0 + i, ys[i]) for i in range(0, h)], fill=col)
    if h > 0:
        y = ys[h - 1]
        d.ellipse([TX0 + h - 2.5, y - 2.5, TX0 + h + 1.5, y + 1.5], fill=headcol)


def render(bezel, mask, now: float) -> Image.Image:
    if _session.fresh(now) or not _S:
        _reset()
    s = _S
    t = _session.t(now)
    blink = int(t * 4) % 2 == 0

    # ---------------- events
    if s["ev"] is None and t >= s["next_ev"]:
        s["ev"] = s["ev_order"][s["ev_n"] % len(s["ev_order"])]
        s["ev_n"] += 1
        s["ev_t"] = t
        s["litany"] = _rng.choice(_LITANY)
        s["pause"] = s["ev"] == "ASYSTOLE"
    if s["ev"] is not None and t - s["ev_t"] > _EV_LEN[s["ev"]]:
        s["ev"] = None
        s["stab_t"] = t
        s["next_ev"] = t + _rng.uniform(26, 42)

    _schedule_beats(t)
    _schedule_souls(t)

    # ---------------- advance write head, fill samples
    t0 = s["t_prev"]
    x0 = s["wx"]
    x1 = t * SPEED
    n = int(x1) - int(x0)
    if n > TW:
        n = TW
    for k in range(n):
        xx = int(x0) + 1 + k
        ts = t0 + (t - t0) * (k + 1) / max(1, n)
        v, p, f = _sample(ts)
        i = xx % TW
        s["buf"][0][i] = v
        s["buf"][1][i] = p
        s["buf"][2][i] = f
    s["wx"] = x1
    s["t_prev"] = t

    img = s["bg"].copy()
    d = ImageDraw.Draw(img)

    ev = s["ev"]
    e_age = t - s["ev_t"] if ev else 0.0
    alarm_c = [GREEN, GREEN, GREEN]
    if ev == "ARRHYTHMIA":
        alarm_c[0] = AMBER
    elif ev == "ASYSTOLE":
        alarm_c[0] = RED if e_age < 5.2 else AMBER
    elif ev == "PSY DIP":
        alarm_c[1] = AMBER
    elif ev == "FEED STALL":
        alarm_c[2] = AMBER
    for ci, (label, cy, hh) in enumerate(CH):
        _draw_trace(d, s["buf"][ci], cy, hh, x1, alarm_c[ci], GREEN_HI)
        if alarm_c[ci] != GREEN and blink:
            d.rectangle([TX0 - 5, cy - hh - 5, TX0 + TW + 5, cy + hh + 5], outline=alarm_c[ci])

    # ---------------- numerics
    since = t - s["last_beat"]
    beat_glow = max(0.0, 1 - since / 0.35) if since >= 0.2 else 0.0
    hr = s["hr_disp"]
    if ev == "ASYSTOLE" and since > 2.0 and e_age < 5.3:
        hr = 0
    _txt(d, NX, 50, "HR", GREEN_DIM, 9)
    _txt(d, NX, 60, "%02d" % hr, alarm_c[0] if alarm_c[0] != GREEN else GREEN_HI, 16)
    hx, hy = NX + 30, 68
    r = 2.5 + 2.5 * beat_glow
    d.polygon([(hx, hy - r), (hx + r, hy), (hx, hy + r), (hx - r, hy)],
              fill=scale(GREEN_HI, 0.3 + 0.7 * beat_glow))
    _txt(d, NX, 80, "SPO2 97", GREEN_MID, 9)

    psi = 97.5 + 1.5 * math.sin(t * 0.21)
    if ev == "PSY DIP" and e_age < 7:
        psi = 97.5 - 61 * max(0.0, 1 - abs(e_age - 3.5) / 3.5)
    _txt(d, NX, 101, "PSI", GREEN_DIM, 9)
    _txt(d, NX, 111, "%.1f" % psi, alarm_c[1] if alarm_c[1] != GREEN else GREEN_HI, 11)
    _txt(d, NX, 124, "ASTRO", GREEN_DIM, 9)

    _txt(d, NX, 141, "FED", GREEN_DIM, 9)
    _txt(d, NX, 151, "%05d" % s["fed"], alarm_c[2] if alarm_c[2] != GREEN else GREEN_HI, 10)
    _txtc(d, 167, "INTAKE 1000 PSYKERS/DAY", GREEN_DIM, 9, x=TX0 + TW / 2 + 12)

    # ---------------- header
    _txtc(d, 18, "GOLDEN THRONE", GREEN_HI, 10)
    _txtc(d, 30, "SUSTAINED 10000 YRS", GREEN_MID, 9)

    # ---------------- status / alarm banner
    ys = 182
    if ev:
        if ev == "ASYSTOLE":
            main = "ASYSTOLE" if e_age < 5.2 else "RHYTHM RESTORED"
            col = (RED if blink else AMBER) if e_age < 5.2 else GREEN_HI
        else:
            main = ev + " DETECTED" if e_age < _EV_LEN[ev] - 2.5 else ev + " RESOLVING"
            col = AMBER if blink or e_age > _EV_LEN[ev] - 2.5 else GREEN_MID
        _txtc(d, ys, main, col, 11)
        _txtc(d, ys + 13, s["litany"], GREEN_MID, 9)
        if ev == "ASYSTOLE" and 4.9 < e_age < 5.4:
            # restorative jolt
            d.rectangle([TX0 - 5, CH[0][1] - 26, TX0 + TW + 5, CH[0][1] + 26], outline=GREEN_HI, width=2)
    elif t - s["stab_t"] < 4.0:
        _txtc(d, ys, "VITALS STABILISED", GREEN_HI, 11)
        _txtc(d, ys + 13, "THE EMPEROR ENDURES", GREEN_MID, 9)
    else:
        _txtc(d, ys, "STATUS: STABLE", GREEN, 11)
        sustain = 99.2 + 0.5 * math.sin(t * 0.05)
        w = 76
        d.rectangle([CX - w / 2, ys + 15, CX + w / 2, ys + 20], outline=GREEN_DIM)
        d.rectangle([CX - w / 2 + 1, ys + 16, CX - w / 2 + 1 + (w - 2) * sustain / 100, ys + 19], fill=GREEN_MID)
        _txtc(d, ys + 23, "SUSTAIN %.1f%%" % sustain, GREEN_DIM, 9)

    # soul motes streaming toward the throne sigil along the bezel
    a = t * 0.5
    for k in range(3):
        aa = a + k * 2.094
        rr = 104
        d.ellipse([CX + rr * math.cos(aa) - 1.5, 120 + rr * math.sin(aa) - 1.5,
                   CX + rr * math.cos(aa) + 1.5, 120 + rr * math.sin(aa) + 1.5], fill=GREEN)
    return _ph.compose(img)
