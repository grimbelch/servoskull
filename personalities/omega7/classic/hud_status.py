"""HUD Status - the OMEGA-7 cogitator's own system monitor.

A round dashboard: a rotating bezel with a sweeping tick, the uptime counter,
three ring gauges (logis load, core temperature, mnemonic memory) whose
values drift smoothly, a sparkline of recent load, and a row of status lamps
for the servo-skull's subsystems.  Over a showing things happen: rite
compilations spike the load and heat the core until a thermal caution is
raised and coolant is purged; memory creeps up until a mnemonic purge; the
vox link drops and recovers; periodically the whole panel runs a self-test
sweep.  Alerts appear in amber (red for faults) and are cleared in green.
"""

from __future__ import annotations

import math
import random

from PIL import Image, ImageDraw

from ..lore._common import CX, CY, Session, font
from ._phosphor import AMBER, GREEN, GREEN_DIM, GREEN_HI, GREEN_MID, RED, Phosphor, blank

NAME = "hud_status"

_rng = random.Random()
_session = Session()
_ph = Phosphor(decay=0.35, bloom=0.55, flicker=0.03)

_TXT: dict = {}
_LAMPS = ["NOO", "VOX", "AUS", "LOG", "SRV", "PWR"]
_FAINT = (5, 40, 16)


def _tmask(s, size):
    k = (s, size)
    m = _TXT.get(k)
    if m is None:
        f = font(size)
        m = Image.new("L", (int(math.ceil(f.getlength(s))) + 2, size + 5), 0)
        ImageDraw.Draw(m).text((0, 0), s, fill=255, font=f)
        if len(_TXT) > 500:
            _TXT.clear()
        _TXT[k] = m
    return m


def _txt_at(img, cx, y, s, col, size):
    """Text horizontally centred on cx."""
    m = _tmask(s, size)
    img.paste(col, (int(cx - (m.width - 2) / 2), int(y)), m)


def _txt_c(img, y, s, col, size):
    _txt_at(img, CX, y, s, col, size)


def _mix(a, b, k):
    k = max(0.0, min(1.0, k))
    return tuple(int(a[i] + (b[i] - a[i]) * k) for i in range(3))


# --------------------------------------------------------------------- state

_S: dict = {}


def _reset(t):
    _S.clear()
    _S.update(
        t0=t, last=t, up0=_rng.randint(2 * 86400, 40 * 86400),
        cpu=0.3, tmp=52.0, mem=0.45, cpu_t=0.3,
        hist=[0.3] * 46, thist=[0.4] * 46, hist_t=t,
        disp=None, disp_t=0.0,
        lamps=["ok"] * 6,
        alerts=[],           # list of dicts {text, col, t0, clear_t, cleared}
        spike_until=0.0, next_spike=t + _rng.uniform(15, 30),
        coolant_until=0.0, thermal=False,
        next_vox=t + _rng.uniform(40, 80), vox_until=0.0,
        selftest=None, next_selftest=t + _rng.uniform(8, 14),
        mem_purge=None, status="VIGILANT", sweep=0.0,
    )


def _alert(t, text, col, dur=None, key=None):
    for a in _S["alerts"]:
        if key and a.get("key") == key and not a.get("cleared"):
            return a
    a = {"text": text, "col": col, "t0": t, "key": key, "cleared": None}
    if dur:
        a["clear_at"] = t + dur
    _S["alerts"].append(a)
    return a


def _clear(t, key, text):
    for a in _S["alerts"]:
        if a.get("key") == key and not a.get("cleared"):
            a["cleared"] = t
            a["ctext"] = text


def _update(t, dt):
    s = _S
    st = t - s["t0"]
    # --- events
    if t >= s["next_spike"] and s["selftest"] is None:
        s["spike_until"] = t + _rng.uniform(9, 16)
        s["next_spike"] = s["spike_until"] + _rng.uniform(25, 45)
        _alert(t, "RITE COMPILATION", GREEN_HI, dur=3.0)
    spiking = t < s["spike_until"]
    if t >= s["next_vox"]:
        s["vox_until"] = t + _rng.uniform(4, 7)
        s["next_vox"] = t + _rng.uniform(60, 110)
        _alert(t, "VOX LINK LOST", RED, key="vox")
    if s["vox_until"] and t >= s["vox_until"]:
        s["vox_until"] = 0.0
        _clear(t, "vox", "VOX RESTORED")
    if s["selftest"] is None and t >= s["next_selftest"]:
        s["selftest"] = t
        _alert(t, "SELF-TEST", GREEN_HI, dur=4.0)
    if s["selftest"] is not None and t - s["selftest"] > 4.5:
        s["selftest"] = None
        s["next_selftest"] = t + _rng.uniform(80, 110)
        _alert(t, "ALL RITES PASSED", GREEN, dur=2.5)

    # --- targets
    base = 0.22 + 0.12 * math.sin(st * 0.21) + 0.07 * math.sin(st * 0.77 + 1.3) + 0.04 * math.sin(st * 2.3)
    if spiking:
        base = 0.86 + 0.08 * math.sin(st * 3.1)
    s["cpu_t"] = base + _rng.uniform(-0.03, 0.03)
    s["cpu"] += (s["cpu_t"] - s["cpu"]) * min(1.0, dt * 2.5)
    heat = 45 + 42 * s["cpu"]
    if t < s["coolant_until"]:
        heat = 38
    s["tmp"] += (heat - s["tmp"]) * min(1.0, dt * 0.35)
    if not s["thermal"] and s["tmp"] > 74:
        s["thermal"] = True
        _alert(t, "THERMAL CAUTION", AMBER, key="therm")
    if s["thermal"] and s["tmp"] > 79 and s["coolant_until"] < t:
        s["coolant_until"] = t + 6.0
        _alert(t, "COOLANT PURGE", GREEN_HI, dur=2.5)
    if s["thermal"] and s["tmp"] < 66:
        s["thermal"] = False
        _clear(t, "therm", "THERMAL NOMINAL")
    # memory creeps up; purge when high
    if s["mem_purge"] is None:
        s["mem"] += dt * (0.004 + 0.01 * s["cpu"])
        if s["mem"] > 0.88:
            s["mem_purge"] = t
            _alert(t, "MNEMONIC PURGE", AMBER, dur=3.0)
    else:
        s["mem"] += (0.32 - s["mem"]) * min(1.0, dt * 1.5)
        if t - s["mem_purge"] > 3.0:
            s["mem_purge"] = None

    # history
    if t - s["hist_t"] >= 0.35:
        s["hist_t"] = t
        s["hist"] = s["hist"][1:] + [s["cpu"]]
        s["thist"] = s["thist"][1:] + [(s["tmp"] - 30) / 60]

    # lamps
    lamps = ["ok"] * 6
    if s["vox_until"]:
        lamps[1] = "err"
    if s["thermal"]:
        lamps[3] = "warn"
    if s["mem_purge"] is not None:
        lamps[0] = "warn"
    if spiking:
        lamps[3] = "busy" if lamps[3] == "ok" else lamps[3]
    s["lamps"] = lamps

    # expire alerts
    keep = []
    for a in s["alerts"]:
        if a.get("clear_at") and t >= a["clear_at"] and not a["cleared"]:
            a["cleared"] = t
            a["ctext"] = None
        if a["cleared"] is None or t - a["cleared"] < 2.2:
            keep.append(a)
    s["alerts"] = keep[-4:]


def _values(t):
    """Displayed gauge values (0..1), with the self-test sweep override."""
    s = _S
    cpu = s["cpu"]
    tmp = (s["tmp"] - 30) / 60
    mem = s["mem"]
    if s["selftest"] is not None:
        u = t - s["selftest"]
        if u < 4.0:
            k = math.sin(min(1.0, u / 3.2) * math.pi)
            cpu = cpu + (1 - cpu) * k
            tmp = tmp + (1 - tmp) * k
            mem = mem + (1 - mem) * k
    return cpu, tmp, mem


# --------------------------------------------------------------------- drawing

def _bezel(img, d, t):
    rot = t * 0.12
    s_ang = (t * 1.1) % (2 * math.pi)
    for i in range(72):
        a = rot + i * 2 * math.pi / 72
        long = i % 6 == 0
        r0 = 102 if long else 106
        ca, sa = math.cos(a), math.sin(a)
        # the sweep brightens ticks just behind it
        da = (s_ang - a) % (2 * math.pi)
        k = max(0.0, 1.0 - da / 1.2)
        col = _mix(GREEN_DIM if not long else GREEN_MID, GREEN_HI, k * k)
        d.line([(CX + r0 * ca, CY + r0 * sa), (CX + 111 * ca, CY + 111 * sa)], fill=col)
    d.arc([CX - 98, CY - 98, CX + 98, CY + 98], 0, 360, fill=(6, 50, 20))


def _ring(img, d, cx, cy, v, label, text, col, t):
    r = 21
    box = [cx - r, cy - r, cx + r, cy + r]
    d.arc(box, 0, 360, fill=_FAINT, width=5)
    end = -90 + 360 * max(0.0, min(1.0, v))
    if v > 0.005:
        d.arc(box, -90, end, fill=col, width=5)
    # bright leading edge
    a = math.radians(end)
    d.line([(cx + (r - 6) * math.cos(a), cy + (r - 6) * math.sin(a)),
            (cx + (r + 2) * math.cos(a), cy + (r + 2) * math.sin(a))], fill=GREEN_HI, width=2)
    for k in range(12):
        a = k * math.pi / 6
        d.point((cx + (r + 4) * math.cos(a), cy + (r + 4) * math.sin(a)), fill=GREEN_MID)
    _txt_at(img, cx, cy - 8, text, GREEN_HI if col != AMBER else AMBER, 12)
    _txt_at(img, cx, cy + r + 6, label, GREEN_MID, 9)


def _spark(img, d, t):
    x0, x1, y0, y1 = 54, 186, 147, 167
    d.rectangle([x0, y0, x1, y1], outline=(6, 50, 20))
    for gy in (y0 + 8, y0 + 16):
        for gx in range(x0 + 2, x1, 4):
            d.point((gx, gy), fill=(6, 50, 20))
    h, th = _S["hist"], _S["thist"]
    n = len(h)
    step = (x1 - x0 - 4) / (n - 1)
    tp = [(x0 + 2 + i * step, y1 - 2 - (y1 - y0 - 4) * max(0.0, min(1.0, v))) for i, v in enumerate(th)]
    cp = [(x0 + 2 + i * step, y1 - 2 - (y1 - y0 - 4) * max(0.0, min(1.0, v))) for i, v in enumerate(h)]
    d.line(tp, fill=(60, 100, 20) if _S["thermal"] else (12, 90, 36))
    d.line(cp, fill=GREEN)
    ex, ey = cp[-1]
    d.ellipse([ex - 2, ey - 2, ex + 2, ey + 2], fill=GREEN_HI)
    _txt_at(img, x0 + 24, y0 - 12, "LOAD 16S", (12, 100, 40), 9)
    _txt_at(img, x1 - 24, y0 - 12, "PEAK %02d" % min(99, int(max(h) * 100)), (12, 100, 40), 9)


def _lamps(img, d, t):
    xs = [CX - 65 + i * 26 for i in range(6)]
    y = 180
    st = _S["selftest"]
    for i, (x, state) in enumerate(zip(xs, _S["lamps"])):
        if st is not None and t - st < 4.0:
            on = int((t - st) * 8) % 6 == i
            col = GREEN_HI if on else GREEN_DIM
        elif state == "err":
            col = RED if int(t * 4) % 2 == 0 else (80, 20, 16)
        elif state == "warn":
            col = AMBER if int(t * 2.5) % 2 == 0 else (110, 70, 16)
        elif state == "busy":
            col = GREEN_HI if int(t * 10 + i) % 2 == 0 else GREEN_MID
        else:
            col = GREEN
        d.ellipse([x - 3, y - 3, x + 3, y + 3], fill=col)
        d.ellipse([x - 5, y - 5, x + 5, y + 5], outline=(6, 50, 20))
        _txt_at(img, x, y + 5, _LAMPS[i], (20, 130, 55) if state == "ok" else col, 9)


def _alerts(img, d, t):
    live = [a for a in _S["alerts"]]
    if not live:
        _txt_c(img, 204, "STATUS: VIGILANT", GREEN, 10)
        return
    a = live[-1]
    if a["cleared"] is not None:
        txt = a.get("ctext") or None
        if txt:
            _txt_c(img, 204, txt, GREEN, 10)
        else:
            _txt_c(img, 204, "STATUS: VIGILANT", GREEN, 10)
        return
    u = t - a["t0"]
    txt = a["text"]
    col = a["col"]
    m = _tmask(txt, 10)
    w = m.width - 2
    k = min(1.0, u / 0.25)
    if col in (AMBER, RED):
        d.rectangle([CX - (w / 2 + 5) * k, 202, CX + (w / 2 + 5) * k, 216], outline=col)
        if k >= 1 and (int(t * 3) % 4 != 3):
            _txt_c(img, 204, txt, col, 10)
    else:
        _txt_c(img, 204, txt, col, 10)


def render(bezel, mask, now: float) -> Image.Image:
    if _session.fresh(now) or not _S:
        _reset(now)
        _ph.reset()
    t = now
    dt = max(0.0, min(0.1, t - _S["last"]))
    _S["last"] = t
    _update(t, dt)

    img = blank()
    d = ImageDraw.Draw(img)
    _bezel(img, d, t)

    # header
    _txt_c(img, 26, "OMEGA-7 COGITATOR", GREEN_MID, 10)
    up = _S["up0"] + int(t - _S["t0"])
    _txt_c(img, 39, "UP %dD %02d:%02d:%02d" % (up // 86400, (up // 3600) % 24, (up // 60) % 60, up % 60),
           GREEN_HI, 12)

    # displayed numbers refresh at ~6 Hz so they are readable
    if _S["disp"] is None or t - _S["disp_t"] > 0.16:
        cpu, tmp, mem = _values(t)
        _S["disp"] = ("%d" % min(99, int(cpu * 100)), "%d" % int(30 + tmp * 60), "%d" % min(99, int(mem * 100)))
        _S["disp_t"] = t
    cpu, tmp, mem = _values(t)
    ds = _S["disp"]
    y = 92
    _ring(img, d, CX - 54, y, cpu, "LOGIS %", ds[0], GREEN, t)
    _ring(img, d, CX, y, tmp, "CORE °C", ds[1], AMBER if _S["thermal"] else GREEN, t)
    _ring(img, d, CX + 54, y, mem, "MNEMO %", ds[2], AMBER if _S["mem_purge"] is not None else GREEN, t)
    _spark(img, d, t)
    _lamps(img, d, t)
    _alerts(img, d, t)
    return _ph.compose(img)
