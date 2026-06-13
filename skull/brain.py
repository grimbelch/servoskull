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
            "prices, news, or anything that may have changed since your training. "
            "For time-sensitive queries (showtimes, hours, events) include today's "
            "date or 'today' in the query. Use sparingly; only search when needed."
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
]

_SPOTIFY_RE = re.compile(
    r"\[SPOTIFY(?::([^\]]+))?\]|\[SPOTIFY_(PAUSE|RESUME|SKIP)\]"
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
        query, action = m.group(1), m.group(2)
        if query:
            cmds.append(("play", query.strip()))
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
