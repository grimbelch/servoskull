"""Mechadendrite Assembly - a Tech-Priest's arms build a weapon part by part.

Two gripper mechadendrites (FABRIK inverse kinematics) seize parts arriving on
a servitor conveyor and fit them onto an assembly jig while a third, welder
mechadendrite binds each joint in a shower of sparks.  The finished weapon is
shown as a rotating 3D wireframe while the Rite of Benediction is performed:
a censer swings, incense rises and a purity seal is affixed.  Then the next
opus begins (bolter, lasgun, plasma gun).
"""

from __future__ import annotations

import math
import random

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter

from ._common import CX, CY, H, W, Session, font, lerp_color, project, rotate_xyz, scale

NAME = "mechadendrite_assembly"

_rng = random.Random()
_session = Session()

JIG = (120.0, 108.0)
BELT_Y = 176.0
PICK_X = 150.0
PART_DT = 8.0            # seconds between parts
TASK = (1.4, 0.4, 2.0, 2.2, 0.4, 1.2)   # reach, grip, carry, fit, release, return
SHOW = 17.0              # benediction showcase length

# arm anchors (just outside the round panel) and rest tips
ANCHORS = [(4.0, 84.0), (236.0, 84.0), (150.0, 2.0)]
RESTS = [(62.0, 74.0), (178.0, 74.0), (150.0, 68.0)]
SEGS = [[34, 32, 30, 28, 26, 22], [34, 32, 30, 28, 26, 22], [30, 28, 26, 24, 22]]
BOW = [(0.2, -1.0), (-0.2, -1.0), (1.0, 0.2)]

# --------------------------------------------------------------------- weapons

def _P(name, polys, attach, depth, lines=()):
    xs = [p[0] for _, _, pts in polys for p in pts]
    ys = [p[1] for _, _, pts in polys for p in pts]
    return {"name": name, "polys": polys, "attach": attach, "depth": depth, "lines": list(lines),
            "c": ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2), "maxy": max(ys)}


_GUN = (70, 72, 82), (150, 150, 168)
_BRASS = (190, 145, 60), (240, 200, 110)
_WOOD = (112, 70, 40), (170, 115, 70)

WEAPONS = {
    "BOLTER": [
        _P("RECEIVER", [(*_GUN, [(-28, -11), (16, -11), (22, -6), (22, 8), (-28, 8)]),
                        (*_BRASS, [(8, -9), (16, -9), (16, -5), (8, -5)])], (0, 0), 7,
           [((35, 35, 42), [(-22, -4), (4, -4)]), ((35, 35, 42), [(-22, 3), (18, 3)])]),
        _P("BARREL", [((58, 58, 66), (140, 140, 150), [(22, -8), (48, -8), (48, -1), (22, -1)]),
                      (*_BRASS, [(48, -10), (56, -10), (56, 1), (48, 1)])], (22, -4), 3,
           [((30, 30, 34), [(30, -5), (44, -5)])]),
        _P("GRIP & STOCK", [(*_GUN, [(-28, -7), (-45, -3), (-47, 8), (-28, 8)]),
                            (*_GUN, [(-16, 8), (-8, 8), (-11, 23), (-19, 23)])], (-28, 1), 5),
        _P("SICKLE MAG", [((52, 52, 58), (130, 130, 140), [(0, 8), (10, 8), (13, 18), (10, 28), (3, 27), (5, 18)])],
           (5, 8), 4, [((170, 130, 60), [(4, 12), (10, 12)])]),
        _P("AUSPEX SIGHT", [((60, 62, 70), (150, 150, 165), [(-8, -11), (6, -11), (6, -17), (-4, -17)]),
                            ((180, 40, 30), (255, 90, 60), [(3, -16), (6, -16), (6, -12), (3, -12)])], (-1, -11), 3),
        _P("AQUILA", [(*_BRASS, [(-23, -4), (-14, 0), (-5, -4), (-8, 2), (-14, 5), (-20, 2)])], (-14, 0), 8),
    ],
    "LASGUN": [
        _P("RECEIVER", [((92, 98, 78), (165, 170, 140), [(-32, -9), (12, -9), (12, 5), (-32, 5)])], (0, 0), 6,
           [((50, 54, 44), [(-26, -3), (6, -3)])]),
        _P("BARREL SHROUD", [((70, 72, 62), (150, 150, 130), [(12, -10), (34, -10), (34, 3), (12, 3)]),
                             ((60, 60, 60), (130, 130, 130), [(34, -6), (54, -6), (54, -1), (34, -1)])], (12, -3), 4,
           [((35, 35, 30), [(16, -8), (16, 1)]), ((35, 35, 30), [(21, -8), (21, 1)]),
            ((35, 35, 30), [(26, -8), (26, 1)]), ((35, 35, 30), [(31, -8), (31, 1)])]),
        _P("STOCK", [(*_WOOD, [(-58, -5), (-32, -7), (-32, 5), (-50, 10), (-58, 10)])], (-32, -1), 5),
        _P("GRIP", [(*_WOOD, [(-25, 5), (-17, 5), (-20, 19), (-28, 19)])], (-21, 5), 4),
        _P("POWER PACK", [((48, 68, 48), (120, 160, 110), [(-6, 5), (10, 5), (10, 19), (-6, 19)]),
                          ((60, 230, 110), (160, 255, 180), [(0, 8), (4, 8), (4, 11), (0, 11)])], (2, 5), 5),
        _P("SIGHT", [((70, 70, 72), (150, 150, 150), [(-16, -9), (-2, -9), (-4, -14), (-14, -14)])], (-9, -9), 3),
    ],
    "PLASMA GUN": [
        _P("RECEIVER", [((62, 52, 74), (145, 125, 165), [(-26, -10), (10, -10), (10, 8), (-26, 8)])], (0, 0), 7,
           [((36, 30, 44), [(-20, 0), (6, 0)])]),
        _P("COIL CHAMBER", [((46, 58, 82), (120, 150, 200), [(10, -13), (32, -13), (32, 7), (10, 7)])], (10, -3), 8,
           [((80, 180, 255), [(14, -11), (14, 5)]), ((80, 180, 255), [(19, -11), (19, 5)]),
            ((80, 180, 255), [(24, -11), (24, 5)]), ((80, 180, 255), [(29, -11), (29, 5)])]),
        _P("BARREL", [((62, 62, 70), (140, 140, 150), [(32, -7), (49, -7), (49, 1), (32, 1)]),
                      (*_BRASS, [(49, -10), (55, -10), (55, 4), (49, 4)])], (32, -3), 4),
        _P("PLASMA FLASK", [((50, 110, 190), (140, 200, 255), [(-20, -19), (-4, -19), (-4, -10), (-20, -10)]),
                            ((150, 220, 255), (220, 245, 255), [(-17, -17), (-7, -17), (-7, -13), (-17, -13)])],
           (-12, -10), 5),
        _P("GRIP", [((62, 52, 74), (145, 125, 165), [(-18, 8), (-10, 8), (-13, 22), (-21, 22)])], (-14, 8), 4),
        _P("STOCK", [((62, 52, 74), (145, 125, 165), [(-26, -6), (-44, -2), (-45, 8), (-26, 8)])], (-26, 1), 5),
    ],
}
_ORDERS = ["BOLTER", "LASGUN", "PLASMA GUN"]
_BLESS = ["MACHINE SPIRIT: CONTENT", "MACHINE SPIRIT: APPEASED", "MACHINE SPIRIT: CONTENT"]


def _purity_seal() -> Image.Image:
    im = Image.new("RGBA", (30, 48), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    for x0, sk in ((9, -2), (15, 2)):
        d.polygon([(x0, 14), (x0 + 6, 14), (x0 + 6 + sk, 46), (x0 + sk, 46)], fill=(220, 205, 160, 255))
        for yy in range(20, 44, 4):
            d.line([(x0 + 1 + sk * (yy - 14) / 32, yy), (x0 + 4 + sk * (yy - 14) / 32, yy)], fill=(90, 60, 40, 255))
    d.ellipse([3, 1, 27, 25], fill=(150, 18, 18, 255), outline=(90, 8, 8, 255))
    d.ellipse([8, 6, 22, 20], outline=(210, 60, 50, 255))
    d.line([(10, 12), (15, 15), (20, 12)], fill=(220, 80, 60, 255), width=2)
    return im


_SEAL = _purity_seal()

# --------------------------------------------------------------------- helpers

def _ease(u):
    u = min(1.0, max(0.0, u))
    return u * u * (3 - 2 * u)


def _lerp(a, b, u):
    return (a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u)


def _bez(p0, p1, p2, u):
    a = _lerp(p0, p1, u)
    b = _lerp(p1, p2, u)
    return _lerp(a, b, u)


_F = np.linspace(0.0, 1.0, 40)
_SHAPE = 0.55 * np.sin(np.pi * _F) + 0.45 * np.sin(2 * np.pi * _F)
_DSHAPE = np.gradient(_SHAPE, _F)
_AMPS = np.linspace(0.0, 160.0, 96)


def _fabrik(joints, lengths, base, target, bow):
    total = sum(lengths)
    bx, by = base
    tx, ty = target
    dx, dy = tx - bx, ty - by
    dist = math.hypot(dx, dy)
    if dist > total * 0.985:
        k = total * 0.985 / dist
        tx, ty = bx + dx * k, by + dy * k
    n = len(joints)
    # Seed the solve with a sinuous S-curve whose arc length matches the arm, so
    # the dendrite snakes gracefully; it is a continuous function of the target.
    dist = math.hypot(tx - bx, ty - by) or 1e-3
    cxv, cyv = (tx - bx) / dist, (ty - by) / dist
    pxv, pyv = -cyv, cxv
    if pxv * bow[0] + pyv * bow[1] < 0:
        pxv, pyv = -pxv, -pyv
    lens = dist * np.sqrt(1.0 + (_DSHAPE[None, :] * _AMPS[:, None] / dist) ** 2).mean(axis=1)
    amp = float(np.interp(total, lens, _AMPS))
    px_ = bx + (tx - bx) * _F + pxv * amp * _SHAPE
    py_ = by + (ty - by) * _F + pyv * amp * _SHAPE
    seg = np.hypot(np.diff(px_), np.diff(py_))
    cum = np.concatenate(([0.0], np.cumsum(seg)))
    kk = cum[-1] / total
    acc = 0.0
    joints[0][0], joints[0][1] = bx, by
    for i in range(1, n):
        acc += lengths[i - 1] * kk
        joints[i][0] = float(np.interp(acc, cum, px_))
        joints[i][1] = float(np.interp(acc, cum, py_))
    for _ in range(3):
        joints[-1][0], joints[-1][1] = tx, ty
        for i in range(n - 2, -1, -1):
            ax, ay = joints[i][0] - joints[i + 1][0], joints[i][1] - joints[i + 1][1]
            L = math.hypot(ax, ay) or 1e-3
            joints[i][0] = joints[i + 1][0] + ax / L * lengths[i]
            joints[i][1] = joints[i + 1][1] + ay / L * lengths[i]
        joints[0][0], joints[0][1] = bx, by
        for i in range(n - 1):
            ax, ay = joints[i + 1][0] - joints[i][0], joints[i + 1][1] - joints[i][1]
            L = math.hypot(ax, ay) or 1e-3
            joints[i + 1][0] = joints[i][0] + ax / L * lengths[i]
            joints[i + 1][1] = joints[i][1] + ay / L * lengths[i]
        if math.hypot(joints[-1][0] - tx, joints[-1][1] - ty) < 0.4:
            break


def _draw_part(d, part, T, glow=0.0, dim=1.0):
    ox, oy = T
    for fill, outline, pts in part["polys"]:
        pp = [(ox + x, oy + y) for x, y in pts]
        oc = lerp_color(outline, (255, 150, 50), glow) if glow > 0 else outline
        d.polygon(pp, fill=scale(fill, dim), outline=scale(oc, dim))
    for col, pts in part["lines"]:
        d.line([(ox + x, oy + y) for x, y in pts], fill=scale(col, dim), width=1)


def _draw_ghost(d, part, T, col):
    ox, oy = T
    for _, _, pts in part["polys"]:
        pp = [(ox + x, oy + y) for x, y in pts]
        d.line(pp + [pp[0]], fill=col, width=1)


def _background() -> Image.Image:
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    rr = np.hypot(xx - CX, yy - CY)
    base = np.clip(1.0 - rr / 150.0, 0.15, 1.0)
    arr = np.stack([30 * base, 24 * base, 20 * base], -1).astype(np.uint8)
    img = Image.fromarray(arr, "RGB")
    d = ImageDraw.Draw(img)
    # great cog of the Omnissiah behind the jig
    cx, cy = JIG[0], JIG[1] - 4
    pts = []
    for i in range(18 * 4):
        a = 2 * math.pi * i / (18 * 4)
        r = 70 if (i % 4) in (1, 2) else 62
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    d.polygon(pts, outline=(52, 40, 28))
    d.ellipse([cx - 50, cy - 50, cx + 50, cy + 50], outline=(46, 36, 26))
    d.ellipse([cx - 20, cy - 20, cx + 20, cy + 20], outline=(40, 32, 24))
    # wall panel seams & rivets
    for x in (40, 200):
        d.line([(x, 30), (x, 170)], fill=(18, 14, 12))
    for x, y in ((46, 60), (46, 150), (194, 60), (194, 150), (120, 30)):
        d.ellipse([x - 1.5, y - 1.5, x + 1.5, y + 1.5], fill=(80, 64, 44))
    # jig cradle
    jx, jy = JIG
    d.rectangle([jx - 62, jy + 34, jx + 62, jy + 38], fill=(60, 50, 38), outline=(110, 90, 60))
    for px in (-24, 18):
        d.rectangle([jx + px - 3, jy + 9, jx + px + 3, jy + 34], fill=(50, 42, 34), outline=(100, 84, 56))
        d.rectangle([jx + px - 6, jy + 7, jx + px + 6, jy + 10], fill=(120, 96, 52))
    # conveyor frame + hazard stripes
    d.rectangle([20, BELT_Y + 11, 220, BELT_Y + 20], fill=(30, 26, 22))
    for x in range(10, 230, 10):
        d.polygon([(x, BELT_Y + 12), (x + 5, BELT_Y + 12), (x + 1, BELT_Y + 19), (x - 4, BELT_Y + 19)],
                  fill=(150, 120, 20))
    return img


# --------------------------------------------------------------------- state

_S: dict = {}


def _new_build(kind=None):
    s = _S
    if kind is None:
        opts = [k for k in _ORDERS if k != s.get("kind")]
        kind = _rng.choice(opts)
    s["kind"] = kind
    s["parts"] = WEAPONS[kind]
    s["first_arm"] = _rng.randint(0, 1)
    s["seal_pos"] = (JIG[0] + _rng.uniform(40, 50), JIG[1] + _rng.uniform(24, 30))
    s["bless"] = _rng.choice(_BLESS)
    s["tilt"] = _rng.uniform(0.2, 0.45)
    s["spin"] = _rng.choice((-1.0, 1.0)) * _rng.uniform(0.8, 1.1)
    np_parts = len(s["parts"])
    s["show0"] = (np_parts - 1) * PART_DT + 2.0 + sum(TASK[:5]) + 0.6
    s["total"] = s["show0"] + SHOW
    s["build_start"] = s.get("t", 0.0)
    s["serial"] = _rng.randint(100, 999)


def _reset():
    _S.clear()
    _S["bg"] = _background()
    _S["joints"] = []
    for a in range(3):
        bx, by = ANCHORS[a]
        rx, ry = RESTS[a]
        n = len(SEGS[a]) + 1
        _S["joints"].append([[bx + (rx - bx) * i / (n - 1), by + (ry - by) * i / (n - 1)] for i in range(n)])
    _S["np"] = np.random.default_rng(_rng.getrandbits(32))
    m = 140
    _S["spk"] = {k: np.zeros(m, np.float32) for k in ("x", "y", "vx", "vy", "age", "life")}
    _S["spk"]["age"][:] = 9
    _S["spk"]["life"][:] = 1
    _S["spk_next"] = 0
    m = 260
    _S["smk"] = {k: np.zeros(m, np.float32) for k in ("x", "y", "vx", "vy", "age", "life")}
    _S["smk"]["age"][:] = 9
    _S["smk"]["life"][:] = 1
    _S["smk_next"] = 0
    _S["belt"] = 0.0
    _S["last_t"] = 0.0
    _S["t"] = 0.0
    _S["censer_phi"] = 0.0
    _new_build(_rng.choice(_ORDERS))


def _task_times(k):
    s0 = k * PART_DT + 2.0
    out, acc = [], s0
    for dtk in TASK:
        out.append((acc, acc + dtk))
        acc += dtk
    return out


def _part_world_target(part):
    return JIG


def _pickup_T(part):
    return (PICK_X - part["c"][0], BELT_Y - part["maxy"])


def _grip_tip_from_T(part, T):
    return (T[0] + part["c"][0], T[1] + part["c"][1] - 7)


def _spawn(pool, key, n, x, y, vx, vy, life):
    s = _S
    p = s[pool]
    m = p["x"].shape[0]
    n = min(n, m)
    if n <= 0:
        return
    ids = (np.arange(n) + s[key]) % m
    s[key] = int((s[key] + n) % m)
    p["x"][ids] = x
    p["y"][ids] = y
    p["vx"][ids] = vx
    p["vy"][ids] = vy
    p["age"][ids] = 0.0
    p["life"][ids] = life


# --------------------------------------------------------------------- render

def render(bezel, mask, now: float) -> Image.Image:
    if _session.fresh(now) or not _S:
        _reset()
    t = _session.t(now)
    s = _S
    s["t"] = t
    dt = max(0.0, min(0.1, t - s["last_t"]))
    s["last_t"] = t
    bt = t - s["build_start"]
    if bt >= s["total"]:
        _new_build()
        s["build_start"] = t
        bt = 0.0
    parts = s["parts"]
    npart = len(parts)
    rng = s["np"]
    show = bt - s["show0"]

    img = s["bg"].copy()
    d = ImageDraw.Draw(img)

    # ---------------- per-part state
    tips = [None, None, None]
    grips = [1.0, 1.0]
    carried = [None, None]
    placed = []
    on_belt = []
    fitting = None
    belt_moving = False
    status = "AWAITING COMPONENT"
    for k, part in enumerate(parts):
        arm = (k + s["first_arm"]) % 2
        tt = _task_times(k)
        a0 = k * PART_DT
        pickT = _pickup_T(part)
        tip_pick = _grip_tip_from_T(part, pickT)
        tip_fit = _grip_tip_from_T(part, JIG)
        rest = RESTS[arm]
        if bt < a0:
            continue
        if bt < tt[1][1]:  # on belt until gripped
            u = (bt - a0) / 2.0
            if u < 1.0:
                belt_moving = True
                x = 250 + (PICK_X - 250) * (1 - (1 - u) ** 2)
                on_belt.append((part, (x - part["c"][0], pickT[1])))
                status = "COMPONENT INBOUND"
            else:
                on_belt.append((part, pickT))
        if tt[0][0] <= bt < tt[5][1]:
            if bt < tt[0][1]:
                u = _ease((bt - tt[0][0]) / TASK[0])
                tips[arm] = _lerp(rest, tip_pick, u)
                grips[arm] = 1.0
                status = f"SEIZING {part['name']}"
            elif bt < tt[1][1]:
                tips[arm] = tip_pick
                grips[arm] = 1.0 - (bt - tt[1][0]) / TASK[1]
                status = f"SEIZING {part['name']}"
            elif bt < tt[2][1]:
                u = _ease((bt - tt[2][0]) / TASK[2])
                hover = (tip_fit[0], tip_fit[1] - 14)
                ctrl = ((tip_pick[0] + hover[0]) / 2, min(tip_pick[1], hover[1]) - 60)
                tips[arm] = _bez(tip_pick, ctrl, hover, u)
                grips[arm] = 0.0
                carried[arm] = part
                status = f"CARRYING {part['name']}"
            elif bt < tt[3][1]:
                u = (bt - tt[3][0]) / TASK[3]
                dy = 14 * (1 - _ease(u / 0.3))
                jit = 0.6 * math.sin(bt * 40) if 0.3 < u < 0.9 else 0.0
                tips[arm] = (tip_fit[0] + jit, tip_fit[1] - dy)
                grips[arm] = 0.0
                carried[arm] = part
                fitting = (k, part, u)
                status = f"FITTING {part['name']}"
            elif bt < tt[4][1]:
                tips[arm] = tip_fit
                grips[arm] = (bt - tt[4][0]) / TASK[4]
                placed.append((k, part))
            else:
                u = _ease((bt - tt[5][0]) / TASK[5])
                up = (tip_fit[0], tip_fit[1] - 20)
                tips[arm] = _bez(tip_fit, up, rest, u)
                grips[arm] = 1.0
                placed.append((k, part))
        elif bt >= tt[5][1]:
            placed.append((k, part))

    if belt_moving:
        s["belt"] += dt * 55.0

    # ---------------- showcase choreography
    showing = show >= 0
    censer = None
    if showing:
        placed = list(enumerate(parts))
        sway = math.sin(t * 1.1)
        if show > 1.2:
            tips[0] = (120 + 34 * sway, 44 + 4 * math.cos(t * 2.2))
            censer = True
        tips[1] = (158 + 4 * math.sin(t * 0.7), 54 + 3 * math.sin(t * 1.3))
        grips[0] = 0.0
        grips[1] = 0.6

    # welder mechadendrite
    weld_pt = None
    wtip = None
    for k, part in enumerate(parts):
        tt = _task_times(k)
        wp = (JIG[0] + part["attach"][0], JIG[1] + part["attach"][1])
        hov = (wp[0] + 10, wp[1] - 14)
        if tt[2][0] + 1.0 <= bt < tt[3][0]:
            u = _ease((bt - tt[2][0] - 1.0) / (TASK[2] - 1.0))
            wtip = _lerp(RESTS[2], hov, u)
        elif tt[3][0] <= bt < tt[3][1]:
            u = (bt - tt[3][0]) / TASK[3]
            if 0.2 < u < 0.92:
                wtip = (wp[0] + 2 + 1.5 * math.sin(bt * 23), wp[1] - 2 + 1.5 * math.cos(bt * 17))
                if u > 0.3:
                    weld_pt = wp
            else:
                wtip = hov
        elif tt[3][1] <= bt < tt[3][1] + 1.2:
            u = _ease((bt - tt[3][1]) / 1.2)
            wtip = _lerp(hov, RESTS[2], u)
    if wtip is None:
        wtip = (RESTS[2][0] + 3 * math.sin(t * 0.9), RESTS[2][1] + 4 * math.sin(t * 0.6 + 1))
    tips[2] = wtip
    for a in range(2):
        if tips[a] is None:
            tips[a] = (RESTS[a][0] + 4 * math.sin(t * 0.8 + a * 2), RESTS[a][1] + 5 * math.sin(t * 0.55 + a))

    for a in range(3):
        _fabrik(s["joints"][a], SEGS[a], ANCHORS[a], tips[a], BOW[a])

    # ---------------- conveyor
    off = s["belt"] % 12
    d.rectangle([24, BELT_Y, 216, BELT_Y + 9], fill=(40, 36, 32), outline=(90, 78, 60))
    x = 24 + (12 - off)
    while x < 216:
        d.line([(x, BELT_Y + 1), (x, BELT_Y + 8)], fill=(66, 58, 48))
        x += 12
    for rx in (30, 210):
        d.ellipse([rx - 6, BELT_Y - 1, rx + 6, BELT_Y + 11], fill=(70, 60, 46), outline=(140, 116, 70))
        a = s["belt"] / 6.0
        d.line([(rx, BELT_Y + 5), (rx + 5 * math.cos(a), BELT_Y + 5 + 5 * math.sin(a))], fill=(170, 140, 80))

    # ---------------- weapon on the jig
    if showing and show >= 3.0:
        _draw_wire(d, parts, show, s)
    else:
        placed_ids = {k for k, _ in placed}
        if not showing:
            for k, part in enumerate(parts):
                if k not in placed_ids and (fitting is None or fitting[0] != k):
                    _draw_ghost(d, part, JIG, (26, 70, 88))
        for k, part in placed:
            glow = 0.0
            tt = _task_times(k)
            since = bt - tt[3][1]
            if since < 2.0:
                glow = max(0.0, 1.0 - since / 2.0)
            if showing:
                glow = max(0.0, 1.0 - show / 1.2) if int(show * 6) % 2 == 0 else 0.0
            _draw_part(d, part, JIG, glow)

    # parts on belt
    for part, T in on_belt:
        _draw_part(d, part, T)

    # ---------------- arms (welder first so grippers are on top)
    _draw_arm(d, s["joints"][2], "weld", 0.0, weld_pt is not None, t)
    for a in (0, 1):
        _draw_arm(d, s["joints"][a], "grip", grips[a], False, t)
        if carried[a] is not None:
            tip = s["joints"][a][-1]
            part = carried[a]
            T = (tip[0] - part["c"][0], tip[1] - part["c"][1] + 7)
            glow = 0.0
            if fitting and fitting[1] is part:
                glow = min(1.0, fitting[2] * 1.5)
            _draw_part(d, part, T, glow)

    # censer on the left dendrite
    orb = None
    if censer:
        tip = s["joints"][0][-1]
        phi = 0.55 * math.sin(t * 2.1 + 0.6)
        orb = (tip[0] + 17 * math.sin(phi), tip[1] + 17 * math.cos(phi))
        d.line([tip, orb], fill=(150, 130, 90), width=1)
        d.ellipse([orb[0] - 5, orb[1] - 4, orb[0] + 5, orb[1] + 5], fill=(170, 130, 55), outline=(230, 190, 110))
        d.line([(orb[0] - 3, orb[1]), (orb[0] + 3, orb[1])], fill=(255, 150, 60))
        if show < SHOW - 1.5 and rng.random() < 0.9:
            nn = 1 + int(rng.random() * 2)
            _spawn("smk", "smk_next", nn, orb[0], orb[1] - 3,
                    rng.normal(0, 5, nn), rng.uniform(-24, -14, nn), rng.uniform(2.5, 4.5, nn))

    # ---------------- sparks
    if weld_pt is not None:
        nn = int(rng.integers(2, 6))
        ang = rng.uniform(-math.pi, 0.2, nn)
        sp = rng.uniform(40, 140, nn)
        _spawn("spk", "spk_next", nn, weld_pt[0], weld_pt[1], np.cos(ang) * sp, np.sin(ang) * sp,
               rng.uniform(0.25, 0.7, nn))
    sp = s["spk"]
    live = sp["age"] < sp["life"]
    if live.any():
        sp["vy"][live] += 320 * dt
        sp["x"][live] += sp["vx"][live] * dt
        sp["y"][live] += sp["vy"][live] * dt
        sp["age"][live] += dt
        for i in np.nonzero(live)[0]:
            x, y = float(sp["x"][i]), float(sp["y"][i])
            k = float(sp["age"][i] / sp["life"][i])
            col = lerp_color((255, 250, 200), (255, 110, 20), k * 1.4)
            d.line([(x, y), (x - sp["vx"][i] * 0.025, y - sp["vy"][i] * 0.025)], fill=col, width=1)
    if weld_pt is not None:
        r = 2.5 + 2.5 * rng.random()
        d.ellipse([weld_pt[0] - r, weld_pt[1] - r, weld_pt[0] + r, weld_pt[1] + r], fill=(255, 245, 220))

    # ---------------- incense smoke (additive, soft)
    sm = s["smk"]
    live = sm["age"] < sm["life"]
    if live.any():
        sm["vx"][live] += rng.normal(0, 14, int(live.sum())) * dt
        sm["x"][live] += sm["vx"][live] * dt
        sm["y"][live] += sm["vy"][live] * dt
        sm["age"][live] += dt
        li = np.nonzero(live)[0]
        qx = (sm["x"][li] / 2).astype(np.int32)
        qy = (sm["y"][li] / 2).astype(np.int32)
        wv = (1.0 - sm["age"][li] / sm["life"][li]) * 60.0
        ok = (qx >= 0) & (qx < W // 2) & (qy >= 0) & (qy < H // 2)
        acc = np.bincount(qy[ok] * (W // 2) + qx[ok], weights=wv[ok], minlength=(W // 2) * (H // 2))
        L = Image.fromarray(np.clip(acc, 0, 255).astype(np.uint8).reshape(H // 2, W // 2), "L")
        L = L.filter(ImageFilter.GaussianBlur(2.5)).resize((W, H), Image.BILINEAR)
        img = ImageChops.add(img, Image.merge("RGB", (L, L.point(lambda v: v * 0.9), L.point(lambda v: v * 0.75))))
        d = ImageDraw.Draw(img)

    # ---------------- purity seal & benediction
    if showing and show >= 7.5:
        u = min(1.0, (show - 7.5) / 0.35)
        sc = 2.0 - 1.2 * _ease(u)
        seal = _SEAL.resize((max(1, int(30 * sc)), max(1, int(48 * sc))), Image.BILINEAR)
        sx, sy = s["seal_pos"]
        img.paste(seal, (int(sx - seal.width / 2), int(sy - 13 * sc)), seal)
        d = ImageDraw.Draw(img)

    # ---------------- HUD
    f10, f9 = font(10), font(9)
    title = f"OPUS: {s['kind']}"
    tw = d.textlength(title, font=f10)
    d.text((CX - tw / 2, 20), title, fill=(220, 180, 100), font=f10)
    n_done = len([1 for _ in placed]) if not showing else npart
    pw = npart * 9
    for i in range(npart):
        x0 = CX - pw / 2 + i * 9
        col = (220, 180, 100) if i < n_done else (60, 50, 36)
        d.rectangle([x0, 34, x0 + 6, 38], fill=col)

    if showing:
        if show < 3.0:
            status, scol = "ASSEMBLY COMPLETE", (120, 255, 150)
        elif show < 6.0:
            status, scol = "RITE OF BENEDICTION", (230, 200, 120)
        elif show < SHOW - 2.0:
            full = s["bless"]
            n = int((show - 6.0) * 18)
            status, scol = full[:max(1, n)], (120, 255, 150)
        else:
            nxt = [k for k in _ORDERS if k != s["kind"]]
            status, scol = "NEXT OPUS PENDING", (200, 170, 110)
    else:
        scol = (255, 170, 70) if status.startswith("FITTING") else (200, 190, 170)
    fs = f10 if d.textlength(status, font=f10) < 150 else f9
    sw = d.textlength(status, font=fs)
    d.text((CX - sw / 2, 194), status, fill=scol, font=fs)
    if showing and show >= 7.5:
        sub = "PURITY SEAL AFFIXED"
    else:
        sub = f"FORGE CELL {s['serial']} +++ TORQ {40 + int(12 * math.sin(t * 1.3)):02d}"
    sw = d.textlength(sub, font=f9)
    d.text((CX - sw / 2, 207), sub, fill=(120, 100, 70), font=f9)
    return img


def _draw_arm(d, joints, kind, grip, active, t):
    pts = [(j[0], j[1]) for j in joints]
    d.line(pts, fill=(40, 30, 22), width=8, joint="curve")
    d.line(pts, fill=(120, 92, 54), width=5, joint="curve")
    d.line(pts, fill=(190, 150, 90), width=1)
    for i, (x, y) in enumerate(pts[:-1]):
        r = 4.5 if i == 0 else 3.5
        d.ellipse([x - r, y - r, x + r, y + r], fill=(56, 50, 46), outline=(200, 160, 90))
        if i:
            d.point((x, y), fill=(255, 80, 40))
    tx, ty = pts[-1]
    px, py = pts[-2]
    ux, uy = tx - px, ty - py
    L = math.hypot(ux, uy) or 1.0
    ux, uy = ux / L, uy / L
    vx, vy = -uy, ux
    if kind == "grip":
        a = 0.25 + 0.6 * grip
        for sgn in (1, -1):
            c, s_ = math.cos(a), math.sin(a) * sgn
            k1 = (tx + (ux * c - vx * s_ * -1) * 0, ty)
            mx = tx + 7 * (ux * c + vx * s_)
            my = ty + 7 * (uy * c + vy * s_)
            ex = mx + 6 * ux - vx * sgn * 2.5 * (1 - grip)
            ey = my + 6 * uy - vy * sgn * 2.5 * (1 - grip)
            d.line([(tx, ty), (mx, my), (ex, ey)], fill=(200, 190, 170), width=2)
        d.ellipse([tx - 3, ty - 3, tx + 3, ty + 3], fill=(90, 80, 70), outline=(210, 180, 120))
    else:
        nx, ny = tx + ux * 8, ty + uy * 8
        d.line([(tx, ty), (nx, ny)], fill=(140, 140, 150), width=4)
        d.line([(tx, ty), (nx, ny)], fill=(200, 200, 210), width=1)
        if active:
            d.ellipse([nx - 3, ny - 3, nx + 3, ny + 3], fill=(200, 230, 255))
        else:
            d.ellipse([nx - 2, ny - 2, nx + 2, ny + 2], fill=(90, 60, 40))


def _draw_wire(d, parts, show, s):
    ay = (show - 3.0) * s["spin"] + 0.0
    ax = s["tilt"] * math.sin((show - 3.0) * 0.6)
    fade_in = min(1.0, (show - 3.0) / 1.0)
    fade_out = min(1.0, max(0.0, (SHOW - show) / 1.5))
    k = fade_in * fade_out
    if k <= 0:
        return
    cx0 = -4.0
    for part in parts:
        dz = part["depth"]
        for _, _, pts in part["polys"]:
            front, back = [], []
            ok = True
            for x, y in pts:
                for z, lst in ((dz, front), (-dz, back)):
                    p = rotate_xyz(((x - cx0) * 1.25, y * 1.25, z * 1.25), ax, ay)
                    q = project(p, fov=200.0, cam_dist=210.0)
                    if q is None:
                        ok = False
                        break
                    lst.append((q[0], q[1] - 12, q[2]))
            if not ok:
                continue
            zf = sum(p[2] for p in front) / len(front)
            zb = sum(p[2] for p in back) / len(back)
            for lst, zz in ((back, zb), (front, zf)):
                b = max(0.35, min(1.0, 1.4 - (zz - 180) / 60.0)) * k
                col = scale((90, 255, 170), b)
                xy = [(p[0], p[1]) for p in lst]
                d.line(xy + [xy[0]], fill=col, width=1)
            colc = scale((60, 190, 130), 0.7 * k)
            for p, q in zip(front, back):
                d.line([(p[0], p[1]), (q[0], q[1])], fill=colc, width=1)
