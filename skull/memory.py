from __future__ import annotations
import json
import pathlib
import threading

from skull import config
from skull import llm as _llm

_MEMORY_PATH = config.data_path("memory.json")
_LONGTERM_PATH = config.data_path("longterm_memory.json")
_lock = threading.Lock()


def _bak(path: pathlib.Path) -> pathlib.Path:
    return path.with_suffix(path.suffix + ".bak")


def _read_facts(path: pathlib.Path) -> list[str]:
    """Load a JSON list of fact strings. On corruption, log LOUDLY and fall back
    to the .bak sidecar rather than silently returning [] — a single stray comma
    once wiped Omega-7's entire long-term memory with zero indication."""
    for candidate, note in ((path, ""), (_bak(path), " (recovered from .bak)")):
        if not candidate.exists():
            continue
        try:
            data = json.loads(candidate.read_text())
        except Exception as e:
            print(f"[memory] CORRUPT {candidate.name}: {e}")
            continue
        if not isinstance(data, list):
            print(f"[memory] {candidate.name} is not a JSON list; ignoring")
            continue
        if note:
            print(f"[memory] {path.name}{note}")
        return [f for f in data if isinstance(f, str)]
    return []


def _write_facts(path: pathlib.Path, facts: list[str]) -> None:
    try:
        # Preserve the last-known-good copy, but never let a corrupt current
        # file clobber a healthy .bak.
        if path.exists():
            try:
                if isinstance(json.loads(path.read_text()), list):
                    _bak(path).write_text(path.read_text())
            except Exception:
                pass
        path.write_text(json.dumps(facts, indent=2) + "\n")
    except Exception as e:
        print(f"[memory] Save error for {path.name}: {e}")


# ── Long-term explicit memory (only changes on direct user instruction) ────────

def load_longterm() -> list[str]:
    with _lock:
        return _read_facts(_LONGTERM_PATH)


def _save_longterm(facts: list[str]) -> None:
    with _lock:
        _write_facts(_LONGTERM_PATH, facts)


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
Given a single conversation exchange plus the facts already known, extract any NEW facts worth remembering long-term about the user or people they mention. \
Include: names, locations (home, work, city), relationships, occupations, hobbies, preferences, pets, important possessions. \
Do NOT include transient information (current questions, today's weather, etc.). \
Do NOT repeat a fact that is already known unless the exchange CORRECTS it. \
Some attributes are single-valued: the user has exactly ONE name and ONE home address. \
If the exchange reveals or corrects such an attribute and it conflicts with an already-known fact, \
you MUST copy the outdated fact(s) verbatim into "replaces" so they are deleted. \
Return a JSON array of objects, each {"fact": "<short fact string>", "replaces": ["<exact existing fact to delete>", ...]}. \
Use an empty "replaces" list for a purely additive fact. \
Return [] if nothing new or memorable was said. \
Return ONLY the JSON array — no explanation, no markdown."""

_MAX_FACTS = 150


def load() -> list[str]:
    with _lock:
        return _read_facts(_MEMORY_PATH)


def _save(facts: list[str]) -> None:
    with _lock:
        _write_facts(_MEMORY_PATH, facts)


def facts_prompt(facts: list[str]) -> str:
    """Format the facts list for injection into the system prompt."""
    if not facts:
        return ""
    lines = "\n".join(f"- {f}" for f in facts)
    return f"\n\nKNOWN FACTS ABOUT THE USER AND THEIR WORLD:\n{lines}\nRefer to these naturally when relevant."


def extract_and_store(user_text: str, assistant_text: str) -> None:
    """Extract memorable facts from one exchange and merge into memory. Runs in background."""
    try:
        existing = load()
        existing_block = "\n".join(f"- {f}" for f in existing) or "(none yet)"
        raw = _llm.simple(
            _EXTRACT_SYSTEM,
            f"Already known facts:\n{existing_block}\n\n"
            f"New exchange:\nUser said: {user_text}\nAssistant replied: {assistant_text}",
            max_tokens=400,
        ).strip()
        # Models sometimes wrap JSON in a ```json fence — strip it before parsing.
        if raw.startswith("```"):
            raw = raw.strip("`")
            raw = raw[raw.find("["):raw.rfind("]") + 1] if "[" in raw else raw
        items = json.loads(raw)
        if not isinstance(items, list) or not items:
            return

        # Accept either bare strings (legacy) or {"fact", "replaces"} objects.
        new_items: list[tuple[str, list[str]]] = []
        for it in items:
            if isinstance(it, str):
                new_items.append((it, []))
            elif isinstance(it, dict) and isinstance(it.get("fact"), str):
                replaces = [r for r in (it.get("replaces") or []) if isinstance(r, str)]
                new_items.append((it["fact"], replaces))
        if not new_items:
            return

        facts = existing[:]
        changed = False
        for fact, replaces in new_items:
            # Delete any facts the model flagged as superseded (case-insensitive).
            for r in replaces:
                rl = r.lower()
                kept = [f for f in facts if f.lower() != rl]
                if len(kept) != len(facts):
                    facts = kept
                    changed = True
            if fact.lower() not in {f.lower() for f in facts}:
                facts.append(fact)
                changed = True

        if not changed:
            return
        if len(facts) > _MAX_FACTS:
            facts = facts[-_MAX_FACTS:]
        _save(facts)
        print(f"[memory] Memory updated → {len(facts)} fact(s)")
    except Exception as e:
        print(f"[memory] Extraction error: {e}")


def store_in_background(user_text: str, assistant_text: str) -> None:
    threading.Thread(target=extract_and_store, args=(user_text, assistant_text), daemon=True).start()


def purge_memory_of_name(name: str) -> int:
    """Remove any facts from memory and longterm_memory containing the name (case-insensitive).
    Returns the total number of facts removed.
    """
    nl = name.lower()
    removed_count = 0
    
    # 1. Purge short-term memory
    facts = load()
    new_facts = [f for f in facts if nl not in f.lower()]
    removed_count += len(facts) - len(new_facts)
    if len(facts) != len(new_facts):
        _save(new_facts)
        
    # 2. Purge long-term memory
    lt_facts = load_longterm()
    new_lt_facts = [f for f in lt_facts if nl not in f.lower()]
    removed_count += len(lt_facts) - len(new_lt_facts)
    if len(lt_facts) != len(new_lt_facts):
        _save_longterm(new_lt_facts)
        
    return removed_count
