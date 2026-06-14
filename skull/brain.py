from __future__ import annotations
import re
from anthropic import Anthropic
from skull.config import ANTHROPIC_API_KEY, CLAUDE_MODEL, SYSTEM_PROMPT
from skull import search as _search

_client = Anthropic(api_key=ANTHROPIC_API_KEY)
_history: list[dict] = []

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
            "injuries, campaigns, scenarios, or equipment. Always use this tool before "
            "answering a Necromunda rules question rather than relying on memory."
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
_TTS_RE = re.compile(r"\[TTS_BACKEND:\s*(piper|elevenlabs)\]", re.IGNORECASE)


def _strip_actions(text: str) -> str:
    text = re.sub(r"\*[^*]*\*", "", text)
    text = re.sub(r"_[^_]*_", "", text)
    return " ".join(text.split())


def respond(user_text: str) -> tuple[str, list[tuple]]:
    """Return (spoken_text, spotify_commands)."""
    messages = _history + [{"role": "user", "content": user_text}]

    # Tool use loop — Claude may call web_search before giving a final answer
    while True:
        response = _client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=800,
            system=SYSTEM_PROMPT,
            tools=_TOOLS,
            messages=messages,
        )

        if response.stop_reason == "tool_use":
            # Execute every tool call in this turn
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                if block.name == "web_search":
                    query = block.input.get("query", "")
                    print(f"[skull] Searching: {query}")
                    result = _search.web_search(query)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })
                elif block.name == "news_search":
                    query = block.input.get("query", "")
                    print(f"[skull] Searching news: {query}")
                    result = _search.news_search(query)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })
                elif block.name == "necromunda_rules":
                    query = block.input.get("query", "")
                    print(f"[skull] Looking up Necromunda rules: {query}")
                    result = _search.necromunda_rules(query)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })
                elif block.name == "netea_rules":
                    query = block.input.get("query", "")
                    print(f"[skull] Looking up NetEA rules: {query}")
                    result = _search.netea_rules(query)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })
                elif block.name == "bluetooth_scan":
                    from skull import bluetooth_ctrl
                    print("[skull] Scanning for Bluetooth devices...")
                    devices = bluetooth_ctrl.scan()
                    if not devices:
                        result = "No Bluetooth devices found nearby."
                    else:
                        lines = [f"{i + 1}. {d['name']}" for i, d in enumerate(devices)]
                        result = "Nearby Bluetooth devices:\n" + "\n".join(lines)
                    print(f"[skull] {result}")
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })
                elif block.name == "bluetooth_connect":
                    from skull import bluetooth_ctrl
                    identifier = block.input.get("identifier", "").strip()
                    devices = bluetooth_ctrl.get_last_scan()
                    device = _resolve_bt_device(identifier, devices)
                    if device is None:
                        result = f"Could not find '{identifier}' in the last scan."
                    else:
                        print(f"[skull] Connecting to {device['name']} ({device['mac']})...")
                        success = bluetooth_ctrl.connect(device["mac"])
                        result = (
                            f"Connected to {device['name']}. Audio will now route through it."
                            if success
                            else f"Failed to connect to {device['name']}. It may be out of range or need pairing."
                        )
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })

            # Append assistant turn + tool results and loop for final answer
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})

        else:
            # Final answer
            raw = next(
                (b.text for b in response.content if hasattr(b, "text")), ""
            )
            break

    # Extract commands (Spotify + TTS backend switches)
    cmds: list[tuple] = []

    def _extract_spotify(m: re.Match) -> str:
        query, device, action = m.group(1), m.group(2), m.group(3)
        if query:
            cmds.append(("play", query.strip(), device.strip() if device else None))
        elif action:
            cmds.append((action.lower(),))
        return ""

    def _extract_tts(m: re.Match) -> str:
        cmds.append(("tts_backend", m.group(1).lower()))
        return ""

    spoken = _SPOTIFY_RE.sub(_extract_spotify, raw)
    spoken = _TTS_RE.sub(_extract_tts, spoken)
    spoken = _strip_actions(spoken).strip()

    # Store only the clean conversational turns in history
    _history.append({"role": "user", "content": user_text})
    _history.append({"role": "assistant", "content": spoken})
    if len(_history) > 20:
        _history[:] = _history[-20:]

    return spoken, cmds


def reset() -> None:
    _history.clear()
