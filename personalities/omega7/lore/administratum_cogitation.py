"""Administratum Cogitation - the tithe ledger of a subsector, audited.

Columns of ledger glyphs stream past a sector grid map while an audit head
ticks off world after world.  Then a single mis-keyed digit is found; the
clerical error cascades along the dependency chains, turning the grid red
cell by cell while auditor cursors chase the failure front.  Resolution is
reached the Imperial way: an unfortunate world is zoomed in on and an
EXTERMINATUS order is stamped across it.  The planet burns, the red recedes
and the records are declared RECONCILED.  A new subsector is then audited.
"""

from __future__ import annotations

import heapq
import math
import random

import numpy as np
from PIL import Image, ImageChops, ImageDraw

from ._common import CX, CY, H, W, Session, font, lerp_color, scale

NAME = "administratum_cogitation"

_rng = random.Random()
_session = Session()

COLS, ROWS = 7, 6
CW, CH, GAP = 18, 15, 2
MX0, MY0 = 51, 58
GOLD = (225, 190, 115)
AMBER = (150, 110, 50)
RED = (235, 45, 30)
GREEN = (110, 225, 120)
AUD = (150, 215, 255)

_SUBSECTORS = ["VORAX", "KHEPRIS", "SOLEMNACE", "DAMOCLES", "OBSCURUS", "CALIXIS", "GOTHIC",
               "ARMAGEDDON", "SCARUS", "MACHARIA", "ULTIMA", "JERICHO"]
_WORLDS = ["ARDENT PRIME", "VOSS IV", "MERIDIAN", "HYDRAPHUR", "SOLACE", "KRIEG MINOR",
           "TALLARN III", "ORBIS VII", "CADIA IX", "HESTIA", "PYRRHUS", "SEPHIRA", "NOVA TERRA"]
_JOKES = [("CAUSE: TYPOGRAPHICAL", "SCRIBE 7 SERVITORISED"),
          ("CAUSE: INK SMUDGE", "SCRIBE 12 REASSIGNED"),
          ("CAUSE: MIS-KEYED DIGIT", "FORM 27-B/6 FILED"),
          ("CAUSE: CLERICAL ERROR", "APPEAL DENIED (M41)")]

_GLYPHS = "0123456789ABCDEF+=#%"


# --------------------------------------------------------------------- statics

def _stamp_image() -> Image.Image:
    f = font(16)
    im = Image.new("RGBA", (150, 44), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rectangle([2, 2, 147, 41], outline=(215, 25, 20, 255), width=3)
    d.rectangle([7, 7, 142, 36], outline=(215, 25, 20, 255), width=1)
    w = d.textlength("EXTERMINATUS", font=f)
    d.text((75 - w / 2, 12), "EXTERMINATUS", fill=(225, 30, 22, 255), font=f)
    a = np.asarray(im).copy()
    g = np.random.default_rng(7)
    holes = g.random(a.shape[:2]) < 0.16
    a[..., 3] = np.where(holes, (a[..., 3] * 0.25).astype(np.uint8), a[..., 3])
    im = Image.fromarray(a, "RGBA")
    return im.rotate(13, expand=True, resample=Image.BICUBIC)


_STAMP = _stamp_image()


def _glyph_atlas():
    f = font(10)
    atl = {}
    for key, col in (("a", (95, 70, 30)), ("r", (120, 22, 16)), ("b", (170, 130, 60))):
        for ch in _GLYPHS:
            im = Image.new("RGB", (10, 12), (0, 0, 0))
            ImageDraw.Draw(im).text((1, 0), ch, fill=col, font=f)
            atl[(key, ch)] = im
    return atl


def _strips(atl, pr):
    """Per-column tall glyph strips (seamless when wrapped at 240)."""
    out = []
    for i in range(20):
        strips = {}
        chars = [_GLYPHS[int(pr.integers(0, len(_GLYPHS)))] for _ in range(20)]
        bright = [pr.random() < 0.12 for _ in range(20)]
        for key in ("a", "r"):
            im = Image.new("RGB", (10, 480), (0, 0, 0))
            for rep in range(2):
                for j, ch in enumerate(chars):
                    k = "b" if (bright[j] and key == "a") else key
                    im.paste(atl[(k, ch)], (0, rep * 240 + j * 12))
            strips[key] = im
        out.append(strips)
    return out


def _planet_images(pr):
    n = 84
    yy, xx = np.mgrid[0:n, 0:n].astype(np.float32)
    x = (xx - n / 2 + 0.5) / (n / 2 - 1)
    y = (yy - n / 2 + 0.5) / (n / 2 - 1)
    rr = x * x + y * y
    inside = rr <= 1.0
    z = np.sqrt(np.clip(1.0 - rr, 0, 1))
    shade = np.clip(0.25 + 0.85 * (-0.5 * x - 0.5 * y + 0.7 * z), 0.05, 1.1)
    ph = pr.random(6) * 6.28
    land = (np.sin(x * 5 + ph[0]) + np.sin(y * 6 + ph[1]) + np.sin((x + y) * 4 + ph[2]) +
            0.6 * np.sin(x * 11 - y * 7 + ph[3])) > 0.7
    base = np.where(land[..., None], np.array([90, 110, 60], np.float32), np.array([40, 70, 120], np.float32))
    noise = pr.random((n, n)).astype(np.float32)
    fire = np.stack([255 * (0.6 + 0.4 * noise), 90 + 120 * noise * land, 20 * noise], -1)
    dead = np.stack([50 + 40 * noise * land, 22 + 10 * noise, 18 + 8 * noise], -1)
    imgs = []
    for col in (base, fire, dead):
        rgb = np.clip(col * shade[..., None], 0, 255).astype(np.uint8)
        a = (inside * 255).astype(np.uint8)
        imgs.append(Image.fromarray(np.dstack([rgb, a]), "RGBA"))
    return imgs


def _cell_xy(i):
    c, r = i % COLS, i // COLS
    return MX0 + c * (CW + GAP), MY0 + r * (CH + GAP)


def _cell_c(i):
    x, y = _cell_xy(i)
    return x + CW / 2, y + CH / 2


_S: dict = {}


# --------------------------------------------------------------------- cycle

def _new_cycle(t):
    s = _S
    pr = s["np"]
    n = COLS * ROWS
    s["c0"] = t
    s["sub"] = _rng.choice(_SUBSECTORS)
    s["ids"] = [_rng.randint(1000, 9999) for _ in range(n)]
    s["tithe"] = [_rng.uniform(0.1, 0.99) for _ in range(n)]
    s["wsize"] = [_rng.choice((1.5, 2, 2, 2.5, 3)) for _ in range(n)]
    s["wcol"] = [_rng.choice(((200, 170, 100), (160, 180, 200), (200, 120, 80), (150, 200, 140)))
                 for _ in range(n)]
    s["rate"] = _rng.uniform(3.8, 5.0)
    src = _rng.randint(12, 30)
    s["src"] = src
    s["t_err"] = 1.0 + src / s["rate"]
    s["t_cas"] = s["t_err"] + 3.8
    # failure propagation along the dependency lattice (Dijkstra, random delays)
    tf = [1e9] * n
    parent = [-1] * n
    tf[src] = 0.0
    pq = [(0.0, src)]
    while pq:
        dcur, i = heapq.heappop(pq)
        if dcur > tf[i]:
            continue
        c, r = i % COLS, i // COLS
        for dc, dr in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            cc, rr = c + dc, r + dr
            if 0 <= cc < COLS and 0 <= rr < ROWS:
                j = rr * COLS + cc
                nd = dcur + _rng.uniform(0.6, 3.4)
                if nd < tf[j]:
                    tf[j] = nd
                    parent[j] = i
                    heapq.heappush(pq, (nd, j))
    mx = max(tf)
    target = _rng.uniform(24, 30)
    k = target / mx
    s["tf"] = [v * k for v in tf]
    s["parent"] = parent
    s["cas_len"] = target + 3.0
    s["t_res"] = s["t_cas"] + s["cas_len"]
    order = sorted(range(n), key=lambda i: s["tf"][i])
    s["doom"] = _rng.choice(order[n // 4: 3 * n // 4])
    s["wname"] = _rng.choice(_WORLDS)
    s["pop"] = _rng.uniform(0.8, 14.0)
    s["t_rec"] = s["t_res"] + 16.0
    s["total"] = s["t_rec"] + 14.0
    digit_pos = _rng.randint(2, 5)
    s["digit_pos"] = digit_pos
    s["joke"] = _rng.choice(_JOKES)
    s["col_red_k"] = [pr.random() for _ in range(20)]
    s["planets"] = _planet_images(pr)
    s["aud"] = [[CX + _rng.uniform(-60, 60), 210.0] for _ in range(3)]
    s["trail"] = [[] for _ in range(3)]
    s["records"] = _rng.randint(120000, 480000)


def _reset(t):
    _S.clear()
    _S["np"] = np.random.default_rng(_rng.getrandbits(32))
    _S["atlas"] = _glyph_atlas()
    _S["strips"] = _strips(_S["atlas"], _S["np"])
    _S["speeds"] = [float(v) for v in _S["np"].uniform(14, 40, 20)]
    _S["last_t"] = t
    _new_cycle(t)


# --------------------------------------------------------------------- draw helpers

def _ctext(d, y, s, col, size=10):
    f = font(size)
    w = d.textlength(s, font=f)
    d.text((CX - w / 2, y), s, fill=col, font=f)


def _record(d, s, i, y, hl_digit=False, flash=False, fail=False):
    f = font(10)
    tithe = f"{s['tithe'][i]:.4f}"
    pre = f"REC {s['ids'][i]}-{chr(65 + i % 26)}  "
    post = " AQ"
    col = RED if fail else GOLD
    if hl_digit:
        p = s["digit_pos"]
        good = tithe
        bad = tithe[:p] + str((int(tithe[p]) + 5) % 10) + tithe[p + 1:]
        full_w = d.textlength(pre + bad + post, font=f)
        x = CX - full_w / 2
        d.text((x, y), pre + bad[:p], fill=GOLD, font=f)
        x2 = x + d.textlength(pre + bad[:p], font=f)
        dw = d.textlength(bad[p], font=f)
        if flash:
            d.rectangle([x2 - 1, y, x2 + dw + 1, y + 12], fill=(120, 10, 8), outline=RED)
        d.text((x2, y), bad[p], fill=(255, 230, 200), font=f)
        d.text((x2 + dw, y), bad[p + 1:] + post, fill=GOLD, font=f)
        return x2 + dw / 2
    txt = pre + tithe + post
    w = d.textlength(txt, font=f)
    d.text((CX - w / 2, y), txt, fill=col, font=f)
    return None


def _cursor(d, x, y, col, label):
    d.polygon([(x, y), (x + 8, y + 5), (x + 4, y + 6), (x + 6, y + 10), (x + 4, y + 11), (x + 2, y + 7), (x, y + 9)],
              fill=col, outline=(20, 30, 40))
    d.text((x + 8, y + 7), label, fill=col, font=font(9))


# --------------------------------------------------------------------- render

def render(bezel, mask, now: float) -> Image.Image:
    if _session.fresh(now) or not _S:
        _reset(0.0)
    t = _session.t(now)
    s = _S
    dt = max(0.0, min(0.1, t - s["last_t"]))
    s["last_t"] = t
    tc = t - s["c0"]
    if tc >= s["total"]:
        _new_cycle(t)
        tc = 0.0
    n = COLS * ROWS
    tf = s["tf"]
    src, doom = s["src"], s["doom"]
    t_err, t_cas, t_res, t_rec = s["t_err"], s["t_cas"], s["t_res"], s["t_rec"]
    tcas = tc - t_cas  # seconds into cascade (negative before)
    in_res = t_res <= tc < t_rec
    rec_u = tc - t_rec
    n_failed = sum(1 for i in range(n) if tcas >= tf[i]) if tcas >= 0 else 0
    red_frac = n_failed / n if tc < t_rec else max(0.0, 1.0 - rec_u / 6.0)

    img = Image.new("RGB", (W, H), (8, 6, 4))

    # ---- ledger streams
    for i, strips in enumerate(s["strips"]):
        key = "r" if s["col_red_k"][i] < red_frac * 1.05 else "a"
        off = (t * s["speeds"][i]) % 240
        img.paste(strips[key], (i * 12 + 1, int(off - 240)))
    d = ImageDraw.Draw(img)
    d.rectangle([40, 161, 200, 214], fill=(10, 7, 4))

    # ---- resolution close-up (planet & stamp) replaces the map
    shake = (0, 0)
    if in_res:
        ru = tc - t_res
        _draw_map_panel(d, s, tc, tcas, dim=True)
        dc = _cell_c(doom)
        # auditors converge
        for k in range(3):
            ang = k * 2.09 + t * 1.5
            _move_aud(s, k, (dc[0] + 11 * math.cos(ang) - 3, dc[1] + 11 * math.sin(ang) - 3), dt, 80)
        if ru < 3.5:
            x, y = _cell_xy(doom)
            p = 3 + 2 * math.sin(t * 10)
            d.rectangle([x - p, y - p, x + CW + p, y + CH + p], outline=RED, width=1)
            _draw_auditors(d, s)
            _ctext(d, 166, "SEEKING RESOLUTION", GOLD, 10)
            _ctext(d, 184, "AUDITORS CONVENE", AUD, 9)
            dots = "." * (int(t * 3) % 4)
            _ctext(d, 198, f"CONSULTING PRECEDENT{dots}", AMBER, 9)
        else:
            z = min(1.0, (ru - 3.5) / 0.8)
            d.rectangle([34, 50, 206, 168], fill=(10, 7, 5), outline=lerp_color(AMBER, RED, z))
            planets = s["planets"]
            if ru < 6.2:
                pimg = planets[0]
            elif ru < 11.0:
                k = min(1.0, (ru - 6.2) / 1.8)
                pimg = Image.blend(planets[0], planets[1], k)
                if ru > 9.0:
                    pimg = Image.blend(pimg, planets[2], (ru - 9.0) / 2.0)
            else:
                pimg = planets[2]
            sz = max(8, int(84 * (0.3 + 0.7 * z)))
            pp = pimg.resize((sz, sz), Image.BILINEAR) if sz != 84 else pimg
            img.paste(pp, (int(CX - sz / 2), int(104 - sz / 2)), pp)
            d = ImageDraw.Draw(img)
            if 6.2 <= ru < 11.0:
                pr = s["np"]
                for _ in range(10):
                    a = pr.random() * 6.283
                    rr = 42 * math.sqrt(pr.random())
                    fx, fy = CX + rr * math.cos(a), 104 + rr * math.sin(a)
                    d.point((fx, fy), fill=(255, 220, 120))
                d.ellipse([CX - 45, 59, CX + 45, 149], outline=(255, 120, 30))
            d.text((40, 54), s["wname"], fill=GOLD, font=font(9))
            pop = s["pop"] if ru < 8.0 else s["pop"] * max(0.0, 1.0 - (ru - 8.0) / 3.0)
            ptxt = f"POP {pop:4.1f} BN"
            d.text((200 - d.textlength(ptxt, font=font(9)), 54), ptxt, fill=GOLD if ru < 8 else RED, font=font(9))
            if ru >= 5.2:
                su = min(1.0, (ru - 5.2) / 0.3)
                sc = 2.4 - 1.4 * su
                st = _STAMP.resize((max(1, int(_STAMP.width * sc)), max(1, int(_STAMP.height * sc))), Image.BILINEAR)
                img.paste(st, (int(CX - st.width / 2), int(104 - st.height / 2)), st)
                d = ImageDraw.Draw(img)
                if 5.5 <= ru < 5.9:
                    pr = s["np"]
                    shake = (int(pr.integers(-4, 5)), int(pr.integers(-4, 5)))
            if ru < 5.2:
                _ctext(d, 172, "SOLUTION IDENTIFIED", GOLD, 10)
                _ctext(d, 186, f"WORLD {s['ids'][doom]} NONCOMPLIANT", RED, 9)
            elif ru < 11.0:
                _ctext(d, 172, "ORDER SANCTIONED", RED, 10)
                _ctext(d, 186, "BY SEAL OF THE", AMBER, 9)
                _ctext(d, 197, "ADMINISTRATUM", AMBER, 9)
            else:
                _ctext(d, 172, "DISCREPANCY REMOVED", GOLD, 10)
                _ctext(d, 186, s["joke"][0], AMBER, 9)
                _ctext(d, 197, s["joke"][1], AMBER, 9)
    else:
        _draw_map_panel(d, s, tc, tcas, dim=False)
        # dependency links during cascade
        if tcas >= 0 and tc < t_res:
            for i in range(n):
                p = s["parent"][i]
                if p >= 0:
                    age = tcas - tf[i]
                    if 0 <= age < 2.5:
                        a, b = _cell_c(p), _cell_c(i)
                        d.line([a, b], fill=scale(RED, 1.0 - age / 2.5), width=2)
            # auditors chase the failure front
            failed = [i for i in range(n) if tcas >= tf[i]]
            failed.sort(key=lambda i: -tf[i])
            for k in range(3):
                if failed:
                    tgt = _cell_c(failed[min(len(failed) - 1, k * 2)])
                    _move_aud(s, k, (tgt[0] - 3, tgt[1] - 3), dt, 38)
            _draw_auditors(d, s)
        elif tc >= t_rec:
            for k in range(3):
                _move_aud(s, k, (80 + k * 40, 214), dt, 50)
        # record box and status
        f10 = font(10)
        d.rectangle([48, 163, 192, 180], fill=(14, 10, 6), outline=AMBER)
        if tc < t_err:
            idx = min(n - 1, int((tc - 1.0) * s["rate"])) if tc > 1.0 else 0
            _record(d, s, idx, 165)
            cnt = s["records"] + int(tc * 4211)
            _ctext(d, 184, "TITHE AUDIT NOMINAL", GREEN, 10)
            _ctext(d, 198, f"RECORDS {cnt:,}", AMBER, 9)
        elif tc < t_cas:
            flash = int(t * 4) % 2 == 0
            _record(d, s, src, 165, hl_digit=True, flash=flash)
            _ctext(d, 184, "DISCREPANCY DETECTED", RED if flash else GOLD, 10)
            _ctext(d, 198, "1 DIGIT MIS-KEYED", AMBER, 9)
        elif tc < t_res:
            fails = [i for i in range(n) if tcas >= tf[i]]
            last = max(fails, key=lambda i: tf[i]) if fails else src
            _record(d, s, last, 165, fail=True)
            deficit = 0.0005 * (10 ** (min(1.0, tcas / (s["cas_len"] - 3)) * 9.5))
            _ctext(d, 184, f"{len(fails):02d} SECTORS FAIL AUDIT", RED, 10)
            _ctext(d, 198, f"DEFICIT {deficit:.3g} AQ", AMBER, 9)
        else:
            if rec_u < 11.0:
                _ctext(d, 166, "RECORDS RECONCILED", GREEN, 10)
                _ctext(d, 184, "DEFICIT 0.0000 AQ", GOLD, 10)
                _ctext(d, 198, "AVE IMPERATOR", AMBER, 9)
            else:
                _ctext(d, 166, "NEXT SUBSECTOR", GOLD, 10)
                _ctext(d, 184, "LEDGER ADVANCING", AMBER, 9)

    # ---- header
    d.rectangle([62, 16, 178, 49], fill=(10, 7, 4))
    _ctext(d, 18, "ADMINISTRATUM", GOLD, 12)
    sub = f"{s['sub']} TITHE AUDIT"
    _ctext(d, 35, sub, AMBER, 9)

    if shake != (0, 0):
        img = ImageChops.offset(img, shake[0], shake[1])
    return img


def _move_aud(s, k, tgt, dt, speed):
    a = s["aud"][k]
    dx, dy = tgt[0] - a[0], tgt[1] - a[1]
    dist = math.hypot(dx, dy)
    step = speed * dt * (1.0 + 0.15 * k)
    if dist > 1e-3:
        m = min(1.0, step / dist)
        a[0] += dx * m
        a[1] += dy * m
    tr = s["trail"][k]
    tr.append((a[0], a[1]))
    if len(tr) > 14:
        del tr[0]


def _draw_auditors(d, s):
    for k in range(3):
        tr = s["trail"][k]
        if len(tr) > 1:
            d.line(tr, fill=scale(AUD, 0.35), width=1)
        a = s["aud"][k]
        _cursor(d, a[0], a[1], AUD, f"A{k + 1}")


def _draw_map_panel(d, s, tc, tcas, dim):
    n = COLS * ROWS
    tf = s["tf"]
    d.rectangle([MX0 - 5, MY0 - 5, MX0 + COLS * (CW + GAP) + 3, MY0 + ROWS * (CH + GAP) + 3],
                fill=(10, 7, 4), outline=AMBER)
    t_err, t_rec = s["t_err"], s["t_rec"]
    rec_u = tc - t_rec
    scan_i = int((tc - 1.0) * s["rate"]) if tc > 1.0 else -1
    doom_dead = tc >= s["t_res"] + 9.0
    blink = int(tc * 4) % 2 == 0
    for i in range(n):
        x, y = _cell_xy(i)
        cx, cy = x + CW / 2, y + CH / 2
        fill, border, dot = (22, 16, 9), (70, 54, 28), s["wcol"][i]
        audited = tc < t_err and i < scan_i
        failed = tcas >= tf[i] and tc < t_rec
        if tc >= t_rec:
            # reconciliation wave spreads out from the doomed world
            dd = math.hypot(cx - _cell_c(s["doom"])[0], cy - _cell_c(s["doom"])[1])
            k = rec_u * 30 - dd
            if k < 0 and rec_u < 6:
                failed = True
            elif k < 40:
                border = lerp_color(GREEN, (70, 54, 28), k / 40)
        if audited:
            border = (80, 120, 60)
        if tc < t_err and i == scan_i:
            border = (255, 240, 180)
            fill = (60, 48, 20)
        if t_err <= tc < s["t_cas"] and i == s["src"]:
            fill = (140, 20, 10) if blink else (60, 10, 5)
            border = RED
        if failed:
            age = tcas - tf[i]
            fresh = 0 <= age < 0.6 and tc < s["t_res"]
            fill = (170, 40, 20) if fresh else (90, 14, 8)
            border = RED if (fresh or blink) else (150, 30, 20)
            dot = (255, 150, 120)
        if dim and i != s["doom"]:
            fill, border, dot = scale(fill, 0.5), scale(border, 0.5), scale(dot, 0.5)
        if i == s["doom"] and doom_dead:
            d.rectangle([x, y, x + CW, y + CH], fill=(0, 0, 0), outline=(120, 20, 15))
            d.line([(x + 3, y + 3), (x + CW - 3, y + CH - 3)], fill=RED)
            d.line([(x + CW - 3, y + 3), (x + 3, y + CH - 3)], fill=RED)
            continue
        d.rectangle([x, y, x + CW, y + CH], fill=fill, outline=border)
        r = s["wsize"][i]
        d.ellipse([cx - r, cy - r - 1, cx + r, cy + r - 1], fill=dot)
        bw = (CW - 4) * s["tithe"][i]
        d.line([(x + 2, y + CH - 2), (x + 2 + bw, y + CH - 2)], fill=scale(GOLD, 0.6) if not failed else RED)
        if audited:
            d.line([(x + CW - 6, y + 4), (x + CW - 4, y + 6), (x + CW - 1, y + 1)], fill=GREEN)
