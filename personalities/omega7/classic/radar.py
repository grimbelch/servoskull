"""Auspex PPI – sweeping radar scope, green-phosphor edition.

A rotating beam paints terrain clutter and contacts with a long phosphor
afterglow. Contacts are tracked (IDs, history dots, velocity vectors), start
UNKNOWN and are resolved by IFF interrogation into FRIENDLY / UNKNOWN /
HOSTILE. Hostiles close on the scope centre and are neutralised by point
defence; tracks occasionally merge and separate, jamming strobes a bearing,
and the scan mode cycles between full surveillance, sector scan and high-PRF.
"""

from __future__ import annotations

import math
import random
from collections import deque

import numpy as np
from PIL import Image, ImageDraw

from ..lore._common import CX, CY, Session, font, scale
from ._phosphor import (AMBER, GREEN, GREEN_DIM, GREEN_FAINT, GREEN_HI, GREEN_MID, RED,
                        Phosphor)

NAME = "radar"

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
_session = Session()
_ph = Phosphor(decay=0.3, bloom=0.55)

R = 92.0                 # scope radius (px)
KM = 40.0                # range at the rim
PXK = R / KM
NB = 720                 # angular bins

_yy, _xx = np.mgrid[0:240, 0:240].astype(np.float32)
_DX, _DY = _xx - CX + 0.5, _yy - CY + 0.5
_RAD = np.sqrt(_DX ** 2 + _DY ** 2)
_ANG = np.mod(np.arctan2(_DX, -_DY), 2 * np.pi)
_ANGQ = (_ANG / (2 * np.pi) * NB).astype(np.int32) % NB
_DISK = (_RAD <= R).astype(np.float32)
_RADI = np.clip(_RAD, 0, 127).astype(np.int32)

_TRAIL = np.zeros(NB, dtype=np.float32)
_tb = np.arange(NB, dtype=np.float32)
_TRAIL[:] = np.where(_tb < 220, np.exp(-_tb / 55.0), 0.0)
_TRAIL[0] = 1.0

B0, B1 = int(CX - R - 1), int(CX + R + 2)          # bounding box of the scope disk
_TRAIL2 = np.concatenate([_TRAIL, _TRAIL])
_NEGQ = (NB - _ANGQ)[B0:B1, B0:B1].astype(np.int32)
_ANGQB = _ANGQ[B0:B1, B0:B1].astype(np.int32)
_RADIB = _RADI[B0:B1, B0:B1]
_RLUT = (np.arange(256, dtype=np.float32)[:, None] / 255.0 * np.array(GREEN, np.float32)).astype(np.uint8)

CLS_COL = {"FRIENDLY": GREEN_HI, "UNKNOWN": AMBER, "HOSTILE": RED}
CLS_TAG = {"FRIENDLY": "FRD", "UNKNOWN": "UNK", "HOSTILE": "HOS"}

_S = {}


def _smooth_noise(n, out=240, seed=None):
    g = np.random.default_rng(seed).random((n, n)).astype(np.float32)
    im = Image.fromarray((g * 255).astype(np.uint8)).resize((out, out), Image.BICUBIC)
    return np.asarray(im, dtype=np.float32) / 255.0


def _build_static():
    """Rings, ticks, labels drawn once per showing."""
    img = Image.new("RGB", (240, 240), (0, 0, 0))
    d = ImageDraw.Draw(img)
    for i, km in enumerate((10, 20, 30, 40)):
        r = km * PXK
        d.ellipse([CX - r, CY - r, CX + r, CY + r], outline=GREEN_DIM if km < 40 else GREEN_MID)
        if km < 40:
            a = math.radians(128)
            _txt(d, CX + (r + 1) * math.sin(a), CY - (r + 1) * math.cos(a), f"{km}", GREEN_DIM, 9, "l")
    for deg in range(0, 360, 5):
        a = math.radians(deg)
        L = 6 if deg % 30 == 0 else (4 if deg % 10 == 0 else 2)
        d.line([(CX + R * math.sin(a), CY - R * math.cos(a)),
                (CX + (R + L) * math.sin(a), CY - (R + L) * math.cos(a))],
               fill=GREEN_MID if deg % 30 == 0 else GREEN_DIM)
    for deg in (0, 90, 180, 270):
        a = math.radians(deg)
        x, y = CX + 105 * math.sin(a), CY - 105 * math.cos(a)
        _txt(d, x, y - 5, f"{deg:03d}", GREEN_MID, 9, "c")
    for deg in (30, 60, 120, 150, 210, 240, 300, 330):
        a = math.radians(deg)
        x, y = CX + 104 * math.sin(a), CY - 104 * math.cos(a)
        _txt(d, x, y - 5, f"{deg // 10:02d}", GREEN_DIM, 9, "c")
    # crosshair spokes
    for deg in range(0, 360, 45):
        a = math.radians(deg)
        d.line([(CX + 6 * math.sin(a), CY - 6 * math.cos(a)), (CX + R * math.sin(a), CY - R * math.cos(a))],
               fill=GREEN_FAINT)
    # own-ship marker
    d.polygon([(CX, CY - 4), (CX + 3, CY + 3), (CX, CY + 1), (CX - 3, CY + 3)], outline=GREEN_HI)
    return np.asarray(img, dtype=np.uint8).copy()


def _build_clutter():
    seed = _rng.randrange(1 << 30)
    coarse = _smooth_noise(9, seed=seed)
    fine = _smooth_noise(40, seed=seed + 1)
    land = np.clip((coarse - 0.58) * 6.0, 0, 1) * (0.55 + 0.45 * fine)
    # coastline edge brighter
    edge = np.clip(1 - np.abs(coarse - 0.6) * 18, 0, 1) * 0.5
    sea = np.exp(-_RAD / 26.0) * (0.25 + 0.75 * _smooth_noise(60, seed=seed + 2))
    speck = (np.random.default_rng(seed + 3).random((240, 240)) > 0.985).astype(np.float32) * 0.35
    c = np.clip(land * 0.55 + edge + sea * 0.9 + speck, 0, 1) * _DISK
    return c.astype(np.float32)


def _new_contact(t, cls=None, pos=None, vel=None):
    _S["next_id"] += 1
    if cls is None:
        cls = _rng.choices(("FRIENDLY", "UNKNOWN", "HOSTILE"), (0.4, 0.25, 0.35))[0]
    if pos is None:
        b = _rng.uniform(0, 2 * math.pi)
        r = _rng.uniform(36, 39.5)
        pos = (r * math.sin(b), r * math.cos(b))
    if vel is None:
        spd = _rng.uniform(0.35, 0.8)          # km / s (sped-up tactical time)
        if cls == "HOSTILE":
            aim = math.atan2(-pos[0], -pos[1]) + _rng.uniform(-0.25, 0.25)
        else:
            aim = math.atan2(-pos[0], -pos[1]) + _rng.uniform(-0.9, 0.9)
        vel = (spd * math.sin(aim), spd * math.cos(aim))
    c = {"id": _S["next_id"] % 100, "x": pos[0], "y": pos[1], "vx": vel[0], "vy": vel[1], "true": cls,
         "cls": "UNKNOWN", "paints": 0, "pt": None, "hist": deque(maxlen=6), "resolve_at": _rng.randint(2, 4),
         "alive": True, "born": t}
    _S["contacts"].append(c)
    return c


def _reset(t):
    _S.clear()
    _S.update(contacts=[], next_id=_rng.randint(0, 40), log=deque(maxlen=3), sweep=0.0, dir=1,
              mode="SURVEILLANCE", mode_t=t, mode_next=t + _rng.uniform(40, 60), period=4.0,
              sector=None, jam=None, jam_next=t + _rng.uniform(35, 55), merge_next=t + _rng.uniform(20, 35),
              pulses=[], ghosts=[], neutralised=0)
    _S["static"] = _build_static()
    _S["clutter"] = _build_clutter()
    _S["base"] = np.minimum((0.16 * _DISK + _S["clutter"] * 0.95) * 255.0, 255.0)[B0:B1, B0:B1].astype(np.float32)
    for _ in range(5):
        c = _new_contact(t)
        r = _rng.uniform(12, 34)
        b = _rng.uniform(0, 2 * math.pi)
        c["x"], c["y"] = r * math.sin(b), r * math.cos(b)
    _log("AUSPEX ONLINE", GREEN_HI, t)
    _ph.reset()


def _log(text, col, t):
    _S["log"].append((text, col, t))


def _bearing(x, y):
    return math.atan2(x, y) % (2 * math.pi)


def _swept(prev, cur, direction, b):
    """Did the beam pass bearing b moving from prev to cur?"""
    if direction > 0:
        span = (cur - prev) % (2 * math.pi)
        return (b - prev) % (2 * math.pi) <= span
    span = (prev - cur) % (2 * math.pi)
    return (prev - b) % (2 * math.pi) <= span


def _update(dt, t):
    prev = _S["sweep"]
    # --- scan-mode phases
    if t > _S["mode_next"]:
        modes = ["SURVEILLANCE", "SECTOR SCAN", "HIGH PRF"]
        modes.remove(_S["mode"])
        m = _rng.choice(modes) if _S["mode"] == "SURVEILLANCE" else "SURVEILLANCE"
        _S["mode"] = m
        _S["mode_next"] = t + (_rng.uniform(45, 65) if m == "SURVEILLANCE" else _rng.uniform(18, 26))
        _S["dir"] = 1
        if m == "SECTOR SCAN":
            hs = [c for c in _S["contacts"] if c["cls"] == "HOSTILE"]
            tgt = _rng.choice(hs) if hs else _rng.choice(_S["contacts"]) if _S["contacts"] else None
            b = _bearing(tgt["x"], tgt["y"]) if tgt else _rng.uniform(0, 2 * math.pi)
            _S["sector"] = (b - 0.8, b + 0.8)
            _S["sweep"] = prev = (b - 0.8) % (2 * math.pi)
            _log(f"SECTOR SCAN {int(math.degrees(b)) % 360:03d}", GREEN_HI, t)
        else:
            _S["sector"] = None
            _log("HIGH PRF MODE" if m == "HIGH PRF" else "SURVEILLANCE 360", GREEN_HI, t)
        _S["period"] = {"SURVEILLANCE": 4.0, "HIGH PRF": 2.4, "SECTOR SCAN": 3.2}[m]
    w = 2 * math.pi / _S["period"]
    if _S["sector"] is not None:
        a0, a1 = _S["sector"]
        rel = (_S["sweep"] - a0) % (2 * math.pi)
        rel += _S["dir"] * w * 0.6 * dt
        if rel > a1 - a0:
            rel = a1 - a0
            _S["dir"] = -1
        elif rel < 0 or rel > 5.5:
            rel = 0.0
            _S["dir"] = 1
        _S["sweep"] = (a0 + rel) % (2 * math.pi)
    else:
        _S["sweep"] = (_S["sweep"] + w * dt) % (2 * math.pi)
    cur = _S["sweep"]
    direction = _S["dir"]

    # --- contacts
    for c in _S["contacts"]:
        c["x"] += c["vx"] * dt
        c["y"] += c["vy"] * dt
        rng_ = math.hypot(c["x"], c["y"])
        if c["true"] == "HOSTILE" and c["cls"] == "HOSTILE" and rng_ < 16:
            # hostile homes in
            aim = math.atan2(-c["x"], -c["y"])
            spd = math.hypot(c["vx"], c["vy"])
            c["vx"] += (spd * math.sin(aim) - c["vx"]) * dt * 0.5
            c["vy"] += (spd * math.cos(aim) - c["vy"]) * dt * 0.5
        if _swept(prev, cur, direction, _bearing(c["x"], c["y"])):
            c["pt"] = t
            c["px"], c["py"] = c["x"], c["y"]
            c["hist"].append((c["x"], c["y"]))
            c["paints"] += 1
            if c["paints"] == c["resolve_at"] and c["cls"] == "UNKNOWN":
                if c["true"] != "UNKNOWN" or _rng.random() < 0.3:
                    c["cls"] = c["true"]
                    col = CLS_COL[c["cls"]]
                    _log(f"C-{c['id']:02d} IFF {c['cls']}", col, t)
                else:
                    c["resolve_at"] += 3
                    _log(f"C-{c['id']:02d} IFF NO REPLY", AMBER, t)
        if rng_ > 41:
            c["alive"] = False
        elif rng_ < 3.5 and c["true"] == "HOSTILE":
            c["alive"] = False
            _S["pulses"].append((c["x"], c["y"], t))
            _S["neutralised"] += 1
            _log(f"C-{c['id']:02d} NEUTRALISED", AMBER, t)
        elif rng_ < 2.5:
            c["alive"] = False
    _S["contacts"] = [c for c in _S["contacts"] if c["alive"]]

    # hostile close alert
    close = [c for c in _S["contacts"] if c["cls"] == "HOSTILE" and math.hypot(c["x"], c["y"]) < 12]
    _S["alert"] = min(close, key=lambda c: math.hypot(c["x"], c["y"])) if close else None

    # replenish
    while len(_S["contacts"]) < 5 or (len(_S["contacts"]) < 8 and _rng.random() < 0.004):
        _new_contact(t)

    # merge event: two tracks converge on a rendezvous point
    if t > _S["merge_next"]:
        _S["merge_next"] = t + _rng.uniform(45, 70)
        pb = _rng.uniform(0, 2 * math.pi)
        pr = _rng.uniform(12, 24)
        P = (pr * math.sin(pb), pr * math.cos(pb))
        T = _rng.uniform(22, 30)
        pair = []
        for off in (_rng.uniform(0.6, 1.2), -_rng.uniform(0.6, 1.2)):
            b = pb + off + math.pi / 2
            start = (P[0] + 0.4 * T * math.sin(b), P[1] + 0.4 * T * math.cos(b))
            vel = ((P[0] - start[0]) / T, (P[1] - start[1]) / T)
            pair.append(_new_contact(t, cls=_rng.choice(("FRIENDLY", "UNKNOWN")), pos=start, vel=vel))
        _S["merge_pair"] = (pair[0], pair[1], False)
    mp = _S.get("merge_pair")
    if mp is not None:
        a, b, merged = mp
        if not (a["alive"] and b["alive"]):
            _S["merge_pair"] = None
        else:
            dd = math.hypot(a["x"] - b["x"], a["y"] - b["y"])
            if not merged and dd < 1.6:
                _S["merge_pair"] = (a, b, True)
                _log(f"TRACK MERGE C-{a['id']:02d}/{b['id']:02d}", AMBER, t)
            elif merged and dd > 4.0:
                _S["merge_pair"] = None
                _log("TRACKS SEPARATED", GREEN_HI, t)

    # jamming
    jam = _S["jam"]
    if jam is None and t > _S["jam_next"]:
        b = _rng.uniform(0, 2 * math.pi)
        diff = np.abs((_ANG - b + np.pi) % (2 * np.pi) - np.pi)
        wedge = (np.clip(1 - diff / 0.07, 0, 1) * _DISK)[B0:B1, B0:B1]
        _S["jam"] = jam = {"b": b, "t0": t, "dur": _rng.uniform(7, 11), "wedge": wedge.astype(np.float32)}
        _log(f"JAMMING BRG {int(math.degrees(b)) % 360:03d}", RED, t)
        # false returns
        _S["ghosts"] = [(b + _rng.uniform(-0.05, 0.05), _rng.uniform(8, 38)) for _ in range(4)]
    if jam is not None and t - jam["t0"] > jam["dur"]:
        _S["jam"] = None
        _S["ghosts"] = []
        _S["jam_next"] = t + _rng.uniform(45, 70)
        _log("JAMMING CLEARED", GREEN_HI, t)
    _S["pulses"] = [p for p in _S["pulses"] if t - p[2] < 1.6]


def _draw_contact(d, c, t):
    if c["pt"] is None:
        return
    age = t - c["pt"]
    k = math.exp(-age / (_S["period"] * 0.9))
    if k < 0.06:
        return
    x, y = CX + c["px"] * PXK, CY - c["py"] * PXK
    col = CLS_COL[c["cls"]]
    # history dots
    for hx, hy in list(c["hist"])[:-1]:
        d.point((CX + hx * PXK, CY - hy * PXK), fill=scale(GREEN_MID, 0.8))
    # velocity vector (next 25 s)
    vx, vy = c["vx"] * 25 * PXK, -c["vy"] * 25 * PXK
    d.line([(x, y), (x + vx, y + vy)], fill=scale(col, 0.55 * k + 0.2))
    s = 3
    cc = scale(col, 0.35 + 0.65 * k)
    if c["cls"] == "FRIENDLY":
        d.ellipse([x - s, y - s, x + s, y + s], outline=cc)
    elif c["cls"] == "HOSTILE":
        d.polygon([(x, y - s - 1), (x + s + 1, y), (x, y + s + 1), (x - s - 1, y)], outline=cc)
    else:
        d.rectangle([x - s, y - s, x + s, y + s], outline=cc)
    d.point((x, y), fill=scale(GREEN_HI, k))
    lx = x + 5 if vx <= 0 else x - 5
    _txt(d, lx, y - 10, f"{c['id']:02d}", scale(col, 0.4 + 0.6 * k), 9, "l" if vx <= 0 else "r")


def render(bezel, mask, now: float) -> Image.Image:
    if _session.fresh(now) or not _S:
        _reset(now)
        _S["prev"] = now
    dt = max(0.0, min(0.1, now - _S["prev"]))
    _S["prev"] = now
    _update(dt, now)

    sweep = _S["sweep"]
    sb = int(sweep / (2 * math.pi) * NB) % NB
    if _S["dir"] > 0:
        trail = _TRAIL2[_NEGQ + sb]
    else:
        trail = _TRAIL2[_ANGQB + (NB - sb)]
    jam = _S["jam"]
    if jam is not None:
        prof = np.random.default_rng().random(128).astype(np.float32) * (0.9 * 255.0)
        base = np.maximum(_S["base"], jam["wedge"] * prof[_RADIB])
    else:
        base = _S["base"]
    trail *= base
    frame = _S["static"].copy()
    reg = frame[B0:B1, B0:B1]
    np.maximum(reg, _RLUT[trail.astype(np.uint8)], out=reg)
    img = Image.fromarray(frame)
    d = ImageDraw.Draw(img)

    # beam
    bx, by = CX + R * math.sin(sweep), CY - R * math.cos(sweep)
    d.line([(CX, CY), (bx, by)], fill=GREEN_HI)
    if _S["sector"] is not None:
        for a in _S["sector"]:
            d.line([(CX, CY), (CX + R * math.sin(a), CY - R * math.cos(a))], fill=GREEN_MID)

    # contacts
    for c in _S["contacts"]:
        _draw_contact(d, c, now)
    for gb, gr in _S["ghosts"]:
        if (sweep - gb) % (2 * math.pi) < 1.2 and int(now * 10) % 3:
            x, y = CX + gr * PXK * math.sin(gb), CY - gr * PXK * math.cos(gb)
            d.rectangle([x - 1, y - 1, x + 1, y + 1], fill=GREEN_HI)
    mp = _S.get("merge_pair")
    if mp is not None and mp[2]:
        a = mp[0]
        if a["pt"] is not None:
            x, y = CX + a["px"] * PXK, CY - a["py"] * PXK
            r = 8 + 2 * math.sin(now * 8)
            d.ellipse([x - r, y - r, x + r, y + r], outline=AMBER)
            _txt(d, x, y + r + 1, "MERGE", AMBER, 9, "c")
    for (px, py, t0) in _S["pulses"]:
        k = (now - t0) / 1.6
        r = 3 + 24 * k
        x, y = CX + px * PXK, CY - py * PXK
        d.ellipse([x - r, y - r, x + r, y + r], outline=scale(AMBER, 1 - k))

    alert = _S.get("alert")
    if alert is not None:
        rr = math.hypot(alert["x"], alert["y"]) * PXK
        if int(now * 4) % 2 == 0:
            d.ellipse([CX - rr, CY - rr, CX + rr, CY + rr], outline=scale(RED, 0.6))
            _txt(d, CX, 44, f"HOSTILE CLOSING {math.hypot(alert['x'], alert['y']):4.1f}KM", RED, 9, "c")

    # HUD
    cs = _S["contacts"]
    nh = sum(1 for c in cs if c["cls"] == "HOSTILE")
    nu = sum(1 for c in cs if c["cls"] == "UNKNOWN")
    _txt(d, CX, 30, f"{_S['mode']}  BRG {int(math.degrees(sweep)) % 360:03d}", GREEN_MID, 9, "c")
    _txt(d, CX - 44, 190, f"TRK {len(cs):02d}", GREEN, 9, "l")
    _txt(d, CX, 190, f"UNK {nu}", AMBER if nu else GREEN_DIM, 9, "c")
    _txt(d, CX + 44, 190, f"HOS {nh}", RED if nh else GREEN_DIM, 9, "r")
    if _S["log"]:
        text, col, t0 = _S["log"][-1]
        age = now - t0
        if age < 5.0:
            k = 1.0 if age < 4.0 else 5.0 - age
            if age > 0.4 or int(age * 14) % 2 == 0:
                _txt(d, CX, 172, text, scale(col, k), 9, "c")
    return _ph.compose(img)
