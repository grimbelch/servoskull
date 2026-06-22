"""
LLM backend for Omega-7 — Claude (Anthropic).

The whole codebase talks to the model through three entry points so call sites
stay independent of the client details:

    run_conversation(...)  agentic tool-use loop  → final assistant text
    simple(system, user)   single-shot completion → text
    vision(system, jpeg)   image + prompt          → text

Tool schemas are passed in Anthropic's shape ({name, description, input_schema}).
Persisted history is plain {"role", "content"(str)} turns.
"""

from __future__ import annotations

from skull import config


# ── Public API ──────────────────────────────────────────────────────────────────

def run_conversation(*, system: str, history: list[dict], user_text: str,
                     tools: list[dict], execute_tool, on_tool_use=None,
                     slow_tools=frozenset(), max_tokens: int = 800,
                     system_suffix: str | None = None) -> str:
    """Run the full tool-use loop and return the final assistant text.

    execute_tool(name, input_dict) -> str        runs one tool, returns its result
    on_tool_use(slow_names: list[str])            called once per turn before slow tools run
    slow_tools                                    names that should trigger on_tool_use
    system_suffix                                 volatile system text (date/memory/mood) kept
                                                  AFTER the prompt-cache breakpoint so it doesn't
                                                  invalidate the cached `tools + system` prefix
    """
    return _provider().run_conversation(
        system=system, system_suffix=system_suffix, history=history, user_text=user_text,
        tools=tools, execute_tool=execute_tool, on_tool_use=on_tool_use,
        slow_tools=slow_tools, max_tokens=max_tokens,
    )


def simple(system: str, user: str, max_tokens: int = 300) -> str:
    """Single-shot completion with a system prompt and one user message."""
    return _provider().simple(system, user, max_tokens)


def vision(system: str, jpeg_bytes: bytes, prompt: str, max_tokens: int = 150) -> str:
    """Describe a JPEG image given a system prompt and instruction."""
    return _provider().vision(system, jpeg_bytes, prompt, max_tokens)


# ── Prompt caching helpers ────────────────────────────────────────────────────
# Caching is a prefix match (tools → system → messages); any byte change before a
# cache_control breakpoint invalidates everything after it. We cache the big stable
# prefix (tools + the frozen SYSTEM_PROMPT) and keep volatile text — the current
# date, recalled facts, mood — in `system_suffix`, AFTER the breakpoint, so it
# never busts the cache. See https://docs.claude.com prompt-caching guidance.

_EPHEMERAL = {"type": "ephemeral"}


def _system_blocks(system: str, system_suffix: str | None) -> list[dict]:
    """System as content blocks: a cached stable block, then an uncached volatile block."""
    blocks: list[dict] = [{"type": "text", "text": system, "cache_control": _EPHEMERAL}]
    if system_suffix:
        blocks.append({"type": "text", "text": system_suffix})  # no breakpoint → not cached
    return blocks


def _move_cache_breakpoint(messages: list[dict]) -> None:
    """Keep exactly one message-level cache breakpoint, on the latest turn we build.

    The tool-use loop re-sends a growing message list each iteration; marking the
    most recent dict-content turn lets the prior turns be read from cache. We strip
    any breakpoint we added before so the count never creeps past the 4-breakpoint
    limit (system block holds the other one)."""
    for m in messages:
        c = m.get("content")
        if isinstance(c, list):
            for b in c:
                if isinstance(b, dict):
                    b.pop("cache_control", None)
    if not messages:
        return
    last = messages[-1]
    content = last["content"]
    if isinstance(content, str):  # the initial user turn — promote to a block so it's markable
        content = [{"type": "text", "text": content}]
        last["content"] = content
    if isinstance(content, list) and content and isinstance(content[-1], dict):
        content[-1]["cache_control"] = _EPHEMERAL


def _log_cache(response, where: str) -> None:
    from skull import config as _cfg
    if not getattr(_cfg, "AUDIO_DEBUG", False):
        return
    u = response.usage
    read = getattr(u, "cache_read_input_tokens", 0) or 0
    write = getattr(u, "cache_creation_input_tokens", 0) or 0
    print(f"[llm] {where} cache: read={read} write={write} uncached_input={u.input_tokens}")


# ── Provider (lazy, cached) ──────────────────────────────────────────────────────

_cached: "_ClaudeProvider | None" = None


def _provider() -> "_ClaudeProvider":
    global _cached
    if _cached is None:
        _cached = _ClaudeProvider()
    return _cached


class _ClaudeProvider:
    def __init__(self):
        from anthropic import Anthropic
        if not config.ANTHROPIC_API_KEY:
            raise RuntimeError("ANTHROPIC_API_KEY is not set.")
        self._client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
        self._model = config.CLAUDE_MODEL

    def run_conversation(self, *, system, system_suffix, history, user_text, tools, execute_tool,
                         on_tool_use, slow_tools, max_tokens):
        system_blocks = _system_blocks(system, system_suffix)
        messages = [{"role": h["role"], "content": h["content"]} for h in history]
        messages.append({"role": "user", "content": user_text})

        while True:
            _move_cache_breakpoint(messages)
            response = self._client.messages.create(
                model=self._model, max_tokens=max_tokens, system=system_blocks,
                tools=tools, messages=messages,
            )
            _log_cache(response, "run_conversation")
            if response.stop_reason != "tool_use":
                return next((b.text for b in response.content if hasattr(b, "text")), "")

            slow = [b.name for b in response.content
                    if getattr(b, "type", None) == "tool_use" and b.name in slow_tools]
            if slow and on_tool_use is not None:
                try:
                    on_tool_use(slow)
                except Exception as e:
                    print(f"[llm] tool-use notify error: {e}")

            tool_results = []
            for block in response.content:
                if getattr(block, "type", None) != "tool_use":
                    continue
                result = execute_tool(block.name, dict(block.input))
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})

    def simple(self, system, user, max_tokens):
        r = self._client.messages.create(
            model=self._model, max_tokens=max_tokens, system=_system_blocks(system, None),
            messages=[{"role": "user", "content": user}],
        )
        _log_cache(r, "simple")
        return next((b.text for b in r.content if hasattr(b, "text")), "").strip()

    def vision(self, system, jpeg_bytes, prompt, max_tokens):
        import base64
        b64 = base64.standard_b64encode(jpeg_bytes).decode()
        r = self._client.messages.create(
            model=self._model, max_tokens=max_tokens, system=_system_blocks(system, None),
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64",
                                             "media_type": "image/jpeg", "data": b64}},
                {"type": "text", "text": prompt},
            ]}],
        )
        return next((b.text for b in r.content if hasattr(b, "text")), "").strip()
