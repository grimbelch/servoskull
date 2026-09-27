"""Imperial Chronometer – today's date in the Imperial Dating System.

The real local date is shown as check number, year-fraction and year (e.g.
0 735 026.M3) inside a brass clock ring: minute and hour arcs, a sweeping red
second pip, and an arc tracking progress through the current 8.766-hour
year-fraction.
"""

from __future__ import annotations

import datetime
import math

from PIL import Image, ImageDraw

from ._common import text_center

NAME = "imperial_chronometer"


def _imperial_date(dt):
    """Real date in the Imperial Dating System: check · year-fraction · year.M."""
    start = datetime.datetime(dt.year, 1, 1)
    hours = (dt - start).total_seconds() / 3600.0
    frac = min(999, int(hours / 8.766))
    into = (hours % 8.766) / 8.766
    return frac, dt.year % 1000, dt.year // 1000 + 1, into


def render(bezel, mask, now):
    dt = datetime.datetime.now()
    frac, year, mill, into = _imperial_date(dt)
    img = Image.new("RGB", (240, 240), (6, 4, 2))
    d = ImageDraw.Draw(img)
    brass, dim, red = (220, 160, 60), (90, 60, 20), (220, 30, 20)

    # Brass bezel with 60 minute ticks
    d.ellipse([6, 6, 234, 234], outline=dim, width=2)
    for i in range(60):
        a = math.radians(i * 6 - 90)
        r0 = 100 if i % 5 == 0 else 106
        col = brass if i % 5 == 0 else dim
        d.line([(120 + r0 * math.cos(a), 120 + r0 * math.sin(a)),
                (120 + 111 * math.cos(a), 120 + 111 * math.sin(a))], fill=col, width=2 if i % 5 == 0 else 1)

    # Hour and minute arcs, sweeping second pip
    sec = dt.second + dt.microsecond / 1e6
    mins = dt.minute + sec / 60.0
    hrs = (dt.hour % 12) + mins / 60.0
    d.arc([22, 22, 218, 218], -90, -90 + mins * 6, fill=(150, 100, 30), width=3)
    d.arc([30, 30, 210, 210], -90, -90 + hrs * 30, fill=(110, 20, 10), width=3)
    a = math.radians(sec * 6 - 90)
    px, py = 120 + 108 * math.cos(a), 120 + 108 * math.sin(a)
    d.ellipse([px - 4, py - 4, px + 4, py + 4], fill=red)

    # Progress through the current year-fraction (8.766 h)
    d.arc([44, 44, 196, 196], -90, -90 + into * 360, fill=(60, 120, 60), width=2)

    text_center(d, 58, "IMPERIAL DATE", dim, 11)
    text_center(d, 80, "CHECK 0 · TERRA", (140, 100, 40), 9)
    text_center(d, 100, f"{frac:03d}.{year:03d}", brass, 28)
    text_center(d, 134, f"M{mill}", (240, 200, 110), 16)
    text_center(d, 160, dt.strftime("%H:%M:%S"), (160, 110, 40), 13)
    if int(now * 2) % 2 == 0:
        text_center(d, 182, "CHRONO-SYNC NOMINAL", (80, 140, 80), 8)
    return img
