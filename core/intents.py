"""Deterministic, pre-LLM intents for the main loop.

Some requests are handled without the model: they must be exact (dice, volume,
display rotation), must work when the model is misbehaving (conversation
reset), or answer a question the skull just asked (a briefing offer, a
maintenance confirmation). Every matcher here is a pure function of the
lower-cased transcript plus a Context of loop facts, returning an Intent or
None, so the whole table is unit-tested in tests/test_intents.py. main.py runs
the matchers in its _LOCAL_INTENTS order and hands each Intent to a handler.

Matching rules of thumb:
- Commands are matched against the whole utterance after dropping filler
  ("please", "omega 7", "can you"…), never as a bare substring, so "please
  resume the story" or "turn off the music" don't trip unrelated handlers.
- A matcher never touches hardware, config or the network.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Context:
    screensavers: tuple[str, ...] = ()
    game_running: bool = False          # Bard's Tale is being played
    awaiting_briefing: bool = False     # the skull just offered the morning briefing
    pending_maintenance: bool = False   # the skull just asked "confirm …? Speak yes"
    eye_styles: tuple[tuple[str, tuple[str, ...]], ...] = ()  # (style, spoken names) per eye design


@dataclass(frozen=True)
class Intent:
    kind: str
    args: dict = field(default_factory=dict)


# ── Helpers ───────────────────────────────────────────────────────────────────

def said_any(text: str, phrases) -> bool:
    """Whole-word/phrase match, so "now" or "know" don't read as "no"."""
    return any(re.search(rf"\b{re.escape(p)}\b", text) for p in phrases)


_FILLER = re.compile(
    r"\b(?:please|now|immediately|hey|ok|okay|omega\s*(?:7|seven|8|eight)|servitor|jax|can you|"
    r"could you|would you|will you|i want you to|i need you to|go ahead and|the|a)\b"
)


def normalize(text: str) -> str:
    """Lower-case, drop punctuation and filler words, collapse whitespace.
    "Omega 7, please stop the music now!" -> "stop music"."""
    t = re.sub(r"[^a-z0-9\s']", " ", (text or "").lower())
    return " ".join(_FILLER.sub(" ", t).split())


# ── Answers to questions the skull asked ──────────────────────────────────────

CONFIRM_YES = ("yes", "yeah", "yep", "yup", "affirmative", "confirm", "confirmed", "do it", "proceed",
               "go ahead", "i'm sure", "i am sure", "correct", "aye")
CONFIRM_NO = ("no", "nope", "nah", "cancel", "abort", "stop", "don't", "do not", "negative",
              "never mind", "nevermind", "wait")


def maintenance_reply(text: str, ctx: Context) -> Intent | None:
    """The yes/no to "confirm a reboot?"; answer None means it was a new request."""
    if not ctx.pending_maintenance:
        return None
    if said_any(text, CONFIRM_YES) and not said_any(text, CONFIRM_NO):
        answer = "yes"
    elif said_any(text, CONFIRM_NO):
        answer = "no"
    else:
        answer = None
    return Intent("maintenance_reply", {"answer": answer})


BRIEFING_KEYS = ("briefing", "morning update", "daily update", "morning report", "daily report",
                 "morning telemetry", "daily telemetry", "morning dispatch", "daily dispatch")
_BRIEFING_YES = ("yes", "sure", "yeah", "yep", "yup", "ready", "affirmative", "proceed", "deliver",
                 "go ahead", "please", "of course", "absolutely", "aye", "correct", "indeed", "do it",
                 "ok", "okay", "give it to me", "tell me", "update", "i am", "i'm ready", "let's hear it",
                 "go on", "hit me", "let's go", "lay it on me", "bring it", "go for it")
_BRIEFING_NO = ("no", "not now", "later", "skip", "negative", "cancel", "nevermind", "never mind",
                "pass", "maybe later", "not yet", "nope", "nah", "not ready", "i'm not", "i am not",
                "don't", "do not")


def briefing(text: str, ctx: Context) -> Intent | None:
    """A request for the morning briefing, or the answer to the skull's offer of one."""
    asked = any(k in text for k in BRIEFING_KEYS)
    if not (ctx.awaiting_briefing or asked):
        return None
    # Declines are checked first so "I am not ready" isn't taken as a yes.
    declined = ctx.awaiting_briefing and said_any(text, _BRIEFING_NO)
    if not declined and (asked or said_any(text, _BRIEFING_YES)):
        answer = "yes"
    elif declined:
        answer = "no"
    else:
        answer = "unclear"
    return Intent("briefing", {"answer": answer})


# ── Commands ──────────────────────────────────────────────────────────────────

_SCREENSAVER_RE = re.compile(r"(?:play|run|show|start|trigger|exec|execute)?\s*([a-z0-9_]+)\s*(?:screensaver|visual emulation)")


def screensaver(text: str, ctx: Context) -> Intent | None:
    if "screensaver" not in text and "visual emulation" not in text:
        return None
    m = _SCREENSAVER_RE.search(text)
    name = m.group(1).strip() if m else None
    if name not in ctx.screensavers:
        name = next((s for s in ctx.screensavers if s in text), None)
    return Intent("screensaver", {"name": name}) if name else None


_BARDS_TALE = r"\bbards?['’]?s?\s*tales?\b"
_GAME_START = re.compile(r"\b(play|start|launch|run|begin|resume|continue|load|boot)\b.*" + _BARDS_TALE)
_GAME_NEW = re.compile(r"\b(new|fresh)\s+(game|party|adventure|campaign)\b|\bstart\s+over\b|\bfrom\s+scratch\b")
# Only consulted while the game is running, so "stop playing" still reaches Spotify otherwise.
_GAME_STOP = re.compile(r"\b(stop|end|quit|halt|exit|pause|enough)\b.*\b(game|playing|dungeon)\b|"
                        r"\b(stop|end|quit|halt|exit|pause)\b.*" + _BARDS_TALE)
_MUSIC_WORDS = re.compile(r"\b(music|song|spotify|album|track|playlist|radio|tune)s?\b")


def bards_tale(text: str, ctx: Context) -> Intent | None:
    if _GAME_START.search(text):
        return Intent("bards_tale", {"action": "start", "new": bool(_GAME_NEW.search(text))})
    if ctx.game_running and _GAME_STOP.search(text) and not _MUSIC_WORDS.search(text):
        return Intent("bards_tale", {"action": "stop"})
    return None


_RESET_TRIGGERS = (
    "forget this conversation", "forget our conversation", "forget the conversation",
    "clear this conversation", "clear our conversation", "clear the conversation",
    "reset this conversation", "reset our conversation", "reset the conversation",
    "new conversation", "start a new conversation", "wipe this conversation",
    "erase this conversation", "purge this conversation", "forget what we",
    "forget everything we", "clear chat history", "forget our chat",
    "clear our chat", "forget our discussion", "forget this discussion",
)


def conversation_reset(text: str, ctx: Context) -> Intent | None:
    return Intent("conversation_reset") if any(p in text for p in _RESET_TRIGGERS) else None


# Whole-utterance forms (after normalize): a bare "resume" or "stop" counts, but
# "please resume the story" or "play music by Sabaton" go to the model.
_MUSIC = r"(?:music|spotify|playback|song|tunes?)"
_SPOTIFY_STOP = re.compile(rf"stop|pause|(?:stop|pause|halt|kill|silence|end|turn off|enough)(?: of)? {_MUSIC}|(?:stop|pause) playing")
_SPOTIFY_RESUME = re.compile(rf"resume|unpause|(?:resume|unpause|continue|start|play) {_MUSIC}|(?:resume|continue|start) playing")
_SPOTIFY_SKIP = re.compile(r"skip|next|(?:skip|next)(?: this| that| current)? (?:song|track|music|tune|one)")


def spotify_control(text: str, ctx: Context) -> Intent | None:
    t = normalize(text)
    for action, pattern in (("stop", _SPOTIFY_STOP), ("resume", _SPOTIFY_RESUME), ("skip", _SPOTIFY_SKIP)):
        if pattern.fullmatch(t):
            return Intent("spotify_control", {"action": action})
    return None


# Only with music/Spotify named: a plain "volume up" is the skull's own volume,
# which the model handles with the set_volume tool.
_VOLUME_UP = ("turn up music", "turn up spotify", "make music louder", "music louder", "louder music",
              "louder spotify", "increase music volume", "increase spotify volume", "crank music",
              "crank tunes", "crank spotify")
_VOLUME_DOWN = ("turn down music", "turn down spotify", "make music quieter", "music quieter",
                "quieter music", "quieter spotify", "decrease music volume", "decrease spotify volume",
                "lower music volume", "lower spotify volume", "music down")
_VOLUME_SET = re.compile(r"(?:music|spotify) volume (?:to )?(\d+)")


def spotify_volume(text: str, ctx: Context) -> Intent | None:
    # Same reason as dice: "set the music volume to fifty" carries no numeral.
    t = normalize(digitize(text))
    if any(p in t for p in _VOLUME_UP):
        return Intent("spotify_volume", {"change": 15})
    if any(p in t for p in _VOLUME_DOWN):
        return Intent("spotify_volume", {"change": -15})
    m = _VOLUME_SET.search(t)
    if m and 0 <= int(m.group(1)) <= 100:
        return Intent("spotify_volume", {"level": int(m.group(1))})
    return None


# Necromunda Skirmish's own dice. "Hit location" is deliberately absent: it
# belonged to the previous edition and the 2026 rulebook has no such roll.
_DICE_NECRO = re.compile(r"roll\s+(?:a\s+|an\s+)?(\d+)?\s*(firepower|ammo|injury|scatter)\s*d(?:ice|ie)?")
# At the table the firepower die is the ammo die: the Ammo check is what it is for,
# and the ammo symbol is the face that distinguishes it. games.necromunda.dice knows
# it only as firepower, so the name is resolved here rather than anywhere downstream.
_DICE_ALIASES = {"ammo": "firepower"}
# D66 is two D6 read as tens then units, so it yields 11-66 and can never show
# 17 or 20. It has to be caught before the generic dN pattern, which would read
# it as a single 66-sided die and roll numbers the game cannot produce.
_DICE_D66 = re.compile(r"roll\s+(?:a\s+|an\s+)?(\d+)?\s*d\s*66\b")
_DICE_STD = re.compile(r"roll\s+(?:a\s+|an\s+)?(\d+)?\s*d\s*(\d+)(?:\s*(?:needing|target|against)\s+(\d+))?")


def dice(text: str, ctx: Context) -> Intent | None:
    # "Roll three injury dice" reached the model, which described the dice-resolution
    # apparatus engaging and rolled nothing: all three patterns below want digits,
    # and speech-to-text writes a small count as a word about as often as a numeral.
    text = digitize(text)
    m = _DICE_NECRO.search(text)
    if m:
        kind = m.group(2).strip()
        return Intent("dice", {"game": "necromunda", "count": int(m.group(1) or 1),
                               "dice_type": _DICE_ALIASES.get(kind, kind)})
    m = _DICE_D66.search(text)
    if m:
        return Intent("dice", {"game": "necromunda", "count": int(m.group(1) or 1),
                               "dice_type": "d66"})
    m = _DICE_STD.search(text)
    if m:
        return Intent("dice", {"game": "standard", "count": int(m.group(1) or 1), "sides": int(m.group(2)),
                               "target": int(m.group(3)) if m.group(3) else None})
    return None


_ROTATE_VERB = re.compile(r"\b(rotate|rotating|turn|turning|adjust|tilt)\b")
_ROTATE_NOUN = re.compile(r"\b(display|screen|eye)\b")
_NUMBER = re.compile(r"([+-]?\d+(?:\.\d+)?)")

# Speech-to-text writes small numbers as words as often as digits -- "rotate your
# display counterclockwise five degrees" against "...15 degrees" -- and a matcher
# that only reads digits silently drops half of them. Three such rotations reached
# the model instead, which narrated a running total it had invented. So the numeric
# matchers digitize first, rather than each inventing its own word list.
_WORD_NUM = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
    "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40,
    "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
    "hundred": 100,
}
_TENS = {"twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"}
_WORD_NUM_RE = re.compile(r"\b(" + "|".join(sorted(_WORD_NUM, key=len, reverse=True)) + r")\b")


def digitize(text: str) -> str:
    """Rewrite spelled-out numbers as digits: "twenty five degrees" -> "25 degrees".

    Only joins a tens word to a following unit ("forty five" -> 45); anything else
    is substituted one word at a time, and text with no number words is unchanged.
    """
    if not _WORD_NUM_RE.search(text):
        return text
    out, words = [], text.split()
    i = 0
    while i < len(words):
        bare = re.sub(r"[^a-z]", "", words[i].lower())
        if bare in _TENS and i + 1 < len(words):
            nxt = re.sub(r"[^a-z]", "", words[i + 1].lower())
            if nxt in _WORD_NUM and _WORD_NUM[nxt] < 10:
                out.append(words[i].lower().replace(bare, str(_WORD_NUM[bare] + _WORD_NUM[nxt])))
                i += 2
                continue
        if bare in _WORD_NUM:
            out.append(words[i].lower().replace(bare, str(_WORD_NUM[bare])))
        else:
            out.append(words[i])
        i += 1
    return " ".join(out)


def display_rotation(text: str, ctx: Context) -> Intent | None:
    if not (_ROTATE_VERB.search(text) and _ROTATE_NOUN.search(text)):
        return None
    text = digitize(text)
    m = _NUMBER.search(text)
    if not m:
        return None
    val = float(m.group(1))
    if re.search(r"\b(counter|counterclockwise|anticlockwise|left|ccw)\b", text):
        degrees = -abs(val)
    elif re.search(r"\b(clockwise|right|cw)\b", text):
        degrees = abs(val)
    else:
        degrees = val
    # "to 18 degrees" is a target; "3 degrees to the left" is a change.
    absolute = bool(re.search(r"\bto\s+[+-]?\d", text)) and not re.search(r"\bby\b", text)
    return Intent("display_rotation", {"degrees": degrees, "absolute": absolute})


_WAIT_KEYS = ("voice wait", "silence wait", "silence duration", "voice duration", "wait period", "wait duration")


def voice_wait(text: str, ctx: Context) -> Intent | None:
    if not any(k in text for k in _WAIT_KEYS) or not re.search(r"\b(set|change|adjust|make)\b", text):
        return None
    text = digitize(text)
    m = _NUMBER.search(text)
    return Intent("voice_wait", {"seconds": float(m.group(1))}) if m else None


# Wake-word sensitivity. This went through the model, which would acknowledge the
# request in character and change nothing: asked twice, across four days, the tool
# never once fired. There is exactly one correct outcome, so it belongs here.
# Both halves must be present, in either order and however far apart: "wake word
# sensitivity", "make the wake word more sensitive", "threshold for your wake word".
_WAKE_REF = re.compile(r"wake\s*(?:word|phrase)|how\s+(?:easily|easy)\s+you\s+wake")
_SENS_REF = re.compile(r"sensitiv|threshold")
_MORE_SENSITIVE = re.compile(r"\b(?:increase|raise|boost|improve|up|more|higher|better)\b")
_LESS_SENSITIVE = re.compile(r"\b(?:decrease|reduce|lower|drop|down|less|fewer|stricter|strict)\b")
_WAKE_LEVEL = re.compile(r"\b(?:to\s+)?(high|medium|low|maximum|minimum|default|normal|standard)\b")
# "0.5", ".55" or "50 percent" — a bare "50" means percent, not a threshold of fifty.
_WAKE_VALUE = re.compile(r"(?:to|at)\s+(0?\.\d+)\b|\b(\d{1,3})\s*(?:percent|%)")


def wake_sensitivity(text: str, ctx: Context) -> Intent | None:
    if not (_WAKE_REF.search(text) and _SENS_REF.search(text)):
        return None
    text = digitize(text)
    m = _WAKE_VALUE.search(text)
    if m:
        raw, pct = m.group(1), m.group(2)
        value = float(raw) if raw else float(pct) / 100.0
        return Intent("wake_sensitivity", {"threshold": value})
    # "set it to high" names a level; a bare direction steps from where it is.
    lvl = _WAKE_LEVEL.search(text)
    if lvl and not _MORE_SENSITIVE.search(text) and not _LESS_SENSITIVE.search(text):
        return Intent("wake_sensitivity", {"level": lvl.group(1)})
    # A threshold is the inverse of a sensitivity: raising one lowers the other, so
    # which noun was spoken decides which way "increase" points.
    asked_threshold = "threshold" in text and "sensitiv" not in text
    if _MORE_SENSITIVE.search(text):
        return Intent("wake_sensitivity", {"direction": "less" if asked_threshold else "more"})
    if _LESS_SENSITIVE.search(text):
        return Intent("wake_sensitivity", {"direction": "more" if asked_threshold else "less"})
    return Intent("wake_sensitivity", {})  # a question: report where it stands


# ── Settings the model used to narrate ────────────────────────────────────────
# Each of these had a tool and no matcher, and each has exactly one correct outcome,
# so a model that answers "acknowledged" without calling the tool is indistinguishable
# from one that did. set_active_game's own description had already been reduced to
# shouting "YOU MUST call this tool", which is the same symptom written down.

# Microphone sensitivity. Distinct from the wake threshold above, which is matched
# first; "wake" is excluded so the two cannot both claim an utterance.
_MIC_REF = re.compile(r"\b(?:mic|microphone|hearing|pickup|pick\s*up)\b|silence\s+threshold")


def mic_sensitivity(text: str, ctx: Context) -> Intent | None:
    if "wake" in text or not _MIC_REF.search(text) or not _SENS_REF.search(text):
        return None
    text = digitize(text)
    m = re.search(r"(?:to|at)\s+(\d{2,4})\b", text)
    if m:
        return Intent("mic_sensitivity", {"threshold": int(m.group(1))})
    lvl = _WAKE_LEVEL.search(text)
    if lvl and not _MORE_SENSITIVE.search(text) and not _LESS_SENSITIVE.search(text):
        return Intent("mic_sensitivity", {"level": lvl.group(1)})
    asked_threshold = "threshold" in text and "sensitiv" not in text
    if _MORE_SENSITIVE.search(text):
        return Intent("mic_sensitivity", {"direction": "less" if asked_threshold else "more"})
    if _LESS_SENSITIVE.search(text):
        return Intent("mic_sensitivity", {"direction": "more" if asked_threshold else "less"})
    return Intent("mic_sensitivity", {})


# The skull's own speaker volume, as opposed to Spotify's, which spotify_volume
# claims first and which always names the music. "Reduce your volume by 30%" buried
# in a longer sentence is the form that was reaching the model and being narrated.
_VOL_REF = re.compile(r"\bvolume\b|\b(?:louder|quieter|softer)\b|turn\s+(?:it|yourself)\s+(?:up|down)")
_VOL_MUSIC = re.compile(r"\b(?:music|spotify|song|track|playlist|tune)\b")
_VOL_ABS = re.compile(r"(?:volume|it)\s*(?:to|at)\s+(\d{1,3})|\bto\s+(\d{1,3})\s*(?:percent|%)")
_VOL_REL = re.compile(r"\b(?:by|another)\s+(\d{1,3})\s*(?:percent|%)?")
_VOL_UP = re.compile(r"\b(?:up|increase|raise|louder|boost|more)\b")
_VOL_DOWN = re.compile(r"\b(?:down|decrease|reduce|lower|quieter|softer|less)\b")


def volume(text: str, ctx: Context) -> Intent | None:
    if _VOL_MUSIC.search(text) or not _VOL_REF.search(text):
        return None
    text = digitize(text)
    down = bool(_VOL_DOWN.search(text))
    m = _VOL_ABS.search(text)
    # "to 50" is a target; "by 30" is a change, and needs a direction to mean anything.
    if m and not re.search(r"\bby\b", text):
        level = int(m.group(1) or m.group(2))
        if 0 <= level <= 100:
            return Intent("volume", {"level": str(level)})
    rel = _VOL_REL.search(text)
    step = int(rel.group(1)) if rel and 0 < int(rel.group(1)) <= 100 else 15
    if down:
        return Intent("volume", {"level": f"-{step}"})
    if _VOL_UP.search(text):
        return Intent("volume", {"level": f"+{step}"})
    return None


# Silent mode. Deliberately narrow: "stop" and "quiet" alone belong to the music
# commands and to a maintenance confirmation, both of which run before this.
_QUIET_ON = re.compile(r"\b(?:silent|quiet)\s+mode\b.*\b(?:on|engage|enable)\b"
                       r"|\b(?:be|stay|keep|remain)\s+(?:quiet|silent)\b"
                       r"|\b(?:stop|cease)\s+(?:talking|speaking|your\s+observations)\b"
                       r"|\bhold\s+your\s+tongue\b|\bno\s+more\s+observations\b"
                       r"|\b(?:engage|enable)\s+(?:silent|quiet)\b")
_QUIET_OFF = re.compile(r"\b(?:silent|quiet)\s+mode\b.*\b(?:off|disengage|disable|lift)\b"
                        r"|\b(?:you\s+(?:can|may)|please)\s+(?:talk|speak)\b"
                        r"|\b(?:resume|restart)\s+(?:your\s+)?(?:observations|talking|speaking|commentary)\b"
                        r"|\bspeak\s+freely\b|\b(?:lift|end)\s+(?:the\s+)?(?:silent|quiet)\b")


def quiet_mode(text: str, ctx: Context) -> Intent | None:
    if _QUIET_OFF.search(text):
        return Intent("quiet_mode", {"enabled": False})
    if _QUIET_ON.search(text):
        return Intent("quiet_mode", {"enabled": True})
    return None


# Where the voice comes out. Casting to a Google Home and switching to a Bluetooth
# speaker are different mechanisms, so the destination decides which one is used.
_OUT_REF = re.compile(r"\b(?:speak|talk|voice|output|audio|sound|speakers?|use)\b")
_OUT_CAST = re.compile(r"\bgoogle\s*home\b|\bchromecast\b|\bnest\b|\bcast(?:ing)?\b")
_OUT_BT = re.compile(r"\bbluetooth\b|\bbt\s+speaker\b|\bexternal\s+speaker\b")
_OUT_INTERNAL = re.compile(r"\b(?:internal|your\s+own|onboard|built\s*-?\s*in)\s+speaker\b"
                           r"|\bspeak\s+(?:from|through)\s+yourself\b")
_OUT_STOP = re.compile(r"\b(?:stop|cease|disable|turn\s+off)\b")


def voice_output(text: str, ctx: Context) -> Intent | None:
    if _OUT_CAST.search(text):
        if not (_OUT_REF.search(text) or _OUT_STOP.search(text)):
            return None
        return Intent("voice_output", {"cast": not _OUT_STOP.search(text)})
    if not _OUT_REF.search(text):
        return None
    if _OUT_BT.search(text):
        return Intent("voice_output", {"target": "bluetooth"})
    if _OUT_INTERNAL.search(text):
        return Intent("voice_output", {"target": "internal"})
    return None


# Quiet hours. "11pm to 7am", "23 to 7", "midnight until six".
_SLEEP_REF = re.compile(r"\bsleep\s+schedule\b|\bquiet\s+hours\b|\bsleep\s+(?:from|between)\b")
_HOUR = r"(\d{1,2})\s*(am|pm)?|\b(midnight|noon|midday)\b"
_SLEEP_RANGE = re.compile(rf"(?:{_HOUR})\s*(?:to|until|till|-|and)\s*(?:{_HOUR})")


def _hour_value(num, meridiem, word) -> int | None:
    if word:
        return 0 if word == "midnight" else 12
    if num is None:
        return None
    h = int(num)
    if meridiem == "pm" and h < 12:
        h += 12
    elif meridiem == "am" and h == 12:
        h = 0
    return h if 0 <= h <= 23 else None


def sleep_schedule(text: str, ctx: Context) -> Intent | None:
    if not _SLEEP_REF.search(text):
        return None
    text = digitize(text)
    if re.search(r"\b(?:off|disable|cancel|stop|no)\b", text) and not _SLEEP_RANGE.search(text):
        return Intent("sleep_schedule", {"enabled": False})
    m = _SLEEP_RANGE.search(text)
    if not m:
        return None  # a question, or hours we cannot read: the model can answer it
    start = _hour_value(m.group(1), m.group(2), m.group(3))
    end = _hour_value(m.group(4), m.group(5), m.group(6))
    if start is None or end is None:
        return None
    return Intent("sleep_schedule", {"start_hour": start, "end_hour": end, "enabled": True})


# Which game is on the table. This decides which dice are rolled and which rulebook
# answers, so getting it silently wrong is worse than most settings.
_GAMES = (
    ("necromunda", ("necromunda",)),
    ("Warhammer Fantasy Roleplay", ("warhammer fantasy roleplay", "fantasy roleplay", "wfrp", "whfrp")),
    ("Warhammer 40k", ("warhammer 40k", "warhammer 40 000", "40k", "forty k")),
    ("NetEpic", ("netepic", "net epic")),
    ("NetEA", ("netea", "net ea", "epic armageddon")),
    ("Kill Team", ("kill team",)),
    ("Bard's Tale", ("bard's tale", "bards tale")),
)
_GAME_SWITCH = re.compile(r"\b(?:playing|play|switch(?:ing)?\s+to|change\s+to|set\s+the\s+(?:active\s+)?game"
                          r"|active\s+game|we're\s+on|we\s+are\s+on|put\s+on|load)\b")


def active_game(text: str, ctx: Context) -> Intent | None:
    if not _GAME_SWITCH.search(text):
        return None
    for canonical, spoken in _GAMES:
        if any(name in text for name in spoken):
            return Intent("active_game", {"game": canonical})
    return None


# Disposition. Asked for three times -- "change your mood to contemplative",
# "...to suspicious" -- and never once matched, because the audit of state-changing
# tools keyed on a set_/switch_ prefix and this one is called shift_mood.
# The mood names come from core.mood so the two cannot fall out of step.
def _mood_names() -> tuple[str, ...]:
    try:
        from core import mood as _m
        return tuple(_m.MOODS.keys())
    except Exception:
        return ()


_MOOD_REF = re.compile(r"\b(?:mood|disposition|demean(?:our|or)|temperament|mode)\b")


def shift_mood(text: str, ctx: Context) -> Intent | None:
    if not _MOOD_REF.search(text):
        return None
    if not re.search(r"\b(?:change|set|shift|switch|become|be|make|go|turn)\b", text):
        return None
    for name in _mood_names():
        if name.lower() in text:
            return Intent("shift_mood", {"mood": name})
    return None


# "Show me a picture of a 40k Ork" went to the model, which answered "Omega-7's
# sacred eye-display now renders blessed imagery upon the screen -- a greenskin Ork
# in all its savage potency" and never called display_art at all. There is one
# correct action, so it belongs here with the rest of them.
_PICTURE_NOUN = re.compile(r"\b(?:picture|image|artwork|art|pic|photo)\b")
_PICTURE_RE = re.compile(
    r"\b(?:show|display|put|render|project|find|bring\s+up|let\s+me\s+see)\b[^.?!]*?"
    r"\b(?:picture|image|artwork|art|pic|photo)\b"
    r"\s*(?:of|for|showing|with)?\s*(?P<subject>[^.?!]*)"
)
# "a picture of A Space Marine" -- the article belongs to the sentence, not the search.
_PICTURE_LEAD = re.compile(r"^(?:a|an|the|some|me|us|your|his|her|their)\s+")


def show_picture(text: str, ctx: Context) -> Intent | None:
    # An explicit picture word is required, so "show me the rules" and "show me the
    # next eye" stay with the matchers and the model that already handle them.
    if not _PICTURE_NOUN.search(text):
        return None
    m = _PICTURE_RE.search(text)
    if not m:
        return None
    subject = m.group("subject").strip()
    while True:
        trimmed = _PICTURE_LEAD.sub("", subject)
        if trimmed == subject:
            break
        subject = trimmed
    subject = subject.strip(" ,'\"").strip()
    if len(subject) < 2:
        return None
    return Intent("show_picture", {"subject": subject})


_HONORIFIC_RE = re.compile(
    r"(?:set|change|update|make)\s+(?:my\s+)?(?:honorific|title)\s+(?:to\s+)?(?P<a>[a-z0-9' -]+?)"
    r"(?:\s+from\s+now\s+on)?[.!?]*$"
    r"|(?:call\s+me|address\s+me\s+as|refer\s+to\s+me\s+as)\s+(?P<b>[a-z0-9' -]+?)"
    r"(?:\s+from\s+now\s+on|\s+henceforth|\s+in\s+future)?[.!?]*$"
)
# "call me back later", "call me when it's done", "call me an Uber" are not titles.
_HONORIFIC_STOP = {"later", "back", "tomorrow", "tonight", "when", "whenever", "if", "at", "in", "on",
                   "after", "before", "once", "again", "now", "please", "up", "out", "about", "soon",
                   "then", "anytime", "sometime", "a", "an"}


def honorific(text: str, ctx: Context) -> Intent | None:
    if not any(k in text for k in ("honorific", "title", "call me", "address me", "refer to me")):
        return None
    m = _HONORIFIC_RE.search(text)
    if not m:
        return None
    name = " ".join((m.group("a") or m.group("b") or "").split())
    words = name.split()
    if not words or len(words) > 4 or any(w in _HONORIFIC_STOP for w in words):
        return None
    return Intent("honorific", {"name": name})


# Matched against the whole utterance (after dropping filler words), never as a
# substring, so "turn off the music" or "restart the song" can't power the Pi down.
# -- Response length ----------------------------------------------------------

# "answers"/"responses"/"replies" phrased as a length request, or a bare directive
# like "be brief". Anchored on those nouns or an explicit verb so "a short rest"
# and "a long story" can't trip it.
_LEN_SHORT = re.compile(
    r"\b(?:short|brief|briefer|shorter|terse|concise|curt|quick|snappy)\s+"
    r"(?:answers?|responses?|replies|reply|mode)\b"
    r"|\b(?:be|speak|keep it|answer|respond|stay)\s+"
    r"(?:more\s+)?(?:brief|briefly|terse|tersely|concise|concisely|curt|short|quick)\b"
    r"|\bshort[\s-]?form\b"
)
_LEN_LONG = re.compile(
    r"\b(?:long|longer|verbose|expansive|detailed|full|thorough)\s+"
    r"(?:answers?|responses?|replies|reply|mode)\b"
    r"|\b(?:be|speak|answer|respond|stay)\s+"
    r"(?:more\s+)?(?:verbose|verbosely|expansive|expansively|freely|long|detailed)\b"
    r"|\bspeak freely\b|\bat length\b|\bdon'?t hold back\b|\belaborate more\b"
)
_LEN_NORMAL = re.compile(
    r"\b(?:normal|standard|default|regular|usual)\s+"
    r"(?:answers?|responses?|replies|reply|length|mode|cadence)\b"
    r"|\b(?:answer|respond|speak)\s+(?:normally|as usual)\b"
)


def response_length(text: str, ctx: Context) -> Intent | None:
    t = normalize(text)
    # NORMAL is tested first: it is the narrowest pattern, and "back to normal
    # answers" would otherwise never be reached past the others.
    if _LEN_NORMAL.search(t):
        return Intent("response_length", {"mode": "NORMAL"})
    if _LEN_SHORT.search(t):
        return Intent("response_length", {"mode": "SHORT"})
    if _LEN_LONG.search(t):
        return Intent("response_length", {"mode": "LONG"})
    return None


_MAINT_COMMANDS = (
    ("update", re.compile(r"(?:run )?(?:self|system) update|update (?:your software|yourself|your system)|pull updates")),
    ("reboot", re.compile(r"reboot(?: system| yourself)?|restart (?:system|yourself)")),
    ("shutdown", re.compile(r"shut ?down(?: system| yourself)?|power (?:down|off)(?: system| yourself)?"
                            r"|turn (?:yourself|system) off|turn off (?:yourself|system)")),
)


def maintenance_command(text: str, ctx: Context) -> Intent | None:
    """"update", "reboot" or "shutdown", only if that is the entire request."""
    t = normalize(text).replace("'", "")
    for action, pattern in _MAINT_COMMANDS:
        if pattern.fullmatch(t):
            return Intent("maintenance", {"action": action})
    return None


_VOICE_REG_RE = re.compile(
    r"\b(?:register|enrol+|record|re-?register|update|retrain)\s+(?:my\s+)?voice(?:\s+(?:print|profile|imprint))?"
    r"(?:\s+(?:as|for)\s+(?P<name>[a-z][a-z' -]{0,30}?))?[.!?]*$"
)


def voice_registration(text: str, ctx: Context) -> Intent | None:
    m = _VOICE_REG_RE.search(text)
    return Intent("voice_registration", {"name": (m.group("name") or "").strip() or None}) if m else None


_ACCESS_CODE_RE = re.compile(r"\b(web|remote)\b.*\b(code|password|pass ?code)\b|\b(code|password|pass ?code)\b.*\b(web|remote)\b|\baccess code\b")


def web_access_code(text: str, ctx: Context) -> Intent | None:
    return Intent("web_access_code") if _ACCESS_CODE_RE.search(text) else None


# Needs both a voice word and a cache word ("clear your voice cache", "rebuild the
# phrase library"): a bare "clear the table" used to wipe the cache and re-pay
# ElevenLabs to re-synthesize every phrase.
_REFRESH_RE = re.compile(r"\b(?:refresh|reload|clear|rebuild|regenerate|update|purge|reset)\s+(?:your\s+|the\s+)?"
                         r"(?:voice|sound|phrase|response|canned|precanned|audio|speech)\s+"
                         r"(?:cache|library|responses|phrases|sounds)\b")


def voice_cache_refresh(text: str, ctx: Context) -> Intent | None:
    return Intent("voice_cache_refresh") if _REFRESH_RE.search(text) else None


# Needs an eye word plus a style name, a cycle word or a style question, and (apart
# from a bare "next eye") a switching verb or "style"/"design": "keep an eye on the
# printer" or "show me what your eye sees" stay with the model.
_EYE_NOUN = re.compile(r"\b(?:eye|eyes|ocular|optic|optics)\b")
_EYE_VERB = re.compile(r"\b(?:switch|change|swap|set|use|show|try|give|make|put|go|cycle|bring|load|wear|"
                       r"activate|select|pick|match|follow|shuffle|randomize|randomise|style|styles|design|designs|look|pattern)\b")
_EYE_LIST = re.compile(r"\b(?:what|which|list|name)\b.*\b(?:styles?|designs?|options|versions?|looks|kinds|types|patterns)\b")
_EYE_NEXT = re.compile(r"\b(?:next|another|different|new)\b")
_EYE_PREV = re.compile(r"\b(?:previous|prior|last)\b")
_EYE_BARE = re.compile(r"(?:next|previous) (?:eye|ocular|optic)(?: style| design)?")


def eye_style(text: str, ctx: Context) -> Intent | None:
    if not ctx.eye_styles:
        return None
    t = normalize(text)
    if not _EYE_NOUN.search(t):
        return None
    if _EYE_LIST.search(t):
        return Intent("eye_style", {"action": "list"})
    if not (_EYE_VERB.search(t) or _EYE_BARE.fullmatch(t)):
        return None
    best = None  # longest spoken name wins: "noosphere cog" over "cog"
    for name, phrases in ctx.eye_styles:
        for p in phrases:
            if re.search(rf"\b{re.escape(p)}\b", t) and (best is None or len(p) > best[1]):
                best = (name, len(p))
    if best:
        return Intent("eye_style", {"action": "set", "name": best[0]})
    if _EYE_PREV.search(t):
        return Intent("eye_style", {"action": "cycle", "step": -1})
    if _EYE_NEXT.search(t):
        return Intent("eye_style", {"action": "cycle", "step": 1})
    return None


# Unambiguous phrases match on their own (they name a backend or contain "voice").
_ELEVENLABS_PHRASES = ("elevenlabs", "eleven labs", "cloud voice", "premium voice", "cloud tts",
                       "fancy voice", "good voice", "better voice", "real voice", "nice voice")
_PIPER_PHRASES = ("piper", "local voice", "standard voice", "local tts", "basic voice",
                  "offline voice", "robot voice", "cheap voice")
# Bare words that are too common to match alone ("Spotify Premium", "premium
# ammunition") — only count when a voice-switch intent word is present.
_SWITCH_INTENT = ("voice", "speak", "sound", "talk", "tts", "switch")
_AMBIGUOUS_ELEVENLABS = ("premium", "cloud")
_AMBIGUOUS_PIPER = ("local", "offline")


def tts_switch(text: str, ctx: Context) -> Intent | None:
    has_intent = any(w in text for w in _SWITCH_INTENT)
    if any(p in text for p in _ELEVENLABS_PHRASES) or (has_intent and any(p in text for p in _AMBIGUOUS_ELEVENLABS)):
        return Intent("tts_switch", {"backend": "elevenlabs"})
    if any(p in text for p in _PIPER_PHRASES) or (has_intent and any(p in text for p in _AMBIGUOUS_PIPER)):
        return Intent("tts_switch", {"backend": "piper"})
    return None


# The whole utterance: "tell me something about the Horus Heresy" is a question
# for the model, not a request for an idle remark.
_IDLE_RE = re.compile(
    r"(?:give me |i want |i'd like )?(?:an? )?(?:idle )?observation|status update|what have you observed"
    r"|hive update|what's happening(?: around you| around here| here)?|what is happening(?: around you| around here| here)?"
    r"|tell me something|say something|ambient (?:report|update|observation)"
)


def idle_observation(text: str, ctx: Context) -> Intent | None:
    return Intent("idle_observation") if _IDLE_RE.fullmatch(normalize(text)) else None
