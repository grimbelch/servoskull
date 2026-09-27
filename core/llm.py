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

from core import config


# ── Public API ──────────────────────────────────────────────────────────────────

def run_conversation(*, system: str, history: list[dict], user_text: str,
                     tools: list[dict], execute_tool, on_tool_use=None,
                     slow_tools=frozenset(), max_tokens: int = 4096,
                     system_suffix: str | None = None, on_text=None) -> str:
    """Run the full tool-use loop and return the final assistant text.

    execute_tool(name, input_dict) -> str        runs one tool, returns its result
    on_tool_use(slow_names: list[str])            called once per turn before slow tools run
    slow_tools                                    names that should trigger on_tool_use
    system_suffix                                 volatile per-turn context (date/speaker/facts/mood).
                                                  Sent with the new user turn, not in the system
                                                  prompt, so tools + system + history stay cacheable
    on_text(delta: str)                           if given, responses are streamed and every piece of
                                                  assistant text is passed here as it arrives. The
                                                  returned text is exactly the concatenation of what
                                                  on_text received, so a caller that speaks the deltas
                                                  has spoken the whole reply
    """
    return _provider().run_conversation(
        system=system, system_suffix=system_suffix, history=history, user_text=user_text,
        tools=tools, execute_tool=execute_tool, on_tool_use=on_tool_use,
        slow_tools=slow_tools, max_tokens=max_tokens, on_text=on_text,
    )


def simple(system: str, user: str, max_tokens: int = 300) -> str:
    """Single-shot completion with a system prompt and one user message."""
    return _provider().simple(system, user, max_tokens)


def vision(system: str, jpeg_bytes: bytes, prompt: str, max_tokens: int = 150) -> str:
    """Describe a JPEG image given a system prompt and instruction."""
    return _provider().vision(system, jpeg_bytes, prompt, max_tokens)


# ── Prompt caching helpers ────────────────────────────────────────────────────
# Caching is a prefix match (tools → system → messages); any byte change before a
# cache_control breakpoint invalidates everything after it. Breakpoints used:
#   1. end of the stable system prompt        (tools + system)
#   2. end of the stored conversation history (reused by the next turn)
#   3. the latest message in the tool loop    (reused by the next loop iteration)
# Volatile per-turn context (clock, speaker, facts, mood) rides in the NEW user turn,
# after all of them, so it never invalidates the cached history.

_EPHEMERAL = {"type": "ephemeral"}

# Per-request timeout (seconds) and SDK retries for connection errors, 429s and 5xx.
_REQUEST_TIMEOUT = 45.0
_MAX_RETRIES = 2
# Tool-use rounds per turn before the model must answer in plain text.
_MAX_TOOL_ROUNDS = 8
# Tool output longer than this is never spoken as a fallback reply.
_MAX_FALLBACK_TOOL_TEXT = 300


def _system_blocks(system: str) -> list[dict]:
    return [{"type": "text", "text": system, "cache_control": _EPHEMERAL}]


def _as_blocks(message: dict) -> list:
    content = message["content"]
    if isinstance(content, str):
        content = [{"type": "text", "text": content}]
        message["content"] = content
    return content


def _set_breakpoints(messages: list[dict], history_end: int) -> None:
    """Mark the end of the stored history and the latest message; clear any others
    so the request never exceeds the 4-breakpoint limit (the system block has one)."""
    for m in messages:
        c = m.get("content")
        if isinstance(c, list):
            for b in c:
                if isinstance(b, dict):
                    b.pop("cache_control", None)
    for idx in {history_end, len(messages) - 1}:
        if 0 <= idx < len(messages):
            content = _as_blocks(messages[idx])
            if content and isinstance(content[-1], dict):
                content[-1]["cache_control"] = _EPHEMERAL


def _log_cache(response, where: str) -> None:
    from core import config as _cfg
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
        # A stalled connection must not freeze the skull for minutes: bound each
        # request and let the SDK retry transient failures with backoff.
        self._client = Anthropic(api_key=config.ANTHROPIC_API_KEY,
                                 timeout=_REQUEST_TIMEOUT, max_retries=_MAX_RETRIES)
        self._model = config.CLAUDE_MODEL

    def run_conversation(self, *, system, system_suffix, history, user_text, tools, execute_tool,
                         on_tool_use, slow_tools, max_tokens, on_text=None):
        system_blocks = _system_blocks(system)
        messages = [{"role": h["role"], "content": h["content"]} for h in history]
        history_end = len(messages) - 1
        if system_suffix:
            user_content = [
                {"type": "text", "text": f"<turn_context>{system_suffix}\n</turn_context>"},
                {"type": "text", "text": user_text},
            ]
        else:
            user_content = user_text
        messages.append({"role": "user", "content": user_content})

        last_tool_text_result = ""
        # Text from every round, in order. A round that ends in a tool call may
        # still say something first ("Consulting the archives."); when streaming,
        # that has already been spoken, so it belongs in the returned reply too.
        texts: list[str] = []
        rounds = 0
        while True:
            _set_breakpoints(messages, history_end)
            extra = {}
            if rounds >= _MAX_TOOL_ROUNDS:
                # Runaway tool loop: force a plain-text answer from what it has.
                print(f"[llm] Tool-use limit ({_MAX_TOOL_ROUNDS} rounds) reached — requesting final answer.")
                extra["tool_choice"] = {"type": "none"}
            response = self._call_with_retry(
                on_text=on_text,
                model=self._model, max_tokens=max_tokens, system=system_blocks,
                tools=tools, messages=messages, **extra,
            )
            _log_cache(response, "run_conversation")
            round_text = " ".join(b.text for b in response.content if hasattr(b, "text") and b.text).strip()
            if round_text:
                texts.append(round_text)
            if response.stop_reason != "tool_use" or rounds >= _MAX_TOOL_ROUNDS:
                if (not round_text and last_tool_text_result
                        and len(last_tool_text_result) <= _MAX_FALLBACK_TOOL_TEXT
                        and "INSTRUCTION" not in last_tool_text_result):
                    # A short, speakable tool result (e.g. a dice roll) with no model text.
                    if on_text is not None:
                        on_text(last_tool_text_result)
                    texts.append(last_tool_text_result)
                return " ".join(texts)
            rounds += 1

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
                if isinstance(result, str) and result.strip():
                    last_tool_text_result = result.strip()
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})

    def _call_with_retry(self, on_text=None, **kwargs):
        # Retries with backoff and the request timeout are handled by the SDK client.
        if on_text is None:
            return self._client.messages.create(**kwargs)
        # Streamed: text deltas go to on_text as they arrive; tool calls and usage
        # come back in the assembled final message exactly as with create().
        emitted = False
        try:
            with self._client.messages.stream(**kwargs) as stream:
                for event in stream:
                    if event.type == "text" and event.text:
                        emitted = True
                        on_text(event.text)
                return stream.get_final_message()
        except Exception as e:
            if emitted:
                raise
            # Nothing was spoken yet, so a plain request loses nothing.
            print(f"[llm] Streaming failed before any text ({type(e).__name__}: {e}) — retrying unstreamed.")
            response = self._client.messages.create(**kwargs)
            for block in response.content:
                if getattr(block, "type", None) == "text" and block.text:
                    on_text(block.text)
            return response

    def simple(self, system, user, max_tokens):
        r = self._call_with_retry(
            model=self._model, max_tokens=max_tokens, system=_system_blocks(system),
            messages=[{"role": "user", "content": user}],
        )
        _log_cache(r, "simple")
        return next((b.text for b in r.content if hasattr(b, "text")), "").strip()

    def vision(self, system, jpeg_bytes, prompt, max_tokens):
        import base64
        b64 = base64.standard_b64encode(jpeg_bytes).decode()
        r = self._call_with_retry(
            model=self._model, max_tokens=max_tokens, system=_system_blocks(system),
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64",
                                             "media_type": "image/jpeg", "data": b64}},
                {"type": "text", "text": prompt},
            ]}],
        )
        return next((b.text for b in r.content if hasattr(b, "text")), "").strip()
