"""Patrol Vector – the skull's patrol route through the nave.

A cathedral floorplan schematic; the skull's marker walks its waypoint loop,
leaving a fading trail, and pings each waypoint with a patrol report.
"""

from __future__ import annotations

import math
import random

from PIL import Image, ImageDraw

from ._common import Session, font, text_center

NAME = "patrol_vector"

_session = Session()


def _text_c(d, cx, y, text, fnt, fill):
    """Draw text horizontally centred on cx."""
    d.text((cx - d.textlength(text, font=fnt) / 2, y), text, fill=fill, font=fnt)


_PATROL_WAYPOINTS = [(120, 196), (120, 150), (74, 120), (120, 120), (166, 120), (120, 90), (120, 52), (150, 150), (90, 150)]
_PATROL_EVENTS = ["NO HERETICS DETECTED", "CANDLE LOW · SECTOR IV", "SERVITOR IDLE · REPORTED",
                  "DUST LEVELS ACCEPTABLE", "PILGRIM COUNT: 3", "RELIQUARY SEALED", "VOX RELAY NOMINAL",
                  "LUMEN FLICKER · SECTOR II", "INCENSE STOCK 62%", "ALL DOORS WARDED"]
_patrol_state = {"bg": None, "seg": 0, "t": 0.0, "pause": 0.0, "msg": "", "ping": 0.0, "trail": []}


def _patrol_background():
    img = Image.new("RGB", (240, 240), (0, 8, 8))
    d = ImageDraw.Draw(img)
    for x in range(0, 240, 16):
        d.line([(x, 0), (x, 240)], fill=(0, 22, 22))
        d.line([(0, x), (240, x)], fill=(0, 22, 22))
    wall = (0, 140, 130)
    d.line([(100, 212), (100, 134), (58, 134), (58, 106), (100, 106), (100, 72)], fill=wall, width=2)
    d.line([(140, 212), (140, 134), (182, 134), (182, 106), (140, 106), (140, 72)], fill=wall, width=2)
    d.line([(100, 212), (140, 212)], fill=wall, width=2)
    d.arc([100, 32, 140, 112], 180, 360, fill=wall, width=2)
    for y in range(146, 206, 16):
        for x in (110, 130):
            d.rectangle([x - 2, y - 2, x + 2, y + 2], fill=(0, 90, 80))
    d.rectangle([114, 44, 126, 56], outline=(180, 150, 40))
    d.text((106, 60), "ALTAR", fill=(120, 100, 30), font=font(7))
    return img


def render(bezel, mask, now):
    if _session.fresh(now):
        _patrol_state.update(seg=0, t=0.0, pause=0.0, msg="", ping=-99.0, trail=[])
    st = _patrol_state
    if st["bg"] is None:
        st["bg"] = _patrol_background()
    wps = _PATROL_WAYPOINTS
    a, b = wps[st["seg"]], wps[(st["seg"] + 1) % len(wps)]
    if now < st["pause"]:
        pos = a
    else:
        seg_len = max(1.0, math.hypot(b[0] - a[0], b[1] - a[1]))
        st["t"] += 1.2 / seg_len
        if st["t"] >= 1.0:
            st["t"], st["seg"] = 0.0, (st["seg"] + 1) % len(wps)
            st["pause"], st["ping"] = now + 2.2, now
            st["msg"] = random.choice(_PATROL_EVENTS)
            a = b
        pos = (a[0] + (b[0] - a[0]) * st["t"], a[1] + (b[1] - a[1]) * st["t"])
    st["trail"].append(pos)
    st["trail"] = st["trail"][-120:]

    img = st["bg"].copy()
    d = ImageDraw.Draw(img)
    for i in range(len(wps)):
        p, q = wps[i], wps[(i + 1) % len(wps)]
        for s in range(0, 10, 2):
            d.line([(p[0] + (q[0] - p[0]) * s / 10, p[1] + (q[1] - p[1]) * s / 10),
                    (p[0] + (q[0] - p[0]) * (s + 1) / 10, p[1] + (q[1] - p[1]) * (s + 1) / 10)], fill=(0, 60, 55))
        d.ellipse([p[0] - 2, p[1] - 2, p[0] + 2, p[1] + 2], outline=(0, 160, 140))
    for i, (x, y) in enumerate(st["trail"]):
        v = i / len(st["trail"])
        d.point((x, y), fill=(int(200 * v), int(40 * v), 0))

    age = now - st["ping"]
    if age < 1.5:
        r = age * 40
        c = int(220 * (1 - age / 1.5))
        d.ellipse([pos[0] - r, pos[1] - r, pos[0] + r, pos[1] + r], outline=(c // 3, c, c))
    x, y = pos
    d.ellipse([x - 5, y - 5, x + 5, y + 5], fill=(220, 210, 180))
    d.ellipse([x - 3, y - 2, x - 1, y], fill=(10, 0, 0))
    d.ellipse([x + 1, y - 2, x + 3, y], fill=(255, 30, 20))

    f = font(8)
    _text_c(d, 120, 18, "PATROL VECTOR · NAVE", f, (0, 200, 180))
    text_center(d, 30, f"WAYPOINT {st['seg'] + 1}/{len(wps)}", (0, 140, 120), 8)
    if st["msg"] and now - st["ping"] < 6:
        _text_c(d, 120, 216, st["msg"], f, (220, 180, 60))
    return img
