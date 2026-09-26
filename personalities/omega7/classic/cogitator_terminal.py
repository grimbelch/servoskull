"""Cogitator Terminal - an interactive session on a Mechanicus cogitator.

A tech-priest logs in and works: commands are typed character by character at
the prompt (with a blinking block cursor and human hesitations), then answered
by the cogitator - process tables of machine spirits, rite listings, litany
logs, noospheric pings, progress bars for rites and decryptions, benedictions
and the occasional amber warning.  After a handful of commands the operator
logs out, the screen wipes, and another adept logs in with different habits.
"""

from __future__ import annotations

import math
import random

from PIL import Image, ImageDraw

from ..lore._common import CX, CY, Session, font, safe_half_width
from ._phosphor import AMBER, GREEN, GREEN_DIM, GREEN_HI, GREEN_MID, RED, Phosphor, blank

NAME = "cogitator_terminal"

_rng = random.Random()
_session = Session()
_ph = Phosphor(decay=0.2, bloom=0.5, flicker=0.03)

_SZ = 10
_LH = 12
_X0 = 30
_Y_TOP, _Y_BOT = 50, 190
_NVIS = (_Y_BOT - _Y_TOP) // _LH

_COLS = {"out": (40, 200, 90), "dim": (20, 120, 50), "hi": GREEN_HI, "warn": AMBER,
         "err": RED, "cmd": GREEN_HI, "pr": GREEN_MID, "pray": (150, 255, 175)}

_USERS = [("MAGOS VOSS", "VOSS"), ("ENGSEER KALL", "KALL"), ("LEXMECH ORIN", "ORIN"),
          ("ADEPT TIRE", "TIRE"), ("TECHPRST HALE", "HALE")]

_TXT: dict = {}


def _tmask(s, size=_SZ):
    k = (s, size)
    m = _TXT.get(k)
    if m is None:
        f = font(size)
        m = Image.new("L", (int(math.ceil(f.getlength(s))) + 2, size + 5), 0)
        ImageDraw.Draw(m).text((0, 0), s, fill=255, font=f)
        if len(_TXT) > 500:
            _TXT.clear()
        _TXT[k] = m
    return m


def _txt(img, x, y, s, col, size=_SZ):
    if s:
        img.paste(col, (int(x), int(y)), _tmask(s, size))


def _txt_c(img, y, s, col, size=_SZ):
    m = _tmask(s, size)
    img.paste(col, (int(CX - (m.width - 2) / 2), int(y)), m)


def _tw(s, size=_SZ):
    return _tmask(s, size).width - 2 if s else 0


# --------------------------------------------------------------------- command library

def _r(a, b):
    return _rng.randint(a, b)


def _cmd_ls():
    files = ["CALIBRATE.RIT", "OILING.RIT", "LITANY_IV.TXT", "SPIRIT.CFG", "AUSPEX.DAT",
             "BLESSING.EXE", "VALVE_3.LOG", "TITHE.LDG", "CANT_BIN.SRC", "ARCHIVE.STC"]
    yield ("type", "ls /rites")
    for f in _rng.sample(files, 5):
        yield ("out", "%s\t%4.1fK\t%s" % (_rng.choice(("RW", "R-", "RX")), _rng.uniform(0.3, 64), f), "out", 0.07, (0, 20, 58))
    yield ("out", "5 RITES. 0 HERETICAL.", "dim", 0.1)


def _cmd_ps():
    yield ("type", "ps -spirits")
    tabs = (0, 30, 100, 126)
    yield ("out", "PID\tSPIRIT\tST\tCPU", "hi", 0.1, tabs)
    names = ["LOGIS-ENG", "AUSPEX", "VOX-CAST", "SERVO-ARM", "CENSER", "MNEMO-CORE", "LUMEN"]
    for n in _rng.sample(names, 4):
        st = _rng.choice(("RUN", "RUN", "SLP", "PRY"))
        yield ("out", "%04d\t%s\t%s\t%2d%%" % (_r(10, 9999), n, st, _r(0, 64)), "out", 0.08, tabs)


def _cmd_rite():
    rite = _rng.choice(["OILING", "CALIBRATION", "CLEANSING", "ALIGNMENT", "UNGUENT"])
    yield ("type", "invoke rite.%s" % rite.lower()[:5] + " -v%d" % _r(1, 9))
    yield ("out", "INVOKING RITE OF %s" % rite, "out", 0.2)
    yield ("prog", "CHANT", _rng.uniform(2.0, 3.5))
    if _rng.random() < 0.3:
        yield ("out", "WARN: SPIRIT RESTLESS", "warn", 0.3)
        yield ("out", "APPLYING SACRED UNGUENT", "out", 0.5)
        yield ("prog", "SOOTHE", 1.6)
    yield ("out", "RITE COMPLETE. SPIRIT PLEASED", "hi", 0.2)


def _cmd_log():
    yield ("type", "cat litany.log")
    ev = ["INCENSE LIT", "CANT IV RECITED", "VALVE 3 ANOINTED", "RUNE OF WARDING SET",
          "BELL STRUCK x3", "SERVITOR PRAISED", "OIL TITHE PAID", "GEAR 12 BLESSED"]
    h = _r(0, 20)
    for i, e in enumerate(_rng.sample(ev, 4)):
        yield ("out", "[%02d:%02d] %s" % ((h + i) % 24, _r(0, 59), e), "out", 0.08)


def _cmd_ping():
    dest = _rng.choice(["FORGE.MARS", "STYGIES.VIII", "AGRIPINAA", "METALICA"])
    yield ("type", "ping %s" % dest.lower())
    lat = _r(300, 900)
    for i in range(3):
        yield ("out", "REPLY %s %dMS" % (dest[:12], lat + _r(-40, 60)), "out", 0.5)
    yield ("out", "3/3 RETURNED. WARP STABLE", "dim", 0.2)


def _cmd_bless():
    tgt = _rng.choice(["servo-7", "auspex", "vox-array", "core-2"])
    yield ("type", "bless %s" % tgt)
    for line in _rng.choice([("O SPIRIT OF THE MACHINE", "ACCEPT THIS OFFERING", "+++ BLESSED +++"),
                             ("FROM THE WEAKNESS OF FLESH", "THE MACHINE DELIVERS US", "+++ AVE +++"),
                             ("GUIDE THIS HUMBLE ENGINE", "THROUGH THE DARK", "+++ SANCTIFIED +++")]):
        yield ("out", line, "pray", 0.45)


def _cmd_decrypt():
    yield ("type", "decrypt vault_%02d.dat" % _r(1, 99))
    for _ in range(3):
        yield ("out", " ".join("%02X" % _r(0, 255) for _ in range(7)), "dim", 0.06)
    yield ("prog", "CIPHER", _rng.uniform(2.5, 4.0))
    if _rng.random() < 0.25:
        yield ("out", "ERR: KEY-RUNE MISMATCH", "err", 0.2)
        yield ("out", "RETRYING WITH SEAL OF MARS", "warn", 0.4)
        yield ("prog", "CIPHER", 1.5)
    yield ("out", "ACCESS GRANTED", "hi", 0.2)


def _cmd_df():
    yield ("type", "df -h")
    tabs = (0, 58, 96)
    yield ("out", "VOL\tSIZE\tUSED", "hi", 0.1, tabs)
    for v in ("MNEMO-A", "MNEMO-B", "RELIQ", "SCRAP"):
        u = _r(8, 97)
        yield ("out", "%s\t%dT\t%d%%" % (v, _r(2, 64), u), "warn" if u > 90 else "out", 0.07, tabs, u)


def _cmd_sync():
    n = _r(4, 60)
    yield ("type", "sync noosphere")
    yield ("out", "UPLOADING %d RECORDS" % n, "out", 0.2)
    yield ("prog", "UPLINK", _rng.uniform(2.0, 3.0))
    yield ("out", "SYNC OK. %d/%d ACCEPTED" % (n, n), "hi", 0.2)


def _cmd_purge():
    yield ("type", "sudo purge heretek.bin")
    yield ("out", "WARN: REQUIRES MAGOS SEAL", "warn", 0.3)
    yield ("out", "SEAL VERIFIED", "out", 0.8)
    yield ("prog", "PURGE", 2.0)
    yield ("out", "HERETEK CODE PURGED", "hi", 0.2)


def _cmd_uptime():
    yield ("type", "uptime")
    yield ("out", "UP %d DAYS  LOAD %.2f" % (_r(20, 900), _rng.uniform(0.1, 2.0)), "out", 0.15)


def _cmd_scan():
    yield ("type", "scan --auspex")
    yield ("prog", "SWEEP", _rng.uniform(1.8, 2.8))
    c = _r(0, 5)
    yield ("out", "%d CONTACTS  0 HOSTILE" % c, "out", 0.15)
    if c:
        yield ("out", "NEAREST %dM BEARING %03d" % (_r(20, 900), _r(0, 359)), "dim", 0.1)


_CMDS = [_cmd_ls, _cmd_ps, _cmd_rite, _cmd_log, _cmd_ping, _cmd_bless, _cmd_decrypt,
         _cmd_df, _cmd_sync, _cmd_purge, _cmd_uptime, _cmd_scan]


def _script():
    """Endless sequence of sessions."""
    first = True
    while True:
        user, short = _rng.choice(_USERS)
        _S["user"] = short
        _S["sess"] = _r(0x10, 0xFF)
        if not first:
            yield ("clear",)
        first = False
        yield ("out", "OMEGA-7 COGITATOR  TTY-3", "dim", 0.15)
        yield ("login", "LOGIN: ", user)
        yield ("login", "RUNE-KEY: ", "*" * _r(6, 9))
        yield ("out", "IDENTITY CONFIRMED", "hi", 0.4)
        yield ("out", "MAY YOUR CODE RUN TRUE", "pray", 0.3)
        yield ("wait", 0.8)
        cmds = _rng.sample(_CMDS, _r(5, 7))
        for c in cmds:
            yield ("wait", _rng.uniform(0.5, 1.6))
            yield from c()
        yield ("wait", 1.2)
        yield ("type", "logout")
        yield ("out", "SESSION CLOSED", "dim", 0.2)
        yield ("out", "PRAISE THE OMNISSIAH", "pray", 0.4)
        yield ("wait", 1.6)


# --------------------------------------------------------------------- state machine

_S: dict = {}


def _reset(t):
    _S.clear()
    _S.update(t0=t, lines=[], scroll=0.0, act=None, act_t=t, gen=None, wipe=None,
              user="", sess=0)
    _S["gen"] = _script()


def _push(text, col, kind="text", **kw):
    e = {"text": text, "col": col, "kind": kind}
    e.update(kw)
    _S["lines"].append(e)
    if len(_S["lines"]) > 40:
        del _S["lines"][:-40]
    _S["scroll"] += _LH


def _prompt():
    return "%s$ " % _S["user"]


def _begin(act, t):
    _S["act"] = act
    _S["act_t"] = t
    k = act[0]
    if k == "type":
        # per-character typing schedule with hesitations
        times, acc = [], _rng.uniform(0.2, 0.6)
        for ch in act[1]:
            acc += _rng.uniform(0.05, 0.13) + (0.25 if _rng.random() < 0.06 else 0.0)
            times.append(acc)
        _S["sched"] = times
        _push(_prompt(), _COLS["pr"], "prompt", cmd="", live=True)
    elif k == "login":
        times, acc = [], _rng.uniform(0.3, 0.6)
        for ch in act[2]:
            acc += _rng.uniform(0.06, 0.14)
            times.append(acc)
        _S["sched"] = times
        _push(act[1], _COLS["dim"], "prompt", cmd="", live=True)
    elif k == "prog":
        _push(act[1], _COLS["out"], "prog", p=0.0, dur=act[2])
    elif k == "clear":
        _S["wipe"] = t


def _step(t):
    """Advance the script; returns when the current action is still running."""
    for _ in range(8):
        act = _S["act"]
        if act is None:
            _begin(next(_S["gen"]), t)
            continue
        u = t - _S["act_t"]
        k = act[0]
        if k in ("type", "login"):
            line = _S["lines"][-1]
            text = act[1] if k == "type" else act[2]
            n = sum(1 for x in _S["sched"] if x <= u)
            line["cmd"] = text[:n]
            if n >= len(text) and u >= _S["sched"][-1] + 0.35:
                line["live"] = False
                _S["act"] = None
                _S["act_t"] = _S["act_t"] + _S["sched"][-1] + 0.35
                continue
            return
        if k == "out":
            if u >= act[3]:
                _push(act[1], _COLS[act[2]], tabs=act[4] if len(act) > 4 else None,
                      bar=act[5] if len(act) > 5 else None)
                _S["act"] = None
                _S["act_t"] += act[3]
                continue
            return
        if k == "wait":
            if u >= act[1]:
                _S["act"] = None
                _S["act_t"] += act[1]
                continue
            return
        if k == "prog":
            line = _S["lines"][-1]
            dur = act[2]
            # progress moves in uneven lurches
            x = min(1.0, u / dur)
            line["p"] = min(1.0, x + 0.04 * math.sin(x * 17))
            if u >= dur + 0.25:
                line["p"] = 1.0
                _S["act"] = None
                _S["act_t"] += dur + 0.25
                continue
            return
        if k == "clear":
            if u >= 0.9:
                _S["lines"] = []
                _S["scroll"] = 0.0
                _S["wipe"] = None
                _S["act"] = None
                _S["act_t"] += 0.9
                continue
            return
        _S["act"] = None
    return


# --------------------------------------------------------------------- drawing

def _draw_lines(img, d, t):
    lines = _S["lines"]
    vis = lines[-(_NVIS + 1):]
    n = len(vis)
    base = _Y_BOT - _LH + _S["scroll"]
    for i, e in enumerate(vis):
        y = base - (n - 1 - i) * _LH
        if y < _Y_TOP - _LH + 2 or y > _Y_BOT + 4:
            continue
        fade = min(1.0, (y - (_Y_TOP - _LH)) / 18.0)
        col = e["col"]
        if fade < 1:
            col = tuple(int(c * max(0.0, fade)) for c in col)
        k = e["kind"]
        if k == "text":
            tabs = e.get("tabs")
            if tabs:
                for field, tx in zip(e["text"].split("\t"), tabs):
                    _txt(img, _X0 + tx, y, field, col)
                if e.get("bar") is not None:
                    bx = _X0 + tabs[-1] + 30
                    d.rectangle([bx, y + 4, bx + 40, y + 9], outline=GREEN_DIM)
                    d.rectangle([bx + 1, y + 5, bx + 1 + int(38 * e["bar"] / 100), y + 8], fill=col)
            else:
                _txt(img, _X0, y, e["text"], col)
        elif k == "prompt":
            _txt(img, _X0, y, e["text"], col)
            x = _X0 + _tw(e["text"])
            cc = _COLS["cmd"] if fade >= 1 else col
            _txt(img, x, y, e["cmd"], cc)
            if e.get("live") and int(t * 2.6) % 2 == 0:
                cx = x + _tw(e["cmd"]) + 1
                d.rectangle([cx, y + 2, cx + 5, y + 11], fill=GREEN_HI)
        elif k == "prog":
            _txt(img, _X0, y, e["text"], col)
            bx0 = _X0 + 44
            bx1 = _X0 + 136
            d.rectangle([bx0, y + 3, bx1, y + 10], outline=_COLS["dim"] if fade >= 1 else col)
            p = e["p"]
            fx = bx0 + 2 + (bx1 - bx0 - 4) * p
            if p > 0:
                d.rectangle([bx0 + 2, y + 5, fx, y + 8], fill=GREEN if p < 1 else GREEN_HI)
                # segment ticks
                for sx in range(bx0 + 10, int(fx), 9):
                    d.line([(sx, y + 5), (sx, y + 8)], fill=(0, 0, 0))
            _txt(img, bx1 + 5, y, "%3d%%" % int(p * 100), GREEN_HI if p >= 1 else col)


def _draw_frame(img, d, t):
    # header plate
    user = _S.get("user", "")
    _txt_c(img, 22, "TTY-3  SESS %02X" % _S.get("sess", 0), GREEN_MID, 9)
    _txt_c(img, 33, "OP: %s" % (user or "----"), (20, 150, 60), 9)
    d.line([(46, 46), (194, 46)], fill=GREEN_DIM)
    d.line([(46, 194), (194, 194)], fill=GREEN_DIM)
    # footer: clock and a load blip
    st = int(t - _S["t0"]) + 4 * 3600 + 17 * 60
    clock = "%02d:%02d:%02d" % ((st // 3600) % 24, (st // 60) % 60, st % 60)
    load = 8 + int(30 * (0.5 + 0.5 * math.sin(t * 0.7)) * (1.6 if _S["act"] and _S["act"][0] == "prog" else 1.0))
    _txt_c(img, 198, "%s  LD %02d%%" % (clock, min(99, load)), (20, 130, 55), 9)
    busy = _S["act"] is not None and _S["act"][0] in ("prog", "out")
    c = GREEN_HI if busy and int(t * 8) % 2 == 0 else GREEN_DIM
    d.ellipse([CX - 2, 212, CX + 2, 216], fill=c)


def render(bezel, mask, now: float) -> Image.Image:
    if _session.fresh(now) or not _S:
        _reset(now)
        _ph.reset()
    t = now
    _step(t)
    # smooth scroll: new lines slide up into place
    _S["scroll"] = max(0.0, _S["scroll"] * 0.55 - 0.3)
    img = blank()
    d = ImageDraw.Draw(img)
    _draw_lines(img, d, t)
    if _S["wipe"] is not None:
        u = min(1.0, (t - _S["wipe"]) / 0.8)
        y = _Y_TOP - 14 + (_Y_BOT - _Y_TOP + 18) * u
        d.rectangle([0, _Y_TOP - 14, 239, y], fill=(0, 0, 0))
        d.line([(20, y), (220, y)], fill=GREEN_HI)
    _draw_frame(img, d, t)
    return _ph.compose(img)
