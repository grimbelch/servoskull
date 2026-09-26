"""Necron Tomb Awakening – a stepped tomb pyramid stirs from its long sleep.

A rotating 3D stepped pyramid is drawn with painter-sorted, back-face-culled
faces.  Circuit-glyph traces etched into every face ignite in waves from the
base to the capstone, canoptek scarabs crawl along the traces, and the HUD
spells out reanimation protocols in procedurally generated Necrontyr glyphs.
At full power the capstone discharges a Monolith-style gauss flux arc
(fractal green lightning with bloom), then the tomb powers down into dormancy
and a new tomb (different tiers, dynasty and circuitry) begins the cycle.
"""

from __future__ import annotations

import math
import random

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter

from ._common import CX, CY, Session, font, safe_half_width

NAME = "necron_awakening"

_rng = random.Random()
_session = Session()

D_CAM = 330.0
F_CAM = 318.0
SCY = 122.0          # screen y of the pyramid's pivot
TILT = 0.52

DYNASTIES = ["SAUTEKH", "NIHILAKH", "NEPHREKH", "MEPHRIT", "NOVOKH", "OGDOBEKH", "SZAREKHAN", "ATUN", "CHARNOVOKH"]
WORLDS = ["SOLEMNACE", "GIDRIM", "MANDRAGORA", "ZANTRAGORA", "MORRIAX", "DRAZAK", "KHEPRA IV", "NEKTHYST",
          "OBYRON PRIME", "TAPHERON"]

# ── Necrontyr glyphs (procedural, fixed per boot) ────────────────────────────


def _make_glyphs(n=36):
    g = random.Random(4242)
    out = []
    for _ in range(n):
        im = Image.new("L", (7, 11), 0)
        d = ImageDraw.Draw(im)
        d.line([(3, 1), (3, 10)], fill=255)
        top = g.randrange(4)
        if top == 0:
            d.ellipse([1, 0, 5, 4], outline=255)
        elif top == 1:
            d.arc([0, 0, 6, 5], 180, 360, fill=255)
        elif top == 2:
            d.point([(1, 1), (5, 1)], fill=255)
        mid = g.randrange(4)
        if mid == 0:
            d.line([(0, 5), (6, 5)], fill=255)
        elif mid == 1:
            d.line([(1, 4), (5, 7)], fill=255)
        elif mid == 2:
            d.line([(0, 6), (2, 6)], fill=255)
            d.line([(4, 4), (6, 4)], fill=255)
        bot = g.randrange(4)
        if bot == 0:
            d.line([(1, 10), (5, 10)], fill=255)
        elif bot == 1:
            d.line([(3, 8), (0, 10)], fill=255)
            d.line([(3, 8), (6, 10)], fill=255)
        elif bot == 2:
            d.point([(1, 9), (5, 9)], fill=255)
        out.append(im)
    return out


_GLYPHS = _make_glyphs()
_GCACHE: dict = {}


def _glyph_strip(code):
    m = _GCACHE.get(code)
    if m is None:
        if len(_GCACHE) > 200:
            _GCACHE.clear()
        im = Image.new("L", (len(code) * 8 + 1, 11), 0)
        for i, c in enumerate(code):
            im.paste(_GLYPHS[c % len(_GLYPHS)], (i * 8, 0))
        m = _GCACHE[code] = im
    return m


_TXT: dict = {}


def _tsprite(text, size):
    key = (text, size)
    m = _TXT.get(key)
    if m is None:
        if len(_TXT) > 300:
            _TXT.clear()
        f = font(size)
        l, t, r, b = f.getbbox(text)
        im = Image.new("L", (max(1, int(r)) + 2, max(1, int(b)) + 2), 0)
        ImageDraw.Draw(im).text((0, 0), text, fill=255, font=f)
        m = _TXT[key] = (im, f.getlength(text))
    return m


def _fit(img, y, text, fill, size, shadow=(0, 0, 0)):
    hw = safe_half_width(y + size * 0.6, 4)
    while size > 9 and _tsprite(text, size)[1] > 2 * hw:
        size -= 1
    m, w = _tsprite(text, size)
    x = int(CX - w / 2)
    if shadow is not None:
        img.paste(shadow, (x + 1, int(y) + 1), m)
    img.paste(fill, (x, int(y)), m)


# ── Tomb geometry ────────────────────────────────────────────────────────────


def _build_tomb():
    B = _rng.uniform(58, 64)
    H = _rng.uniform(78, 92)
    n = _rng.randint(3, 5)
    cap_half = _rng.uniform(9, 13)
    body_h = H * 0.82
    th = body_h / n
    shrink = (B - cap_half) / n
    verts = []
    faces = []   # dict(idx, normal, kind, tier)

    def add(p):
        verts.append(p)
        return len(verts) - 1

    b = B
    y0 = 0.0
    corners = [(-1, 1), (1, 1), (1, -1), (-1, -1)]   # (sx, sz) around the square
    for i in range(n):
        slant = shrink * _rng.uniform(0.55, 0.75)
        t = b - slant
        ledge = shrink - slant
        y1 = y0 + th
        lo = [add((sx * b, y0, sz * b)) for sx, sz in corners]
        hi = [add((sx * t, y1, sz * t)) for sx, sz in corners]
        nb = t - ledge if i < n - 1 else cap_half
        inn = [add((sx * nb, y1, sz * nb)) for sx, sz in corners]
        for k in range(4):
            a, c = k, (k + 1) % 4
            faces.append(dict(idx=[lo[a], lo[c], hi[c], hi[a]], kind="side", tier=i))
            if nb < t - 0.5:
                faces.append(dict(idx=[hi[a], hi[c], inn[c], inn[a]], kind="ledge", tier=i))
        b = nb
        y0 = y1
    apex = add((0.0, H, 0.0))
    capb = [add((sx * b, y0, sz * b)) for sx, sz in corners]
    for k in range(4):
        faces.append(dict(idx=[capb[k], capb[(k + 1) % 4], apex, apex], kind="cap", tier=n))
    V = np.array(verts, np.float32)
    V[:, 1] -= H * 0.45
    for f in faces:
        q = V[f["idx"]]
        nrm = np.cross(q[1] - q[0], q[3] - q[0] if f["kind"] != "cap" else q[2] - q[0])
        c = q.mean(0)
        out = c - np.array([0, -H * 0.45 + (H * 0.2 if f["kind"] == "ledge" else 0), 0], np.float32)
        if f["kind"] == "ledge":
            out = np.array([0, 1, 0], np.float32)
        if float(nrm @ out) < 0:
            nrm = -nrm
        f["n"] = (nrm / (np.linalg.norm(nrm) + 1e-6)).astype(np.float32)
        f["c"] = c
    # circuit traces in face (u,v) coordinates -> 3D points
    tpts = []
    traces = []  # (face index, start, end, height 0..1, is_node_end)
    for fi, f in enumerate(faces):
        q = V[f["idx"]]
        BL, BR, TR, TL = q[0], q[1], q[2], q[3]

        def P(u, v):
            return (1 - v) * ((1 - u) * BL + u * BR) + v * ((1 - u) * TL + u * TR)

        polys = []
        if f["kind"] == "side":
            cols = sorted(_rng.sample([0.12, 0.22, 0.32, 0.42, 0.5, 0.58, 0.68, 0.78, 0.88], _rng.randint(4, 6)))
            for u in cols:
                pts = [(u, 0.04)]
                v = 0.04
                while v < 0.86:
                    v = min(0.9, v + _rng.uniform(0.15, 0.32))
                    pts.append((u, v))
                    if v < 0.86 and _rng.random() < 0.6:
                        u = min(0.92, max(0.08, u + _rng.choice([-1, 1]) * _rng.uniform(0.06, 0.14)))
                        pts.append((u, v))
                polys.append(pts)
            if _rng.random() < 0.7:
                vb = _rng.uniform(0.3, 0.7)
                polys.append([(0.06, vb), (0.94, vb)])
        elif f["kind"] == "ledge":
            polys.append([(0.08, 0.5), (0.92, 0.5)])
        else:
            polys.append([(0.5, 0.05), (0.5, 0.75)])
        for pts in polys:
            s = len(tpts)
            for u, v in pts:
                tpts.append(P(u, v))
            hmid = float(np.mean([p[1] for p in tpts[s:]]))
            traces.append((fi, s, len(tpts), hmid))
    TP = np.array(tpts, np.float32)
    hmin, hmax = float(V[:, 1].min()), float(V[:, 1].max())
    traces = [(fi, s, e, (h - hmin) / (hmax - hmin)) for fi, s, e, h in traces]
    return dict(V=V, faces=faces, TP=TP, traces=traces, n=n, H=H, apex=apex, hmin=hmin, hmax=hmax)


def _xform(P, theta):
    c, s = math.cos(theta), math.sin(theta)
    ca, sa = math.cos(TILT), math.sin(TILT)
    x = P[:, 0] * c + P[:, 2] * s
    z = -P[:, 0] * s + P[:, 2] * c
    y = P[:, 1]
    y2 = y * ca + z * sa
    z2 = -y * sa + z * ca
    return x, y2, z2


def _proj(x, y, z):
    k = F_CAM / (z + D_CAM)
    return CX + x * k, SCY - y * k


def _rot_normals(N, theta):
    x, y, z = _xform(N, theta)
    return np.stack([x, y, z], 1)


# ── Lightning ────────────────────────────────────────────────────────────────


def _bolt(x0, y0, x1, y1, disp, depth=5):
    pts = [(x0, y0), (x1, y1)]
    for _ in range(depth):
        nxt = [pts[0]]
        for (ax, ay), (bx, by) in zip(pts, pts[1:]):
            mx, my = (ax + bx) / 2, (ay + by) / 2
            dx, dy = bx - ax, by - ay
            L = math.hypot(dx, dy) + 1e-6
            o = _rng.uniform(-1, 1) * disp * L / 60
            nxt.append((mx - dy / L * o, my + dx / L * o))
            nxt.append((bx, by))
        pts = nxt
        disp *= 0.55
    return pts


# ── State / story ────────────────────────────────────────────────────────────
_S: dict = {}


def _new_cycle(t0):
    tomb = _build_tomb()
    dur = dict(dormant=_rng.uniform(7, 10), wake=_rng.uniform(26, 32), awake=_rng.uniform(16, 22),
               surge=_rng.uniform(11, 14), sleep=_rng.uniform(13, 16))
    marks = []
    acc = 0.0
    for k in ("dormant", "wake", "awake", "surge", "sleep"):
        acc += dur[k]
        marks.append((acc, k))
    g = np.random.default_rng(_rng.randrange(1 << 30))
    ntr = len(tomb["traces"])
    NS = 140
    # ring of glyphs around the rim
    ring = []
    for k in range(30):
        a = k / 30 * 2 * math.pi
        ring.append((a, _rng.randrange(len(_GLYPHS))))
    bg = Image.new("RGB", (240, 240), (0, 4, 2))
    bd = ImageDraw.Draw(bg)
    for _ in range(60):
        x, y = _rng.randrange(240), _rng.randrange(150)
        v = _rng.randint(30, 90)
        bd.point((x, y), fill=(v // 2, v, v // 2))
    _S.clear()
    _S.update(t0=t0, tomb=tomb, marks=marks, total=acc,
              theta=_rng.uniform(0, 2 * math.pi), spin=_rng.choice([-1, 1]) * _rng.uniform(0.14, 0.2),
              sc_tr=g.integers(0, ntr, NS), sc_s=g.random(NS).astype(np.float32),
              sc_v=(g.uniform(0.25, 0.7, NS) * g.choice([-1, 1], NS)).astype(np.float32),
              sc_on=g.random(NS).astype(np.float32),
              dynasty=_rng.choice(DYNASTIES), world=_rng.choice(WORLDS), ring=ring, bg=bg,
              legion=_rng.randint(8000, 60000), bolts=[], bolt_t=-1.0, last=None,
              glyph_line=tuple(_rng.randrange(len(_GLYPHS)) for _ in range(12)),
              pulses=[_rng.random() for _ in range(3)])


def _reset():
    _new_cycle(0.0)


def _phase(t):
    prev = 0.0
    for end, k in _S["marks"]:
        if t < end:
            return k, t - prev, end - prev
        prev = end
    return "done", 0.0, 1.0


def render(bezel, mask, now: float) -> Image.Image:
    if _session.fresh(now):
        _reset()
    ta = _session.t(now)
    if ta - _S["t0"] >= _S["total"]:
        _new_cycle(ta)
    S = _S
    t = ta - S["t0"]
    dt = 1 / 30 if S["last"] is None else min(0.1, max(0.0, now - S["last"]))
    S["last"] = now
    ph, pt, pd = _phase(t)
    u = pt / pd

    # power levels
    if ph == "dormant":
        front, power, scar = -0.1, 0.0, 0.0
    elif ph == "wake":
        front, power, scar = u * 1.1, u, u
    elif ph == "awake":
        front, power, scar = 1.2, 1.0, 1.0
    elif ph == "surge":
        front, power, scar = 1.2, 1.0 + 0.6 * math.sin(min(1.0, u * 1.3) * math.pi), 1.0
    else:
        front, power, scar = 1.2, max(0.0, 1 - u * 1.3), max(0.0, 1 - u * 1.5)
        front = 1.2 - u * 1.4

    spin = S["spin"] * (1.0 + 1.2 * (ph == "surge") * math.sin(u * math.pi))
    S["theta"] += spin * dt
    th = S["theta"]
    tomb = S["tomb"]
    V, TP, faces = tomb["V"], tomb["TP"], tomb["faces"]

    img = S["bg"].copy()
    d = ImageDraw.Draw(img)

    # ground: concentric tomb-plaza rings + radial causeways
    gcol = (0, int(30 + 30 * min(1.0, power)), 14)
    ring_r = [70, 88]
    angs = np.linspace(0, 2 * math.pi, 49, dtype=np.float32)
    gy = float(tomb["V"][:, 1].min())
    for R in ring_r:
        P = np.stack([np.cos(angs) * R, np.full_like(angs, gy), np.sin(angs) * R], 1)
        x, y, z = _xform(P, th)
        sx, sy = _proj(x, y, z)
        d.line(list(zip(sx.tolist(), sy.tolist())), fill=gcol, width=1)
    P = []
    for k in range(8):
        a = k * math.pi / 4 + math.pi / 8
        P += [(math.cos(a) * 70, gy, math.sin(a) * 70), (math.cos(a) * 88, gy, math.sin(a) * 88)]
    x, y, z = _xform(np.array(P, np.float32), th)
    sx, sy = _proj(x, y, z)
    for k in range(8):
        d.line([(sx[2 * k], sy[2 * k]), (sx[2 * k + 1], sy[2 * k + 1])], fill=gcol)

    # project geometry
    vx, vy, vz = _xform(V, th)
    psx, psy = _proj(vx, vy, vz)
    tx, ty, tz = _xform(TP, th)
    tsx, tsy = _proj(tx, ty, tz)
    tsx_l, tsy_l = tsx.tolist(), tsy.tolist()
    psx_l, psy_l = psx.tolist(), psy.tolist()
    N = np.array([f["n"] for f in faces], np.float32)
    C = np.array([f["c"] for f in faces], np.float32)
    nx, ny, nz = _xform(N, th)
    cx, cy, cz = _xform(C, th)
    facing = (nx * cx + ny * cy + nz * (cz + D_CAM)) < 0
    light = np.clip(nx * -0.4 + ny * 0.75 + nz * -0.5, 0, 1)
    order = np.argsort(-cz)

    # trace brightness (vectorised)
    trs = tomb["traces"]
    hts = np.array([h for _, _, _, h in trs], np.float32)
    lit = (hts < front).astype(np.float32)
    pulse = np.zeros_like(hts)
    for k, p0 in enumerate(S["pulses"]):
        fr = ((t * 0.32 + p0) % 1.0) * 1.4 - 0.2
        pulse = np.maximum(pulse, np.exp(-((hts - fr) / 0.07) ** 2))
    near_front = np.exp(-((hts - front) / 0.05) ** 2) * (ph == "wake")
    pw = min(1.0, power)
    br = np.clip(0.1 + lit * (0.3 + 0.35 * pw + 0.5 * pulse * pw) + near_front * 0.9, 0, 1.3)
    if ph == "surge":
        br = np.clip(br + 0.25 * (power - 1.0) + 0.3 * (np.sin(t * 25 + hts * 20) > 0.6), 0, 1.4)
    face_traces: dict = {}
    for i, tr in enumerate(trs):
        face_traces.setdefault(tr[0], []).append(i)

    edge_b = 0.25 + 0.6 * pw
    for fi in order.tolist():
        if not facing[fi]:
            continue
        f = faces[fi]
        idx = f["idx"]
        poly = [(psx_l[j], psy_l[j]) for j in (idx if f["kind"] != "cap" else idx[:3])]
        L = float(light[fi])
        if f["kind"] == "cap":
            g = min(1.0, power) * (0.5 + 0.5 * math.sin(t * 4)) if ph != "dormant" else 0.0
            fill = (int(6 + 30 * g), int(20 + 40 * L + 150 * g), int(12 + 60 * g))
        else:
            fill = (int(7 + 16 * L), int(10 + 26 * L), int(9 + 18 * L))
        ec = (int(20 + 60 * edge_b * L), int(60 + 150 * edge_b), int(30 + 70 * edge_b))
        d.polygon(poly, fill=fill, outline=ec)
        for ti in face_traces.get(fi, ()):
            _, s, e, _h = trs[ti]
            b = float(br[ti])
            col = (int(min(255, 20 + 150 * b * b)), int(min(255, 40 + 215 * b)), int(min(255, 20 + 140 * b * b)))
            pts = list(zip(tsx_l[s:e], tsy_l[s:e]))
            d.line(pts, fill=col, width=1)
            if b > 0.45:
                ex, ey = pts[-1]
                d.rectangle([ex - 1, ey - 1, ex + 1, ey + 1], outline=col)

    # canoptek scarabs crawling along the traces
    nsc = int(len(S["sc_tr"]) * scar)
    if nsc > 0:
        tr_s = np.array([s for _, s, _, _ in trs], np.int64)
        tr_n = np.array([e - s - 1 for _, s, e, _ in trs], np.int64)
        tr_f = np.array([fi for fi, _, _, _ in trs], np.int64)
        sel = np.argsort(S["sc_on"])[:nsc]
        ti = S["sc_tr"][sel]
        nseg = np.maximum(tr_n[ti], 1)
        s = S["sc_s"][sel] + S["sc_v"][sel] * dt * (1.5 if ph == "surge" else 1.0)
        # bounce at the ends of each trace; hop to another trace occasionally
        over = (s < 0) | (s > 1)
        S["sc_v"][sel[over]] *= -1
        s = np.clip(s, 0, 1)
        S["sc_s"][sel] = s
        if _rng.random() < 0.2:
            k = int(sel[_rng.randrange(len(sel))])
            S["sc_tr"][k] = _rng.randrange(len(trs))
            S["sc_s"][k] = _rng.random()
        pos = s * nseg
        seg = np.minimum(pos.astype(np.int64), nseg - 1)
        fr = pos - seg
        a = tr_s[ti] + seg
        b_ = a + 1
        sx = tsx[a] + (tsx[b_] - tsx[a]) * fr
        sy = tsy[a] + (tsy[b_] - tsy[a]) * fr
        vis = facing[tr_f[ti]]
        pts = [(float(x), float(y)) for x, y, v in zip(sx, sy, vis) if v]
        if pts:
            d.point([(x + 1, y) for x, y in pts] + [(x - 1, y) for x, y in pts] +
                    [(x, y + 1) for x, y in pts] + [(x, y - 1) for x, y in pts], fill=(40, 160, 110))
            d.point(pts, fill=(235, 255, 240))

    # gauss flux arc
    ax_, ay_ = psx_l[tomb["apex"]], psy_l[tomb["apex"]]
    flash = 0.0
    if ph == "surge":
        inten = math.sin(min(1.0, u * 1.2) * math.pi)
        if t - S["bolt_t"] > 0.07:
            S["bolt_t"] = t
            bolts = []
            nb = 1 + int(inten * 6)
            for _ in range(nb):
                a = _rng.uniform(0, 2 * math.pi)
                r = _rng.uniform(70, 104)
                ex, ey = CX + math.cos(a) * r, CY + math.sin(a) * r
                bolts.append(_bolt(ax_, ay_, ex, ey, 34))
            if inten > 0.5:
                j = _rng.randrange(len(V) - 1)
                bolts.append(_bolt(ax_, ay_, psx_l[j], psy_l[j], 16, 4))
            S["bolts"] = bolts
        for pts in S["bolts"]:
            d.line(pts, fill=(30, 150, 60), width=3)
            d.line(pts, fill=(210, 255, 220), width=1)
        rr = 4 + 6 * inten + _rng.uniform(0, 2)
        d.ellipse([ax_ - rr, ay_ - rr, ax_ + rr, ay_ + rr], fill=(180, 255, 200))
        if 0.45 < u < 0.55:
            flash = 1.0 - abs(u - 0.5) / 0.05
    elif ph in ("wake", "awake") and power > 0.3:
        rr = 2 + 2 * power + math.sin(t * 6)
        d.ellipse([ax_ - rr, ay_ - rr, ax_ + rr, ay_ + rr], fill=(90, 230, 130))

    # bloom
    glow_k = 0.25 + 0.5 * min(1.0, power) + (0.9 if ph == "surge" else 0.0) * math.sin(min(1.0, u * 1.2) * math.pi)
    if glow_k > 0.2:
        small = img.resize((60, 60), Image.BILINEAR).filter(ImageFilter.GaussianBlur(2))
        k = min(2.0, glow_k)
        lut = [min(255, int(i * k)) for i in range(256)] * 3
        glow = small.point(lut).resize((240, 240), Image.BILINEAR)
        img = ImageChops.add(img, glow)
    if flash > 0:
        img = Image.blend(img, Image.new("RGB", (240, 240), (170, 255, 190)), 0.6 * flash)
    d = ImageDraw.Draw(img)

    # glyph ring around the rim
    wave = t * (1.6 if ph in ("awake", "surge") else 0.8)
    for k, (a, gi) in enumerate(S["ring"]):
        a2 = a + th * 0.25
        x = CX + math.cos(a2) * 103 - 3
        y = CY + math.sin(a2) * 103 - 5
        lv = 0.5 + 0.5 * math.sin(wave - k * 0.6)
        g = int(25 + (40 + 150 * lv) * (0.25 + 0.75 * min(1.0, power)))
        img.paste((0, g, g // 3), (int(x), int(y)), _GLYPHS[gi])

    # readouts
    gl = S["glyph_line"]
    if int(t * 3) != S.get("gtick"):
        S["gtick"] = int(t * 3)
        if ph != "dormant" or _rng.random() < 0.2:
            gl = gl[1:] + (_rng.randrange(len(_GLYPHS)),)
            S["glyph_line"] = gl
    strip = _glyph_strip(gl[:9])
    gc = (60, 230, 120) if ph != "dormant" else (30, 100, 50)
    img.paste(gc, (CX - strip.width // 2, 26), strip)
    _fit(img, 39, f"TOMB WORLD {S['world']}", (120, 200, 140), 9)

    pct = {"dormant": 0, "wake": int(u * 100), "awake": 100, "surge": 100,
           "sleep": max(0, int(100 - u * 100)), "done": 0}[ph]
    if ph == "dormant":
        st, sub = "STASIS-CRYPT DORMANT", "SLEEP CYCLE: 60,000,000 YRS"
    elif ph == "wake":
        st, sub = "REANIMATION PROTOCOL", f"{pct:3d}%  LEGION {int(S['legion'] * u):,}"
    elif ph == "awake":
        st, sub = f"{S['dynasty']} DYNASTY RISES", f"LEGION {S['legion']:,} ONLINE"
    elif ph == "surge":
        st, sub = "GAUSS FLUX ARC", "PURGE THE LIVING"
    else:
        st, sub = "RETURNING TO STASIS", f"POWER {pct:3d}%"
    d.rounded_rectangle([CX - 62, 184, CX + 62, 219], radius=6, fill=(0, 12, 5), outline=(20, 90, 45))
    blink = ph == "surge" and int(t * 6) % 2 == 0
    _fit(img, 185, st, (255, 255, 255) if blink else (90, 255, 140), 11)
    _fit(img, 198, sub, (70, 170, 100), 9)
    # reanimation bar
    if ph in ("wake", "sleep"):
        bw = 70
        x0 = CX - bw // 2
        d.rectangle([x0, 211, x0 + bw, 214], outline=(30, 90, 50))
        d.rectangle([x0 + 1, 212, x0 + 1 + int((bw - 2) * pct / 100), 213], fill=(90, 255, 140))
    return img
