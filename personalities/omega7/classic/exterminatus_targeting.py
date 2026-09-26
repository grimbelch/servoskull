"""Exterminatus Targeting - orbital fire-control plot for a condemned world.

A rotating 3D wireframe planet (graticule, faint landmasses) is acquired from
orbit.  Its hive cities are designated and locked one by one by a slewing
reticle while the globe spins down into orbital sync.  Cyclonic torpedo
trajectories are plotted from the fleet, firing solutions scroll by, the
countdown runs with authorisation codes, the torpedoes fall, and a firestorm
wave spreads across the sphere.  "EXTERMINATUS COMPLETE" - then a new world.
"""

from __future__ import annotations

import math
import random

import numpy as np
from PIL import Image, ImageDraw

from ..lore._common import CX, CY, Session, font, lerp_color, scale
from ._phosphor import (AMBER, GREEN, GREEN_DIM, GREEN_FAINT, GREEN_HI, GREEN_MID, RED,
                        Phosphor, blank)

NAME = "exterminatus_targeting"

_rng = random.Random()
_session = Session()
_ph = Phosphor(decay=0.72, bloom=0.6, flicker=0.03)

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


# ------------------------------------------------------------- geometry ---
GR = 56.0            # globe radius
GCX, GCY = CX, 114.0
CAM = 300.0
FOV = 300.0
TILT = 0.38

_WORLDS = ["HYDRAPHUR IV", "TARSIS ULTRA", "CADIA MINOR", "VOLSCANI", "GORGONUS",
           "KRIEG SECUNDUS", "ARMAGEDDON VII", "MORDIAN III", "HALO STAR IX", "PISCINA II",
           "VALHALLA IX", "TALLARN PRIME", "GORGON'S REST", "SARUM", "DELVARUS"]
_REASONS = ["XENOS TAINT", "HERESY UNBOUND", "WARP BREACH", "TYRANID SPORES",
            "GENESTEALER CULT", "NURGLE PLAGUE", "DAEMONIC INCURSION", "MUTANT UPRISING"]
_CITIES = ["HIVE PRIMUS", "HIVE TERTIUS", "SPIRE ANGELUS", "HIVE VOLSCAN", "SPIRE OMNIS",
           "HIVE GORGON", "HIVE SECUNDUS", "SPIRE CALIX", "HIVE MORTIS", "HIVE DOMINUS",
           "SPIRE KARTH", "HIVE OBLIQ"]
_SHIPS = ["VENGEANCE", "HAMMER OF DOOM", "IRON RESOLVE", "LEX TALIONIS", "DIVINE RIGHT"]
_AUTH = ["INQ. SEAL", "LORD ADMIRAL", "MAGOS FIDES", "ORDO MALLEUS", "ASTROPATH"]


def _build_mesh():
    polys = []
    n = 48
    for lat in (-60, -30, 0, 30, 60):
        la = math.radians(lat)
        a = np.linspace(0, 2 * math.pi, n + 1)
        polys.append(np.stack([np.cos(la) * np.cos(a), np.full_like(a, -math.sin(la)),
                               np.cos(la) * np.sin(a)], 1))
    for k in range(12):
        lo = k * math.pi / 6
        b = np.linspace(-math.pi / 2, math.pi / 2, n // 2 + 1)
        polys.append(np.stack([np.cos(b) * math.cos(lo), -np.sin(b), np.cos(b) * math.sin(lo)], 1))
    lens = [len(p) for p in polys]
    return np.concatenate(polys).astype(np.float32) * GR, lens


_MESH, _MLENS = _build_mesh()


def _rot(spin):
    cs, ss = math.cos(spin), math.sin(spin)
    ct, st = math.cos(TILT), math.sin(TILT)
    ry = np.array([[cs, 0, ss], [0, 1, 0], [-ss, 0, cs]], np.float32)
    rx = np.array([[1, 0, 0], [0, ct, -st], [0, st, ct]], np.float32)
    return rx @ ry


def _proj(q):
    f = FOV / (q[:, 2] + CAM)
    return GCX + q[:, 0] * f, GCY + q[:, 1] * f


def _front(q):
    return q[:, 2] < -(GR * GR) / CAM


def _unit(v):
    return v / np.linalg.norm(v, axis=-1, keepdims=True)


# -------------------------------------------------------------- phases ---
T_ACQ, T_DES, T_PLOT, T_CD, T_LAUNCH, T_BURN, T_DONE, T_END = 0, 5, 31, 41, 51, 55, 68, 77
FLIGHT = 3.2

_S: dict = {}


def _new_world(t0):
    s = _S
    s["t0"] = t0
    s["name"] = _rng.choice(_WORLDS)
    s["reason"] = _rng.choice(_REASONS)
    s["pop"] = _rng.uniform(8, 96)
    s["ship"] = _rng.choice(_SHIPS)
    s["auth"] = _rng.sample(_AUTH, 3)
    s["code"] = "%s-%d-%s" % (_rng.choice(["VERMILION", "OMEGA", "OBSIDIAN", "CRIMSON", "IRON"]),
                              _rng.randint(1, 9), _rng.choice(["ALPHA", "SIGMA", "RHO", "THETA"]))
    s["spin_end"] = _rng.uniform(0, 2 * math.pi)
    nc = _rng.randint(5, 6)
    # cities placed so they face the camera once the globe settles into sync
    cities = []
    names = _rng.sample(_CITIES, nc)
    for i in range(nc):
        for _ in range(40):
            lon = s["spin_end"] - math.pi / 2 + _rng.uniform(-0.95, 0.95)
            lat = _rng.uniform(-0.75, 0.9)
            v = np.array([math.cos(lat) * math.cos(lon), -math.sin(lat),
                          math.cos(lat) * math.sin(lon)], np.float32)
            if all(float(np.dot(v, c)) < 0.93 for c in cities):
                break
        cities.append(v)
    s["cities"] = np.array(cities, np.float32) * GR
    s["cnames"] = names
    s["cpop"] = [_rng.uniform(0.8, 14.0) for _ in range(nc)]
    s["locked"] = [None] * nc     # lock time
    s["order"] = []
    s["cur"] = None
    s["cur_t"] = 0.0
    s["ret"] = (GCX, GCY)
    # landmass point cloud
    pr = np.random.default_rng(_rng.getrandbits(32))
    centres = _unit(pr.normal(size=(7, 3)))
    pts = []
    for c in centres:
        k = int(pr.integers(40, 110))
        p = c[None, :] + pr.normal(scale=pr.uniform(0.12, 0.3), size=(k, 3))
        pts.append(p)
    s["land"] = (_unit(np.concatenate(pts)) * GR).astype(np.float32)
    s["ships"] = np.array([[-55, -50, -40], [-38, -63, -36], [-68, -33, -36]], np.float32)
    s["tstart"] = [0.0] * nc
    # firing solutions
    s["sol"] = ["SOL %d  DV %.2f  ETA %02d" % (i + 1, _rng.uniform(2, 6), _rng.randint(18, 60))
                for i in range(nc)]


def _reset():
    _S.clear()
    _ph.reset()
    _new_world(0.0)
    _S["bg"] = _static_bg()


def _static_bg():
    img = Image.new("RGB", (240, 240), (0, 0, 0))
    d = ImageDraw.Draw(img)
    for i in range(72):
        a = math.radians(i * 5)
        r0 = 104 if i % 6 else 98
        c = GREEN_DIM if i % 6 else GREEN_MID
        d.line([(CX + r0 * math.cos(a), CY + r0 * math.sin(a)),
                (CX + 108 * math.cos(a), CY + 108 * math.sin(a))], fill=c)
    d.arc([CX - 110, CY - 110, CX + 110, CY + 110], 0, 360, fill=GREEN_FAINT)
    return img


def _spin(lt):
    u = min(1.0, lt / T_CD)
    return _S["spin_end"] - 2.4 * (1 - u) ** 2 + 0.01 * max(0.0, lt - T_CD)


# ---------------------------------------------------------------- draw ---
def _draw_mesh(d, q, burn_fn, alpha):
    sx, sy = _proj(q)
    fr = _front(q)
    cls = np.where(fr, 1, 0)
    if burn_fn is not None:
        b = burn_fn(q)            # 0 none, 2 burned, 3 front
        cls = np.where(b > 0, np.where(fr, b, 0), cls)
    cols = {0: scale(GREEN_FAINT, alpha * 1.4), 1: scale(GREEN_MID, alpha),
            2: scale((120, 44, 16), alpha), 3: scale(AMBER, alpha)}
    xs, ys, cl = sx.tolist(), sy.tolist(), cls.tolist()
    i0 = 0
    for L in _MLENS:
        run = [(xs[i0], ys[i0])]
        rc = cl[i0]
        for i in range(i0 + 1, i0 + L):
            c = min(cl[i], cl[i - 1]) if cl[i] != cl[i - 1] else cl[i]
            if c != rc and len(run) > 1:
                d.line(run, fill=cols[rc])
                run = [run[-1]]
            rc = c
            run.append((xs[i], ys[i]))
        if len(run) > 1:
            d.line(run, fill=cols[rc])
        i0 += L


def _bracket(d, x, y, r, col, L=5):
    for sxn, syn in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
        px, py = x + sxn * r, y + syn * r
        d.line([(px, py), (px - sxn * L, py)], fill=col)
        d.line([(px, py), (px, py - syn * L)], fill=col)


def _arc_pts(ship, tgt, upto):
    """Trajectory in camera frame from ship to target (both camera-frame)."""
    n = 26
    s = np.linspace(0, upto, n, dtype=np.float32)[:, None]
    rs, rt = np.linalg.norm(ship), np.linalg.norm(tgt)
    dirs = _unit(ship[None, :] * (1 - s) + tgt[None, :] * s)
    rad = rs * (1 - s) + rt * s + 26 * np.sin(np.pi * s) * (1 - s)
    return dirs * rad


def _visible_pts(p):
    f = FOV / (p[:, 2] + CAM)
    x, y = GCX + p[:, 0] * f, GCY + p[:, 1] * f
    hid = (p[:, 2] > 0) & (np.hypot(x - GCX, y - GCY) < GR * 1.02)
    return x, y, hid


def render(bezel, mask, now: float) -> Image.Image:
    if _session.fresh(now) or not _S:
        _reset()
    s = _S
    tt = _session.t(now)
    lt = tt - s["t0"]
    if lt >= T_END:
        _new_world(tt)
        lt = 0.0

    img = s["bg"].copy()
    d = ImageDraw.Draw(img)
    arr = None

    spin = _spin(lt)
    R = _rot(spin)
    q = _MESH @ R.T
    cities = s["cities"] @ R.T
    nc = len(cities)
    blink = int(tt * 4) % 2 == 0

    # fade in / out
    alpha = min(1.0, 0.25 + lt / 3.0)
    if lt > T_END - 3:
        alpha = max(0.0, (T_END - lt) / 3.0)

    # --- burn wave function ---
    burn_fn = None
    wave = -1.0
    if lt >= T_LAUNCH + FLIGHT:
        wave = (lt - T_LAUNCH - FLIGHT) * 0.24
        cdirs = _unit(cities)

        def burn_fn(qq, cdirs=cdirs, wave=wave):
            u = _unit(qq)
            ang = np.arccos(np.clip(u @ cdirs.T, -1, 1))
            dt = np.arange(nc, dtype=np.float32) * 0.18
            m = (ang - (wave - dt)[None, :]).min(1)
            return np.where(m < -0.12, 2, np.where(m < 0, 3, 0))

    # --- landmass dots ---
    land = s["land"] @ R.T
    lf = _front(land)
    lx, ly = _proj(land[lf])
    if len(lx):
        arr = np.asarray(img).copy()
        xi = np.clip(lx.astype(np.int32), 0, 239)
        yi = np.clip(ly.astype(np.int32), 0, 239)
        lc = np.array(scale(GREEN_DIM, alpha * 1.3), np.uint8)
        if burn_fn is not None:
            b = burn_fn(land[lf])
            cols = np.where((b > 0)[:, None], np.array(scale((200, 70, 20), alpha), np.uint8)[None, :],
                            lc[None, :])
            cols = np.where((b == 3)[:, None], np.array(scale(AMBER, alpha), np.uint8)[None, :], cols)
            arr[yi, xi] = cols
        else:
            arr[yi, xi] = lc
        img = Image.fromarray(arr)
        d = ImageDraw.Draw(img)

    # --- globe ---
    limb = GR * FOV / math.sqrt(CAM * CAM - GR * GR)
    limb_col = GREEN if wave < 0 else lerp_color(GREEN, AMBER, min(1.0, wave / 1.5))
    if lt > T_DONE:
        limb_col = (140, 50, 20)
    d.ellipse([GCX - limb, GCY - limb, GCX + limb, GCY + limb], outline=scale(limb_col, alpha))
    if wave >= 0 and wave < 3.0:
        # atmosphere ignition halo
        hr = limb + 3 + 2 * math.sin(tt * 9)
        d.ellipse([GCX - hr, GCY - hr, GCX + hr, GCY + hr], outline=scale(AMBER, alpha * 0.6))
    _draw_mesh(d, q, burn_fn, alpha)

    # equatorial scan sweep during acquire
    if lt < T_DES + 1:
        yy = GCY - limb + (lt / (T_DES + 1)) * 2 * limb
        hw = math.sqrt(max(0.0, limb * limb - (yy - GCY) ** 2))
        d.line([(GCX - hw, yy), (GCX + hw, yy)], fill=GREEN_HI)

    csx, csy = _proj(cities)
    cfr = _front(cities)

    # --- designation ---
    if T_DES <= lt < T_PLOT:
        slot = (T_PLOT - T_DES - 2) / nc
        idx = int((lt - T_DES) / slot)
        if idx < nc and (s["cur"] is None or idx >= len(s["order"])):
            if idx >= len(s["order"]):
                cand = [i for i in range(nc) if s["locked"][i] is None]
                if cand:
                    best = min(cand, key=lambda i: float(cities[i][2]))
                    s["order"].append(best)
                    s["cur"] = best
                    s["cur_t"] = lt
        cur = s["cur"]
        if cur is not None and s["locked"][cur] is None:
            age = lt - s["cur_t"]
            tx, ty = float(csx[cur]), float(csy[cur])
            rx, ry = s["ret"]
            k = min(1.0, age / 0.8)
            rx += (tx - rx) * (0.25 + 0.5 * k)
            ry += (ty - ry) * (0.25 + 0.5 * k)
            s["ret"] = (rx, ry)
            lock = max(0.0, min(1.0, (age - 0.8) / (slot - 1.4)))
            rr = 20 - 12 * lock
            _bracket(d, rx, ry, rr, AMBER if lock > 0.3 else GREEN_HI)
            d.line([(rx - 30, ry), (rx - rr - 3, ry)], fill=GREEN_MID)
            d.line([(rx + rr + 3, ry), (rx + 30, ry)], fill=GREEN_MID)
            d.line([(rx, ry - 30), (rx, ry - rr - 3)], fill=GREEN_MID)
            d.line([(rx, ry + rr + 3), (rx, ry + 30)], fill=GREEN_MID)
            lx = rx + 14 if rx < CX + 20 else rx - 14 - _tlen(s["cnames"][cur], 9)
            ly0, ly1 = ry - rr - 12, ry + rr + 2
            if ly1 > 160:
                ly0, ly1 = ry - rr - 22, ry - rr - 12
            _txt(d, lx, ly0, s["cnames"][cur], GREEN_HI, 9)
            _txt(d, lx, ly1, "ACQ %3d%%" % int(lock * 100), GREEN_MID, 9)
            if lock >= 1.0:
                s["locked"][cur] = lt
    # --- city markers ---
    for i in range(nc):
        if not cfr[i]:
            continue
        x, y = float(csx[i]), float(csy[i])
        lk = s["locked"][i]
        if lk is None:
            d.rectangle([x - 1, y - 1, x + 1, y + 1], outline=scale(GREEN_HI, alpha))
            continue
        if wave > 0.05 + i * 0.18:
            continue
        age = lt - lk
        col = RED if (age < 1.2 and blink) else AMBER
        r = 4
        d.polygon([(x, y - r), (x + r, y), (x, y + r), (x - r, y)], outline=scale(col, alpha))
        if age < 0.6:
            rr = 4 + age * 18
            d.ellipse([x - rr, y - rr, x + rr, y + rr], outline=AMBER)
        _txt(d, x + 5, y - 11, str(s["order"].index(i) + 1) if i in s["order"] else "", scale(AMBER, alpha), 9)

    # --- trajectories ---
    ships = s["ships"]
    if T_PLOT <= lt < T_LAUNCH + FLIGHT + 0.5:
        for k in range(3):
            p = _visible_pts(ships[k:k + 1])
            x, y = float(p[0][0]), float(p[1][0])
            d.polygon([(x - 4, y + 2), (x + 4, y + 2), (x, y - 4)], outline=GREEN_HI)
        for j, i in enumerate(s["order"]):
            ship = ships[j % 3]
            if lt < T_LAUNCH:
                upto = max(0.0, min(1.0, (lt - T_PLOT - j * 1.2) / 1.5))
            else:
                upto = 1.0
            if upto <= 0:
                continue
            pts = _arc_pts(ship, cities[i], upto)
            x, y, hid = _visible_pts(pts)
            xs, ys, hs = x.tolist(), y.tolist(), hid.tolist()
            col = GREEN_MID if lt < T_LAUNCH else GREEN_DIM
            for m in range(0, len(xs) - 1):
                if hs[m] or hs[m + 1] or (m % 3 == 2 and lt < T_LAUNCH):
                    continue
                d.line([(xs[m], ys[m]), (xs[m + 1], ys[m + 1])], fill=col)
            if lt < T_LAUNCH and upto < 1 and not hs[-1]:
                d.ellipse([xs[-1] - 1.5, ys[-1] - 1.5, xs[-1] + 1.5, ys[-1] + 1.5], fill=GREEN_HI)
            # torpedo in flight
            if T_LAUNCH <= lt:
                fl = (lt - T_LAUNCH - j * 0.25) / FLIGHT
                if 0 < fl < 1:
                    tp = _arc_pts(ship, cities[i], fl)[-1:]
                    x, y, hid = _visible_pts(tp)
                    if not hid[0]:
                        x, y = float(x[0]), float(y[0])
                        d.ellipse([x - 2.5, y - 2.5, x + 2.5, y + 2.5], fill=GREEN_HI)
                        d.ellipse([x - 5, y - 5, x + 5, y + 5], outline=AMBER)
                elif fl >= 1 and fl < 1.35 and cfr[i]:
                    x, y = float(csx[i]), float(csy[i])
                    rr = (fl - 1) * 50
                    d.ellipse([x - rr, y - rr, x + rr, y + rr], outline=AMBER)
                    d.ellipse([x - 3, y - 3, x + 3, y + 3], fill=GREEN_HI)

    # --------------------------------------------------------- HUD text ---
    _txtc(d, 18, "ORDO EXTERMINATUS", scale(GREEN_MID, 1.0), 9)
    _txtc(d, 30, s["name"], GREEN_HI if lt < T_DONE else AMBER, 11)
    if lt < T_BURN:
        popv = s["pop"]
    elif lt < T_DONE:
        popv = s["pop"] * max(0.0, 1 - (lt - T_BURN) / (T_DONE - T_BURN - 2)) ** 2
    else:
        popv = 0.0
    lockn = sum(1 for v in s["locked"] if v is not None)
    # left readouts
    _txt(d, 18, 88, "POP", GREEN_DIM, 9)
    _txt(d, 18, 98, "%.1fB" % popv if popv > 0.05 else "NULL", AMBER if popv < s["pop"] else GREEN, 9)
    _txt(d, 18, 114, "TGT", GREEN_DIM, 9)
    _txt(d, 18, 124, "%d/%d" % (lockn, nc), GREEN, 9)
    _txt(d, 18, 140, "ROT", GREEN_DIM, 9)
    _txt(d, 18, 150, "%03d" % (int(math.degrees(spin)) % 360), GREEN, 9)
    # right readouts
    _txtr(d, 222, 88, "ALT", GREEN_DIM, 9)
    _txtr(d, 222, 98, "%dKM" % (36000 - int(min(lt, T_CD) * 90)), GREEN, 9)
    _txtr(d, 222, 114, "SYNC", GREEN_DIM, 9)
    sync = min(100, int(100 * min(1.0, lt / T_CD) ** 0.5))
    _txtr(d, 222, 124, "%d%%" % sync, GREEN if sync < 100 else GREEN_HI, 9)
    _txtr(d, 222, 140, "CYC", GREEN_DIM, 9)
    armed = lt >= T_CD
    _txtr(d, 222, 150, "ARMED" if armed else "SAFE", (AMBER if blink else RED) if armed and lt < T_LAUNCH else GREEN, 9)

    # bottom status
    yb = 180
    if lt < T_DES:
        _txtc(d, yb, "ACQUIRING WORLD", GREEN_HI if blink else GREEN_MID, 10)
        _txtc(d, yb + 12, "CAUSE: " + s["reason"], AMBER, 9)
    elif lt < T_PLOT:
        _txtc(d, yb, "DESIGNATING HIVES", GREEN_HI, 10)
        _txtc(d, yb + 12, "CAUSE: " + s["reason"], AMBER, 9)
    elif lt < T_CD:
        _txtc(d, yb, "PLOTTING SOLUTIONS", GREEN_HI, 10)
        k = min(len(s["order"]) - 1, int((lt - T_PLOT) / 1.2))
        if k >= 0:
            _txtc(d, yb + 12, s["sol"][s["order"][k]], GREEN_MID, 9)
    elif lt < T_LAUNCH:
        rem = T_LAUNCH - lt
        _txtc(d, yb - 3, "T-%05.2f" % rem, RED if blink or rem > 3 else AMBER, 16)
        k = int((lt - T_CD) / 2.5)
        if k < 3:
            _txtc(d, yb + 14, "AUTH " + s["auth"][k] + " OK", GREEN, 9)
        else:
            _txtc(d, yb + 14, s["code"], AMBER, 9)
    elif lt < T_BURN:
        _txtc(d, yb, "CYCLONIC TORPEDOES AWAY", RED if blink else AMBER, 10)
    elif lt < T_DONE:
        pct = min(100, int(100 * (lt - T_BURN) / (T_DONE - T_BURN - 1)))
        _txtc(d, yb, "FIRESTORM %d%%" % pct, AMBER, 11)
        w = 70
        d.rectangle([CX - w / 2, yb + 15, CX + w / 2, yb + 19], outline=GREEN_DIM)
        d.rectangle([CX - w / 2 + 1, yb + 16, CX - w / 2 + 1 + (w - 2) * pct / 100, yb + 18], fill=AMBER)
    else:
        _txtc(d, yb - 2, "EXTERMINATUS", GREEN_HI if blink else GREEN, 13)
        _txtc(d, yb + 12, "COMPLETE", GREEN_HI, 11)
    if lt >= T_DONE:
        _txtc(d, 200, "BIOSIGNS: NULL", GREEN_MID, 9)
    elif T_PLOT <= lt < T_CD:
        _txtc(d, 200, "ORBIT: " + s["ship"], GREEN_DIM, 9)

    # rotating outer marker
    a = tt * 0.6
    x, y = CX + 101 * math.cos(a), CY + 101 * math.sin(a)
    d.ellipse([x - 2, y - 2, x + 2, y + 2], fill=GREEN)

    # strike flash
    if T_LAUNCH + FLIGHT <= lt < T_LAUNCH + FLIGHT + 0.3:
        k = 1 - (lt - T_LAUNCH - FLIGHT) / 0.3
        d.ellipse([GCX - limb, GCY - limb, GCX + limb, GCY + limb], outline=scale(GREEN_HI, k), width=3)
    return _ph.compose(img)
