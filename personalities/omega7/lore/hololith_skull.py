"""Hololith Skull – Omega-7's rotating self-schema.

A wireframe skull turns on a hololith projector beam with scanlines and
occasional tearing; its right socket shows the red augmetic lens whenever
it faces the viewer.
"""

from __future__ import annotations

import math
import random

import numpy as np
from PIL import Image, ImageDraw

from ._common import text_center

NAME = "hololith_skull"


_holo_lines = None


def _build_holo_skull():
    lines = []
    rx, ry, rz, cy = 52, 56, 64, -20
    for th in (18, 36, 54, 72, 90, 104):
        t = math.radians(th)
        ring = []
        for k in range(25):
            p = 2 * math.pi * k / 24
            ring.append((rx * math.sin(t) * math.cos(p), cy - ry * math.cos(t), rz * math.sin(t) * math.sin(p)))
        lines.append(ring)
    for k in range(12):
        p = 2 * math.pi * k / 12
        mer = []
        for th in range(0, 106, 8):
            t = math.radians(th)
            mer.append((rx * math.sin(t) * math.cos(p), cy - ry * math.cos(t), rz * math.sin(t) * math.sin(p)))
        lines.append(mer)
    # Eye sockets (front = -z)
    for sx in (-21, 21):
        ring = []
        for k in range(17):
            a = 2 * math.pi * k / 16
            ring.append((sx + 14 * math.cos(a), 18 + 12 * math.sin(a), -54 + 3 * abs(math.cos(a))))
        lines.append(ring)
    lines.append([(0, 30, -60), (-8, 46, -57), (8, 46, -57), (0, 30, -60)])
    lines.append([(-46, 10, -20), (-40, 34, -42), (-30, 40, -52), (-12, 50, -58)])
    lines.append([(46, 10, -20), (40, 34, -42), (30, 40, -52), (12, 50, -58)])
    lines.append([(x, 54, -52 + 0.02 * x * x) for x in range(-24, 25, 4)])
    for x in range(-22, 23, 6):
        lines.append([(x, 54, -52 + 0.02 * x * x), (x, 62, -51 + 0.02 * x * x)])
    lines.append([(x, 64, -50 + 0.02 * x * x) for x in range(-24, 25, 4)])
    lines.append([(-40, 32, -8), (-38, 66, -20), (-24, 82, -38), (0, 86, -46),
                  (24, 82, -38), (38, 66, -20), (40, 32, -8)])
    return lines


def render(bezel, mask, now):
    global _holo_lines
    if _holo_lines is None:
        _holo_lines = _build_holo_skull()
    img = Image.new("RGB", (240, 240), (0, 6, 10))
    d = ImageDraw.Draw(img)
    yaw = now * 0.7
    pitch = 0.18 * math.sin(now * 0.5)
    cyw, syw, cp, sp = math.cos(yaw), math.sin(yaw), math.cos(pitch), math.sin(pitch)
    bob = 4 * math.sin(now * 1.3)

    def proj(p):
        x, y, z = p
        x, z = x * cyw - z * syw, x * syw + z * cyw
        y, z = y * cp - z * sp, y * sp + z * cp
        f = 220.0 / (260.0 + z)
        return (120 + x * f, 124 + bob + y * f, z)

    # Projector cone and base emitter
    d.polygon([(120, 214), (74, 70), (166, 70)], fill=(0, 16, 24))
    d.ellipse([92, 206, 148, 220], outline=(0, 120, 160), width=2)
    for i in range(3):
        a = now * 3 + i * 2.1
        d.point((120 + 26 * math.cos(a), 213 + 6 * math.sin(a)), fill=(150, 240, 255))

    for ln in _holo_lines:
        pts = [proj(p) for p in ln]
        for (x1, y1, z1), (x2, y2, z2) in zip(pts, pts[1:]):
            depth = max(0.25, min(1.0, 0.65 - (z1 + z2) / 260.0))
            d.line([(x1, y1), (x2, y2)], fill=(int(40 * depth), int(200 * depth), int(255 * depth)), width=1)

    # Omega-7's augmetic lens glows in the right socket when facing the viewer
    ex, ey, ez = proj((21, 18, -56))
    if ez < 0:
        g = 0.7 + 0.3 * math.sin(now * 4)
        d.ellipse([ex - 7, ey - 7, ex + 7, ey + 7], fill=(int(140 * g), 0, 0))
        d.ellipse([ex - 3, ey - 3, ex + 3, ey + 3], fill=(255, int(80 * g), 60))

    arr = np.asarray(img).copy()
    arr[::3] = (arr[::3] * 0.55).astype(np.uint8)
    if random.random() < 0.06:
        y0 = random.randint(40, 180)
        y1 = y0 + random.randint(3, 12)
        arr[y0:y1] = np.roll(arr[y0:y1], random.randint(-12, 12), axis=1)
    img = Image.fromarray(arr)
    d = ImageDraw.Draw(img)
    text_center(d, 20, "HOLOLITH // SELF-SCHEMA", (80, 200, 230), 9)
    text_center(d, 32, f"CRANIAL INTEGRITY {97 + int(now) % 3}%", (40, 130, 160), 8)
    return img
