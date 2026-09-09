from __future__ import annotations
import json
import threading

from core import config
from core import llm as _llm
from core import db

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

# ── Long-term explicit memory (only changes on direct user instruction) ────────

def load_longterm(personality: str | None = None) -> list[str]:
    return db.get_memory_facts(longterm=True, personality=personality)

def remember(fact: str, personality: str | None = None) -> str:
    """Add a fact to long-term memory. Returns confirmation string."""
    p = personality or config.get_personality_key()
    facts = load_longterm(personality=p)
    if fact.lower() in {f.lower() for f in facts}:
        return "Already committed to long-term memory."
    db.add_memory_fact(fact, longterm=True, personality=p)
    print(f"[memory] Longterm stored ({p}): {fact!r}")
    return f"Committed to long-term memory: {fact}"

def forget(query: str, personality: str | None = None) -> str:
    """Remove the fact most closely matching query. Returns confirmation string."""
    p = personality or config.get_personality_key()
    facts = load_longterm(personality=p)
    q = query.lower()
    matches = [f for f in facts if q in f.lower()]
    if not matches:
        return f"No long-term memory found matching: {query}"
    for m in matches:
        db.remove_memory_fact(m, longterm=True, personality=p)
    removed = "; ".join(matches)
    print(f"[memory] Longterm removed ({p}): {removed!r}")
    return f"Erased from long-term memory: {removed}"

def update(query: str, new_fact: str, personality: str | None = None) -> str:
    """Replace the fact matching query with new_fact. Returns confirmation string."""
    p = personality or config.get_personality_key()
    facts = load_longterm(personality=p)
    q = query.lower()
    matches = [f for f in facts if q in f.lower()]
    if not matches:
        return f"No long-term memory found matching: {query}. Use remember_fact to add it as new."
    for m in matches:
        db.update_memory_fact(m, new_fact, longterm=True, personality=p)
    print(f"[memory] Longterm updated ({p}): {matches} → {new_fact!r}")
    return f"Updated long-term memory: {'; '.join(matches)} → {new_fact}"

def longterm_prompt(facts: list[str]) -> str:
    if not facts:
        return ""
    lines = "\n".join(f"- {f}" for f in facts)
    return f"\n\nEXPLICITLY REMEMBERED FACTS (permanent until forgotten):\n{lines}"

# ── Short-term implicit memory (extracted automatically) ─────────────────────────

def load(personality: str | None = None) -> list[str]:
    return db.get_memory_facts(longterm=False, personality=personality)

def facts_prompt(facts: list[str]) -> str:
    """Format the facts list for injection into the system prompt."""
    if not facts:
        return ""
    lines = "\n".join(f"- {f}" for f in facts)
    return f"\n\nKNOWN FACTS ABOUT THE USER AND THEIR WORLD:\n{lines}\nRefer to these naturally when relevant."

def extract_and_store(user_text: str, assistant_text: str, personality: str | None = None) -> None:
    """Extract memorable facts from one exchange and merge into memory. Runs in background."""
    p = personality or config.get_personality_key()
    try:
        existing = load(personality=p)
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

        changed = False
        for fact, replaces in new_items:
            # Delete any facts the model flagged as superseded (case-insensitive).
            for r in replaces:
                rl = r.lower()
                matches = [f for f in existing if f.lower() == rl]
                for m in matches:
                    db.remove_memory_fact(m, longterm=False, personality=p)
                    changed = True
                    existing.remove(m)
                    
            if fact.lower() not in {f.lower() for f in existing}:
                db.add_memory_fact(fact, longterm=False, personality=p)
                existing.append(fact)
                changed = True

        if changed:
            db.enforce_memory_limit(_MAX_FACTS, personality=p)
            print(f"[memory] Memory updated ({p}) → {len(existing)} fact(s)")
            
    except Exception as e:
        print(f"[memory] Extraction error ({p}): {e}")

def store_in_background(user_text: str, assistant_text: str, personality: str | None = None) -> None:
    p = personality or config.get_personality_key()
    threading.Thread(target=extract_and_store, args=(user_text, assistant_text, p), daemon=True).start()

def purge_memory_of_name(name: str, personality: str | None = None) -> int:
    """Remove any facts from memory and longterm_memory containing the name (case-insensitive).
    Returns the total number of facts removed.
    """
    return db.remove_facts_by_name(name, personality=personality)

