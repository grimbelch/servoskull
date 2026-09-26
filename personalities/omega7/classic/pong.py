"""COG-PONG – Machine Spirit vs Servitor, green-phosphor arcade edition.

Two cogitator paddles play matches to five points. The ball carries spin
(English) from moving paddles, rallies speed up, points trigger an exit burst
and a banner, and each match ends with a winner plaque before a new one starts.
"""

from __future__ import annotations

import math
import random
from collections import deque

from PIL import Image, ImageDraw

from ..lore._common import CX, CY, Session, font, scale
from ._phosphor import (AMBER, GREEN, GREEN_DIM, GREEN_FAINT, GREEN_HI, GREEN_MID, RED,
                        Phosphor, blank)

NAME = "pong"

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
    return m.width


# ------------------------------------------------------------- state ---
_rng = random.Random()
_session = Session()
_ph = Phosphor(decay=0.62, bloom=0.65)

LX, RX = 44.0, 196.0          # paddle faces
TOP, BOT = 60.0, 180.0        # walls
PH = 13.0                     # paddle half height
WIN = 5
NAMES = ("MACHINE SPIRIT", "SERVITOR")
SHORT = ("M.SPIRIT", "SERVITOR")

_S = {}


def _reset():
    _S.clear()
    _S.update(
        score=[0, 0], match=1, serve_side=_rng.choice((0, 1)),
        paddles=[{"y": CY, "v": 0.0, "target": CY, "err": 0.0, "flash": 0.0, "skill": 0.9},
                 {"y": CY, "v": 0.0, "target": CY, "err": 0.0, "flash": 0.0, "skill": 0.86}],
        ball=None, trail=deque(maxlen=14), sparks=[], rings=[],
        state="intro", t_state=0.0, rally=0, best_rally=0, banner="", banner_col=GREEN_HI,
        winner=None, last=None, flash=0.0, total_points=0,
    )
    _ph.reset()


def _set_state(st, t):
    _S["state"] = st
    _S["t_state"] = t


def _serve():
    side = _S["serve_side"]
    sp = 135.0
    ang = _rng.uniform(-0.45, 0.45)
    dx = 1 if side == 0 else -1
    _S["ball"] = {"x": CX, "y": _rng.uniform(TOP + 20, BOT - 20), "vx": dx * sp * math.cos(ang),
                  "vy": sp * math.sin(ang), "spin": 0.0, "speed": sp, "rot": 0.0}
    _S["trail"].clear()
    _S["rally"] = 0
    for p in _S["paddles"]:
        p["err"] = 0.0


def _predict(ball, x_target):
    """Where the ball crosses x_target, reflecting off walls (spin ignored)."""
    if ball["vx"] == 0:
        return ball["y"]
    t = (x_target - ball["x"]) / ball["vx"]
    if t < 0:
        return CY
    y = ball["y"] + ball["vy"] * t
    span = BOT - TOP - 6
    rel = (y - TOP - 3) % (2 * span)
    if rel > span:
        rel = 2 * span - rel
    return TOP + 3 + rel


def _spark_burst(x, y, n, spd, direction=None, col=GREEN_HI):
    for _ in range(n):
        a = _rng.uniform(0, 2 * math.pi) if direction is None else direction + _rng.uniform(-1.1, 1.1)
        s = _rng.uniform(0.3, 1.0) * spd
        _S["sparks"].append([x, y, math.cos(a) * s, math.sin(a) * s, 1.0, col])


def _update(dt, t):
    st = _S["state"]
    ts = t - _S["t_state"]
    ball = _S["ball"]

    # paddles always move toward their target
    for i, p in enumerate(_S["paddles"]):
        if ball is not None and st == "play":
            face = LX if i == 0 else RX
            coming = (ball["vx"] < 0) if i == 0 else (ball["vx"] > 0)
            if coming:
                pred = _predict(ball, face)
                # reaction error grows with ball speed and spin
                if p["err"] == 0.0:
                    miss_k = (ball["speed"] - 120) / 180.0 + abs(ball["spin"]) / 90.0
                    p["err"] = _rng.gauss(0, 4 + 16 * max(0.0, miss_k) * (1.2 - p["skill"]) * 3)
                    if abs(p["err"]) < 0.01:
                        p["err"] = 0.01
                    # aim for an off-centre hit to add angle / English
                    p["aim"] = _rng.uniform(-8, 8)
                p["target"] = pred + p["err"] + p.get("aim", 0.0)
            else:
                p["err"] = 0.0
                p["target"] = CY + (ball["y"] - CY) * 0.3
        else:
            p["target"] = CY
        maxv = 150.0 + 60.0 * p["skill"]
        dv = max(-maxv, min(maxv, (p["target"] - p["y"]) * 9.0))
        p["v"] += (dv - p["v"]) * min(1.0, dt * 12)
        p["y"] = max(TOP + PH, min(BOT - PH, p["y"] + p["v"] * dt))
        p["flash"] = max(0.0, p["flash"] - dt * 3)

    if st == "intro":
        if ts > 3.0:
            _set_state("serve", t)
    elif st == "serve":
        if ball is None or ts < 0.05:
            _serve()
        if ts > 1.6:
            _set_state("play", t)
    elif st == "play":
        _step_ball(dt, t)
    elif st == "point":
        if ts > 2.4:
            if max(_S["score"]) >= WIN:
                _S["winner"] = 0 if _S["score"][0] > _S["score"][1] else 1
                _set_state("winner", t)
            else:
                _set_state("serve", t)
                _S["ball"] = None
    elif st == "winner":
        if ts > 7.0:
            _S["score"] = [0, 0]
            _S["match"] += 1
            _S["winner"] = None
            _S["paddles"][0]["skill"] = _rng.uniform(0.82, 0.95)
            _S["paddles"][1]["skill"] = _rng.uniform(0.82, 0.95)
            _set_state("intro", t)
            _S["ball"] = None

    # particles
    keep = []
    for sp in _S["sparks"]:
        sp[0] += sp[2] * dt
        sp[1] += sp[3] * dt
        sp[2] *= 0.94
        sp[3] *= 0.94
        sp[4] -= dt * 1.6
        if sp[4] > 0:
            keep.append(sp)
    _S["sparks"] = keep
    _S["rings"] = [r for r in _S["rings"] if t - r[2] < 1.2]
    _S["flash"] = max(0.0, _S["flash"] - dt * 2.5)


def _step_ball(dt, t):
    b = _S["ball"]
    sub = 3
    h = dt / sub
    for _ in range(sub):
        # spin (English) curves the path and slowly bleeds off
        b["vy"] += b["spin"] * 2.2 * h
        b["spin"] *= (1 - 0.5 * h)
        b["rot"] += b["spin"] * h * 0.2
        b["x"] += b["vx"] * h
        b["y"] += b["vy"] * h
        if b["y"] < TOP + 3:
            b["y"] = TOP + 3
            b["vy"] = abs(b["vy"])
            b["spin"] *= -0.6
            _spark_burst(b["x"], TOP, 4, 50, math.pi / 2, GREEN)
        elif b["y"] > BOT - 3:
            b["y"] = BOT - 3
            b["vy"] = -abs(b["vy"])
            b["spin"] *= -0.6
            _spark_burst(b["x"], BOT, 4, 50, -math.pi / 2, GREEN)

        for i, face in ((0, LX), (1, RX)):
            p = _S["paddles"][i]
            moving_in = b["vx"] < 0 if i == 0 else b["vx"] > 0
            crossed = (b["x"] <= face + 3) if i == 0 else (b["x"] >= face - 3)
            if moving_in and crossed:
                off = b["y"] - p["y"]
                if abs(off) <= PH + 3:
                    _S["rally"] += 1
                    _S["best_rally"] = max(_S["best_rally"], _S["rally"])
                    b["speed"] = min(330.0, b["speed"] * 1.06)
                    ang = (off / (PH + 3)) * 0.85
                    dirx = 1 if i == 0 else -1
                    b["vx"] = dirx * b["speed"] * math.cos(ang)
                    b["vy"] = b["speed"] * math.sin(ang)
                    b["spin"] = p["v"] * 0.35
                    b["x"] = face + 3 * dirx
                    p["flash"] = 1.0
                    _spark_burst(face, b["y"], 7, 90, 0 if i == 0 else math.pi, GREEN_HI)
                    if _S["rally"] in (10, 20, 30):
                        _S["flash"] = 1.0
                    p["err"] = 0.0
                elif (b["x"] < face - 10) if i == 0 else (b["x"] > face + 10):
                    pass
        # out of play
        if b["x"] < LX - 26 or b["x"] > RX + 26:
            scorer = 1 if b["x"] < CX else 0
            _S["score"][scorer] += 1
            _S["total_points"] += 1
            _S["serve_side"] = 1 - scorer
            ex = LX - 20 if scorer == 1 else RX + 20
            _S["rings"].append((ex, b["y"], t))
            _spark_burst(ex, b["y"], 22, 120, None, GREEN_HI)
            _S["banner"] = f"POINT {SHORT[scorer]}"
            _S["banner_col"] = GREEN_HI
            _S["last"] = scorer
            _S["ball"] = None
            _S["trail"].clear()
            _set_state("point", t)
            return
    _S["trail"].append((b["x"], b["y"]))


# ------------------------------------------------------------- drawing ---
def _draw_court(d, t):
    # wall rails with tick marks
    for y in (TOP, BOT):
        d.line([(LX - 14, y), (RX + 14, y)], fill=GREEN_MID)
        for x in range(int(LX), int(RX) + 1, 8):
            d.line([(x, y + (2 if y == TOP else -2)), (x, y)], fill=GREEN_DIM)
    # centre net
    for y in range(int(TOP) + 4, int(BOT) - 2, 8):
        d.line([(CX, y), (CX, y + 3)], fill=GREEN_DIM)
    # corner brackets beyond goal lines
    for x, sgn in ((LX - 20, 1), (RX + 20, -1)):
        d.line([(x, TOP + 4), (x, TOP + 14)], fill=GREEN_FAINT)
        d.line([(x, BOT - 14), (x, BOT - 4)], fill=GREEN_FAINT)
    # centre circle
    d.ellipse([CX - 16, CY - 16, CX + 16, CY + 16], outline=GREEN_FAINT)


def _draw_hud(d, t):
    s0, s1 = _S["score"]
    st = _S["state"]
    hot = _S["last"] if st == "point" else None
    c0 = AMBER if hot == 0 and int(t * 6) % 2 == 0 else GREEN_HI
    c1 = AMBER if hot == 1 and int(t * 6) % 2 == 0 else GREEN_HI
    _txt(d, CX - 14, 20, f"{s0}", c0, 16, "r")
    _txt(d, CX + 14, 20, f"{s1}", c1, 16, "l")
    _txt(d, CX, 23, ":", GREEN_MID, 12, "c")
    _txt(d, CX - 8, 42, SHORT[0], GREEN_MID, 9, "r")
    _txt(d, CX + 8, 42, SHORT[1], GREEN_MID, 9, "l")
    # serve / possession pips
    for i in range(WIN):
        x0 = CX - 58 + i * 7
        d.rectangle([x0, 54, x0 + 4, 55], fill=GREEN_HI if i < s0 else GREEN_DIM)
        x1 = CX + 54 - i * 7
        d.rectangle([x1, 54, x1 + 4, 55], fill=GREEN_HI if i < s1 else GREEN_DIM)

    b = _S["ball"]
    spd = b["speed"] if b else 0.0
    rally = _S["rally"]
    _txt(d, CX - 50, 186, f"RALLY {rally:02d}", AMBER if rally >= 10 else GREEN_MID, 9, "l")
    _txt(d, CX + 50, 186, f"V {spd / 60:4.1f}", GREEN_MID, 9, "r")
    # speed bar
    frac = max(0.0, min(1.0, (spd - 120) / 210))
    d.rectangle([CX - 40, 199, CX + 40, 201], outline=GREEN_DIM)
    if frac > 0:
        d.rectangle([CX - 40, 199, CX - 40 + 80 * frac, 201], fill=AMBER if frac > 0.8 else GREEN)
    _txt(d, CX, 205, f"MATCH {_S['match']:02d}  BEST {_S['best_rally']:02d}", GREEN_DIM, 9, "c")


def _banner(d, text, col, y=CY - 9, pulse=1.0, size=12):
    m = _mask(text, size)
    w = m.width + 14
    x0, x1 = CX - w / 2, CX + w / 2
    d.rectangle([x0, y - 4, x1, y + m.height + 3], fill=(0, 0, 0))
    k = 0.55 + 0.45 * pulse
    for (xa, sgn) in ((x0, 1), (x1, -1)):
        d.line([(xa, y - 4), (xa + 6 * sgn, y - 4)], fill=scale(col, k))
        d.line([(xa, y + m.height + 3), (xa + 6 * sgn, y + m.height + 3)], fill=scale(col, k))
        d.line([(xa, y - 4), (xa, y + m.height + 3)], fill=scale(col, k))
    d.bitmap((int(CX - m.width / 2), int(y)), m, fill=scale(col, k))


def _draw(d, t):
    st = _S["state"]
    ts = t - _S["t_state"]
    _draw_court(d, t)

    # paddles
    for i, face in ((0, LX), (1, RX)):
        p = _S["paddles"][i]
        x0 = face - 4 if i == 0 else face
        x1 = face if i == 0 else face + 4
        col = GREEN_HI if p["flash"] > 0.3 else GREEN
        d.rectangle([x0, p["y"] - PH, x1, p["y"] + PH], fill=col)
        # motion ghost echo
        if abs(p["v"]) > 30:
            gy = p["y"] - p["v"] * 0.05
            d.rectangle([x0, gy - PH, x1, gy + PH], outline=GREEN_DIM)
        # target indicator tick
        tx = x0 - 5 if i == 0 else x1 + 3
        d.line([(tx, p["target"]), (tx + 2, p["target"])], fill=GREEN_DIM)

    # predicted trajectory (the receiving cogitator's computation), dotted
    b = _S["ball"]
    if b is not None and st == "play" and abs(b["vx"]) > 1:
        face = RX - 3 if b["vx"] > 0 else LX + 3
        x, y, vx, vy = b["x"], b["y"], b["vx"], b["vy"]
        step = 7.0 / math.hypot(vx, vy)
        k = 0
        while (vx > 0 and x < face) or (vx < 0 and x > face):
            x += vx * step
            y += vy * step
            if y < TOP + 3:
                y = 2 * (TOP + 3) - y
                vy = -vy
            elif y > BOT - 3:
                y = 2 * (BOT - 3) - y
                vy = -vy
            k += 1
            if k > 3:
                d.point((x, y), fill=GREEN_DIM)
            if k > 60:
                break
        d.line([(x - 2, y), (x + 2, y)], fill=GREEN_MID)
        d.line([(x, y - 2), (x, y + 2)], fill=GREEN_MID)

    # ball trail
    tr = list(_S["trail"])
    n = len(tr)
    for k in range(1, n):
        c = scale(GREEN, 0.15 + 0.6 * k / n)
        d.line([tr[k - 1], tr[k]], fill=c, width=1 if k < n * 0.6 else 2)
    if b is not None:
        bx, by = b["x"], b["y"]
        blink = st != "serve" or int(ts * 8) % 2 == 0
        if blink:
            d.rectangle([bx - 2, by - 2, bx + 2, by + 2], fill=GREEN_HI)
            if abs(b["spin"]) > 10:
                # spin indicator: orbiting tick
                a = b["rot"] * 6
                d.point((bx + 5 * math.cos(a), by + 5 * math.sin(a)), fill=AMBER)
                d.point((bx - 5 * math.cos(a), by - 5 * math.sin(a)), fill=GREEN_MID)

    for sp in _S["sparks"]:
        d.point((sp[0], sp[1]), fill=scale(sp[5], sp[4]))
    for (x, y, t0) in _S["rings"]:
        r = (t - t0) * 60
        d.ellipse([x - r, y - r, x + r, y + r], outline=scale(GREEN_HI, 1 - (t - t0) / 1.2))

    if st == "intro":
        _banner(d, f"MATCH {_S['match']:02d}", GREEN_HI, CY - 28, 1.0, 12)
        _txt(d, CX, CY - 6, "MACHINE SPIRIT", GREEN, 9, "c")
        _txt(d, CX, CY + 6, "VS", AMBER, 9, "c")
        _txt(d, CX, CY + 18, "SERVITOR", GREEN, 9, "c")
    elif st == "serve":
        side = _S["serve_side"]
        _txt(d, CX, CY + 36, f"SERVE {SHORT[side]}", GREEN_MID, 9, "c")
        # countdown pips
        for k in range(3):
            on = ts > k * 0.5
            d.rectangle([CX - 10 + k * 8, CY + 48, CX - 6 + k * 8, CY + 50], fill=GREEN_HI if on else GREEN_DIM)
    elif st == "point":
        _banner(d, _S["banner"], _S["banner_col"], CY - 30, 0.5 + 0.5 * math.sin(ts * 12))
    elif st == "winner":
        w = _S["winner"]
        pulse = 0.5 + 0.5 * math.sin(ts * 5)
        _banner(d, NAMES[w], AMBER, CY - 34, pulse, 12)
        _txt(d, CX, CY - 14, "VICTORIOUS", GREEN_HI, 12, "c")
        s0, s1 = _S["score"]
        _txt(d, CX, CY + 4, f"FINAL {s0} - {s1}", GREEN, 9, "c")
        _txt(d, CX, CY + 16, f"LONGEST RALLY {_S['best_rally']:02d}", GREEN_MID, 9, "c")
        if ts > 4.5:
            _txt(d, CX, CY + 30, "RE-SANCTIFYING MATCH", GREEN_DIM if int(ts * 4) % 2 else GREEN_MID, 9, "c")
        # celebratory sparks from winner's side
        if _rng.random() < 0.5:
            x = LX if w == 0 else RX
            _spark_burst(x, _rng.uniform(TOP, BOT), 2, 80, 0 if w == 0 else math.pi, GREEN_HI)
    if _S["flash"] > 0 and _S["ball"] is not None:
        _txt(d, CX, TOP + 6, f"RALLY x{_S['rally']}", scale(AMBER, _S["flash"]), 9, "c")

    _draw_hud(d, t)


def render(bezel, mask, now: float) -> Image.Image:
    if _session.fresh(now) or not _S:
        _reset()
        _S["prev"] = now
        _S["t_state"] = now
    dt = max(0.0, min(0.1, now - _S["prev"]))
    _S["prev"] = now
    _update(dt, now)
    img = blank()
    d = ImageDraw.Draw(img)
    _draw(d, now)
    return _ph.compose(img)
