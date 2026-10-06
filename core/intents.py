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
    t = normalize(text)
    if any(p in t for p in _VOLUME_UP):
        return Intent("spotify_volume", {"change": 15})
    if any(p in t for p in _VOLUME_DOWN):
        return Intent("spotify_volume", {"change": -15})
    m = _VOLUME_SET.search(t)
    if m and 0 <= int(m.group(1)) <= 100:
        return Intent("spotify_volume", {"level": int(m.group(1))})
    return None


_DICE_NECRO = re.compile(r"roll\s+(?:a\s+|an\s+)?(\d+)?\s*(firepower|injury|scatter|hit\s+location|location)\s*d(?:ice|ie)?")
_DICE_STD = re.compile(r"roll\s+(?:a\s+|an\s+)?(\d+)?\s*d\s*(\d+)(?:\s*(?:needing|target|against)\s+(\d+))?")


def dice(text: str, ctx: Context) -> Intent | None:
    m = _DICE_NECRO.search(text)
    if m:
        kind = m.group(2).strip()
        return Intent("dice", {"game": "necromunda", "count": int(m.group(1) or 1),
                               "dice_type": "location" if "location" in kind else kind})
    m = _DICE_STD.search(text)
    if m:
        return Intent("dice", {"game": "standard", "count": int(m.group(1) or 1), "sides": int(m.group(2)),
                               "target": int(m.group(3)) if m.group(3) else None})
    return None


_ROTATE_VERB = re.compile(r"\b(rotate|rotating|turn|turning|adjust|tilt)\b")
_ROTATE_NOUN = re.compile(r"\b(display|screen|eye)\b")
_NUMBER = re.compile(r"([+-]?\d+(?:\.\d+)?)")


def display_rotation(text: str, ctx: Context) -> Intent | None:
    if not (_ROTATE_VERB.search(text) and _ROTATE_NOUN.search(text)):
        return None
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
    m = _NUMBER.search(text)
    return Intent("voice_wait", {"seconds": float(m.group(1))}) if m else None


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
                       r"activate|select|pick|style|styles|design|designs|look|pattern)\b")
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
