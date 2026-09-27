"""Thought for the Day – an auto-quill scribes Imperial maxims on parchment.

A quill nib writes each maxim letter by letter across a scorched parchment
disc, holds it, then takes up the next.
"""

from __future__ import annotations

import random

import numpy as np
from PIL import Image, ImageDraw

from ._common import Session, font, text_center

NAME = "thought_for_the_day"

_session = Session()

_YY, _XX = np.mgrid[0:240, 0:240].astype(np.float32)
_RR = np.hypot(_XX - 120, _YY - 120)


_TFTD_QUOTES = [
    "The Emperor protects.",
    "Idle hands invite heresy. Idle cogitators invite worse.",
    "Every rivet is a prayer. Every weld a hymn.",
    "The flesh is weak. The skull endures.",
    "Serve in life. Serve in death. Serve beyond.",
    "An unanswered vox is a warning unheeded.",
    "Trust the machine. Test the man.",
    "Doubt is the rust upon the soul.",
    "The Omnissiah counts every cycle wasted.",
    "Even the smallest cog turns the Titan.",
    "Oil the gear. Bless the servitor. Question nothing.",
    "Faith is armour no lasbolt can pierce.",
    "Remember the fallen. Repurpose the fallen.",
    "A clean lens sees every heresy.",
    "To hesitate is to invite the xenos.",
    "Your labours feed the Astronomican.",
    "What the Emperor wills, the skull records.",
    "Knowledge is earned, never questioned.",
    "The candle gutters. The duty does not.",
    "Obedience is the first sacrament.",
]
_tftd_state = {"quote": None, "start": 0.0, "bg": None}


def _tftd_background():
    arr = np.zeros((240, 240, 3), np.float32)
    rng = np.random.default_rng(7)
    grain = rng.normal(0, 6, (240, 240)).astype(np.float32)
    edge = np.clip((_RR - 80) / 30.0, 0, 1)
    base = np.array([196, 172, 122], np.float32)
    burn = np.array([95, 60, 25], np.float32)
    for c in range(3):
        arr[..., c] = base[c] * (1 - edge) + burn[c] * edge + grain
    arr[_RR > 112] = (20, 10, 4)
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    d = ImageDraw.Draw(img)
    d.ellipse([8, 8, 232, 232], outline=(110, 20, 15), width=3)
    text_center(d, 40, "THOUGHT FOR THE DAY", (120, 20, 15), 10)
    d.line([(66, 60), (108, 60)], fill=(90, 50, 20), width=1)
    d.line([(132, 60), (174, 60)], fill=(90, 50, 20), width=1)
    d.polygon([(120, 54), (126, 60), (120, 66), (114, 60)], outline=(120, 20, 15), fill=(160, 40, 25))
    return img


def _wrap_to_circle(text, qf, d, max_w=164):
    """Word-wrap to a width that sits inside the parchment disc."""
    lines, cur = [], ""
    for w in text.split():
        trial = (cur + " " + w).strip()
        if cur and d.textlength(trial, font=qf) > max_w:
            lines.append(cur)
            cur = w
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines


def render(bezel, mask, now):
    if _session.fresh(now):
        _tftd_state["quote"] = None
    st = _tftd_state
    if st["bg"] is None:
        st["bg"] = _tftd_background()
    qf, line_h = font(15), 20
    if st["quote"] is None or now - st["start"] > 4 + len(st["quote"]) / 16.0 + 7:
        choices = [q for q in _TFTD_QUOTES if q != st["quote"]]
        st["quote"], st["start"] = random.choice(choices), now

    img = st["bg"].copy()
    d = ImageDraw.Draw(img)
    q, t = st["quote"], now - st["start"]
    n = int(max(0.0, t - 0.6) * 16)
    lines = _wrap_to_circle(q, qf, d)
    y = 120 - len(lines) * line_h / 2 + 6
    shown, qx, qy = n, None, None
    ink = (40, 22, 10)
    for ln in lines:
        part = ln[:max(0, shown)]
        shown -= len(ln) + 1
        w = d.textlength(ln, font=qf)
        x = 120 - w / 2
        if part:
            d.text((x, y), part, fill=ink, font=qf)
            qx, qy = x + d.textlength(part, font=qf), y + 14
        y += line_h

    # Auto-quill nib hovers at the write head while typing
    if n < len(q) + 3 and qx is not None:
        jx, jy = random.uniform(-1, 1), random.uniform(-1, 1)
        d.line([(qx + jx, qy + jy), (qx + 24 + jx, qy - 34 + jy)], fill=(70, 50, 30), width=2)
        d.polygon([(qx + jx, qy + jy), (qx + 4 + jx, qy - 7 + jy), (qx - 1 + jx, qy - 6 + jy)], fill=(20, 20, 20))
        d.line([(qx + 14 + jx, qy - 20), (qx + 30 + jx, qy - 48)], fill=(210, 200, 180), width=4)
    elif n >= len(q) + 3:
        text_center(d, 186, "+ AVE IMPERATOR +", (120, 20, 15), 9)
    return img
