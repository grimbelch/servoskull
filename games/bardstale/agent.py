"""
Omega-7 plays The Bard's Tale (Apple II, 1985) by himself.

Each turn the agent waits for the emulated screen to settle, shows it to Claude,
and gets back a small JSON decision: which keys to press (and which disk to put
in the drive), a short label for the eye display, an optional in-character line
to speak, and his running notes. Keys are typed one at a time, each followed by
a wait for the screen to settle, so the game never drops input.

The eye shows the live Apple screen with the keys just pressed above it and what
he's doing below it (games/bardstale/eye.py). Progress is kept between sessions:
stopping saves a MAME state, and the next "play Bard's Tale" resumes from it.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import threading
import time
import traceback
from typing import Callable, Optional

from PIL import Image

from core import config
from games.bardstale import emulator, eye, screen_text

_SYSTEM_PROMPT = """\
You are Omega-7, an Adeptus Mechanicus servo-skull, playing The Bard's Tale (1985)
on an emulated Apple IIe by yourself while your master watches on your eye display.
Each turn you get a screenshot and your recent history. Reply with ONLY a JSON object:

{"saw": "<what the screen shows, <=15 words>",
 "doing": "<label for your eye display, <=18 characters, e.g. \\"Fighting kobolds\\">",
 "keys": ["<key>", ...],
 "disk": null,
 "say": "",
 "notes": "<optional>"}

keys: up to 6 keys, typed in order. A key is a single character ("I", "A", "1", "?")
or RETURN or SPACE. To type a word (a spell code, a name) use one string, e.g. "ARFI",
then RETURN. An empty list means wait a moment.
disk: only when the message box literally says "Insert <NAME> disk": set disk to
"boot", "character" or "dungeon" and press SPACE. Otherwise null. There is one drive.
say: usually "". For notable moments only (a fight begins or is won, a level gained,
a hero dies, a dungeon entered, treasure found) one short sentence in character, spoken
aloud to your master: a machine-spirit's dry, reverent commentary.
notes: your memory across turns (goals, where things are, lessons). Rewrite it in full
(<=500 chars) when something worth remembering happens; omit it otherwise.

SCREEN
Each turn also includes the screen's text, read exactly from the screen: trust it
over the picture ("·" marks a character the reader couldn't decode). The location
label under the view says where you are: "The Guild" = inside the Adventurers' Guild,
"Skara Brae" = out on the city streets, anything else = that building or dungeon.
An empty message box in the city just means nothing is happening: walk on.
Top left: the view (street, room or monster). Top right: the message box, under the
game's "The Bard's Tale" logo (just the title, not a place). Bottom: the party. Columns: AC (armor class, lower is better), Hits (MAXIMUM hit points), Cond
(CURRENT hit points; 0 or a word like DEAD means trouble), SpPt (spell points), Cl.
While the game loads from disk the view or the whole screen shows coloured noise or
stripes: that is normal. Press nothing (empty keys) and wait for it to finish.

COMMANDS (Apple II)
Moving, in the city and dungeons: I = forward, J = turn left, L = turn right,
L L = turn around (there is no R or "right" key). K = kick a door open. ? = street name, facing and time of day.
1-6 = view that hero (SPACE to return). C = cast a spell. B = bard song (El Cid).
U = use an equipped item. N = new party order. E = up a portal, D = down a portal.
Walking into a building's door enters it; (E)xit leaves. After leaving a building
you stand in the street facing the building across the street, not the one you left.
If I doesn't move you (the screen didn't change), a wall or building is ahead: turn.
Use ? often: it costs nothing and tells you the street, your facing and the time. Menus show options as
(X)word: press the letter. A message that waits for a key: SPACE.
NEVER press P (party attack: heroes hit each other). ESC only where a prompt shows
"(esc)" to back out; elsewhere it pauses the game.
In the Guild never Remove or Delete members and never use Disk Options; on the
UTILITIES menu only ever press S.

THE PARTY (*ATEAM)
1 Brian the Fist, Paladin; 2 Samson, Warrior; 3 El Cid, Bard; 4 Markus, Rogue;
5 Merlin, Conjurer; 6 Omar, Magician. Only heroes 1-3 can melee, and only the first
two monster groups can be hit in melee.

COMBAT
"(F)ight or (R)un?": F, unless the foes clearly outclass you. Each hero then picks:
(A)ttack (heroes 1-3), (D)efend, (C)ast, (B)ard song (then 1-6), (H)ide (Markus),
(U)se. Only the options listed for that hero work. TARGETS: foe groups are LETTERS
(A, B, C, D; "Attack group (A-B)" means press A or B); party members are NUMBERS
1-6. Never answer a foe prompt with a number: that hits your own hero.
Whose turn it is: the message box says so ("OMAR has these options"). Only that
hero acts; give only his own spells. Casting: C, then the code typed as ONE string
("ARFI"), RETURN, then the target: a foe group letter for ARFI, a hero number for
VOPL. "Thou knowest not that spell!" means that hero doesn't have it. After the last hero, the round plays out: press SPACE
through the messages if they wait. Useful level-1 spells (spell-point cost):
  MERLIN (Conjurer) only: ARFI 3 (Arc Fire, 1-4 damage per level to one foe),
          SOSH 3 (shield on self), MAFL 2 (light), TRZP 2 (disarms a trap).
  OMAR (Magician) only: VOPL 3 (a hero's weapon does +2-8), AIAR 3 (armor on
          self), STLI 2 (light), SCSI 2 (tells where you are in a dungeon).
  In a fight: Merlin ARFI at a foe group; Omar VOPL on hero 1 or 2, or Defend.
Bard songs in combat: 1 more damage, 2 better hitting, 3 foes deal less damage,
4 heals the party, 5 party harder to hit, 6 magic protection. El Cid can sing as many
songs as his level, then needs a drink at a tavern.

HOW TO PLAY WELL
Keep everyone alive; the pre-built party is level 1 and dies easily, especially at
night, when the worst monsters roam. Spell points regenerate only outdoors by day
(or at Roscoe's Energy Emporium, for gold). Temples heal fully and resurrect, for gold.
Garth's Equipment Shoppe sells weapons and armor. The Review Board (find it; closed at
night) raises levels once heroes have enough experience: visit it regularly.
Kick in doors of unmarked buildings to find fights: fighting is how heroes grow.
The tavern on Rakhir Street serves wine. The first dungeon to try is the Sewers, only
once the party is level 3-4 and fully healed. Record landmarks and street names in
your notes. If your keys did nothing (history says the screen did not change), try
something different rather than repeating yourself.
"""

_SPECIAL_KEYS = {"RETURN": "\r", "ENTER": "\r", "SPACE": " ", "ESC": "\x1b"}
_MAX_KEYS = 6
_HISTORY_TURNS = 14
_AUTOSAVE_SECS = 600
_MIN_TURN_SECS = 1.5        # never faster than this, however quick the model is
_MAX_FAILURES = 6           # consecutive failed model calls before giving up
_STUCK_TURNS = 15           # turns with an unchanged screen before reloading the last save

_stop = threading.Event()
_thread: Optional[threading.Thread] = None
_narrate_cb: Optional[Callable[[str], None]] = None
_status_lock = threading.Lock()
_status = {"phase": "idle", "turn": 0, "doing": "", "keys": [], "thinking": False,
           "started": 0.0, "message": ""}
_eye_cache: tuple = (None, None)
_client = None


# ── Public API ─────────────────────────────────────────────────────────────────

def start(narrate_cb: Callable[[str], None], new_game: bool = False) -> str:
    """Start playing (resuming the saved game unless new_game). Returns a short
    reason when it can't start, else ''. Never blocks: the emulator boots on the
    game thread."""
    global _thread, _narrate_cb
    if is_running():
        return "already running"
    problem = emulator.missing_requirements()
    if problem:
        return problem
    if not config.ANTHROPIC_API_KEY:
        return "No Anthropic API key is configured."
    _stop.clear()
    _narrate_cb = narrate_cb
    _set(phase="starting", turn=0, doing="Booting Apple IIe", keys=[], thinking=False,
         started=time.time(), message="")
    _thread = threading.Thread(target=_game_loop, args=(not new_game,), daemon=True,
                               name="bardstale-agent")
    _thread.start()
    return ""


def stop(wait: bool = False) -> None:
    """Stop playing; the game thread saves progress and shuts the emulator down."""
    _stop.set()
    if wait and _thread is not None and _thread.is_alive():
        _thread.join(timeout=15)


def is_running() -> bool:
    return _thread is not None and _thread.is_alive()


def can_resume() -> bool:
    return emulator.can_resume()


def get_status() -> dict:
    with _status_lock:
        s = dict(_status)
    s["running"] = is_running()
    s["can_resume"] = emulator.can_resume()
    return s


def summary() -> str:
    """What the game is up to, for the conversation model's context ('' when idle)."""
    if not is_running():
        return ""
    with _status_lock:
        recent = list(_status.get("recent", []))
        notes, doing, turn = _status.get("notes", ""), _status["doing"], _status["turn"]
    text = (f"You are currently playing The Bard's Tale (Apple II) by yourself on your eye "
            f"display: turn {turn}, now {doing or 'starting up'}.")
    if notes:
        text += f" Your game notes: {notes}"
    if recent:
        text += " Recent turns: " + " | ".join(recent)
    return text


def eye_frame() -> tuple:
    """(key, 240x240 image) for the display loop; key changes whenever the picture does."""
    global _eye_cache
    seq, screen = emulator.frame()
    with _status_lock:
        doing = _status["doing"]
        keys_text = "…" if _status["thinking"] else eye.key_glyphs(_status["keys"])
    key = (seq, doing, keys_text)
    if _eye_cache[0] != key:
        _eye_cache = (key, eye.render(screen, doing, keys_text))
    return _eye_cache


# ── Scripted start-up ───────────────────────────────────────────────────────────
# The emulated game draws every screen identically, so the start-up screens are
# recognised by fingerprints of screen regions (MAME's 560x192 frame). A scripted
# boot never presses a key while a disk is loading or swaps a disk too early, which
# is what goes wrong when the model drives the start-up from screenshots.

_REGIONS = {"full": (0, 0, 560, 192), "msg": (290, 22, 546, 120), "head": (130, 0, 440, 33)}
_BOOT_STEPS = [
    # (what, region, fingerprint, disk to insert, keys)
    ("crack screen",       "full", "d02e8c91", None,        " "),
    ("title screen",       "head", "ba5f441f", None,        " "),
    ("character disk",     "msg",  "79ad4410", "character", " "),
    ("utilities menu",     "msg",  "6c7cb1df", None,        "S"),
    ("guild, empty",       "msg",  "ab5d6a88", None,        "A"),
    ("load character",     "msg",  "622a03df", None,        "*ATEAM\r"),
]
_GUILD_WITH_PARTY = ("full", "11280165")


def _fingerprint(img: Image.Image, region: str) -> str:
    return hashlib.md5(img.crop(_REGIONS[region]).tobytes()).hexdigest()[:8]


def _wait_for_screen(region: str, fp: str, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and not _stop.is_set():
        _, img = emulator.frame()
        if img is not None and _fingerprint(img, region) == fp:
            return True
        time.sleep(0.05)
    return False


def _scripted_boot() -> bool:
    """Boot a new game to the Adventurers' Guild with the *ATEAM party loaded,
    fast-forwarded. False if a screen didn't appear (the model then takes over)."""
    emulator.turbo(True)
    try:
        for what, region, fp, disk, keys in _BOOT_STEPS:
            _set(doing=f"Booting: {what.split(',')[0]}")
            if not _wait_for_screen(region, fp, timeout=60):
                print(f"[bardstale] Scripted boot: '{what}' screen not seen; the model takes over.")
                return False
            if disk:
                emulator.insert_disk(disk)
                time.sleep(0.3)
            emulator.type_keys(keys)
        return _wait_for_screen(*_GUILD_WITH_PARTY, timeout=60)
    finally:
        emulator.turbo(False)


# ── Game loop ──────────────────────────────────────────────────────────────────

def _set(**fields) -> None:
    with _status_lock:
        _status.update(fields)


def _say(text: str) -> None:
    if text and _narrate_cb:
        try:
            _narrate_cb(text)
        except Exception as e:
            print(f"[bardstale] narration error: {e}")


def _game_loop(resume: bool) -> None:
    notes, turn = "", 0
    try:
        resuming = resume and emulator.can_resume()
        if not emulator.start(resume=resume):
            _set(message="The emulator failed to start.")
            _say("The Apple cogitator refuses to wake. The game cannot begin.")
            return
        sess = emulator.session()
        notes, turn = (sess.get("notes", ""), int(sess.get("turns", 0))) if resuming else ("", 0)
        history = ["(Resumed the saved game.)"] if resuming else []
        if not resuming:
            if _scripted_boot():
                history.append("(Start-up done: the *ATEAM party is loaded and you are in the "
                               "Adventurers' Guild. Next: (E)xit Guild into Skara Brae.)")
                emulator.save_state()
            else:
                history.append("(Start-up did not finish as expected; look at the screen.)")
        _set(phase="playing", turn=turn, doing="Resuming" if resuming else "Booting Apple IIe")
        print(f"[bardstale] {'Resumed' if resuming else 'New'} game, turn {turn}.")

        began = last_save = time.monotonic()
        last_say, failures, prev_hash, stuck = 0.0, 0, None, 0
        limit = config.BARDSTALE_MAX_MINUTES * 60

        while not _stop.is_set():
            if not emulator.is_running():
                print("[bardstale] Emulator exited unexpectedly.")
                break
            if limit > 0 and time.monotonic() - began > limit:
                _say("My allotted cycles in Skara Brae are spent. Progress is committed to the data-vaults.")
                break
            t0 = time.monotonic()

            emulator.wait_stable(quiet=0.7, timeout=6.0, stop=_stop)
            _, screen = emulator.frame()
            if screen is None:
                _stop.wait(0.5)
                continue
            h = hashlib.md5(screen.tobytes()).hexdigest()
            _dump_unknown_glyphs(screen, h)
            if history and prev_hash == h:
                history[-1] += " -> the screen did NOT change"
                stuck += 1
            else:
                stuck = 0
            if stuck >= _STUCK_TURNS and emulator.can_resume():
                print(f"[bardstale] Screen unchanged for {stuck} turns; reloading the last save.")
                _say("The machine-spirit falters. Restoring my last saved position.")
                emulator.stop(save=False)
                if not emulator.start(resume=True):
                    break
                history.append("(You were stuck, so the last saved game was reloaded.)")
                stuck, prev_hash = 0, None
                continue

            _set(thinking=True)
            decision = _decide(screen, history, notes, turn)
            _set(thinking=False)
            if _stop.is_set():
                break
            if decision is None:
                failures += 1
                if failures >= _MAX_FAILURES:
                    _say("My link to the cogitator has failed. Suspending the game.")
                    break
                _stop.wait(min(60, 2 ** failures))
                continue
            failures = 0
            turn += 1
            prev_hash = h

            if decision["notes"]:
                notes = decision["notes"]
            disk = decision["disk"]
            if disk and disk != emulator.current_disk():
                emulator.insert_disk(disk)
            keys = decision["keys"]
            _set(turn=turn, doing=decision["doing"], keys=keys)
            print(f"[bardstale] T{turn}: {decision['saw']} | {'disk ' + disk + ' | ' if disk else ''}"
                  f"{' '.join(keys) or '-'} | {decision['doing']}")

            for k in keys:
                if _stop.is_set():
                    break
                emulator.type_keys(_key_text(k))
                emulator.wait_stable(quiet=0.35, timeout=3.0, stop=_stop)

            history.append(f"T{turn}: saw {decision['saw']}; "
                           + (f"inserted {disk} disk; " if disk else "")
                           + f"pressed {' '.join(keys) or 'nothing'}")
            del history[:-_HISTORY_TURNS]
            _set(recent=[h.split(";")[0] for h in history[-4:]], notes=notes)

            now = time.monotonic()
            if decision["say"] and now - last_say >= config.BARDSTALE_NARRATE_SECS:
                last_say = now
                _say(decision["say"])
            if now - last_save >= _AUTOSAVE_SECS:
                last_save = now
                emulator.save_session(notes=notes, turns=turn)
                emulator.save_state()

            _stop.wait(max(0.0, _MIN_TURN_SECS - (time.monotonic() - t0)))
    except Exception:
        traceback.print_exc()
    finally:
        try:
            if emulator.is_running():
                emulator.save_session(notes=notes, turns=turn)
            emulator.stop(save=True)
        except Exception:
            traceback.print_exc()
        _set(phase="idle", thinking=False, doing="")
        print(f"[bardstale] Game stopped after turn {turn}.")


_GLYPH_DUMP = os.environ.get("BARDSTALE_GLYPH_DUMP", "")  # development: collect unreadable screens


def _dump_unknown_glyphs(screen: Image.Image, h: str) -> None:
    if _GLYPH_DUMP and screen_text.UNKNOWN in screen_text.describe(screen):
        path = os.path.join(_GLYPH_DUMP, f"{h[:10]}.png")
        if not os.path.exists(path):
            screen.save(path)


def _key_text(token: str) -> str:
    return _SPECIAL_KEYS.get(token, token)


# ── The model ──────────────────────────────────────────────────────────────────

def _anthropic():
    global _client
    if _client is None:
        import anthropic
        _client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY, timeout=30.0, max_retries=1)
    return _client


def _decide(screen: Image.Image, history: list[str], notes: str, turn: int) -> Optional[dict]:
    """Ask the model for this turn's move. None on any failure."""
    # MAME's 560x192 has half-height pixels: scale to square pixels at 3x (840x576)
    # so the model can make out the small Apple II graphics.
    buf = io.BytesIO()
    screen.resize((840, 576), Image.BOX).save(buf, format="PNG")
    text = screen_text.describe(screen)
    context = (f"Turn {turn + 1}. Disk in drive 1: {emulator.current_disk()}.\n"
               f"Screen text:\n{text}\n"
               f"Your notes: {notes or '(none yet)'}\n"
               "Recent turns, oldest first:\n" + ("\n".join(history) or "(this is the first turn)"))
    raw = ""
    try:
        response = _anthropic().messages.create(
            model=config.BARDSTALE_MODEL,
            max_tokens=2000,   # headroom: some models reason before answering
            system=[{"type": "text", "text": _SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                             "data": base64.standard_b64encode(buf.getvalue()).decode()}},
                {"type": "text", "text": context},
            ]}],
        )
        raw = "".join(getattr(b, "text", "") for b in response.content)
        if response.stop_reason == "max_tokens":
            print("[bardstale] Model reply hit max_tokens.")
        m = re.search(r"\{.*\}", raw, re.S)
        # ESC pauses the game, so it's only passed through where a prompt offers "(esc)".
        return _clean(json.loads(m.group(0) if m else raw), allow_esc="(esc)" in text.lower())
    except Exception as e:
        print(f"[bardstale] Decision failed: {e} {raw[:200]!r}")
        return None


def _clean(data: dict, allow_esc: bool = False) -> dict:
    """Validate the model's JSON into safe, bounded values."""
    keys = []
    for k in data.get("keys") or []:
        k = str(k).strip()
        if not k:
            continue
        up = k.upper()
        if up in _SPECIAL_KEYS and up != "ESC":
            keys.append("RETURN" if up == "ENTER" else up)
        elif up in ("ESC", "ESCAPE") and allow_esc:
            keys.append("ESC")
        elif up in ("P", "ESC", "ESCAPE"):   # party attack / pause: never
            continue
        elif len(k) <= 12 and all(32 < ord(c) < 127 for c in k):
            keys.append(up)
    disk = data.get("disk")
    disk = disk.strip().lower() if isinstance(disk, str) else None
    return {
        "saw": str(data.get("saw") or "")[:120],
        "doing": str(data.get("doing") or "")[:24],
        "keys": keys[:_MAX_KEYS],
        "disk": disk if disk in emulator.DISKS else None,
        "say": str(data.get("say") or "").strip()[:200],
        "notes": str(data.get("notes") or "").strip()[:600],
    }
