"""Inquisitorial Dossier – an Ordo cogitator assembles a case, then judgement falls.

On a green-phosphor link-map, procedurally sketched suspect pict-captures (faces,
hoods, augmetics, scars, rebreathers) are scanned in one stroke at a time inside
bracketed pict frames. Evidence tags come up and data links run from each to the
suspects it implicates, pulses travelling along them. When the web converges, the
prime suspect's pict is pulled to the centre, the witch-sign on the brow is
revealed and an EXCOMMUNICATE TRAITORIS alarm banner slams across it. The screen
then fades and a new case opens.
"""

from __future__ import annotations

import math
import random

import numpy as np
from PIL import Image, ImageDraw

from ..classic._phosphor import AMBER, GREEN, GREEN_DIM, GREEN_FAINT, GREEN_HI, GREEN_MID, RED as ALARM, Phosphor
from ._common import CX, CY, Session, font, safe_half_width

NAME = "inquisitorial_dossier"

_rng = random.Random()
_session = Session()

INK = GREEN            # portrait strokes: green line art on the black pict frame
PARCH = (0, 0, 0)
RED = ALARM
_ph = Phosphor(decay=0.45, bloom=0.55, flicker=0.03)

SURNAMES = ["KESSLER", "VORNE", "HALDEX", "MORDANT", "SKARL", "VANTE", "OKKAR", "DREMMEL", "CASSIUS", "IVRAIN",
            "THRASK", "MALVOR", "SYLLA", "KORDAN", "BEX", "ORLOCK", "ZANDER", "HELGAR", "QUILL", "RASK"]
ROLES = ["SCRIBE", "ADEPT", "MERCHANT", "PREACHER", "NOBLE", "GUARDSMAN", "TECH-ADEPT", "SERVANT", "ARBITRATOR",
         "HAB-WORKER", "RIGGER", "ASTROPATH"]
EVIDENCE = [("HERETICAL", "TEXTS"), ("XENOS", "ARTEFACT"), ("WITCH-SIGN", "SIGHTED"), ("FORBIDDEN", "TOME"),
            ("CULT", "MARKINGS"), ("BLOOD", "RITES"), ("ENCRYPTED", "VOX-LOG"), ("WARP", "RESIDUE"),
            ("GENE-SCAN:", "MUTANT"), ("TAINTED", "RELIC"), ("DAEMON", "SIGIL"), ("SMUGGLED", "XENOTECH"),
            ("WITNESS", "TESTIMONY"), ("PICT", "CAPTURE"), ("ILLICIT", "CREDITS"), ("PSYKER", "SCAN +")]
STATUS = ["CROSS-REFERENCING...", "INTERROGATION: 3RD DEGREE", "AUDITING TITHE-ROLLS", "SERVO-SKULL SURVEILLANCE",
          "ASTROPATHIC QUERY SENT", "EXCRUCIATION SANCTIONED", "SIFTING VOX-TRAFFIC", "CONFESSION EXTRACTED",
          "HERESY PATTERN MATCH", "WARRANT OF THE ORDO"]
INQUISITORS = ["GREYFAX", "RAVENOR", "EISENHORN", "CZEVAK", "KARAMAZOV", "VARL", "HAND", "ROTH", "SEVASTUS"]
ORDOS = ["HERETICUS", "MALLEUS", "XENOS"]
SENTENCES = ["SENTENCE: DEATH", "SENTENCE: PURGATION", "TO THE PENAL LEGION", "SENTENCE: BURNING"]

# ── cached text ─────────────────────────────────────────────────────────────
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


def _text(img, x, y, text, fill, size, shadow=None):
    m, w = _tsprite(text, size)
    if shadow is not None:
        img.paste(shadow, (int(x) + 1, int(y) + 1), m)
    img.paste(fill, (int(x), int(y)), m)
    return w


def _fit(img, y, text, fill, size, shadow=None):
    hw = safe_half_width(y + size * 0.6, 4)
    while size > 9 and _tsprite(text, size)[1] > 2 * hw:
        size -= 1
    w = _tsprite(text, size)[1]
    _text(img, CX - w / 2, y, text, fill, size, shadow)


# ── static art ──────────────────────────────────────────────────────────────


def _rosette(size=22):
    """The Inquisition's I with a skull at its heart, as phosphor line art."""
    s = 4
    im = Image.new("RGBA", (size * s, size * s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    c = size * s / 2
    R = c - 2
    d.ellipse([c - R, c - R, c + R, c + R], outline=GREEN_MID + (255,), width=s)
    hi = GREEN + (255,)
    d.rectangle([c - 2 * s, c - R * 0.76, c + 2 * s, c + R * 0.76], outline=hi, width=s)
    for yy in (-0.62, 0.62):
        w = R * 0.62
        d.rectangle([c - w, c + yy * R - 1.2 * s, c + w, c + yy * R + 1.2 * s], outline=hi, width=s)
    d.ellipse([c - 3.6 * s, c - 3.8 * s, c + 3.6 * s, c + 2.6 * s], fill=(0, 0, 0, 255), outline=GREEN_HI + (255,), width=s)
    d.ellipse([c - 2.4 * s, c - 1.6 * s, c - 0.8 * s, c + 0.0 * s], fill=GREEN_HI + (255,))
    d.ellipse([c + 0.8 * s, c - 1.6 * s, c + 2.4 * s, c + 0.0 * s], fill=GREEN_HI + (255,))
    return im.resize((size, size), Image.LANCZOS)


_ROSETTE = _rosette(24)


def _board(rng):
    """Black link-map: a faint grid and scattered node marks from other cases."""
    img = Image.new("RGB", (240, 240), (0, 0, 0))
    d = ImageDraw.Draw(img)
    for x in range(0, 240, 16):
        for y in range(0, 240, 16):
            d.point((x, y), fill=GREEN_FAINT)
    for _ in range(14):
        x, y = rng.randint(30, 210), rng.randint(60, 200)
        d.rectangle([x - 1, y - 1, x + 1, y + 1], outline=GREEN_FAINT)
    return img


# ── portraits ───────────────────────────────────────────────────────────────


def _portrait_strokes(rng):
    """Return a list of drawing closures (in an 80x80 space) for a suspect."""
    S = []
    cx = 40 + rng.uniform(-2, 2)
    cy = 36 + rng.uniform(-2, 2)
    hw = rng.uniform(12, 16)
    hh = rng.uniform(16, 20)
    hood = rng.random() < 0.35
    aug_eye = rng.random() < 0.4
    aug_side = rng.choice([-1, 1])
    rebreather = rng.random() < 0.22
    scar = rng.random() < 0.4
    cables = rng.random() < 0.3 and not hood
    beard = rng.random() < 0.3 and not rebreather
    hair = rng.choice(["bald", "short", "mohawk", "long", "topknot"]) if not hood else None
    w = 2
    # shoulders
    S.append(lambda d: d.line([(4, 80), (14, 64), (cx - 8, 60), (cx, 62), (cx + 8, 60), (66, 64), (76, 80)],
                              fill=INK, width=w))
    S.append(lambda d: d.line([(cx - 7, cy + hh - 3), (cx - 7, 60)], fill=INK, width=w))
    S.append(lambda d: d.line([(cx + 7, cy + hh - 3), (cx + 7, 60)], fill=INK, width=w))
    # head
    jaw = rng.uniform(0.55, 0.85)
    pts = []
    for k in range(25):
        a = math.pi + k / 24 * math.pi
        pts.append((cx + math.cos(a) * hw, cy + math.sin(a) * hh * 0.9))
    pts += [(cx + hw * 0.95, cy + hh * 0.35), (cx + hw * jaw, cy + hh * 0.85), (cx, cy + hh),
            (cx - hw * jaw, cy + hh * 0.85), (cx - hw * 0.95, cy + hh * 0.35), pts[0]]
    S.append(lambda d, p=pts: d.line(p, fill=INK, width=w))
    if hood:
        peak = cy - hh - rng.uniform(8, 14)
        hp = [(8, 80), (12, 58), (cx - hw - 7, cy - 4), (cx - hw * 0.4, peak + 6), (cx, peak),
              (cx + hw * 0.4, peak + 6), (cx + hw + 7, cy - 4), (68, 58), (72, 80)]
        S.append(lambda d, p=hp: d.line(p, fill=INK, width=w))
        S.append(lambda d: [d.line([(cx - hw - 3 + k * 2, cy - hh * 0.5 + k * 3), (cx - hw + 1 + k * 2, cy - hh * 0.5 + k * 3 - 4)],
                                   fill=INK, width=1) for k in range(5)])
    elif hair == "short":
        S.append(lambda d: d.arc([cx - hw - 1, cy - hh - 2, cx + hw + 1, cy + hh * 0.3], 190, 350, fill=INK, width=w + 1))
    elif hair == "mohawk":
        S.append(lambda d: [d.line([(cx - 2 + k % 2 * 4, cy - hh + 1), (cx - 1 + k % 2 * 2, cy - hh - 8 + k % 3)], fill=INK, width=w)
                            for k in range(5)])
    elif hair == "long":
        S.append(lambda d: d.line([(cx - hw - 1, cy + hh * 0.6), (cx - hw - 2, cy - hh * 0.6), (cx - hw * 0.3, cy - hh - 2),
                                   (cx + hw * 0.6, cy - hh - 1), (cx + hw + 2, cy - hh * 0.5), (cx + hw + 1, cy + hh * 0.6)],
                                  fill=INK, width=w))
    elif hair == "topknot":
        S.append(lambda d: d.ellipse([cx - 4, cy - hh - 8, cx + 4, cy - hh + 1], outline=INK, width=w))
    else:  # bald with a tattoo
        S.append(lambda d: d.line([(cx - 4, cy - hh + 6), (cx, cy - hh + 2), (cx + 4, cy - hh + 6)], fill=INK, width=1))
    ey = cy - hh * 0.12
    ex = hw * 0.45
    brow = rng.uniform(-3, 3)
    S.append(lambda d: d.line([(cx - ex - 5, ey - 5 + brow), (cx - ex + 4, ey - 4 - brow)], fill=INK, width=w))
    S.append(lambda d: d.line([(cx + ex - 4, ey - 4 - brow), (cx + ex + 5, ey - 5 + brow)], fill=INK, width=w))
    for side in (-1, 1):
        if aug_eye and side == aug_side:
            S.append(lambda d, s=side: (d.ellipse([cx + s * ex - 5, ey - 5, cx + s * ex + 5, ey + 5], outline=INK, width=w),
                                        d.ellipse([cx + s * ex - 2, ey - 2, cx + s * ex + 2, ey + 2], fill=AMBER),
                                        d.line([(cx + s * ex + s * 5, ey), (cx + s * (hw + 3), ey + 2)], fill=INK, width=1)))
        else:
            S.append(lambda d, s=side: (d.line([(cx + s * ex - 3, ey), (cx + s * ex + 3, ey)], fill=INK, width=w),
                                        d.point((cx + s * ex, ey + 1), fill=INK)))
    S.append(lambda d: d.line([(cx, ey + 1), (cx - 2, ey + 9), (cx + 2, ey + 10)], fill=INK, width=w))
    my = cy + hh * 0.52
    if rebreather:
        S.append(lambda d: (d.rectangle([cx - 7, my - 4, cx + 7, my + 5], outline=INK, width=w),
                            [d.line([(cx - 4 + k * 3, my - 2), (cx - 4 + k * 3, my + 3)], fill=INK, width=1) for k in range(4)],
                            d.line([(cx + 7, my + 2), (cx + hw + 6, my + 10), (cx + hw + 8, 62)], fill=INK, width=1)))
    else:
        curve = rng.uniform(-2, 2)
        S.append(lambda d: d.line([(cx - 6, my), (cx, my + curve), (cx + 6, my)], fill=INK, width=w))
    if beard:
        S.append(lambda d: [d.line([(cx - hw * 0.7 + k * hw * 0.2, cy + hh * 0.7), (cx - hw * 0.6 + k * hw * 0.18, cy + hh + 5)],
                                   fill=INK, width=1) for k in range(8)])
    if scar:
        sx = rng.choice([-1, 1])
        S.append(lambda d: (d.line([(cx + sx * ex - 6 * sx, ey - 10), (cx + sx * ex + 6 * sx, ey + 12)], fill=GREEN_MID, width=w),
                            [d.line([(cx + sx * ex - 6 * sx + k * 3 * sx - 2, ey - 8 + k * 5), (cx + sx * ex - 6 * sx + k * 3 * sx + 2, ey - 8 + k * 5)],
                                    fill=GREEN_MID, width=1) for k in range(4)]))
    if cables:
        side = -aug_side if aug_eye else rng.choice([-1, 1])
        S.append(lambda d: (d.line([(cx + side * hw, cy - 4), (cx + side * (hw + 7), cy + 8), (cx + side * (hw + 6), 60)], fill=INK, width=1),
                            d.line([(cx + side * hw, cy + 1), (cx + side * (hw + 4), cy + 12), (cx + side * (hw + 2), 60)], fill=INK, width=1),
                            d.rectangle([cx + side * hw - 2, cy - 6, cx + side * hw + 2, cy + 3], fill=INK)))
    brand = (cx, cy - hh * 0.55)
    return S, brand


def _chaos_star(d, x, y, r, col):
    for k in range(8):
        a = k * math.pi / 4
        d.line([(x, y), (x + math.cos(a) * r, y + math.sin(a) * r)], fill=col, width=2)
    d.ellipse([x - r * 0.35, y - r * 0.35, x + r * 0.35, y + r * 0.35], outline=col, width=1)


CARD_W, CARD_H = 46, 60


def _brackets(d, x0, y0, x1, y1, col, k=6):
    for (x, y, dx, dy) in ((x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)):
        d.line([(x, y + dy * k), (x, y), (x + dx * k, y)], fill=col)


def _render_suspect_card(sp, nstrokes, brand=False):
    big = Image.new("RGB", (80, 80), (0, 0, 0))
    d = ImageDraw.Draw(big)
    for f in sp["strokes"][:nstrokes]:
        f(d)
    if brand:
        _chaos_star(d, sp["brand"][0], sp["brand"][1], 6, RED)
    portrait = big.resize((38, 38), Image.LANCZOS)
    card = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 255))
    cd = ImageDraw.Draw(card)
    card.paste(portrait, (4, 5))
    if nstrokes < len(sp["strokes"]):                      # the pict-scan line sweeps down
        sy = 5 + int(38 * nstrokes / max(1, len(sp["strokes"])))
        cd.line([(4, sy), (41, sy)], fill=GREEN_HI + (255,))
    _brackets(cd, 2, 3, 43, 44, GREEN_MID + (255,))
    nm = sp["name"]
    m, w = _tsprite(nm, 9)
    card.paste(GREEN_HI + (255,), (int(CARD_W / 2 - w / 2), 46), m)
    return card


def _render_evidence(ev, rng):
    a, b = ev
    w = 58
    card = Image.new("RGBA", (w, 24), (0, 0, 0, 255))
    cd = ImageDraw.Draw(card)
    cd.rectangle([0, 0, w - 1, 23], outline=GREEN_DIM + (255,))
    cd.rectangle([0, 0, 2, 23], fill=GREEN_MID + (255,))
    for i, s in enumerate((a, b)):
        m, tw = _tsprite(s, 9)
        card.paste((GREEN if i == 0 else GREEN_MID) + (255,), (int(w / 2 - tw / 2 + 1), 2 + i * 10), m)
    return card


def _build_stamp():
    """The verdict as a cogitator alarm banner: a crisp double-ruled box, straight."""
    W, H = 168, 46
    im = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, W - 1, H - 1], outline=255, width=2)
    d.rectangle([4, 4, W - 5, H - 5], outline=160, width=1)
    for i, s in enumerate(("EXCOMMUNICATE", "TRAITORIS")):
        f = font(15)
        tw = d.textlength(s, font=f)
        d.text((W / 2 - tw / 2, 6 + i * 17), s, fill=255, font=f, stroke_width=1, stroke_fill=255)
    for x in (10, W - 16):                                     # +++ markers either side
        d.text((x, 16), "+", fill=200, font=font(11))
    return im


# ── state ───────────────────────────────────────────────────────────────────
_S: dict = {}

SLOTS_4 = [(70, 98), (170, 98), (70, 162), (170, 162)]
SLOTS_3 = [(66, 104), (174, 104), (120, 160)]
EV_SLOTS_4 = [(120, 72), (120, 104), (120, 136), (120, 168)]
EV_SLOTS_3 = [(120, 76), (120, 108), (58, 166), (182, 166)]


def _new_case(t0):
    rng = _rng
    ns = rng.choice([3, 4, 4])
    slots = SLOTS_4 if ns == 4 else SLOTS_3
    evs = EV_SLOTS_4 if ns == 4 else EV_SLOTS_3
    names = rng.sample(SURNAMES, ns)
    suspects = []
    for i in range(ns):
        strokes, brand = _portrait_strokes(rng)
        sp = dict(name=names[i], strokes=strokes, brand=brand, pos=slots[i], ang=0.0,
                  t_pin=2.5 + i * 2.6, drawn=-1, card=None, role=rng.choice(ROLES))
        suspects.append(sp)
    prime = rng.randrange(ns)
    nev = min(len(evs), rng.randint(5, 6))
    ev_items = rng.sample(EVIDENCE, nev)
    ev_slots = rng.sample(evs, nev)
    evidence = []
    t_ev = 2.5 + ns * 2.6 + 1.5
    for k in range(nev):
        targets = [prime] if rng.random() < 0.7 else [rng.choice([i for i in range(ns) if i != prime])]
        if rng.random() < 0.45:
            other = rng.randrange(ns)
            if other not in targets:
                targets.append(other)
        evidence.append(dict(item=ev_items[k], pos=ev_slots[k], t=t_ev, targets=targets,
                             img=_render_evidence(ev_items[k], rng)))
        t_ev += rng.uniform(7.0, 8.5)
    # a guaranteed thread from the last evidence to the prime suspect
    if prime not in evidence[-1]["targets"]:
        evidence[-1]["targets"].insert(0, prime)
    assoc = []
    for _ in range(rng.randint(1, 2)):
        a, b = rng.sample(range(ns), 2)
        assoc.append((a, b, rng.uniform(t_ev * 0.5, t_ev - 2)))
    t_prime = t_ev + 1.0
    _S.clear()
    _S.update(t0=t0, board=_board(rng), suspects=suspects, prime=prime, evidence=evidence, assoc=assoc,
              t_prime=t_prime, t_stamp=t_prime + 5.0, t_end=t_prime + 14.5, stamp=_build_stamp(),
              case=f"{rng.randint(100, 9999):04d}.M42", ordo=rng.choice(ORDOS), inq=rng.choice(INQUISITORS),
              status=rng.sample(STATUS, 6), sentence=rng.choice(SENTENCES), last_prime_card=None)


def _reset():
    _new_case(0.0)


def _ease_out(x):
    x = min(1.0, max(0.0, x))
    return 1 - (1 - x) ** 3


def _bounce(x):
    x = min(1.0, max(0.0, x))
    if x < 0.7:
        return (x / 0.7) ** 2
    return 1.0 - 0.12 * math.sin((x - 0.7) / 0.3 * math.pi)


def _string_pts(a, b, sag, frac, n=14):
    (x0, y0), (x1, y1) = a, b
    out = []
    m = max(2, int(n * frac) + 1)
    for i in range(m):
        u = min(frac, i / n)
        x = x0 + (x1 - x0) * u
        y = y0 + (y1 - y0) * u + sag * 4 * u * (1 - u)
        out.append((x, y))
    if frac < 1:
        u = frac
        out.append((x0 + (x1 - x0) * u, y0 + (y1 - y0) * u + sag * 4 * u * (1 - u)))
    return out


def _pin(d, x, y, col=GREEN_MID):
    """A link node."""
    d.rectangle([x - 2, y - 2, x + 2, y + 2], outline=col, fill=(0, 0, 0))
    d.point((x, y), fill=GREEN_HI)


def render(bezel, mask, now: float) -> Image.Image:
    if _session.fresh(now):
        _reset()
        _ph.reset()
    ta = _session.t(now)
    S = _S
    if ta - S["t0"] > S["t_end"]:
        _new_case(ta)
        S = _S
    t = ta - S["t0"]
    img = S["board"].copy()
    d = ImageDraw.Draw(img)
    prime = S["prime"]
    tp = S["t_prime"]
    zoom = _ease_out((t - tp) / 1.6) if t > tp else 0.0

    # header
    hdr = min(1.0, t / 1.5)
    img.paste(_ROSETTE, (CX - 12, 9), _ROSETTE)
    if hdr > 0:
        s1 = f"ORDO {S['ordo']}"
        s1 = s1[:max(1, int(len(s1) * hdr))]
        _fit(img, 35, "+++ " + s1 + " +++", GREEN_HI, 10)
        _fit(img, 47, f"CASE FILE {S['case']}", GREEN_MID, 9)

    # suspects
    anchor = {}
    order = [i for i in range(len(S["suspects"])) if i != prime] + [prime]
    deferred = None
    for i in order:
        sp = S["suspects"][i]
        age = t - sp["t_pin"]
        if age < 0:
            continue
        n = len(sp["strokes"])
        k = min(n, int(max(0.0, age - 0.4) / 1.6 * n))
        brand = i == prime and t > tp + 1.8
        key = (k, brand)
        if sp["drawn"] != key:
            sp["drawn"] = key
            card = _render_suspect_card(sp, k, brand)
            sp["card"] = card.rotate(sp["ang"], resample=Image.BICUBIC, expand=True)
            sp["card_up"] = card
        x, y = sp["pos"]
        dy = (1 - _bounce(age / 0.5)) * -40
        card = sp["card"]
        if i == prime and zoom > 0:
            sc = 1 + 0.75 * zoom
            base = sp["card_up"]
            card = base.resize((int(base.width * sc), int(base.height * sc)), Image.BILINEAR)
            card = card.rotate(sp["ang"] * (1 - zoom), resample=Image.BILINEAR, expand=True)
            x = x + (CX - x) * zoom
            y = y + (126 - y) * zoom
        cx0 = int(x - card.width / 2)
        cy0 = int(y + dy - card.height / 2)
        alpha = card.getchannel("A")
        if i == prime and zoom > 0:
            deferred = (card, cx0, cy0, alpha)
        else:
            img.paste(card, (cx0, cy0), card)
        if i != prime and zoom > 0:
            img.paste((0, 0, 0), (cx0, cy0), alpha.point(lambda v, z=zoom: int(v * 0.7 * z)))
        ang = math.radians(sp["ang"]) if not (i == prime and zoom > 0) else 0.0
        py = -card.height / 2 + 5 if i == prime and zoom > 0 else -CARD_H / 2 + 5
        anchor[i] = (x - math.sin(ang) * py, y + dy + math.cos(ang) * py)
        if age < 3.0 and not zoom:
            label = sp["role"]
            m, w = _tsprite(label, 9)
            lx = max(x - w / 2, CX - safe_half_width(y + 36, 8))
            _text(img, lx, y + 32, label, GREEN_MID, 9)

    # evidence slips + strings
    string_draw = []
    for ev in S["evidence"]:
        age = t - ev["t"]
        if age < 0:
            continue
        x, y = ev["pos"]
        dyy = (1 - _bounce(age / 0.45)) * -30
        im = ev["img"]
        a = im.getchannel("A")
        ex0, ey0 = int(x - im.width / 2), int(y + dyy - im.height / 2)
        dimk = 0.55 * zoom
        img.paste(im, (ex0, ey0), im)
        if dimk > 0:
            img.paste((0, 0, 0), (ex0, ey0), a.point(lambda v, z=dimk: int(v * z)))
        pa = (x, y + dyy - im.height / 2 + 3)
        for j, tgt in enumerate(ev["targets"]):
            if tgt not in anchor:
                continue
            fr = min(1.0, max(0.0, (age - 0.6 - j * 0.5) / 0.9))
            if fr > 0:
                string_draw.append((pa, anchor[tgt], fr, tgt == prime))
        string_draw.append(("pin", pa))
    for a, b, ts in S["assoc"]:
        if a in anchor and b in anchor and t > ts:
            string_draw.append((anchor[a], anchor[b], min(1.0, (t - ts) / 1.2), False))
    glow = 0.5 + 0.5 * math.sin(t * 6) if t > tp else 0.0
    for item in string_draw:
        if item[0] == "pin":
            continue
        pa, pb, fr, to_prime = item
        pts = _string_pts(pa, pb, 0, fr, n=24)
        hot = to_prime and t > tp
        col = AMBER if hot else GREEN_DIM if zoom else GREEN_MID
        for q in range(0, len(pts) - 1, 2):                 # dashed data link
            d.line([pts[q], pts[q + 1]], fill=col, width=1)
        if fr >= 1:                                          # a pulse runs along it
            u = (t * (0.9 if hot else 0.45) + (pa[0] + pb[1]) * 0.013) % 1.0
            px, py = pa[0] + (pb[0] - pa[0]) * u, pa[1] + (pb[1] - pa[1]) * u
            d.rectangle([px - 1, py - 1, px + 1, py + 1], fill=GREEN_HI if not hot else AMBER)
    for item in string_draw:
        if item[0] == "pin":
            _pin(d, *item[1], col=GREEN)
    if deferred is not None:
        for i, p in anchor.items():
            if i != prime:
                _pin(d, p[0], p[1])
        card, cx0, cy0, alpha = deferred
        img.paste(card, (cx0, cy0), card)
        if t < S["t_stamp"]:
            g = 0.5 + 0.5 * glow
            d.rectangle([cx0 - 3, cy0 - 3, cx0 + card.width + 2, cy0 + card.height + 2],
                        outline=tuple(int(c * g) for c in AMBER), width=1)
    for i, p in anchor.items():
        if deferred is None or i == prime:
            _pin(d, p[0], p[1])

    # status line
    if t < tp:
        idx = int(t / 6.5) % len(S["status"])
        msg = S["status"][idx]
        k = int((t % 6.5) * 18)
        msg = msg[:k]
        _fit(img, 212, "> " + msg + ("_" if int(t * 3) % 2 else " "), GREEN, 9)
    else:
        if int((t - tp) * 3) % 3 != 0 or t > tp + 2:
            _fit(img, 206 if t < S["t_stamp"] else 212,
                 "PRIME SUSPECT IDENTIFIED" if t < S["t_stamp"] else S["sentence"],
                 AMBER if t < S["t_stamp"] else RED, 10)

    # the stamp
    ts = S["t_stamp"]
    shake = (0, 0)
    if t > ts:
        st = S["stamp"]
        u = (t - ts) / 0.22
        sc = 1.0 + 1.6 * (1 - min(1.0, u)) ** 2
        m = st if sc <= 1.001 else st.resize((int(st.width * sc), int(st.height * sc)), Image.BILINEAR)
        if u < 1.0:
            m = m.point(lambda v, a=0.3 + 0.7 * u: int(v * a))
        img.paste(RED, (int(CX - m.width / 2), int(128 - m.height / 2)), m)
        if 1.0 <= u < 3.2:
            k = (3.2 - u) / 2.2
            shake = (int(_rng.uniform(-4, 4) * k), int(_rng.uniform(-4, 4) * k))
        if t > ts + 1.5:
            _fit(img, 196, f"BY ORDER OF INQ. {S['inq']}", GREEN_HI, 9)
    if shake != (0, 0):
        sh = Image.new("RGB", (240, 240), (0, 0, 0))
        sh.paste(img, shake)
        img = sh
    # fade out at case end
    rem = S["t_end"] - t
    if rem < 2.0:
        img = Image.blend(Image.new("RGB", (240, 240), (0, 0, 0)), img, max(0.0, rem / 2.0))
    elif t < 0.8:
        img = Image.blend(Image.new("RGB", (240, 240), (0, 0, 0)), img, t / 0.8)
    return _ph.compose(img)
