"""
Response-length state for Omega-7. The owner sets it by voice — "short answers",
"long answers", "normal answers" — and it steers how much the model says.

Length is enforced through the system prompt rather than max_tokens: the same
budget carries tool-call blocks, and clipping that would truncate a tool's JSON
mid-call instead of just shortening the prose. Persists across restarts via the
SQLite KV store, the same way mood and quiet mode do.
"""

from __future__ import annotations
import threading

from core import config
from core import db

MODES: dict[str, dict] = {
    "SHORT": {
        "label": "Terse",
        "spoken": "Vox-protocol set to terse. This unit will be brief.",
        "system_addendum": (
            "RESPONSE LENGTH — TERSE: Answer in one or two short sentences. Give the "
            "answer itself and stop. No preamble, no restating the question, no lore "
            "tangents, no devotional flourishes, no offers of further assistance. "
            "Stay in character, but let brevity be the service. If a complete answer "
            "genuinely cannot fit, give the essential part and say you can expand."
        ),
    },
    "NORMAL": {
        "label": "Standard",
        "spoken": "Vox-protocol restored to standard cadence.",
        "system_addendum": "",
    },
    "LONG": {
        "label": "Expansive",
        "spoken": "Vox-protocol set to expansive. This unit will speak freely.",
        "system_addendum": (
            "RESPONSE LENGTH — EXPANSIVE: Speak at length and in full. Elaborate, "
            "supply context and relevant Imperial lore, follow interesting tangents, "
            "and let the character breathe. Several paragraphs are welcome where the "
            "subject earns them. Do not pad an answer that is genuinely simple."
        ),
    },
}

_JAX_SPOKEN = {
    "SHORT": "Okay! Short answers from now on!",
    "NORMAL": "Okay! Back to normal!",
    "LONG": "Okay! I'll tell you everything!",
}

_JAX_ADDENDA = {
    "SHORT": (
        "RESPONSE LENGTH — SHORT: Answer in one or two short sentences, then stop. "
        "Still warm and friendly, just brief."
    ),
    "NORMAL": "",
    "LONG": (
        "RESPONSE LENGTH — LONG: Talk freely and at length, with lots of happy detail "
        "and enthusiasm. Several paragraphs are welcome."
    ),
}

_DEFAULT = "NORMAL"
_state_lock = threading.Lock()


def _get_state() -> dict:
    state = {"mode": _DEFAULT}
    saved = db.kv_get("verbosity_state", {})
    if isinstance(saved, dict):
        state.update(saved)
    return state


def _save_state(state: dict) -> None:
    db.kv_set("verbosity_state", state)


# ── Public API ────────────────────────────────────────────────────────────────

def get() -> str:
    """Current mode name: SHORT, NORMAL or LONG."""
    with _state_lock:
        state = _get_state()
        m = str(state.get("mode", _DEFAULT)).upper()
        if m not in MODES:
            m = _DEFAULT
            state["mode"] = m
            _save_state(state)
        return m


def label() -> str:
    return MODES[get()]["label"]


def set_mode(mode: str) -> str:
    """Set the mode. Returns the in-character line to speak back."""
    mode = str(mode or "").strip().upper()
    if mode not in MODES:
        return f"Unknown vox-protocol '{mode}'. This unit knows short, normal and long."
    with _state_lock:
        state = _get_state()
        prev = str(state.get("mode", _DEFAULT)).upper()
        state["mode"] = mode
        _save_state(state)
    if mode != prev:
        print(f"[verbosity] {prev} → {mode}")
    if config.get_personality_key() == "jax":
        return _JAX_SPOKEN.get(mode, _JAX_SPOKEN[_DEFAULT])
    return MODES[mode]["spoken"]


def system_addendum() -> str:
    """System prompt snippet for the current mode; empty string in NORMAL."""
    mode = get()
    text = (_JAX_ADDENDA if config.get_personality_key() == "jax" else
            {k: v["system_addendum"] for k, v in MODES.items()}).get(mode, "")
    return "\n\n" + text if text else ""


def all_modes() -> list[str]:
    return list(MODES.keys())
