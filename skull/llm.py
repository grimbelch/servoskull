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
                     slow_tools=frozenset(), max_tokens: int = 800) -> str:
    """Run the full tool-use loop and return the final assistant text.

    execute_tool(name, input_dict) -> str        runs one tool, returns its result
    on_tool_use(slow_names: list[str])            called once per turn before slow tools run
    slow_tools                                    names that should trigger on_tool_use
    """
    return _provider().run_conversation(
        system=system, history=history, user_text=user_text, tools=tools,
        execute_tool=execute_tool, on_tool_use=on_tool_use,
        slow_tools=slow_tools, max_tokens=max_tokens,
    )


def simple(system: str, user: str, max_tokens: int = 300) -> str:
    """Single-shot completion with a system prompt and one user message."""
    return _provider().simple(system, user, max_tokens)


def vision(system: str, jpeg_bytes: bytes, prompt: str, max_tokens: int = 150) -> str:
    """Describe a JPEG image given a system prompt and instruction."""
    return _provider().vision(system, jpeg_bytes, prompt, max_tokens)


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

    def run_conversation(self, *, system, history, user_text, tools, execute_tool,
                         on_tool_use, slow_tools, max_tokens):
        messages = [{"role": h["role"], "content": h["content"]} for h in history]
        messages.append({"role": "user", "content": user_text})

        while True:
            response = self._client.messages.create(
                model=self._model, max_tokens=max_tokens, system=system,
                tools=tools, messages=messages,
            )
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
            model=self._model, max_tokens=max_tokens, system=system,
            messages=[{"role": "user", "content": user}],
        )
        return next((b.text for b in r.content if hasattr(b, "text")), "").strip()

    def vision(self, system, jpeg_bytes, prompt, max_tokens):
        import base64
        b64 = base64.standard_b64encode(jpeg_bytes).decode()
        r = self._client.messages.create(
            model=self._model, max_tokens=max_tokens, system=system,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64",
                                             "media_type": "image/jpeg", "data": b64}},
                {"type": "text", "text": prompt},
            ]}],
        )
        return next((b.text for b in r.content if hasattr(b, "text")), "").strip()
