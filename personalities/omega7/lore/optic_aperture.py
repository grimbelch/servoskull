"""Optic Aperture – iris blades calibrate the red lens.

Nine iris blades open and close over the glowing red optic while the focus
ring turns through its range marks and the f-stop reads out.
"""

from __future__ import annotations

import math

from PIL import Image, ImageDraw

from ._common import font, text_center

NAME = "optic_aperture"


def _text_c(d, cx, y, text, fnt, fill):
    """Draw text horizontally centred on cx."""
    d.text((cx - d.textlength(text, font=fnt) / 2, y), text, fill=fill, font=fnt)


def render(bezel, mask, now):
    img = Image.new("RGB", (240, 240), (8, 6, 6))
    d = ImageDraw.Draw(img)
    cycle = now % 9.0
    if cycle < 3.0:
        k = cycle / 3.0
    elif cycle < 4.5:
        k = 1.0
    elif cycle < 7.5:
        k = 1.0 - (cycle - 4.5) / 3.0
    else:
        k = 0.0
    k = k * k * (3 - 2 * k)
    ap = 14 + 58 * k
    R, N = 92, 9
    twist = -1.6 * k + now * 0.05

    # Red optic behind the blades
    for r in range(int(ap) + 4, 0, -4):
        g = 1 - r / (ap + 4)
        d.ellipse([120 - r, 120 - r, 120 + r, 120 + r], fill=(int(90 + 165 * g), int(20 * g * g * 5), int(10 * g)))
    d.ellipse([104, 102, 114, 110], fill=(255, 200, 190))

    pts = [(120 + ap * math.cos(twist + 2 * math.pi * i / N), 120 + ap * math.sin(twist + 2 * math.pi * i / N)) for i in range(N)]

    def rim_hit(p, q):
        dx, dy = q[0] - p[0], q[1] - p[1]
        L = math.hypot(dx, dy)
        dx, dy = dx / L, dy / L
        fx, fy = p[0] - 120, p[1] - 120
        b = fx * dx + fy * dy
        t = -b + math.sqrt(max(0.0, b * b - (fx * fx + fy * fy - R * R)))
        return (p[0] + dx * t, p[1] + dy * t)

    rims = [rim_hit(pts[i], pts[(i + 1) % N]) for i in range(N)]
    for i in range(N):
        p1, p2 = pts[(i + 1) % N], pts[(i + 2) % N]
        r_a, r_b = rims[i], rims[(i + 1) % N]
        a0 = math.atan2(r_b[1] - 120, r_b[0] - 120)
        a1 = math.atan2(r_a[1] - 120, r_a[0] - 120)
        da = (a1 - a0 + math.pi) % (2 * math.pi) - math.pi
        arc = [(120 + R * math.cos(a0 + da * s / 8), 120 + R * math.sin(a0 + da * s / 8)) for s in range(9)]
        shade = 45 + 18 * ((i * 4) % N) / N
        d.polygon([p1, p2] + arc, fill=(int(shade * 1.1), int(shade), int(shade * 0.9)), outline=(20, 18, 16))

    # Focus ring with range marks
    d.ellipse([120 - R - 2, 120 - R - 2, 120 + R + 2, 120 + R + 2], outline=(150, 110, 50), width=3)
    f = font(9)
    ring_rot = -k * 70
    for j, lab in enumerate(("0.5", "1", "2", "5", "10", "INF")):
        a = math.radians(ring_rot + j * 30 - 165)
        x, y = 120 + 105 * math.cos(a), 120 + 105 * math.sin(a)
        _text_c(d, x, y - 5, lab, f, (190, 140, 60))
    d.polygon([(120, 16), (116, 8), (124, 8)], fill=(220, 30, 20))
    fstop = 16.0 / (1 + 7 * k)
    text_center(d, 214, f"OPTIC CALIBRATION  f/{fstop:.1f}", (200, 60, 40), 8)
    return img
