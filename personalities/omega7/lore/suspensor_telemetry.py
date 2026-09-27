"""Suspensor Telemetry – anti-grav flight instruments.

An attitude horizon rolls and pitches as the skull hovers, with a roll
scale, altitude and grav-flux readouts and suspensor ripples radiating
beneath it.
"""

from __future__ import annotations

import math

from PIL import Image, ImageDraw

from ._common import font

NAME = "suspensor_telemetry"


def _text_c(d, cx, y, text, fnt, fill):
    """Draw text horizontally centred on cx."""
    d.text((cx - d.textlength(text, font=fnt) / 2, y), text, fill=fill, font=fnt)


def render(bezel, mask, now):
    img = Image.new("RGB", (240, 240), (4, 4, 2))
    d = ImageDraw.Draw(img)
    roll = 9 * math.sin(now * 0.7) + 3 * math.sin(now * 1.9)
    pitch = 7 * math.sin(now * 0.45 + 1.0)
    alt = 1.72 + 0.06 * math.sin(now * 0.9) + 0.02 * math.sin(now * 3.1)
    amber, dim = (230, 160, 40), (110, 70, 20)

    # Grav ripples radiating beneath the skull
    for k in range(4):
        r = 74 + ((now * 18 + k * 10) % 40)
        fade = 1 - (r - 74) / 40.0
        d.ellipse([120 - r, 120 - r, 120 + r, 120 + r], outline=(int(60 * fade), int(110 * fade), int(90 * fade)), width=1)

    # Attitude horizon inside a 70px window
    hz = Image.new("RGB", (240, 240), (30, 18, 8))
    hd = ImageDraw.Draw(hz)
    ca, sa = math.cos(math.radians(roll)), math.sin(math.radians(roll))
    off = pitch * 3.0

    def rot(x, y):
        return (120 + x * ca - y * sa, 120 + x * sa + y * ca)

    hd.polygon([rot(-200, off), rot(200, off), rot(200, 300), rot(-200, 300)], fill=(60, 30, 12))
    hd.line([rot(-200, off), rot(200, off)], fill=amber, width=2)
    for p in range(-20, 25, 10):
        if p == 0:
            continue
        y = off - p * 3.0
        w = 22 if p % 20 == 0 else 12
        hd.line([rot(-w, y), rot(w, y)], fill=(200, 150, 70), width=1)
    hmask = Image.new("L", (240, 240), 0)
    ImageDraw.Draw(hmask).ellipse([50, 50, 190, 190], fill=255)
    img.paste(hz, (0, 0), hmask)
    d.ellipse([50, 50, 190, 190], outline=dim, width=2)

    # Fixed skull reference marker
    d.line([(92, 120), (110, 120), (115, 126), (120, 120), (125, 126), (130, 120), (148, 120)], fill=(255, 220, 90), width=3)
    d.ellipse([117, 117, 123, 123], fill=(220, 30, 20))

    # Roll scale
    for a in (-30, -20, -10, 0, 10, 20, 30):
        rad = math.radians(a - 90)
        d.line([(120 + 72 * math.cos(rad), 120 + 72 * math.sin(rad)),
                (120 + (80 if a % 30 == 0 else 77) * math.cos(rad), 120 + (80 if a % 30 == 0 else 77) * math.sin(rad))], fill=dim, width=2)
    rad = math.radians(roll - 90)
    tx, ty = 120 + 70 * math.cos(rad), 120 + 70 * math.sin(rad)
    d.polygon([(tx, ty), (tx - 4, ty + 7), (tx + 4, ty + 7)], fill=amber)

    f = font(9)
    _text_c(d, 120, 22, "SUSPENSOR FIELD", f, amber)
    d.text((196, 104), "ALT", fill=dim, font=f)
    d.text((192, 116), f"{alt:.2f}m", fill=amber, font=f)
    d.text((22, 104), "ROLL", fill=dim, font=f)
    d.text((22, 116), f"{roll:+.0f}°", fill=amber, font=f)
    flux = 88 + int(6 * math.sin(now * 1.7))
    _text_c(d, 120, 196, f"GRAV FLUX {flux}%  ·  HOVER", f, (90, 170, 120))
    return img
