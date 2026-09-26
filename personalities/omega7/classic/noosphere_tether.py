"""Noosphere Tether - a live Noosphere data-network map.

Servo-skulls, cogitators and forge nodes hang in a slowly turning 3D cloud,
tethered to the Omega-7 relay. Link brightness shows bandwidth, which drifts.
Data packets route along lowest-cost paths; when a node drops out its links go
dark, in-flight packets re-route (amber flash) and the signal meter sags until
the node is restored. A tracking bracket cycles through nodes with an info card.
"""

from __future__ import annotations

import heapq
import math
import random

import numpy as np
from PIL import Image, ImageDraw

from ..lore._common import CX, CY, Session, font
from ._phosphor import AMBER, GREEN, GREEN_DIM, GREEN_FAINT, GREEN_HI, GREEN_MID, RED, Phosphor, blank

NAME = "noosphere_tether"

_rng = random.Random()
_session = Session()
_ph = Phosphor(decay=0.7, bloom=0.55)
_S: dict = {}

FOV, CAM = 310.0, 340.0
TYPES = [("SKULL", "SERVO-SKULL"), ("COG", "COGITATOR"), ("FORGE", "FORGE NODE")]

_TXT: dict = {}


def _tsprite(text, size):
    key = (text, size)
    m = _TXT.get(key)
    if m is None:
        if len(_TXT) > 250:
            _TXT.clear()
        f = font(size)
        _, _, r, b = f.getbbox(text)
        im = Image.new("L", (max(1, int(r)) + 2, max(1, int(b)) + 2), 0)
        ImageDraw.Draw(im).text((0, 0), text, fill=255, font=f)
        m = _TXT[key] = (im, f.getlength(text))
    return m


def _text(img, x, y, text, fill, size=11, anchor="c"):
    m, w = _tsprite(text, size)
    if anchor == "c":
        x = x - w / 2
    elif anchor == "r":
        x = x - w
    img.paste(fill, (int(x), int(y)), m)


def _col(c, k):
    k = max(0.0, k)
    return (min(255, int(c[0] * k)), min(255, int(c[1] * k)), min(255, int(c[2] * k)))


def _build_bg():
    img = blank()
    d = ImageDraw.Draw(img)
    for k in range(60):
        a = k * math.pi / 30
        r0 = 104 if k % 5 else 100
        d.line([(CX + r0 * math.cos(a), CY + r0 * math.sin(a)),
                (CX + 108 * math.cos(a), CY + 108 * math.sin(a))], fill=GREEN_DIM if k % 5 else GREEN_MID)
    d.ellipse([CX - 96, CY - 96, CX + 96, CY + 96], outline=GREEN_FAINT)
    _text(img, CX, 16, "NOOSPHERE TETHER", GREEN_MID, 10)
    _text(img, 18, 90, "SIG", GREEN_DIM, 9, "l")
    return img


def _reset():
    _S.clear()
    _S["bg"] = _build_bg()
    _S["last"] = None
    nodes = [{"p": (0.0, 0.0, 0.0), "type": "HUB", "name": "OMEGA-7 RELAY", "code": "O7"}]
    counts = {"SKULL": 0, "COG": 0, "FORGE": 0}
    tries = 0
    while len(nodes) < 15 and tries < 800:
        tries += 1
        a = _rng.uniform(0, 6.283)
        r = _rng.uniform(30, 86)
        p = (r * math.cos(a), r * math.sin(a) * 0.68, _rng.uniform(-42, 42))
        if any((p[0] - n["p"][0]) ** 2 + (p[1] - n["p"][1]) ** 2 + (p[2] - n["p"][2]) ** 2 < 30 ** 2 for n in nodes):
            continue
        t, long = _rng.choice(TYPES) if len(nodes) > 3 else TYPES[len(nodes) - 1]
        counts[t] += 1
        nodes.append({"p": p, "type": t, "name": f"{long}-{counts[t]:02d}" if t != "FORGE" else f"FORGE {'ABGDEZHK'[(counts[t] - 1) % 8]}"})
    n = len(nodes)
    P = np.array([nd["p"] for nd in nodes], np.float32)
    # links: each node to its 2-3 nearest + hub tethers to the nearest ring
    links = set()
    for i in range(n):
        dd = np.sum((P - P[i]) ** 2, axis=1)
        order = np.argsort(dd)[1:4]
        for j in order[: 2 + (i % 2)]:
            links.add((min(i, int(j)), max(i, int(j))))
    dd0 = np.sum(P ** 2, axis=1)
    for j in np.argsort(dd0)[1:6]:
        links.add((0, int(j)))
    links = sorted(links)
    _S["nodes"] = nodes
    _S["P"] = P
    _S["links"] = links
    _S["bw"] = {l: _rng.uniform(0.3, 1.0) for l in links}
    _S["bw_t"] = {l: _rng.uniform(0.3, 1.0) for l in links}
    _S["adj"] = {i: [] for i in range(n)}
    for a, b in links:
        _S["adj"][a].append(b)
        _S["adj"][b].append(a)
    _S["off"] = {}           # node -> t_back
    _S["next_drop"] = _rng.uniform(18, 28)
    _S["packets"] = []
    _S["flash"] = []         # (node, t, color)
    _S["event"] = ("UPLINK NOMINAL", 0.0, GREEN)
    _S["delivered"] = 0
    _S["sig"] = 0.9
    _S["yaw"] = _rng.uniform(0, 6.28)
    _S["next_pkt"] = 0.0
    _ph.reset()


def _route(a, b):
    off = _S["off"]
    bw = _S["bw"]
    if a in off or b in off:
        return None
    dist = {a: 0.0}
    prev = {}
    h = [(0.0, a)]
    while h:
        dcur, u = heapq.heappop(h)
        if u == b:
            path = [b]
            while path[-1] in prev:
                path.append(prev[path[-1]])
            return path[::-1]
        if dcur > dist.get(u, 1e9):
            continue
        for v in _S["adj"][u]:
            if v in off:
                continue
            w = 1.0 / (0.15 + bw[(min(u, v), max(u, v))])
            nd = dcur + w
            if nd < dist.get(v, 1e9):
                dist[v] = nd
                prev[v] = u
                heapq.heappush(h, (nd, v))
    return None


def render(bezel, mask, now: float) -> Image.Image:
    if _session.fresh(now):
        _reset()
    S = _S
    ta = _session.t(now)
    dt = 1 / 30 if S["last"] is None else min(0.1, max(0.0, now - S["last"]))
    S["last"] = now
    nodes, P, links = S["nodes"], S["P"], S["links"]
    n = len(nodes)
    off = S["off"]

    # bandwidth drift
    if _rng.random() < dt * 1.5:
        l = _rng.choice(links)
        S["bw_t"][l] = _rng.uniform(0.2, 1.0)
    for l in links:
        S["bw"][l] += (S["bw_t"][l] - S["bw"][l]) * min(1.0, dt * 0.8)

    # dropouts / restores
    if ta > S["next_drop"] and not off:
        cand = [i for i in range(1, n)]
        k = _rng.choice(cand)
        off[k] = ta + _rng.uniform(10, 16)
        S["next_drop"] = ta + _rng.uniform(30, 42)
        S["event"] = (f"NODE LOST {nodes[k]['name']}", ta, RED)
        S["flash"].append((k, ta, RED))
        for pk in S["packets"]:
            rem = pk["path"][pk["seg"] + 1:]
            if k in rem:
                nxt = pk["path"][pk["seg"] + 1]
                if nxt == k:  # heading straight into the dead node: packet lost
                    pk["dead"] = True
                    continue
                newp = _route(nxt, pk["path"][-1])
                if newp:
                    pk["path"] = pk["path"][: pk["seg"] + 1] + newp
                    pk["rer"] = True
                    S["flash"].append((nxt, ta, AMBER))
                else:
                    pk["dead"] = True
    for k, tb in list(off.items()):
        if ta > tb:
            del off[k]
            S["event"] = (f"LINK RESTORED {nodes[k]['name']}", ta, GREEN_HI)
            S["flash"].append((k, ta, GREEN_HI))
    if off and ta - S["event"][1] > 2.5 and S["event"][2] == RED:
        S["event"] = ("REROUTING", ta, AMBER)

    # spawn packets
    if ta > S["next_pkt"] and len(S["packets"]) < 16:
        S["next_pkt"] = ta + _rng.uniform(0.15, 0.45)
        a = _rng.randrange(n)
        b = _rng.randrange(n)
        if a != b:
            path = _route(a, b)
            if path and len(path) > 1:
                S["packets"].append({"path": path, "seg": 0, "u": 0.0, "rer": False, "dead": False})

    # projection
    S["yaw"] += dt * 0.12
    yaw = S["yaw"]
    pitch = 0.25 * math.sin(ta * 0.07)
    cy_, sy_, cp, sp = math.cos(yaw), math.sin(yaw), math.cos(pitch), math.sin(pitch)
    x, y, z = P[:, 0], P[:, 1], P[:, 2]
    x2 = x * cy_ + z * sy_
    z2 = -x * sy_ + z * cy_
    y2 = y * cp - z2 * sp
    z3 = y * sp + z2 * cp
    f = FOV / (z3 + CAM)
    sx = (CX + x2 * f).tolist()
    sy = (CY - 2 + y2 * f).tolist()
    depth = np.clip(0.55 - z3 / 140.0, 0.25, 1.0).tolist()

    img = S["bg"].copy()
    d = ImageDraw.Draw(img)

    # links
    for l in links:
        a, b = l
        dk = (depth[a] + depth[b]) * 0.5
        if a in off or b in off:
            # broken tether: dashed
            xa, ya, xb, yb = sx[a], sy[a], sx[b], sy[b]
            for k in range(0, 10, 2):
                u0, u1 = k / 10, (k + 1) / 10
                d.line([(xa + (xb - xa) * u0, ya + (yb - ya) * u0), (xa + (xb - xa) * u1, ya + (yb - ya) * u1)],
                       fill=_col(AMBER, 0.25))
            continue
        bw = S["bw"][l]
        c = _col(GREEN, (0.15 + 0.6 * bw) * dk)
        d.line([(sx[a], sy[a]), (sx[b], sy[b])], fill=c, width=2 if bw > 0.8 and dk > 0.6 else 1)

    # packets
    keep = []
    hi, lo, am = [], [], []
    for pk in S["packets"]:
        path = pk["path"]
        a, b = path[pk["seg"]], path[pk["seg"] + 1]
        if pk["dead"]:
            S["flash"].append((a, ta, AMBER))
            continue
        key = (min(a, b), max(a, b))
        bw = S["bw"].get(key, 0.5)
        L = float(np.linalg.norm(P[a] - P[b])) + 1.0
        pk["u"] += dt * (40 + 70 * bw) / L
        while pk["u"] >= 1.0:
            pk["u"] -= 1.0
            pk["seg"] += 1
            if pk["seg"] >= len(path) - 1:
                break
        if pk["seg"] >= len(path) - 1:
            if not pk["dead"]:
                S["delivered"] += 1
                S["flash"].append((path[-1], ta, GREEN))
            continue
        a, b = path[pk["seg"]], path[pk["seg"] + 1]
        u = pk["u"]
        px = sx[a] + (sx[b] - sx[a]) * u
        py = sy[a] + (sy[b] - sy[a]) * u
        (am if pk["rer"] else hi if bw > 0.55 else lo).append((px, py))
        keep.append(pk)
    S["packets"] = keep
    for px, py in lo:
        d.rectangle([px - 1, py - 1, px + 1, py + 1], fill=GREEN)
    for px, py in hi:
        d.ellipse([px - 2, py - 2, px + 2, py + 2], fill=GREEN_HI)
    for px, py in am:
        d.ellipse([px - 2, py - 2, px + 2, py + 2], fill=AMBER)

    # nodes (far first)
    for i in sorted(range(n), key=lambda i: depth[i]):
        nd = nodes[i]
        x0, y0, dk = sx[i], sy[i], depth[i]
        s = 3.0 + 2.5 * dk
        t = nd["type"]
        if i in off:
            c = RED if int(ta * 4) % 2 else _col(RED, 0.5)
            d.line([(x0 - s, y0 - s), (x0 + s, y0 + s)], fill=c, width=2)
            d.line([(x0 - s, y0 + s), (x0 + s, y0 - s)], fill=c, width=2)
            continue
        c = _col(GREEN_HI, 0.5 + 0.5 * dk) if dk > 0.6 else _col(GREEN, 0.4 + 0.8 * dk)
        if t == "HUB":
            pr = 7 + 1.5 * math.sin(ta * 3)
            d.ellipse([x0 - pr - 5, y0 - pr - 5, x0 + pr + 5, y0 + pr + 5], outline=GREEN_MID)
            d.ellipse([x0 - pr, y0 - pr, x0 + pr, y0 + pr], fill=(0, 30, 12), outline=GREEN_HI)
            d.line([(x0 - 3, y0), (x0 + 3, y0)], fill=GREEN_HI)
            d.line([(x0, y0 - 3), (x0, y0 + 3)], fill=GREEN_HI)
            _text(img, x0, y0 + pr + 6, "OMEGA-7", GREEN_MID, 9)
        elif t == "SKULL":
            d.ellipse([x0 - s, y0 - s, x0 + s, y0 + s], fill=(0, 20, 8), outline=c)
            d.point((x0, y0), fill=c)
        elif t == "COG":
            d.rectangle([x0 - s, y0 - s, x0 + s, y0 + s], fill=(0, 20, 8), outline=c)
        else:
            pts = [(x0 + (s + 1) * math.cos(k * math.pi / 3 + ta * 0.5), y0 + (s + 1) * math.sin(k * math.pi / 3 + ta * 0.5)) for k in range(6)]
            d.polygon(pts, fill=(0, 20, 8), outline=c)

    # flashes
    fl = []
    for k, t0, c in S["flash"]:
        age = ta - t0
        if age < 0.9:
            r = 4 + age * 16
            d.ellipse([sx[k] - r, sy[k] - r, sx[k] + r, sy[k] + r], outline=_col(c, 1 - age / 0.9))
            fl.append((k, t0, c))
    S["flash"] = fl

    # tracked node + info card
    sel = 1 + int(ta / 6.0) % (n - 1)
    if sel in off:
        sel = 0
    nd = nodes[sel]
    x0, y0 = sx[sel], sy[sel]
    br = 9 + 8 * max(0.0, 1 - ((ta / 6.0) % 1.0) * 5)
    for ax, ay in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
        xa, ya = x0 + ax * br, y0 + ay * br
        d.line([(xa, ya), (xa - ax * 4, ya)], fill=GREEN_HI)
        d.line([(xa, ya), (xa, ya - ay * 4)], fill=GREEN_HI)
    deg = len([1 for v in S["adj"][sel] if v not in off])
    load = int(40 + 35 * math.sin(ta * 0.3 + sel * 1.7))
    _text(img, CX, 186, nd["name"], GREEN_HI, 11)
    _text(img, CX, 200, f"LOAD {load:02d}%  LINKS {deg}", GREEN_MID, 9)

    # signal meter (left), packet counter (right)
    tot_bw = sum(S["bw"][l] for l in links if l[0] not in off and l[1] not in off) / max(1, len(links))
    target = min(1.0, tot_bw * 1.35) * (0.72 if off else 1.0)
    S["sig"] += (target - S["sig"]) * min(1.0, dt * 1.5)
    sig = S["sig"]
    for k in range(5):
        on = sig > (k + 0.5) / 5.5
        h = 4 + k * 3
        x_ = 18 + k * 5
        c = (GREEN if sig > 0.5 else AMBER) if on else GREEN_FAINT
        d.rectangle([x_, 118 - h, x_ + 3, 118], fill=c)
    _text(img, 18, 121, f"{int(sig * 100):02d}%", GREEN_MID, 9, "l")
    _text(img, 222, 100, "PKT", GREEN_DIM, 9, "r")
    _text(img, 222, 111, f"{S['delivered'] % 10000:04d}", GREEN_MID, 9, "r")

    # status line
    ev, et, ec = S["event"]
    if not off and ta - et > 5 and ec != GREEN:
        S["event"] = ("UPLINK NOMINAL", ta, GREEN)
        ev, ec = "UPLINK NOMINAL", GREEN
    _text(img, CX, 28, ev, ec, 10)
    return _ph.compose(img)
