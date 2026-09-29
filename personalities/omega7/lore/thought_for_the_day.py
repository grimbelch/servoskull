"""Thought for the Day – the daily Ministorum dispatch arrives on the cogitator.

A green-phosphor terminal receives the vox-dispatch: a decryption bar fills, then
the maxim is set in capitals, each character flickering through cipher glyphs
before it resolves, a block cursor at the write head. The Ministorum seal and
AVE IMPERATOR follow, it holds, and a scan-wipe clears the screen for the next.
"""

from __future__ import annotations

import datetime
import math
import random

from PIL import ImageDraw

from ..classic._phosphor import AMBER, GREEN, GREEN_DIM, GREEN_HI, GREEN_MID, Phosphor, blank
from ._common import CX, Session, font, safe_half_width

NAME = "thought_for_the_day"

_session = Session()
_ph = Phosphor(decay=0.35, bloom=0.6, flicker=0.035)
_rng = random.Random()

_QUOTES = [
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
_CIPHER = "#%&*+=?/\\<>[]{}0123456789$@"
_SEALS = ["MINISTORUM SEAL: SANCTIONED", "CENSOR: APPROVED FOR ALL DECKS",
          "DISSEMINATION: MANDATORY", "RECITE AT EACH SHIFT-CHANGE"]

# Timeline of one dispatch (seconds)
_RECEIVE = 1.8          # decryption bar
_CPS = 15.0             # characters set per second
_RESOLVE = 0.25         # a character shows cipher glyphs this long before resolving
_HOLD = 7.0             # after the seal appears
_WIPE = 0.8

_state = {"quote": None, "start": 0.0, "seal": "", "dispatch": "", "spots": []}

_TOP_Y = 26
_BODY_TOP, _BODY_BOT = 96, 176
_SZ_BODY, _LH_BODY = 14, 18


def _imperial_date() -> str:
    """Imperial dating: check number, year-fraction (000-999), year, millennium."""
    today = datetime.date.today()
    frac = int((today.timetuple().tm_yday - 1) / 365 * 1000)
    return f"0 {frac:03d} {today.year % 1000:03d}.M42"


def _aquila(d, cx: float, cy: float, col, s: float = 1.0) -> None:
    """A line-art double-headed eagle: two heads, a spread of pinions each side."""
    for side in (-1, 1):
        hx = cx + side * 5 * s
        d.line([(cx, cy + 4 * s), (hx, cy - 3 * s), (hx + side * 3 * s, cy - 6 * s)], fill=col, width=1)
        d.point((hx + side * 1 * s, cy - 4 * s), fill=GREEN_HI)
        for i in range(5):                                   # pinions fan out and down
            ang = math.radians(8 + i * 11)
            length = (30 - i * 3) * s
            x0, y0 = cx + side * 6 * s, cy + 1 * s + i * 1.4 * s
            d.line([(x0, y0), (x0 + side * length * math.cos(ang), y0 + length * math.sin(ang) - 6 * s)],
                   fill=col, width=1)
    d.polygon([(cx, cy - 1 * s), (cx + 3 * s, cy + 5 * s), (cx, cy + 12 * s), (cx - 3 * s, cy + 5 * s)],
              outline=col)


def _wrap(text: str, f) -> list[tuple[str, float]]:
    """Word-wrap to the circle: each line as wide as the chord at its height allows."""
    words, lines, cur = text.split(), [], ""
    tmp = ImageDraw.Draw(blank())
    y = _BODY_TOP
    for w in words:
        trial = (cur + " " + w).strip()
        max_w = 2 * safe_half_width(y + _LH_BODY / 2, margin=18)
        if cur and tmp.textlength(trial, font=f) > max_w:
            lines.append(cur)
            cur, y = w, y + _LH_BODY
        else:
            cur = trial
    if cur:
        lines.append(cur)
    # centre the block vertically in the body area
    top = (_BODY_TOP + _BODY_BOT) / 2 - len(lines) * _LH_BODY / 2
    return [(ln, top + i * _LH_BODY) for i, ln in enumerate(lines)]


def _centered(d, y, s, col, size):
    f = font(size)
    d.text((CX - d.textlength(s, font=f) / 2, y), s, fill=col, font=f)


def _new_dispatch(now: float) -> None:
    prev = _state["quote"]
    _state["quote"] = _rng.choice([q for q in _QUOTES if q != prev]).upper()
    _state["start"] = now
    _state["seal"] = _rng.choice(_SEALS)
    f, tmp = font(_SZ_BODY), ImageDraw.Draw(blank())
    spots = []                                                # (x, y, char) in typing order
    for line, y in _wrap(_state["quote"], f):
        x = CX - tmp.textlength(line, font=f) / 2
        for ch in line + " ":                                 # the trailing space is the wrap
            spots.append((x, y, ch))
            x += tmp.textlength(ch, font=f)
    _state["spots"] = spots
    _state["dispatch"] = f"DISPATCH {_rng.randint(100, 999)}-{_rng.choice('ABKMTV')}  //  {_imperial_date()}"


def render(bezel, mask, now):
    if _session.fresh(now):
        _ph.reset()
        _new_dispatch(now)
    quote = _state["quote"]
    typing = len(quote) / _CPS + _RESOLVE
    total = _RECEIVE + typing + 0.8 + _HOLD
    t = now - _state["start"]
    if t > total + _WIPE:
        _new_dispatch(now)
        t = 0.0

    img = blank()
    d = ImageDraw.Draw(img)

    # Header: aquila, title, dispatch line, rule
    _aquila(d, CX, _TOP_Y, GREEN_MID, 0.9)
    _centered(d, _TOP_Y + 18, "+++ THOUGHT FOR THE DAY +++", GREEN_HI, 11)
    _centered(d, _TOP_Y + 33, _state["dispatch"], GREEN_DIM, 9)
    half = safe_half_width(_TOP_Y + 50, margin=22)
    d.line([(CX - half, _TOP_Y + 50), (CX + half, _TOP_Y + 50)], fill=GREEN_DIM)

    if t < _RECEIVE:                                          # receiving: decrypt bar
        blink = int(now * 3) % 2 == 0
        _centered(d, 104, "INCOMING VOX-DISPATCH", GREEN if blink else GREEN_MID, 11)
        frac = t / _RECEIVE
        bx0, bx1, by = CX - 70, CX + 70, 126
        d.rectangle([bx0, by, bx1, by + 9], outline=GREEN_MID)
        d.rectangle([bx0 + 2, by + 2, bx0 + 2 + int((bx1 - bx0 - 4) * frac), by + 7], fill=GREEN)
        noise = "".join(_rng.choice(_CIPHER) for _ in range(14))
        _centered(d, 144, f"DECRYPT {int(frac * 100):3d}%  {noise}", GREEN_DIM, 9)
    else:                                                     # the maxim, set character by character
        f = font(_SZ_BODY)
        tt = t - _RECEIVE
        n_done = int(tt * _CPS)                               # characters started
        spots = _state["spots"]
        for k, (x, y, ch) in enumerate(spots[:n_done]):
            if ch == " ":
                continue
            decoding = tt - k / _CPS < _RESOLVE
            d.text((x, y), _rng.choice(_CIPHER) if decoding else ch,
                   fill=GREEN_HI if decoding else GREEN, font=f)
        cx, cy, _ = spots[min(n_done, len(spots) - 1)]
        if n_done < len(spots) or int(now * 2.5) % 2 == 0:  # solid while setting, then blinks
            d.rectangle([cx + 1, cy + 2, cx + 8, cy + _SZ_BODY + 1], fill=GREEN_HI)
        if tt > typing + 0.8:                                 # sealed
            _centered(d, 184, "+ AVE IMPERATOR +", AMBER, 11)
            _centered(d, 199, _state["seal"], GREEN_MID, 8)

    if t > total:                                             # scan-wipe to black
        wipe_y = int((t - total) / _WIPE * 240)
        d.rectangle([0, 0, 239, wipe_y], fill=(0, 0, 0))
        d.line([(0, wipe_y), (239, wipe_y)], fill=GREEN_HI, width=2)
    return _ph.compose(img)
