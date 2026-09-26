"""Canticle Rain - the binharic canticle falling through the cogitator's eye.

Three depth layers of falling glyph columns (far: small and dim and slow, near:
large, bright and fast) drift with a slow parallax sway.  Each column has a
white-hot leading glyph and a fading tail of binary, hex and Mechanicus
sigils.  The rain ebbs and surges over a showing, and every so often a verse
of the Canticle of the Omnissiah resolves out of the rain horizontally, holds,
then dissolves back into falling glyphs.

This is also the system fallback screensaver: resets are trivial and glyph
masks are built lazily and cached for the life of the process.
"""

from __future__ import annotations

import math
import random

from PIL import Image, ImageDraw

from ..lore._common import CX, CY, Session, font, safe_half_width
from ._phosphor import GREEN, GREEN_DIM, GREEN_HI, GREEN_MID, AMBER, Phosphor, blank

NAME = "canticle_rain"

_rng = random.Random()
_session = Session()
_ph = Phosphor(decay=0.45, bloom=0.6, flicker=0.03)

_HEX = "0123456789ABCDEF"
_N_MECH = 8
# glyph ids: 0..1 binary, 2..17 hex, 18.. mechanicus sigils
_VERSES = [
    ("THE FLESH", "IS WEAK"),
    ("PRAISE THE", "OMNISSIAH"),
    ("KNOWLEDGE", "IS POWER"),
    ("THE MACHINE", "ABIDES"),
    ("FROM THE", "WEAKNESS", "OF THE MIND"),
    ("THE SPIRIT", "IS WILLING"),
    ("HAIL THE", "MACHINE GOD"),
    ("THE OMNISSIAH", "KNOWS ALL"),
    ("GUIDE MY", "HAND AND EYE"),
    ("ALL IS", "DATA"),
]

# layer: (font size, x pitch, y pitch, speed range px/s, tail range, depth, colour ramp endpoints)
_LAYERS = [
    dict(size=9, px=9, py=10, spd=(22, 42), tail=(5, 10), depth=0.25, n=22,
         head=(90, 170, 110), body=(14, 95, 40), end=(4, 30, 12)),
    dict(size=11, px=13, py=13, spd=(48, 85), tail=(7, 12), depth=0.6, n=15,
         head=(150, 235, 170), body=(26, 170, 70), end=(6, 45, 18)),
    dict(size=14, px=18, py=17, spd=(95, 150), tail=(6, 11), depth=1.0, n=6,
         head=(215, 255, 225), body=(45, 235, 105), end=(8, 60, 24)),
]

_GLYPHS: dict = {}   # (layer index, glyph id) -> L mask sized to the cell
_TXT: dict = {}


def _mech_mask(k, w, h):
    m = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(m)
    x0, y0, x1, y1 = 1, 1, w - 2, h - 2
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    r = min(x1 - x0, y1 - y0) / 2
    if k == 0:    # cog
        d.ellipse([cx - r * 0.55, cy - r * 0.55, cx + r * 0.55, cy + r * 0.55], outline=255)
        for i in range(6):
            a = i * math.pi / 3
            d.line([(cx + r * 0.55 * math.cos(a), cy + r * 0.55 * math.sin(a)),
                    (cx + r * math.cos(a), cy + r * math.sin(a))], fill=255)
    elif k == 1:  # delta
        d.polygon([(cx, y0), (x1, y1), (x0, y1)], outline=255)
    elif k == 2:  # omega-ish
        d.arc([x0, y0, x1, y1 - 2], 140, 400, fill=255)
        d.line([(x0, y1), (cx - 2, y1)], fill=255)
        d.line([(cx + 2, y1), (x1, y1)], fill=255)
    elif k == 3:  # sigma
        d.line([(x1, y0), (x0, y0), (cx, cy), (x0, y1), (x1, y1)], fill=255)
    elif k == 4:  # psi
        d.line([(cx, y0), (cx, y1)], fill=255)
        d.arc([x0, y0 - (y1 - y0) * 0.4, x1, cy + 1], 0, 180, fill=255)
    elif k == 5:  # xi
        for yy in (y0, cy, y1):
            d.line([(x0, yy), (x1, yy)], fill=255)
    elif k == 6:  # skull dot pair
        d.rectangle([x0, y0, x1, cy + 1], outline=255)
        d.point([(cx - 1, cy - 1), (cx + 1, cy - 1)], fill=255)
        d.line([(cx - 1, y1), (cx + 1, y1)], fill=255)
    else:         # hex cell
        pts = [(cx + r * math.cos(a), cy + r * math.sin(a)) for a in [i * math.pi / 3 for i in range(6)]]
        d.polygon(pts, outline=255)
        d.point((cx, cy), fill=255)
    return m


def _glyph(li, gid):
    key = (li, gid)
    m = _GLYPHS.get(key)
    if m is None:
        L = _LAYERS[li]
        w, h = L["px"] - 1, L["py"]
        if gid >= 18:
            m = _mech_mask(gid - 18, w, h - 1)
        else:
            ch = "01"[gid] if gid < 2 else _HEX[gid - 2]
            f = font(L["size"])
            top = f.getbbox("0")[1]
            m = Image.new("L", (w, h), 0)
            cw = f.getlength(ch)
            ImageDraw.Draw(m).text(((w - cw) / 2, -top), ch, fill=255, font=f)
        _GLYPHS[key] = m
    return m


def _tmask(s, size):
    k = (s, size)
    m = _TXT.get(k)
    if m is None:
        f = font(size)
        m = Image.new("L", (int(math.ceil(f.getlength(s))) + 2, size + 5), 0)
        ImageDraw.Draw(m).text((0, 0), s, fill=255, font=f)
        if len(_TXT) > 300:
            _TXT.clear()
        _TXT[k] = m
    return m


def _txt_c(img, y, s, col, size):
    m = _tmask(s, size)
    img.paste(col, (int(CX - (m.width - 2) / 2), int(y)), m)


def _ramp(L, n):
    """Colour for tail position k (0 = head)."""
    out = []
    hc, bc, ec = L["head"], L["body"], L["end"]
    for k in range(n + 1):
        if k == 0:
            out.append(hc)
            continue
        u = k / n
        a, b, t = (bc, ec, (u - 0.25) / 0.75) if u > 0.25 else (hc, bc, u / 0.25)
        t = max(0.0, min(1.0, t)) ** 0.8
        out.append(tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3)))
    return out


_RAMPS = [[_ramp(L, n) for n in range(0, 16)] for L in _LAYERS]


def _rand_gid():
    r = _rng.random()
    if r < 0.66:
        return _rng.randint(0, 1)
    if r < 0.94:
        return 2 + _rng.randint(0, 15)
    return 18 + _rng.randint(0, _N_MECH - 1)


# --------------------------------------------------------------------- state

_S: dict = {}


def _new_drop(li, x=None, y=None):
    L = _LAYERS[li]
    return {
        "x": _rng.uniform(0, 240) if x is None else x,
        "y": _rng.uniform(-240, 0) if y is None else y,
        "v": _rng.uniform(*L["spd"]),
        "tail": _rng.randint(*L["tail"]),
        "g": [_rand_gid() for _ in range(260 // L["py"] + 20)],
    }


def _reset(t):
    _S.clear()
    _S["t0"] = t
    _S["last"] = t
    layers = []
    for li, L in enumerate(_LAYERS):
        drops = []
        for i in range(L["n"]):
            d = _new_drop(li, x=(i + _rng.random() * 0.6) * 240.0 / L["n"])
            d["y"] = _rng.uniform(-60, 260)
            drops.append(d)
        layers.append(drops)
    _S["layers"] = layers
    _S["verse"] = None
    _S["next_verse"] = t + _rng.uniform(7, 11)
    _S["surge"] = 0.0
    _S["next_surge"] = t + _rng.uniform(40, 70)
    _S["bits"] = _rng.randint(0x1000, 0x8000)
    _S["vi"] = _rng.randrange(len(_VERSES))


def _start_verse(t):
    lines = _VERSES[_S["vi"] % len(_VERSES)]
    _S["vi"] += 1
    size, pitch = 14, 12
    n = len(lines)
    y0 = CY - n * 22 / 2 + _rng.uniform(-18, 18)
    letters = []
    for li, line in enumerate(lines):
        y = y0 + li * 22
        x0 = CX - len(line) * pitch / 2
        for i, ch in enumerate(line):
            if ch == " ":
                continue
            cw = font(size).getlength(ch)
            letters.append({
                "ch": ch, "x": x0 + i * pitch + (pitch - cw) / 2, "gx": x0 + i * pitch, "y": y,
                "rev": t + 0.25 + _rng.uniform(0, 1.6) + i * 0.04,
                "gone": None, "g": _rand_gid(),
            })
    w = max(len(l) for l in lines) * pitch
    _S["verse"] = {"t0": t, "letters": letters, "lines": lines, "y0": y0, "n": n, "w": w,
                   "hold": t + 2.4 + 3.5, "end": None, "num": _S["vi"]}


def _update_verse(t):
    v = _S["verse"]
    if v is None:
        if t >= _S["next_verse"]:
            _start_verse(t)
        return
    if v["end"] is None and t >= v["hold"]:
        v["end"] = t
        for L in v["letters"]:
            L["gone"] = t + _rng.uniform(0, 1.4)
    if v["end"] is not None:
        alive = False
        for L in v["letters"]:
            if L["gone"] is not None and t >= L["gone"]:
                if not L.get("dropped"):
                    L["dropped"] = True
                    # the letter falls away as a near-layer drop
                    d = _new_drop(2, x=L["x"] - 3, y=L["y"] + 8)
                    d["tail"] = _rng.randint(4, 8)
                    _S["layers"][2].append(d)
            else:
                alive = True
        if not alive and t > v["end"] + 1.6:
            _S["verse"] = None
            _S["next_verse"] = t + _rng.uniform(13, 22)


# --------------------------------------------------------------------- render

def _draw_rain(img, t, dt, sway, speed_k, density):
    for li, drops in enumerate(_S["layers"]):
        L = _LAYERS[li]
        py, px = L["py"], L["px"]
        ramps = _RAMPS[li]
        xoff = sway * L["depth"]
        keep = []
        base_n = L["n"]
        for di, d in enumerate(drops):
            d["y"] += d["v"] * dt * speed_k
            tail = d["tail"]
            if d["y"] - tail * py > 250:
                if di >= base_n:
                    continue   # extra drops (from dissolved verses) die here
                nd = _new_drop(li, x=d["x"], y=_rng.uniform(-120, -10))
                if _rng.random() > density:
                    nd["y"] -= _rng.uniform(80, 260)   # sparser rain: longer gaps
                drops[di] = d = nd
                tail = d["tail"]
            keep.append(d)
            head = int(d["y"] // py)
            g = d["g"]
            ng = len(g)
            if _rng.random() < 0.08:
                g[_rng.randrange(ng)] = _rand_gid()
            x = int((d["x"] + xoff) % 246) - 3
            ramp = ramps[tail]
            for k in range(tail + 1):
                row = head - k
                y = row * py
                if y < -py or y > 240:
                    continue
                gid = g[row % ng]
                if k == 0 and _rng.random() < 0.35:
                    gid = _rand_gid()
                img.paste(ramp[k], (x, y), _glyph(li, gid))
        if len(keep) != len(drops):
            _S["layers"][li] = keep


def _draw_verse(img, d, t):
    v = _S["verse"]
    if v is None:
        return
    age = t - v["t0"]
    ending = v["end"] is not None
    # a dark band opens in the rain behind the verse
    open_k = min(1.0, age / 0.4)
    if ending:
        open_k = max(0.0, 1.0 - (t - v["end"]) / 1.2)
    if open_k > 0:
        hw = v["w"] / 2 + 12
        y0 = v["y0"] - 6
        y1 = v["y0"] + v["n"] * 22 + 1
        hh = (y1 - y0) / 2 * open_k
        my = (y0 + y1) / 2
        d.rectangle([CX - hw, my - hh, CX + hw, my + hh], fill=(0, 0, 0))
        if open_k > 0.9:
            c = (10, 90, 36)
            d.line([(CX - hw, my - hh), (CX - hw + 6, my - hh)], fill=c)
            d.line([(CX - hw, my - hh), (CX - hw, my - hh + 6)], fill=c)
            d.line([(CX + hw, my + hh), (CX + hw - 6, my + hh)], fill=c)
            d.line([(CX + hw, my + hh), (CX + hw, my + hh - 6)], fill=c)
            d.line([(CX + hw, my - hh), (CX + hw - 6, my - hh)], fill=c)
            d.line([(CX - hw, my + hh), (CX - hw + 6, my + hh)], fill=c)
            if not ending:
                _txt_c(img, my - hh - 13, "CANTICLE %02d" % (v["num"] % 100), (20, 120, 50), 9)
    all_rev = True
    for L in v["letters"]:
        if L.get("dropped"):
            continue
        x, y = int(L["x"]), int(L["y"])
        if t < L["rev"]:
            all_rev = False
            if _rng.random() < 0.5:
                L["g"] = _rand_gid()
            img.paste((30, 150, 60), (int(L["gx"]) - 3, y + 1), _glyph(2, L["g"]))
        else:
            since = t - L["rev"]
            if since < 0.35:
                c = GREEN_HI
            else:
                k = min(1.0, (since - 0.35) / 0.6)
                c = tuple(int(GREEN_HI[i] + (GREEN[i] - GREEN_HI[i]) * k) for i in range(3))
            img.paste(c, (x, y), _tmask(L["ch"], 14))
    # verification sweep once the verse has fully resolved
    if all_rev and not ending:
        last = max(L["rev"] for L in v["letters"])
        u = (t - last) / 0.7
        if 0 <= u <= 1:
            sx = CX - v["w"] / 2 - 8 + u * (v["w"] + 16)
            d.line([(sx, v["y0"] - 3), (sx, v["y0"] + v["n"] * 22 - 2)], fill=GREEN_HI)


def _hud(img, d, t, surge):
    # faint labels at the rim, on small dark plates so the rain passes behind
    d.rectangle([CX - 34, 17, CX + 34, 29], fill=(0, 0, 0))
    d.rectangle([CX - 18, 211, CX + 18, 223], fill=(0, 0, 0))
    _txt_c(img, 18, "+ CANTICLE +", (12, 80, 34), 9)
    bits = _S["bits"]
    _txt_c(img, 212, "%04X" % (bits & 0xFFFF), AMBER if surge > 0.5 else (12, 80, 34), 9)
    if surge > 0.05:
        k = min(1.0, surge)
        if int(t * 4) % 2 == 0 or surge < 0.9:
            _txt_c(img, 30, "DATA SURGE", tuple(int(c * k) for c in AMBER), 9)


def render(bezel, mask, now: float) -> Image.Image:
    if _session.fresh(now) or not _S:
        _reset(now)
        _ph.reset()
    t = now
    dt = max(0.0, min(0.1, t - _S["last"]))
    _S["last"] = t
    st = t - _S["t0"]

    # surge events: speed and density swell briefly
    if t >= _S["next_surge"] and _S["surge"] <= 0:
        _S["surge_t"] = t
        _S["surge"] = 0.01
        _S["next_surge"] = t + _rng.uniform(45, 80)
    surge = 0.0
    if "surge_t" in _S:
        u = t - _S["surge_t"]
        if u < 7.0:
            surge = min(1.0, u / 0.8) * min(1.0, (7.0 - u) / 1.5)
        _S["surge"] = surge
    speed_k = 1.0 + 0.75 * surge
    density = 0.55 + 0.3 * (0.5 + 0.5 * math.sin(st * 2 * math.pi / 75.0)) + 0.3 * surge
    sway = 7.0 * math.sin(st * 0.21) + 3.0 * math.sin(st * 0.53)
    _S["bits"] += int(dt * 900 * speed_k) + 1

    img = blank()
    d = ImageDraw.Draw(img)
    _draw_rain(img, t, dt, sway, speed_k, density)
    _update_verse(t)
    _draw_verse(img, d, t)
    _hud(img, d, t, surge)
    return _ph.compose(img)
