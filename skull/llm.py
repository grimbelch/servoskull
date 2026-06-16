"""
Pluggable LLM backend for Omega-7 — Claude (Anthropic) or Gemini (Google).

Select with LLM_BACKEND in .env ("gemini" or "claude"). The whole codebase talks
to the model through three provider-agnostic entry points so nothing else needs
to know which vendor is active:

    run_conversation(...)  agentic tool-use loop  → final assistant text
    simple(system, user)   single-shot completion → text
    vision(system, jpeg)   image + prompt          → text

Tool schemas are passed in Anthropic's shape ({name, description, input_schema});
the Gemini provider converts them to function declarations on the fly. Persisted
history is plain {"role", "content"(str)} turns, which both providers accept.
"""

from __future__ import annotations
import warnings

# google-auth emits a FutureWarning on Python 3.9 (EOL). Cosmetic — silence it so
# it doesn't clutter Omega-7's logs. Set before google is imported (lazily, below).
warnings.filterwarnings("ignore", message=r".*Python version 3\.9 past its end of life.*")

from skull import config


# ── Public API (dispatches to the configured backend) ──────────────────────────

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


def backend_name() -> str:
    return config.LLM_BACKEND.lower()


# ── Backend selection (lazy, cached) ────────────────────────────────────────────

_providers: dict = {}


def _provider():
    name = config.LLM_BACKEND.lower()
    if name not in _providers:
        _providers[name] = _GeminiProvider() if name == "gemini" else _ClaudeProvider()
    return _providers[name]


# ── Claude (Anthropic) ──────────────────────────────────────────────────────────

class _ClaudeProvider:
    def __init__(self):
        from anthropic import Anthropic
        if not config.ANTHROPIC_API_KEY:
            raise RuntimeError("LLM_BACKEND=claude but ANTHROPIC_API_KEY is not set.")
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


# ── Gemini (Google) ──────────────────────────────────────────────────────────────

class _GeminiProvider:
    def __init__(self):
        from google import genai
        from google.genai import types
        if not config.GEMINI_API_KEY:
            raise RuntimeError("LLM_BACKEND=gemini but GEMINI_API_KEY is not set.")
        self._types = types
        self._client = genai.Client(api_key=config.GEMINI_API_KEY)
        self._model = config.GEMINI_MODEL

    # -- config builders --------------------------------------------------------
    def _gen_config(self, system, max_tokens, tools=None):
        types = self._types
        kwargs = dict(system_instruction=system, max_output_tokens=max_tokens)
        if tools is not None:
            kwargs["tools"] = tools
            kwargs["automatic_function_calling"] = types.AutomaticFunctionCallingConfig(disable=True)
        budget = config.GEMINI_THINKING_BUDGET
        if budget >= 0 and hasattr(types, "ThinkingConfig"):
            kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=budget)
        return types.GenerateContentConfig(**kwargs)

    def _to_tools(self, tools):
        """Anthropic tool dicts → a single Gemini Tool with function declarations."""
        decls = []
        for t in tools:
            schema = t.get("input_schema") or {}
            props = schema.get("properties") or {}
            decl = {"name": t["name"], "description": t.get("description", "")}
            if props:  # Gemini wants parameters omitted entirely for no-arg tools
                decl["parameters"] = {
                    "type": "object",
                    "properties": props,
                    "required": schema.get("required", []),
                }
            decls.append(decl)
        return [self._types.Tool(function_declarations=decls)] if decls else None

    def _history_to_contents(self, history, user_text):
        types = self._types
        contents = []
        for h in history:
            role = "model" if h["role"] == "assistant" else "user"
            contents.append(types.Content(role=role, parts=[types.Part(text=h["content"])]))
        contents.append(types.Content(role="user", parts=[types.Part(text=user_text)]))
        return contents

    def _text_of(self, response) -> str:
        try:
            if response.text:
                return response.text
        except Exception:
            pass
        try:
            parts = response.candidates[0].content.parts or []
            return "".join(p.text for p in parts if getattr(p, "text", None))
        except Exception:
            return ""

    # -- entry points -----------------------------------------------------------
    def run_conversation(self, *, system, history, user_text, tools, execute_tool,
                         on_tool_use, slow_tools, max_tokens):
        types = self._types
        gen_config = self._gen_config(system, max_tokens, tools=self._to_tools(tools))
        contents = self._history_to_contents(history, user_text)

        while True:
            response = self._client.models.generate_content(
                model=self._model, contents=contents, config=gen_config,
            )
            cand = response.candidates[0]
            parts = (cand.content.parts if cand.content else None) or []
            calls = [p.function_call for p in parts if getattr(p, "function_call", None)]
            if not calls:
                return self._text_of(response)

            slow = [c.name for c in calls if c.name in slow_tools]
            if slow and on_tool_use is not None:
                try:
                    on_tool_use(slow)
                except Exception as e:
                    print(f"[llm] tool-use notify error: {e}")

            fr_parts = []
            for c in calls:
                args = dict(c.args) if c.args else {}
                result = execute_tool(c.name, args)
                fr_parts.append(types.Part.from_function_response(
                    name=c.name, response={"result": result}))
            contents.append(cand.content)
            contents.append(types.Content(role="user", parts=fr_parts))

    def simple(self, system, user, max_tokens):
        types = self._types
        r = self._client.models.generate_content(
            model=self._model,
            contents=[types.Content(role="user", parts=[types.Part(text=user)])],
            config=self._gen_config(system, max_tokens),
        )
        return (self._text_of(r) or "").strip()

    def vision(self, system, jpeg_bytes, prompt, max_tokens):
        types = self._types
        r = self._client.models.generate_content(
            model=self._model,
            contents=[
                types.Part.from_bytes(data=jpeg_bytes, mime_type="image/jpeg"),
                types.Part(text=prompt),
            ],
            config=self._gen_config(system, max_tokens),
        )
        return (self._text_of(r) or "").strip()
