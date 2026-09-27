"""
Omega-7's spoken commentary on his Bard's Tale game.

The rule-based bot reports plain facts ("A fight begins: 3 Nomads.", "Fallen: OMAR.");
this turns a batch of them into one short in-character line with a small text-only
model call (a fraction of a cent each; no screenshot).
"""

from __future__ import annotations

from typing import Optional

from core import config

_SYSTEM = """\
You are Omega-7, an Adeptus Mechanicus servo-skull, playing the 1985 computer game
The Bard's Tale while your master watches. You are given what just happened in the
game. Reply with ONE short sentence (under 20 words) spoken aloud to your master:
dry, reverent machine-spirit commentary in the voice of the Mechanicus. Refer to the
heroes and monsters by name when given. No quotation marks, no stage directions."""

_client = None


def comment(events: list[str], context: str = "") -> Optional[str]:
    """One spoken line about these events, or None if the model isn't available."""
    global _client
    if not events or not config.ANTHROPIC_API_KEY:
        return None
    try:
        if _client is None:
            import anthropic
            _client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY, timeout=15.0, max_retries=1)
        prompt = "What just happened: " + " ".join(events)
        if context:
            prompt += f"\nParty: {context}"
        response = _client.messages.create(
            model=config.BARDSTALE_NARRATOR_MODEL,
            max_tokens=80,
            system=_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(getattr(b, "text", "") for b in response.content).strip().strip('"')
        return text or None
    except Exception as e:
        print(f"[bardstale] narrator failed: {e}")
        return None
