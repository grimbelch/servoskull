from __future__ import annotations
import json
import pathlib
import threading

from anthropic import Anthropic
from skull.config import ANTHROPIC_API_KEY, CLAUDE_MODEL

_MEMORY_PATH = pathlib.Path("memory.json")
_LONGTERM_PATH = pathlib.Path("longterm_memory.json")
_lock = threading.Lock()


# ── Long-term explicit memory (only changes on direct user instruction) ────────

def load_longterm() -> list[str]:
    with _lock:
        try:
            if _LONGTERM_PATH.exists():
                return json.loads(_LONGTERM_PATH.read_text())
        except Exception:
            pass
        return []


def _save_longterm(facts: list[str]) -> None:
    with _lock:
        try:
            _LONGTERM_PATH.write_text(json.dumps(facts, indent=2))
        except Exception as e:
            print(f"[memory] Longterm save error: {e}")


def remember(fact: str) -> str:
    """Add a fact to long-term memory. Returns confirmation string."""
    facts = load_longterm()
    if fact.lower() in {f.lower() for f in facts}:
        return "Already committed to long-term memory."
    facts.append(fact)
    _save_longterm(facts)
    print(f"[memory] Longterm stored: {fact!r}")
    return f"Committed to long-term memory: {fact}"


def forget(query: str) -> str:
    """Remove the fact most closely matching query. Returns confirmation string."""
    facts = load_longterm()
    q = query.lower()
    matches = [f for f in facts if q in f.lower()]
    if not matches:
        return f"No long-term memory found matching: {query}"
    for m in matches:
        facts.remove(m)
    _save_longterm(facts)
    removed = "; ".join(matches)
    print(f"[memory] Longterm removed: {removed!r}")
    return f"Erased from long-term memory: {removed}"


def update(query: str, new_fact: str) -> str:
    """Replace the fact matching query with new_fact. Returns confirmation string."""
    facts = load_longterm()
    q = query.lower()
    matches = [f for f in facts if q in f.lower()]
    if not matches:
        return f"No long-term memory found matching: {query}. Use remember_fact to add it as new."
    for m in matches:
        idx = facts.index(m)
        facts[idx] = new_fact
    _save_longterm(facts)
    print(f"[memory] Longterm updated: {matches} → {new_fact!r}")
    return f"Updated long-term memory: {'; '.join(matches)} → {new_fact}"


def longterm_prompt(facts: list[str]) -> str:
    if not facts:
        return ""
    lines = "\n".join(f"- {f}" for f in facts)
    return f"\n\nEXPLICITLY REMEMBERED FACTS (permanent until forgotten):\n{lines}"

_EXTRACT_SYSTEM = """\
You are a memory extraction system for an AI assistant. \
Given a single conversation exchange, extract any facts worth remembering long-term about the user or people they mention. \
Include: names, locations (home, work, city), relationships, occupations, hobbies, preferences, pets, important possessions. \
Do NOT include transient information (current questions, today's weather, etc.). \
Return a JSON array of short fact strings (one fact per string). \
Return [] if nothing memorable was said. \
Return ONLY the JSON array — no explanation, no markdown."""

_client = Anthropic(api_key=ANTHROPIC_API_KEY)
_MAX_FACTS = 150


def load() -> list[str]:
    with _lock:
        try:
            if _MEMORY_PATH.exists():
                return json.loads(_MEMORY_PATH.read_text())
        except Exception:
            pass
        return []


def _save(facts: list[str]) -> None:
    with _lock:
        try:
            _MEMORY_PATH.write_text(json.dumps(facts, indent=2))
        except Exception as e:
            print(f"[memory] Save error: {e}")


def facts_prompt(facts: list[str]) -> str:
    """Format the facts list for injection into the system prompt."""
    if not facts:
        return ""
    lines = "\n".join(f"- {f}" for f in facts)
    return f"\n\nKNOWN FACTS ABOUT THE USER AND THEIR WORLD:\n{lines}\nRefer to these naturally when relevant."


def extract_and_store(user_text: str, assistant_text: str) -> None:
    """Extract memorable facts from one exchange and merge into memory. Runs in background."""
    try:
        response = _client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=300,
            system=_EXTRACT_SYSTEM,
            messages=[{
                "role": "user",
                "content": f"User said: {user_text}\nAssistant replied: {assistant_text}",
            }],
        )
        raw = next((b.text for b in response.content if hasattr(b, "text")), "[]").strip()
        new_facts: list[str] = json.loads(raw)
        if not isinstance(new_facts, list) or not new_facts:
            return

        existing = load()
        existing_lower = {f.lower() for f in existing}
        added = [f for f in new_facts if isinstance(f, str) and f.lower() not in existing_lower]
        if not added:
            return

        merged = existing + added
        if len(merged) > _MAX_FACTS:
            merged = merged[-_MAX_FACTS:]
        _save(merged)
        print(f"[memory] Stored {len(added)} new fact(s): {added}")
    except Exception as e:
        print(f"[memory] Extraction error: {e}")


def store_in_background(user_text: str, assistant_text: str) -> None:
    threading.Thread(target=extract_and_store, args=(user_text, assistant_text), daemon=True).start()
