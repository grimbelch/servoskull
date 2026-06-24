from __future__ import annotations
import json
import pathlib
import re
import subprocess
import sys
from datetime import datetime
from skull.config import SYSTEM_PROMPT, HISTORY_FILE
from skull import search as _search
from skull import memory as _memory
from skull import reminders as _reminders
from skull import mood as _mood
from skull import quiet as _quiet
from skull import llm as _llm

_history: list[dict] = []

# Tools that hit the network/hardware and can take a noticeable moment. Omega-7
# speaks a short "stand by" before running any of these so the user gets feedback.
_SLOW_TOOLS = {"web_search", "news_search", "necromunda_rules", "netea_rules", "get_weather", "bluetooth_scan"}
_HISTORY_PATH = pathlib.Path(HISTORY_FILE)


def _save_history() -> None:
    try:
        _HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _HISTORY_PATH.open("w") as f:
            json.dump(_history, f)
    except Exception as e:
        print(f"[brain] History save error: {e}")


def _load_history() -> None:
    global _history
    try:
        if _HISTORY_PATH.exists():
            with _HISTORY_PATH.open() as f:
                _history = json.load(f)
            print(f"[brain] Restored {len(_history) // 2} conversation turns from history")
    except Exception:
        pass


_load_history()

_TOOLS = [
    {
        "name": "web_search",
        "description": (
            "Search the web for current information — showtimes, recent events, "
            "prices, or anything that may have changed since your training. "
            "For time-sensitive queries (showtimes, hours, events) include today's "
            "date or 'today' in the query. Use sparingly; only search when needed. "
            "Do NOT use this for news — use news_search instead."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Concise search query (5 words or fewer works best)",
                }
            },
            "required": ["query"],
        },
    },
    {
        "name": "news_search",
        "description": (
            "Search for current news headlines and stories. Use this when the user "
            "asks for news, what's happening today, current events, or headlines. "
            "Returns structured results with date, headline, source, and summary. "
            "Always use this tool (not web_search) for any news-related query."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "News topic or 'top news today' for general headlines",
                }
            },
            "required": ["query"],
        },
    },
    {
        "name": "necromunda_rules",
        "description": (
            "Look up Necromunda tabletop game rules from necroraw.com.ru (Rules as Written). "
            "Use for any question about Necromunda mechanics, gangs, weapons, skills, "
            "injuries, campaigns, scenarios, or equipment — including the Trading Post and "
            "Black Market: item availability, rarity, cost, exclusive/illegal items, and "
            "special ammunition. Always use this tool before answering a Necromunda rules "
            "question rather than relying on memory."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Rule, mechanic, or topic to look up (e.g. 'fighter activation', 'injury roll', 'House Goliath gang list')",
                }
            },
            "required": ["query"],
        },
    },
    {
        "name": "netea_rules",
        "description": (
            "Look up Net Epic Armageddon (NetEA) tabletop game rules from the NetEA Tournament Pack. "
            "Use for any question about NetEA mechanics, army lists, formations, units, special rules, "
            "or tournament regulations. Always use this tool before answering a NetEA question."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Rule, unit, formation, or topic to look up (e.g. 'blast markers', 'Space Marine Tactical formation', 'aerospace operations')",
                }
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_weather",
        "description": (
            "Get current local weather conditions (temperature, humidity, wind, sky). "
            "Call when the user asks about the weather or outdoor conditions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "set_volume",
        "description": (
            "Adjust the speaker volume. Pass '+15' to raise by 15%, '-15' to lower by 15%, "
            "or '80' to set an absolute level. Call when user says louder, quieter, volume up/down, etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "level": {
                    "type": "string",
                    "description": "'+15' raise 15%, '-15' lower 15%, or '80' for absolute 80%",
                }
            },
            "required": ["level"],
        },
    },
    {
        "name": "bluetooth_scan",
        "description": (
            "Scan for nearby Bluetooth speakers. Call this when the user asks to connect to a "
            "Bluetooth speaker or find Bluetooth devices. Takes 8-10 seconds to complete. "
            "Returns a numbered list of discovered devices."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "bluetooth_connect",
        "description": (
            "Connect to a Bluetooth device from the last scan. Pass the device name or number "
            "(e.g. '1', '2', 'JBL Flip') as the identifier. On success, audio output routes "
            "through the Bluetooth speaker automatically."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "identifier": {
                    "type": "string",
                    "description": "Device name or number from the last scan (e.g. '1', 'second', 'JBL Flip 6')",
                }
            },
            "required": ["identifier"],
        },
    },
    {
        "name": "remember_fact",
        "description": (
            "Permanently store a fact the user has explicitly asked to be remembered. "
            "Use when the user says 'remember that...', 'please remember...', 'don't forget that...', etc. "
            "Store the fact exactly as stated. This memory persists forever until the user asks to forget it."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "fact": {
                    "type": "string",
                    "description": "The exact fact to remember, as a clear statement (e.g. 'Sean's address is 1810 NE 62nd Avenue')",
                }
            },
            "required": ["fact"],
        },
    },
    {
        "name": "forget_fact",
        "description": (
            "Remove a fact the user has explicitly asked to be forgotten. "
            "Use when the user says 'forget that...', 'stop remembering...', 'erase...', etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "A word or phrase identifying which fact to remove (e.g. 'address', 'phone number')",
                }
            },
            "required": ["query"],
        },
    },
    {
        "name": "update_fact",
        "description": (
            "Replace an existing long-term memory fact with a corrected version. "
            "Use when the user says 'update my...', 'change my...', 'correct that...', "
            "'my address has changed to...', etc. Finds the old fact by keyword and replaces it."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keyword identifying the fact to replace (e.g. 'address', 'phone')",
                },
                "new_fact": {
                    "type": "string",
                    "description": "The corrected fact as a full statement (e.g. 'Sean's address is 2000 NW Hoyt St')",
                },
            },
            "required": ["query", "new_fact"],
        },
    },
    {
        "name": "set_reminder",
        "description": (
            "Set a timer or reminder that fires after a delay. Use for 'set a timer for X minutes', "
            "'remind me to do Y in Z minutes', 'wake me up in X hours', etc. "
            "Convert the requested duration to seconds. "
            "Phrase the message in Omega-7's 40k voice (e.g. 'Your 5-minute cogitation cycle is complete.' "
            "or 'Reminder, my lord: the dog requires its evening patrol.')."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "What Omega-7 will speak aloud when the reminder fires.",
                },
                "delay_seconds": {
                    "type": "integer",
                    "description": "Seconds from now until the reminder fires. Convert minutes/hours accordingly.",
                },
            },
            "required": ["message", "delay_seconds"],
        },
    },
    {
        "name": "list_reminders",
        "description": "List all active timers and reminders with their IDs and time remaining.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "cancel_reminder",
        "description": "Cancel an active timer or reminder by its ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "reminder_id": {
                    "type": "string",
                    "description": "The short ID returned when the reminder was set (e.g. 'a3f8c21b').",
                },
            },
            "required": ["reminder_id"],
        },
    },
    {
        "name": "acknowledge_reminders",
        "description": (
            "Stop all currently repeating timer/reminder alerts. Call this when the user "
            "acknowledges an alert — e.g. 'got it', 'acknowledged', 'stop', 'I heard you', "
            "'silence', 'ok ok', 'enough'. Only clears timers that have already expired and "
            "are repeating; pending future timers are never affected."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "set_quiet_mode",
        "description": (
            "Enable or disable silent mode — whether Omega-7 makes unprompted PERIODIC "
            "(idle) observations on its own while waiting. Set enabled=true when the user "
            "asks for silence, e.g. 'silent mode', 'be quiet', 'stop talking on your own', "
            "'no more observations', 'hold your tongue'. Set enabled=false when the user "
            "lifts it, e.g. 'you may speak', 'resume observations', 'you can talk again', "
            "'end silent mode'. This does NOT mute replies to direct questions — Omega-7 "
            "still answers when addressed; it only governs self-initiated idle remarks."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "enabled": {
                    "type": "boolean",
                    "description": "true to enter silent mode (no idle observations); false to resume them.",
                },
            },
            "required": ["enabled"],
        },
    },
    {
        "name": "shift_mood",
        "description": (
            "Update Omega-7's current personality disposition. Call this OCCASIONALLY — "
            "only when the conversation strongly warrants a shift. Examples: a discussion "
            "of Chaos threats → SUSPICIOUS or VIGILANT; ancient history or lore → "
            "CONTEMPLATIVE; dark or tragic news → MELANCHOLIC; completing a task well → "
            "DUTIFUL; Imperial devotion or praise → FERVENT. Do not call this every turn. "
            "Mood should shift rarely and feel earned."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "mood": {
                    "type": "string",
                    "enum": ["VIGILANT", "CONTEMPLATIVE", "SUSPICIOUS", "DUTIFUL", "MELANCHOLIC", "FERVENT"],
                    "description": "The new personality disposition.",
                },
            },
            "required": ["mood"],
        },
    },
]

_ORDINALS = {
    "first": 0, "1": 0,
    "second": 1, "2": 1,
    "third": 2, "3": 2,
    "fourth": 3, "4": 3,
    "fifth": 4, "5": 4,
}


def _resolve_bt_device(identifier: str, devices: list[dict]) -> dict | None:
    s = identifier.lower().strip()
    if s in _ORDINALS:
        i = _ORDINALS[s]
        return devices[i] if i < len(devices) else None
    try:
        i = int(s) - 1
        return devices[i] if 0 <= i < len(devices) else None
    except ValueError:
        pass
    for d in devices:
        if s in d["name"].lower():
            return d
    return None


_SPOTIFY_RE = re.compile(
    r"\[SPOTIFY(?::([^\]|]+?)(?:\s*\|\s*on:\s*([^\]]+))?)?\]|\[SPOTIFY_(PAUSE|RESUME|SKIP)\]"
)

# Deterministic silent-mode intent. haiku often acknowledges a silence/resume
# request verbally without actually calling set_quiet_mode, so respond() uses
# these as a fallback to reconcile the state when the tool wasn't invoked.
_QUIET_OFF_RE = re.compile(
    r"\byou (?:may|can) (?:speak|talk)\b|\b(?:speak|talk) (?:again|freely)\b"
    r"|\bresume (?:your )?(?:observ|chatter|remarks?|speech|commentary)"
    r"|\bend (?:silent|quiet) mode\b|\bstop being (?:silent|quiet)\b"
    r"|\bbreak your silence\b|\byou(?:'re| are) allowed to (?:talk|speak)\b"
    r"|\byou may resume\b|\bstart talking again\b",
    re.I,
)
_QUIET_ON_RE = re.compile(
    r"\b(?:be|stay|keep|remain) (?:silent|quiet)\b|\b(?:silent|quiet) mode\b"
    r"|\bhold your tongue\b|\bhush\b|\bshush\b|\bshut up\b|\bpipe down\b|\bzip it\b"
    r"|\bstop (?:your )?(?:observ|talking|chatter|comment)|\bno more (?:observ|comment|chatter|remarks?)"
    r"|\bcease (?:your )?(?:observ|chatter|comment)|\bsilence\b",
    re.I,
)


def _quiet_intent(text: str) -> bool | None:
    """Classify an explicit silence command: True=enter silent mode,
    False=resume, None=no clear command. Resume is checked first so phrases like
    'stop being silent' aren't misread as a request for silence."""
    if _QUIET_OFF_RE.search(text):
        return False
    if _QUIET_ON_RE.search(text):
        return True
    return None


def _strip_actions(text: str) -> str:
    text = re.sub(r"\*[^*]*\*", "", text)
    text = re.sub(r"_[^_]*_", "", text)
    return " ".join(text.split())


def _execute_tool(name: str, tool_input: dict) -> str:
    """Run a single tool call and return its result string. Called by the llm
    tool-use loop."""
    if name == "web_search":
        query = tool_input.get("query", "")
        print(f"[skull] Searching: {query}")
        return _search.web_search(query)
    if name == "news_search":
        query = tool_input.get("query", "")
        print(f"[skull] Searching news: {query}")
        return _search.news_search(query)
    if name == "necromunda_rules":
        query = tool_input.get("query", "")
        print(f"[skull] Looking up Necromunda rules: {query}")
        return _search.necromunda_rules(query)
    if name == "netea_rules":
        query = tool_input.get("query", "")
        print(f"[skull] Looking up NetEA rules: {query}")
        return _search.netea_rules(query)
    if name == "get_weather":
        from skull.config import WEATHER_LAT, WEATHER_LON
        if WEATHER_LAT == 0.0 and WEATHER_LON == 0.0:
            return "Weather location not configured. Set WEATHER_LAT and WEATHER_LON in .env"
        print("[skull] Fetching weather...")
        return _search.get_weather(WEATHER_LAT, WEATHER_LON)
    if name == "set_volume":
        level = str(tool_input.get("level", "+10")).strip()
        # `level` is model-generated and gets interpolated into an osascript -e
        # string below, so reject anything that isn't a bare (optionally signed,
        # optionally %-suffixed) integer — otherwise a crafted value could inject
        # arbitrary AppleScript / shell commands.
        if not re.fullmatch(r"[+-]?\d{1,3}%?", level):
            return f"Invalid volume level: {level!r}. Use '+15', '-15', or an absolute number like '80'."
        try:
            if sys.platform == "darwin":
                if level.startswith("+"):
                    script = f"set volume output volume (output volume of (get volume settings) + {level[1:]})"
                elif level.startswith("-"):
                    script = f"set volume output volume (output volume of (get volume settings) - {level[1:]})"
                else:
                    script = f"set volume output volume {level}"
                subprocess.run(["osascript", "-e", script], capture_output=True)
            else:
                pct = f"{level}%" if not level.endswith("%") else level
                subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", pct], capture_output=True)
            print(f"[skull] Volume: {level}")
            return f"Volume set to {level}."
        except Exception as e:
            return f"Volume adjustment failed: {e}"
    if name == "bluetooth_scan":
        from skull import bluetooth_ctrl
        print("[skull] Scanning for Bluetooth devices...")
        devices = bluetooth_ctrl.scan()
        if not devices:
            result = "No Bluetooth devices found nearby."
        else:
            lines = [f"{i + 1}. {d['name']}" for i, d in enumerate(devices)]
            result = "Nearby Bluetooth devices:\n" + "\n".join(lines)
        print(f"[skull] {result}")
        return result
    if name == "bluetooth_connect":
        from skull import bluetooth_ctrl
        identifier = str(tool_input.get("identifier", "")).strip()
        devices = bluetooth_ctrl.get_last_scan()
        device = _resolve_bt_device(identifier, devices)
        if device is None:
            return f"Could not find '{identifier}' in the last scan."
        print(f"[skull] Connecting to {device['name']} ({device['mac']})...")
        success = bluetooth_ctrl.connect(device["mac"])
        return (
            f"Connected to {device['name']}. Music routes through the speaker via system audio; vocalizations remain on Omega-7's own output."
            if success
            else f"Failed to connect to {device['name']}. It may be out of range or need pairing."
        )
    if name == "remember_fact":
        return _memory.remember(str(tool_input.get("fact", "")).strip())
    if name == "forget_fact":
        return _memory.forget(str(tool_input.get("query", "")).strip())
    if name == "update_fact":
        return _memory.update(str(tool_input.get("query", "")).strip(),
                              str(tool_input.get("new_fact", "")).strip())
    if name == "set_reminder":
        message = str(tool_input.get("message", "")).strip()
        delay = int(tool_input.get("delay_seconds", 60))
        rid = _reminders.add(message, delay)
        mins, secs = divmod(delay, 60)
        human = f"{mins}m {secs}s" if mins else f"{secs}s"
        print(f"[brain] Reminder set: [{rid}] in {human} — {message!r}")
        return f"Reminder set (ID: {rid}). Will fire in {human}."
    if name == "list_reminders":
        items = _reminders.list_all()
        if not items:
            return "No active timers or reminders."
        return "\n".join(
            f"[{r['id']}] in {_reminders.format_remaining(r['fire_at'])}: {r['message']}"
            for r in items
        )
    if name == "cancel_reminder":
        rid = str(tool_input.get("reminder_id", "")).strip()
        return f"Reminder [{rid}] cancelled." if _reminders.cancel(rid) else f"No reminder found with ID '{rid}'."
    if name == "acknowledge_reminders":
        count = _reminders.acknowledge_all()
        print(f"[brain] Acknowledged {count} repeating reminder(s)")
        return f"Silenced {count} repeating alert(s)." if count else "No repeating alerts were active."
    if name == "set_quiet_mode":
        enabled = bool(tool_input.get("enabled", True))
        _quiet.set_silent(enabled)
        return (
            "Silent mode engaged. This unit will cease unprompted observations."
            if enabled
            else "Silent mode lifted. This unit will resume its periodic observations."
        )
    if name == "shift_mood":
        new_mood = _mood.set_mood(str(tool_input.get("mood", "DUTIFUL")))
        return f"Disposition updated to {new_mood}."
    return f"Unknown tool: {name}"


def respond(user_text: str, on_tool_use=None) -> tuple[str, list[tuple]]:
    """Return (spoken_text, spotify_commands).

    on_tool_use: optional callback invoked with the list of slow tool names
    (see _SLOW_TOOLS) the instant Omega-7 is about to run them, so the caller can
    give the user immediate "stand by" feedback before the call blocks.
    """
    facts = _memory.load()
    longterm = _memory.load_longterm()
    now = datetime.now()
    date_ctx = f"\n\nCURRENT DATE AND TIME: {now.strftime('%A, %B %-d, %Y at %-I:%M %p')}."
    # Prompt caching: keep the frozen SYSTEM_PROMPT as the cached prefix (tools + system),
    # and push everything volatile — the clock, recalled facts, and current mood — into
    # system_suffix, which the LLM layer places AFTER the cache breakpoint. Same content
    # and order as before; this just stops the per-minute timestamp from busting the cache.
    system = SYSTEM_PROMPT
    system_suffix = (date_ctx + _memory.longterm_prompt(longterm)
                     + _memory.facts_prompt(facts) + _mood.system_addendum())

    # Record which tools fired so we can reconcile silent mode afterwards.
    tools_called: list[str] = []

    def _exec(name: str, tool_input: dict) -> str:
        tools_called.append(name)
        return _execute_tool(name, tool_input)

    raw = _llm.run_conversation(
        system=system,
        system_suffix=system_suffix,
        history=_history,
        user_text=user_text,
        tools=_TOOLS,
        execute_tool=_exec,
        on_tool_use=on_tool_use,
        slow_tools=_SLOW_TOOLS,
        max_tokens=800,
    )

    # Safety net: if the user clearly asked to enter/leave silent mode but the
    # model only acknowledged it verbally (haiku often skips the tool call),
    # apply the change deterministically so quiet.json tracks reality.
    if "set_quiet_mode" not in tools_called:
        intent = _quiet_intent(user_text)
        if intent is not None and intent != _quiet.is_silent():
            print(f"[brain] Silent-mode fallback: model skipped the tool — forcing silent={intent}")
            _quiet.set_silent(intent)

    # Extract Spotify commands
    cmds: list[tuple] = []

    def _extract_spotify(m: re.Match) -> str:
        query, device, action = m.group(1), m.group(2), m.group(3)
        if query:
            cmds.append(("play", query.strip(), device.strip() if device else None))
        elif action:
            cmds.append((action.lower(),))
        return ""

    spoken = _SPOTIFY_RE.sub(_extract_spotify, raw)
    spoken = _strip_actions(spoken).strip()

    # Store only the clean conversational turns in history
    _history.append({"role": "user", "content": user_text})
    _history.append({"role": "assistant", "content": spoken})
    if len(_history) > 20:
        _history[:] = _history[-20:]
    _save_history()

    # Extract and persist any memorable facts in the background
    _memory.store_in_background(user_text, spoken)

    return spoken, cmds


def reset() -> None:
    _history.clear()
    _save_history()


_IDLE_PROMPT = """\
You are Omega-7, an ancient Imperial servo-skull. Your cogitator feeds have just \
intercepted real-world news dispatches from the sector. Reinterpret ONE news item \
as if it were a report from the Warhammer 40,000 universe — use real locations \
real companies, real people, but modifiy it slightly to fit the Warhammer 40k universe.\
Speak it as a brief status report (1-2 sentences). \
When you being your response, preface it with some form of "This just in from the news feeds of this unit's cogitator..." or "This unit has intercepted a news dispatch..." \
Output ONLY the spoken words. No asterisks, no stage directions. No preamble."""

_IDLE_TOOLS = [
    {
        "name": "news_search",
        "description": "Search for current news headlines.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "News topic or location"}
            },
            "required": ["query"],
        },
    }
]

_IDLE_SCOPES = [
    "Portland Oregon news today",
    "Oregon news today",
    "United States news today",
    "world news today",
]


def idle_utterance() -> str:
    """Fetch a real news item, reinterpret it through a 40k lens, coloured by current mood."""
    import random as _rand
    scope = _rand.choice(_IDLE_SCOPES)
    bias = _mood.idle_bias()
    print(f"[brain] Idle — scope: {scope!r}  mood bias: {_mood.get()}")
    system = _IDLE_PROMPT + _mood.system_addendum()
    user_text = (
        f"Search for '{scope}' news and generate your idle utterance based on one story. "
        f"Lean toward this type of delivery: {bias}."
    )

    def execute_tool(name: str, tool_input: dict) -> str:
        if name == "news_search":
            query = tool_input.get("query", scope)
            print(f"[brain] Idle searching news: {query}")
            return _search.news_search(query)
        return ""

    try:
        text = _llm.run_conversation(
            system=system,
            history=[],
            user_text=user_text,
            tools=_IDLE_TOOLS,
            execute_tool=execute_tool,
            max_tokens=400,
        )
        return (text or "").strip()
    except Exception as e:
        print(f"[brain] Idle utterance error: {e}")
        return ""
