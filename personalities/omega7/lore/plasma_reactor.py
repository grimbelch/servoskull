"""Plasma Reactor Containment - cross-section of a Titan plasma reactor.

A numpy particle plasma swirls inside three magnetic containment rings whose
field visibly pulses.  Core temperature, field strength and pressure creep
toward critical; sometimes the field nearly fails (red alarm, rings buckle)
and is reinforced; finally a Tech-Priest performs the Rite of Venting, steam
bursts from the vent ports and the readouts fall.  Then the cycle repeats
with a different reactor, plasma hue and spin.
"""

from __future__ import annotations

import math
import random

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter

from ._common import CX, CY, H, W, Session, font, lerp_color, scale

NAME = "plasma_reactor"

_rng = random.Random()
_session = Session()

N_PLASMA = 1100
N_STEAM = 520
RINGS = (22.0, 40.0, 58.0)
VENT_R = 70.0
VENT_ANGS = [math.radians(a) for a in (45, 135, 225, 315)]

_YY, _XX = np.mgrid[0:H, 0:W].astype(np.float32)
_RR = np.hypot(_XX - CX, _YY - CY)
_CORE = np.exp(-(_RR / 8.0) ** 2).astype(np.float32)
_HALO = np.exp(-(_RR / 30.0) ** 2).astype(np.float32) * (_RR < 60)
_RED = Image.new("RGB", (W, H), (70, 0, 0))

_PALETTES = [
    # (outer plasma, hot inner, core)
    ((110, 60, 255), (230, 200, 255), (255, 240, 255)),   # violet
    ((40, 140, 255), (170, 235, 255), (240, 255, 255)),   # sun-blue
    ((255, 110, 30), (255, 220, 120), (255, 250, 220)),   # solar orange
    ((40, 230, 170), (190, 255, 230), (240, 255, 250)),   # green-white
]
_REACTORS = ["REACTOR PRIMUS", "WARLORD CORE", "REAVER CORE", "WARHOUND CORE",
             "SANCTUM IGNIS", "CORE MAGNIFICAT"]
_LITANY = ["RITE OF VENTING", "BLESSED BE THE VALVE", "RELEASE THY WRATH",
           "COOL THY FURY", "SPIRIT, BE CALMED", "INCENSE APPLIED"]

_S: dict = {}


# --------------------------------------------------------------------- setup

def _background() -> Image.Image:
    img = Image.new("RGB", (W, H), (6, 6, 8))
    # brushed metal radial shading
    shade = (18 + 14 * np.cos(_RR / 9.0) * np.exp(-_RR / 140.0)).clip(0, 40)
    arr = np.stack([shade * 1.0, shade * 0.95, shade * 0.9], axis=-1).astype(np.uint8)
    img = Image.fromarray(arr, "RGB")
    d = ImageDraw.Draw(img)
    # outer cog band
    teeth = 20
    pts = []
    for i in range(teeth * 4):
        a = 2 * math.pi * i / (teeth * 4)
        r = 88 if (i % 4) in (1, 2) else 83
        pts.append((CX + r * math.cos(a), CY + r * math.sin(a)))
    d.polygon(pts, fill=(44, 38, 32), outline=(90, 74, 50))
    d.ellipse([CX - 78, CY - 78, CX + 78, CY + 78], fill=(20, 18, 17), outline=(70, 58, 42))
    for i in range(20):
        a = 2 * math.pi * (i + 0.5) / 20
        x, y = CX + 81 * math.cos(a), CY + 81 * math.sin(a)
        d.ellipse([x - 1.5, y - 1.5, x + 1.5, y + 1.5], fill=(120, 100, 70))
    # chamber wall
    d.ellipse([CX - 65, CY - 65, CX + 65, CY + 65], fill=(60, 44, 28))
    d.ellipse([CX - 61, CY - 61, CX + 61, CY + 61], fill=(4, 3, 6))
    # vent ports (closed)
    for a in VENT_ANGS:
        _vent_shape(d, a, (30, 28, 26), (100, 90, 70))
    # gauge sockets
    for c in (180.0, 0.0):
        d.arc([CX - 106, CY - 106, CX + 106, CY + 106], c - 36, c + 36, fill=(60, 52, 40), width=2)
        d.arc([CX - 90, CY - 90, CX + 90, CY + 90], c - 36, c + 36, fill=(60, 52, 40), width=1)
    return img


def _vent_shape(d, a, fill, outline):
    ca, sa = math.cos(a), math.sin(a)
    pts = []
    for rr, ww in ((-5, -6), (-5, 6), (6, 5), (6, -5)):
        r = VENT_R + rr
        pts.append((CX + r * ca - ww * sa, CY + r * sa + ww * ca))
    d.polygon(pts, fill=fill, outline=outline)
    return pts


def _new_cycle():
    rise = _rng.uniform(46, 66)
    s = _S
    s["pal"] = _rng.choice(_PALETTES)
    s["dir"] = _rng.choice((-1.0, 1.0))
    s["name"] = _rng.choice(_REACTORS)
    s["rise"] = rise
    s["breach"] = _rng.random() < 0.72
    s["b_at"] = rise * _rng.uniform(0.5, 0.72)
    s["b_len"] = _rng.uniform(8.5, 11.0)
    s["vent"] = _rng.uniform(12.0, 15.0)
    s["post"] = _rng.uniform(6.0, 8.0)
    s["total"] = rise + s["vent"] + s["post"]
    s["h0"] = _rng.uniform(0.22, 0.34)
    s["hp"] = _rng.uniform(0.9, 0.97)
    s["lobes"] = _rng.choice((2, 3, 3, 4, 5))
    s["litany"] = _rng.sample(_LITANY[1:], 4)
    s["dist_k"] = _rng.choice((3, 4, 5))
    core = np.array(s["pal"][2], dtype=np.float32)
    s["core3"] = _CORE[..., None] * core[None, None, :]
    s["halo3"] = _HALO[..., None] * np.array(s["pal"][0], dtype=np.float32)[None, None, :]
    # recolour particles for new palette
    s["h_vent_start"] = None


def _reset():
    _S.clear()
    _S["bg"] = _background()
    _S["buf"] = np.zeros((H, W, 3), dtype=np.float32)
    n = N_PLASMA
    _S["pr"] = np.random.default_rng(_rng.getrandbits(32))
    pr = _S["pr"]
    _S["home"] = (np.sqrt(pr.random(n)) * 0.95 + 0.04).astype(np.float32)
    _S["r"] = (_S["home"] * 30).astype(np.float32)
    _S["th"] = (pr.random(n) * 2 * math.pi).astype(np.float32)
    _S["ph"] = (pr.random(n) * 2 * math.pi).astype(np.float32)
    _S["spd"] = (0.75 + pr.random(n) * 0.5).astype(np.float32)
    m = N_STEAM
    _S["sx"] = np.zeros(m, np.float32)
    _S["sy"] = np.zeros(m, np.float32)
    _S["svx"] = np.zeros(m, np.float32)
    _S["svy"] = np.zeros(m, np.float32)
    _S["sage"] = np.ones(m, np.float32)
    _S["slife"] = np.ones(m, np.float32)
    _S["snext"] = 0
    _S["cycle_start"] = 0.0
    _S["last_t"] = 0.0
    _S["burst_done"] = False
    _new_cycle()


# --------------------------------------------------------------------- story

def _smooth(x):
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


def _state(tc, t):
    s = _S
    st = {"alarm": False, "distort": 0.0, "vent": 0.0}
    rise = s["rise"]
    h0, hp = s["h0"], s["hp"]
    wob = 0.012 * math.sin(t * 1.7) + 0.008 * math.sin(t * 4.3)
    field_pulse = 0.03 * math.sin(t * 2.3)
    if tc < rise:
        u = tc / rise
        h = h0 + (hp - h0) * u ** 1.35 + wob
        field = 0.97 - 0.22 * h + field_pulse
        status, scol = "CONTAINMENT NOMINAL", (90, 220, 110)
        if h > 0.62:
            status, scol = "CORE TEMP RISING", (240, 180, 60)
        if h > 0.84:
            status = "WARNING: OVERHEAT"
            scol = (255, 150, 40) if int(t * 3) % 2 else (180, 90, 20)
        if s["breach"]:
            b0, bl = s["b_at"], s["b_len"]
            if b0 <= tc < b0 + bl:
                v = (tc - b0) / bl
                bump = math.sin(math.pi * v)
                h += 0.09 * bump
                if v < 0.62:
                    st["distort"] = _smooth(v / 0.35)
                    field -= 0.5 * _smooth(v / 0.5)
                    st["alarm"] = int(t * 4) % 2 == 0
                    status = "!! BREACH IMMINENT !!"
                    scol = (255, 60, 40) if st["alarm"] else (160, 20, 10)
                else:
                    w = (v - 0.62) / 0.38
                    st["distort"] = 1.0 - _smooth(w)
                    field -= 0.5 * (1.0 - _smooth(w * 1.2))
                    status, scol = "FIELD REINFORCING", (255, 190, 60)
            elif b0 + bl <= tc < b0 + bl + 4.5:
                status, scol = "FIELD STABILISED", (90, 230, 140)
        s["h_top"] = h
    elif tc < rise + s["vent"]:
        v = (tc - rise) / s["vent"]
        htop = s.get("h_top", hp)
        k = _smooth((v - 0.12) / 0.8)
        h = htop + (h0 * 0.85 - htop) * k + wob * 0.5
        field = 0.97 - 0.22 * h + field_pulse
        st["vent"] = 0.0 if v < 0.12 else (min(1.0, (v - 0.12) / 0.08) * (1.0 - _smooth((v - 0.7) / 0.3)))
        if v < 0.12:
            status = "RITE OF VENTING"[: max(1, int(len("RITE OF VENTING") * v / 0.1))]
        else:
            status = s["litany"][min(3, int((v - 0.12) / 0.22))]
        scol = (170, 220, 255)
    else:
        v = (tc - rise - s["vent"]) / s["post"]
        h = h0 * 0.85 + wob * 0.5 + 0.03 * v
        field = 0.97 - 0.22 * h + field_pulse
        if v < 0.5:
            status, scol = "VENTS SEALED", (140, 210, 255)
        else:
            status, scol = "OMNISSIAH BE PRAISED", (230, 200, 110)
    st["h"] = max(0.0, min(1.05, h))
    st["field"] = max(0.05, min(1.0, field))
    st["status"], st["scol"] = status, scol
    return st


# --------------------------------------------------------------------- render

def _gauge(d, centre_deg, frac, flip):
    n = 15
    for i in range(n):
        f = i / (n - 1)
        a = math.radians(centre_deg + (32 - 64 * f) * (1 if flip else -1))
        lit = f <= frac + 1e-6
        if lit:
            col = lerp_color((60, 210, 90), (250, 190, 40), f / 0.6) if f < 0.6 else \
                lerp_color((250, 190, 40), (255, 40, 30), (f - 0.6) / 0.4)
        else:
            col = (34, 30, 26)
        ca, sa = math.cos(a), math.sin(a)
        d.line([(CX + 93 * ca, CY + 93 * sa), (CX + 104 * ca, CY + 104 * sa)], fill=col, width=3)


def _plate(d, box):
    d.rounded_rectangle(box, radius=4, fill=(14, 12, 10), outline=(96, 78, 50))


def render(bezel, mask, now: float) -> Image.Image:
    if _session.fresh(now) or not _S:
        _reset()
    t = _session.t(now)
    s = _S
    dt = max(0.0, min(0.1, t - s["last_t"]))
    s["last_t"] = t
    tc = t - s["cycle_start"]
    if tc >= s["total"]:
        s["cycle_start"] = t
        tc = 0.0
        s["burst_done"] = False
        _new_cycle()
    st = _state(tc, t)
    h, field, distort = st["h"], st["field"], st["distort"]
    pr = s["pr"]
    pal_out, pal_hot, _ = s["pal"]

    # ---- plasma particle update
    r, th = s["r"], s["th"]
    omega = s["dir"] * (0.7 + 3.2 * h) * (1.7 - r / 50.0) * s["spd"]
    th += omega * dt
    spread = 0.72 + 0.26 * h + 0.2 * distort + 0.12 * (1.0 - field)
    target = s["home"] * RINGS[2] * spread
    noise = pr.standard_normal(N_PLASMA).astype(np.float32)
    r += (target - r) * min(1.0, 2.0 * dt) + noise * (1.5 + 7.0 * h) * math.sqrt(dt + 1e-6) * 3.0
    np.clip(r, 0.0, RINGS[2] + 8, out=r)
    th %= 2 * math.pi
    lobes = s["lobes"]
    reff = r + (1.5 + 4.5 * h) * np.sin(lobes * th + t * 4.0 * s["dir"] + s["ph"] * 0.4) * (r / RINGS[2])
    kd = s["dist_k"]
    rmax = RINGS[2] - 2.0 + distort * (7.0 * np.sin(kd * th + t * 6.0) + 3.0 * np.sin(7 * th - t * 11.0))
    reff = np.minimum(reff, rmax)
    reff = np.maximum(reff, 0.0)
    px = (CX + reff * np.cos(th)).astype(np.int32)
    py = (CY + reff * np.sin(th)).astype(np.int32)
    ok = (px >= 0) & (px < W) & (py >= 0) & (py < H)
    idx = (py[ok] * W + px[ok])
    rn = np.clip(reff[ok] / RINGS[2], 0.0, 1.0)
    hot = (1.0 - rn) ** 1.6
    arm = 0.5 + 0.5 * np.sin(lobes * th[ok] - reff[ok] * 0.16 * s["dir"] + t * 1.3 * s["dir"])
    bright = (16.0 + 26.0 * h) * (1.0 - 0.3 * rn) * (0.25 + 1.5 * arm * arm)
    buf = s["buf"]
    buf *= 0.86 ** (dt * 30.0)
    flat = buf.reshape(-1, 3)
    for c in range(3):
        wgt = bright * (pal_out[c] / 255.0 * (1.0 - hot) + pal_hot[c] / 255.0 * hot)
        flat[:, c] += np.bincount(idx, weights=wgt, minlength=W * H).astype(np.float32)

    # ---- steam particles (venting)
    vent = st["vent"]
    sx, sy, svx, svy, sage, slife = s["sx"], s["sy"], s["svx"], s["svy"], s["sage"], s["slife"]
    n_spawn = 0
    if vent > 0.0:
        if not s["burst_done"]:
            n_spawn = 260
            s["burst_done"] = True
        else:
            n_spawn = int(vent * 320 * dt + pr.random())
    if n_spawn:
        n_spawn = min(n_spawn, N_STEAM)
        k0 = s["snext"]
        ids = (np.arange(n_spawn) + k0) % N_STEAM
        s["snext"] = (k0 + n_spawn) % N_STEAM
        va = np.array(VENT_ANGS, np.float32)[pr.integers(0, 4, n_spawn)]
        ca, sa = np.cos(va), np.sin(va)
        sp = pr.uniform(30, 75, n_spawn).astype(np.float32)
        side = pr.normal(0, 14, n_spawn).astype(np.float32)
        sx[ids] = CX + (VENT_R + 5) * ca
        sy[ids] = CY + (VENT_R + 5) * sa
        svx[ids] = ca * sp - sa * side
        svy[ids] = sa * sp + ca * side
        sage[ids] = 0.0
        slife[ids] = pr.uniform(0.7, 1.7, n_spawn).astype(np.float32)
    alive = sage < slife
    if alive.any():
        drag = max(0.0, 1.0 - 1.6 * dt)
        svx *= drag
        svy *= drag
        svy -= 10.0 * dt
        sx += svx * dt
        sy += svy * dt
        sage += dt
        a_idx = np.nonzero(alive)[0]
        qx = sx[a_idx].astype(np.int32)
        qy = sy[a_idx].astype(np.int32)
        life_k = np.clip(1.0 - sage[a_idx] / slife[a_idx], 0.0, 1.0)
        good = (qx >= 1) & (qx < W - 1) & (qy >= 1) & (qy < H - 1)
        qx, qy, life_k = qx[good], qy[good], life_k[good]
        base = qy * W + qx
        allidx = np.concatenate([base, base + 1, base + W, base + W + 1])
        wv = np.tile(life_k * 24.0, 4)
        steam = np.bincount(allidx, weights=wv, minlength=W * H).astype(np.float32)
        flat[:, 0] += steam * 0.85
        flat[:, 1] += steam * 0.92
        flat[:, 2] += steam

    # ---- compose plasma layer with core + glow
    core_k = 0.35 + 0.65 * h + 0.06 * math.sin(t * 9.0)
    out = buf + s["core3"] * core_k + s["halo3"] * (0.05 + 0.12 * h)
    np.clip(out, 0, 255, out=out)
    pimg = Image.fromarray(out.astype(np.uint8), "RGB")
    glow = pimg.resize((60, 60), Image.BOX).filter(ImageFilter.GaussianBlur(2)).resize((W, H), Image.BILINEAR)
    pimg = ImageChops.add(pimg, glow)
    img = ImageChops.add(s["bg"], pimg)
    fx = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(fx)

    # ---- containment rings
    breach_col = (255, 70, 30)
    field_col = lerp_color((255, 90, 40), (90, 200, 255), (field - 0.35) / 0.55)
    if distort > 0.05:
        field_col = lerp_color(field_col, breach_col, distort)
    wspeed = 2.5 + 4.0 * h
    nseg = 64
    angs = [2 * math.pi * i / nseg for i in range(nseg + 1)]
    for i, R in enumerate(RINGS):
        pulse = 0.5 + 0.5 * math.sin(t * wspeed - i * 1.3)
        b = (0.3 + 0.7 * pulse) * (0.45 + 0.55 * field)
        if distort > 0.05 and _rng.random() < 0.25 * distort:
            b *= 0.3  # flicker
        amp = distort * (2.5 + 2.5 * i)
        ph = t * (5 + i) + i
        pts = []
        for a in angs:
            rr = R + amp * math.sin(kd * a + ph) + distort * 1.5 * math.sin(7 * a - t * 13)
            pts.append((CX + rr * math.cos(a), CY + rr * math.sin(a)))
        d.line(pts, fill=scale(field_col, b * 0.45), width=4)
        d.line(pts, fill=scale(lerp_color(field_col, (255, 255, 255), 0.35 * pulse), b), width=1)
    # field coil nodes on chamber wall
    for i in range(8):
        a = 2 * math.pi * i / 8 + math.pi / 8
        x, y = CX + 63 * math.cos(a), CY + 63 * math.sin(a)
        b = 0.35 + 0.65 * (0.5 + 0.5 * math.sin(t * wspeed * 1.5 + i * 0.8)) * field
        d.rectangle([x - 2.5, y - 2.5, x + 2.5, y + 2.5], fill=scale(field_col, b), outline=(60, 45, 25))

    img = ImageChops.add(img, fx)
    d = ImageDraw.Draw(img)

    # ---- vent ports
    for i, a in enumerate(VENT_ANGS):
        if vent > 0.0:
            fl = 0.6 + 0.4 * math.sin(t * 20 + i * 2)
            _vent_shape(d, a, lerp_color((120, 60, 20), (255, 230, 180), vent * fl), (200, 170, 110))
        elif st["alarm"]:
            _vent_shape(d, a, (90, 10, 5), (200, 60, 40))

    # ---- gauges
    press = 0.18 + 0.78 * h + 0.05 * distort
    _gauge(d, 180.0, min(1.0, h), False)
    _gauge(d, 0.0, min(1.0, press), True)
    f9 = font(9)
    d.text((34, 64), "T", fill=(200, 170, 110), font=f9)
    d.text((201, 64), "P", fill=(200, 170, 110), font=f9)

    # ---- HUD plates
    f10 = font(10)
    _plate(d, (58, 17, 182, 52))
    title = s["name"]
    tw = d.textlength(title, font=f10)
    d.text((CX - tw / 2, 20), title, fill=(210, 170, 100), font=f10)
    status = st["status"]
    fs = font(10)
    sw = d.textlength(status, font=fs)
    if sw > 150:
        fs = font(9)
        sw = d.textlength(status, font=fs)
    d.text((CX - sw / 2, 35), status, fill=st["scol"], font=fs)

    _plate(d, (52, 186, 188, 218))
    temp_k = int(1800 + 9800 * h + 40 * math.sin(t * 7))
    mpa = 2.0 + 30.0 * press + 0.3 * math.sin(t * 5.3)
    tcol = lerp_color((200, 220, 200), (255, 70, 40), (h - 0.6) / 0.35)
    l1 = f"CORE {temp_k:05d}K"
    w1 = d.textlength(l1, font=f10)
    d.text((CX - w1 / 2, 189), l1, fill=tcol, font=f10)
    fcol = lerp_color((255, 70, 40), (120, 210, 255), (field - 0.4) / 0.4)
    l2 = f"FLD {int(field * 100):03d}%  P {mpa:4.1f}"
    w2 = d.textlength(l2, font=f10)
    d.text((CX - w2 / 2, 203), l2, fill=fcol, font=f10)

    # ---- alarm
    if st["alarm"]:
        img = ImageChops.add(img, _RED)
        d = ImageDraw.Draw(img)
        d.ellipse([CX - 113, CY - 113, CX + 113, CY + 113], outline=(255, 40, 20), width=4)
    return img
