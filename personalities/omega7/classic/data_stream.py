"""Data Stream - a cogitator memory inspector reading the noospheric feed.

A hex dump scrolls through the eye: address column, six bytes per row and an
ASCII column, with the zero bytes dimmed.  The read rate wanders between
steady scanning, fast bursts, slow decode passes and seeks to new memory
segments.  Framed packets in the stream are picked out, bracketed and decoded
in a readout line; now and then a checksum fails, is flagged in amber, and is
corrected in place.  A throughput graph runs along the bottom.
"""

from __future__ import annotations

import math
import random

from PIL import Image, ImageDraw

from ..lore._common import CX, CY, Session, font
from ._phosphor import AMBER, GREEN, GREEN_DIM, GREEN_HI, GREEN_MID, RED, Phosphor, blank

NAME = "data_stream"

_rng = random.Random()
_session = Session()
_ph = Phosphor(decay=0.35, bloom=0.5, flicker=0.03)

_SZ = 9
_DP = 5          # hex digit pitch
_AP = 6          # ascii pitch
_NB = 6          # bytes per row
_RH = 11         # row height
_X_ADDR = 44
_X_BYTES = _X_ADDR + 4 * _DP + 8
_X_ASCII = _X_BYTES + _NB * 14 - 4 + 8
_Y_TOP, _Y_BOT = 46, 166
_DECODE_Y = 104

_WORDS = ["OMNI", "RITE", "MARS", "VOX7", "OIL", "COG", "LUX", "AVE", "DEUS", "MECH", "NOOS",
          "SKULL", "FORGE", "HAIL", "LOGIS", "RUNE", "AUSPEX", "SERVO", "MAGOS"]
_PKT_TYPES = [("NOOSPHERIC", 0x11), ("VOX-CAST", 0x22), ("AUSPEX", 0x31), ("RITE-DATA", 0x44),
              ("LOGIS", 0x52), ("SERVO-CMD", 0x63), ("TITHE", 0x70)]

_GLY: dict = {}
_TXT: dict = {}


def _glyph(ch):
    m = _GLY.get(ch)
    if m is None:
        f = font(_SZ)
        top = f.getbbox("0")[1]
        m = Image.new("L", (_AP, _RH), 0)
        w = f.getlength(ch)
        ImageDraw.Draw(m).text((max(0.0, (_DP - w) / 2) if ch in "0123456789ABCDEF" else (_AP - w) / 2, 1 - top),
                               ch, fill=255, font=f)
        _GLY[ch] = m
    return m


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


def _txt(img, x, y, s, col, size=_SZ):
    img.paste(col, (int(x), int(y)), _tmask(s, size))


def _txt_c(img, y, s, col, size=_SZ):
    m = _tmask(s, size)
    img.paste(col, (int(CX - (m.width - 2) / 2), int(y)), m)


def _scale(c, k):
    k = max(0.0, min(1.0, k))
    return (int(c[0] * k), int(c[1] * k), int(c[2] * k))


# --------------------------------------------------------------------- byte stream

_S: dict = {}


def _gen_bytes():
    """Refill the pending byte queue with either noise or a framed packet."""
    q = _S["queue"]
    if _rng.random() < 0.45:
        pid = _S["pkt_n"] = _S["pkt_n"] + 1
        if len(_S["pkts"]) > 120:
            for k in [k for k in _S["pkts"] if k < pid - 60]:
                del _S["pkts"][k]
        name, code = _rng.choice(_PKT_TYPES)
        payload = []
        for _ in range(_rng.randint(1, 2)):
            payload += [ord(c) for c in _rng.choice(_WORDS)]
            payload += [_rng.randint(0, 255) for _ in range(_rng.randint(0, 3))]
        body = [code, len(payload)] + payload
        crc = sum(body) & 0xFF
        frame = [0x7E] + body + [crc, 0x7E]
        _S["pkts"][pid] = {"name": name, "len": len(payload), "crc": crc, "code": code,
                           "text": "".join(chr(b) for b in payload if 65 <= b <= 90)}
        for b in frame:
            q.append((b, pid))
    else:
        for _ in range(_rng.randint(4, 14)):
            r = _rng.random()
            b = 0 if r < 0.35 else (0xFF if r < 0.42 else _rng.randint(0, 255))
            q.append((b, 0))


def _ascii(b):
    return chr(b) if (65 <= b <= 90 or 48 <= b <= 57) else "."


def _render_row(row):
    """Pre-render the row into L masks: address, bytes, zero bytes, ascii."""
    ma = Image.new("L", (4 * _DP + 2, _RH), 0)
    for i, ch in enumerate("%04X" % (row["addr"] & 0xFFFF)):
        ma.paste(_glyph(ch), (i * _DP, 0))
    mb = Image.new("L", (_NB * 14, _RH), 0)
    mz = Image.new("L", (_NB * 14, _RH), 0)
    ms = Image.new("L", (_NB * _AP, _RH), 0)
    for i, b in enumerate(row["b"]):
        tgt = mz if b == 0 else mb
        hx = "%02X" % b
        tgt.paste(_glyph(hx[0]), (i * 14, 0))
        tgt.paste(_glyph(hx[1]), (i * 14 + _DP, 0))
        ms.paste(_glyph(_ascii(b)), (i * _AP, 0))
    row["m"] = (ma, mb, mz, ms)


def _new_row():
    q = _S["queue"]
    while len(q) < _NB:
        _gen_bytes()
    bs, ps = [], []
    for _ in range(_NB):
        b, p = q.pop(0)
        bs.append(b)
        ps.append(p)
    row = {"addr": _S["addr"], "b": bs, "p": ps}
    _S["addr"] += _NB
    _render_row(row)
    return row


def _reset(t):
    _S.clear()
    _S.update(t0=t, last=t, queue=[], pkts={}, pkt_n=_rng.randint(100, 900),
              seg=_rng.randint(0x10, 0xEF), off=0.0, rate=5.0, phase="scan",
              phase_end=t + _rng.uniform(6, 10), hist=[0.0] * 34, hist_t=t,
              decode=None, err=None, next_err=t + _rng.uniform(14, 24),
              flash=None, seek_to=None, bytes_total=0)
    _S["addr"] = (_S["seg"] << 8) | (_rng.randint(0, 40) * _NB)
    _S["rows"] = [_new_row() for _ in range(14)]


def _pick_phase(t):
    r = _rng.random()
    st = t - _S["t0"]
    if r < 0.30:
        _S["phase"], dur = "decode", _rng.uniform(5, 8)
    elif r < 0.5:
        _S["phase"], dur = "burst", _rng.uniform(2.5, 4)
    elif r < 0.62 and st > 20:
        _S["phase"], dur = "seek", 2.6
        _S["seg"] = (_S["seg"] + _rng.randint(3, 60)) & 0xFF
        _S["seek_to"] = _S["seg"]
    else:
        _S["phase"], dur = "scan", _rng.uniform(5, 9)
    _S["phase_end"] = t + dur
    _S["decode"] = None


def _target_rate():
    p = _S["phase"]
    if _S["err"] is not None:
        return 0.0
    return {"scan": 4.5, "burst": 16.0, "decode": 0.7, "seek": 30.0}[p]


def _scroll(dt):
    _S["rate"] += (_target_rate() - _S["rate"]) * min(1.0, dt * 3.0)
    _S["off"] += _S["rate"] * dt * _RH
    _S["bytes_total"] += _S["rate"] * dt * _NB
    rows = _S["rows"]
    while _S["off"] >= _RH:
        _S["off"] -= _RH
        rows.pop(0)
        if _S["phase"] == "seek" and _S["seek_to"] is not None and _S["rate"] > 20:
            _S["addr"] = (_S["seek_to"] << 8) | (_rng.randint(0, 30) * _NB)
            _S["seek_to"] = None
        rows.append(_new_row())


def _row_y(i):
    return _Y_TOP + i * _RH - _S["off"]


def _visible_pkt(t):
    """Find a packet whose frame is entirely on screen in the upper-middle rows."""
    rows = _S["rows"]
    seen = {}
    for i, r in enumerate(rows):
        y = _row_y(i)
        for j, p in enumerate(r["p"]):
            if p:
                seen.setdefault(p, []).append((i, j, y))
    best = None
    for p, cells in seen.items():
        ys = [c[2] for c in cells]
        info = _S["pkts"].get(p)
        if info is None or min(ys) < _Y_TOP + 8 or max(ys) > _Y_BOT - 14:
            continue
        # full frame: header + code + len + payload + crc + trailer
        if len(cells) != info["len"] + 5:
            continue
        if best is None or abs(ys[0] - 70) < abs(best[1][0][2] - 70):
            best = (p, cells)
    return best


# --------------------------------------------------------------------- drawing

def _draw_byte(img, d, i, j, col, box=None):
    row = _S["rows"][i]
    y = int(_row_y(i))
    x = _X_BYTES + j * 14
    d.rectangle([x - 1, y, x + 2 * _DP, y + _RH - 1], fill=box or (0, 0, 0))
    hx = "%02X" % row["b"][j]
    img.paste(col, (x, y), _glyph(hx[0]))
    img.paste(col, (x + _DP, y), _glyph(hx[1]))
    xa = _X_ASCII + j * _AP
    d.rectangle([xa, y, xa + _AP - 1, y + _RH - 1], fill=box or (0, 0, 0))
    img.paste(col, (xa, y), _glyph(_ascii(row["b"][j])))


def _draw_rows(img, d, t):
    # decode cursor band
    d.rectangle([_X_ADDR - 6, _DECODE_Y - 1, _X_ASCII + _NB * _AP + 4, _DECODE_Y + _RH - 1], fill=(0, 22, 9))
    for i, row in enumerate(_S["rows"]):
        y = _row_y(i)
        if y < _Y_TOP - _RH or y > _Y_BOT:
            continue
        k = min(1.0, (y - (_Y_TOP - _RH)) / 14.0, (_Y_BOT - y) / 14.0)
        if k <= 0:
            continue
        near = max(0.0, 1.0 - abs(y - _DECODE_Y) / 30.0)
        k *= 0.72 + 0.28 * near
        ma, mb, mz, ms = row["m"]
        yi = int(y)
        img.paste(_scale(GREEN_MID, k), (_X_ADDR, yi), ma)
        img.paste(_scale(GREEN, k), (_X_BYTES, yi), mb)
        img.paste(_scale((12, 90, 36), k), (_X_BYTES, yi), mz)
        img.paste(_scale((30, 180, 80), k), (_X_ASCII, yi), ms)
    # column rules
    d.line([(_X_BYTES - 5, _Y_TOP - 4), (_X_BYTES - 5, _Y_BOT + 2)], fill=(6, 50, 20))
    d.line([(_X_ASCII - 5, _Y_TOP - 4), (_X_ASCII - 5, _Y_BOT + 2)], fill=(6, 50, 20))
    d.line([(_X_ADDR - 4, _Y_TOP - 5), (_X_ASCII + _NB * _AP + 2, _Y_TOP - 5)], fill=(6, 50, 20))
    d.line([(_X_ADDR - 4, _Y_BOT + 3), (_X_ASCII + _NB * _AP + 2, _Y_BOT + 3)], fill=(6, 50, 20))
    # a marching read head on the cursor band
    hx = _X_ADDR - 10
    d.polygon([(hx, _DECODE_Y + 1), (hx + 4, _DECODE_Y + 5), (hx, _DECODE_Y + 9)], fill=GREEN)


def _draw_decode(img, d, t):
    dec = _S["decode"]
    if dec is None:
        found = _visible_pkt(t)
        if found:
            _S["decode"] = dec = {"pid": found[0], "t0": t}
        else:
            return None
    pid = dec["pid"]
    info = _S["pkts"].get(pid)
    cells = []
    for i, r in enumerate(_S["rows"]):
        for j, p in enumerate(r["p"]):
            if p == pid:
                cells.append((i, j))
    if not cells or info is None:
        _S["decode"] = None
        return None
    u = t - dec["t0"]
    n_lit = int(u * 14)
    for c, (i, j) in enumerate(cells):
        if c > n_lit:
            break
        hot = c == n_lit or c in (0, len(cells) - 1)
        _draw_byte(img, d, i, j, GREEN_HI if hot else (120, 255, 150), box=(0, 40, 16))
    # brackets at frame start and end
    (i0, j0), (i1, j1) = cells[0], cells[-1]
    y0, y1 = int(_row_y(i0)), int(_row_y(i1))
    xa = _X_BYTES + j0 * 14 - 3
    d.line([(xa, y0), (xa, y0 + _RH - 1)], fill=GREEN_HI)
    d.line([(xa, y0), (xa + 3, y0)], fill=GREEN_HI)
    d.line([(xa, y0 + _RH - 1), (xa + 3, y0 + _RH - 1)], fill=GREEN_HI)
    xb = _X_BYTES + j1 * 14 + 2 * _DP + 2
    if n_lit >= len(cells):
        d.line([(xb, y1), (xb, y1 + _RH - 1)], fill=GREEN_HI)
        d.line([(xb - 3, y1), (xb, y1)], fill=GREEN_HI)
        d.line([(xb - 3, y1 + _RH - 1), (xb, y1 + _RH - 1)], fill=GREEN_HI)
    if n_lit < len(cells):
        return ("DECODING PKT %04d" % (pid % 10000), GREEN_MID)
    if u > 5.5 and _S["phase"] != "decode":
        _S["decode"] = None
    if info["text"] and int((u - len(cells) / 14.0) / 1.6) % 2 == 1:
        return ("PAYLOAD \"%s\"" % info["text"][:14], GREEN_HI)
    return ("%s  L%02d  CRC %02X OK" % (info["name"], info["len"], info["crc"]), GREEN)


def _update_err(t):
    err = _S["err"]
    if err is None:
        if t >= _S["next_err"] and _S["phase"] in ("scan", "decode"):
            i = _rng.randint(4, 7)
            j = _rng.randrange(_NB)
            row = _S["rows"][i]
            _S["err"] = {"t0": t, "row": row, "j": j, "good": row["b"][j],
                         "addr": row["addr"] + j}
            row["b"][j] = (row["b"][j] ^ (1 << _rng.randint(0, 7))) & 0xFF
            _render_row(row)
            _S["next_err"] = t + _rng.uniform(18, 32)
        return
    u = t - err["t0"]
    if u >= 1.6 and not err.get("fixed"):
        err["fixed"] = True
        err["row"]["b"][err["j"]] = err["good"]
        _render_row(err["row"])
    if u >= 3.2:
        _S["err"] = None


def _draw_err(img, d, t):
    err = _S["err"]
    if err is None:
        return None
    try:
        i = _S["rows"].index(err["row"])
    except ValueError:
        return None
    u = t - err["t0"]
    j = err["j"]
    y = int(_row_y(i))
    if not err.get("fixed"):
        on = int(u * 6) % 2 == 0
        _draw_byte(img, d, i, j, AMBER if on else (160, 100, 20), box=(40, 20, 0))
        x = _X_BYTES + j * 14
        d.rectangle([x - 3, y - 2, x + 2 * _DP + 2, y + _RH + 1], outline=AMBER)
        d.polygon([(_X_ADDR - 12, y + 1), (_X_ADDR - 6, y + 5), (_X_ADDR - 12, y + 9)], fill=RED)
        return ("CRC FAIL @%04X  PARITY" % (err["addr"] & 0xFFFF), AMBER)
    k = min(1.0, (u - 1.6) / 1.0)
    col = tuple(int(GREEN_HI[c] + (GREEN[c] - GREEN_HI[c]) * k) for c in range(3))
    _draw_byte(img, d, i, j, col, box=(0, 50, 20) if u < 2.2 else None)
    return ("CORRECTED @%04X  BIT-FIX" % (err["addr"] & 0xFFFF), GREEN_HI)


def _draw_hud(img, d, t, status):
    ph = _S["phase"]
    head = {"scan": "READ", "burst": "BURST", "decode": "DECODE", "seek": "SEEK"}[ph]
    _txt_c(img, 18, "MEM-INSPECT", GREEN_MID)
    seg = "SEG %02X00" % _S["seg"]
    col = AMBER if ph == "seek" and int(t * 5) % 2 else GREEN
    _txt_c(img, 29, "%s  %s" % (seg, head), col)
    # status / decode readout
    if status:
        _txt_c(img, 171, status[0], status[1])
    else:
        _txt_c(img, 171, "PKTS %d  RD %06X" % (_S["pkt_n"] % 10000, int(_S["bytes_total"]) & 0xFFFFFF), (12, 100, 40))
    # throughput graph
    h = _S["hist"]
    x0 = CX - len(h) * 3 // 2 - 14
    base = 203
    d.line([(x0 - 2, base + 1), (x0 + len(h) * 3, base + 1)], fill=GREEN_DIM)
    mx = max(10.0, max(h))
    for k, v in enumerate(h):
        bh = int(v / mx * 14)
        if bh > 0:
            c = GREEN if k == len(h) - 1 else (20, 140, 58)
            d.line([(x0 + k * 3, base - bh), (x0 + k * 3, base)], fill=c)
    _txt(img, x0 + len(h) * 3 + 3, base - 10, "%dK" % int(h[-1]), GREEN_MID)


def render(bezel, mask, now: float) -> Image.Image:
    if _session.fresh(now) or not _S:
        _reset(now)
        _ph.reset()
    t = now
    dt = max(0.0, min(0.1, t - _S["last"]))
    _S["last"] = t
    if t >= _S["phase_end"] and _S["err"] is None:
        _pick_phase(t)
    _scroll(dt)
    _update_err(t)
    if t - _S["hist_t"] >= 0.2:
        _S["hist_t"] = t
        v = _S["rate"] * _NB * 5.0 * (0.8 + 0.4 * _rng.random()) + _rng.uniform(0, 8)
        _S["hist"] = _S["hist"][1:] + [v]

    img = blank()
    d = ImageDraw.Draw(img)
    _draw_rows(img, d, t)
    status = None
    if _S["phase"] == "decode" or _S["decode"] is not None:
        status = _draw_decode(img, d, t)
    es = _draw_err(img, d, t)
    if es:
        status = es
    _draw_hud(img, d, t, status)
    return _ph.compose(img)
