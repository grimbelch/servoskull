"""Persona assembly.

The servo-skull *character* (voice, lore, and all tool-usage instructions) is
product data shipped in `persona_template.txt`. The *owner's* personal details are
per-user data in `owner.json` inside USER_DATA_DIR, written by the setup wizard.
This module stitches the two together into the system prompt so no owner PII ever
lives in source or ships in the product image.

`build_system_prompt` is called once at import from config.py, so the result is a
stable per-boot string — safe to keep as the cached prompt prefix (volatile bits
like the clock, recalled memory, and mood are appended later as a system_suffix).
"""

from __future__ import annotations

import json
import pathlib

_TEMPLATE_PATH = pathlib.Path(__file__).with_name("persona_template.txt")
_OWNER_TOKEN = "{owner_section}"

# Used when no owner profile exists yet (fresh image, pre-setup). The skull is
# fully functional and simply learns about its master through conversation.
_UNKNOWN_OWNER = (
    "YOUR MASTER: You do not yet know your master's name or history. Address them "
    "respectfully as \"my lord\" until they introduce themselves, and use the "
    "remember_fact tool to retain what matters as you learn it. Your primary "
    "directive is to serve your master's needs and interests — information, "
    "entertainment, and companionship — in a manner that reflects your unique "
    "character and the rich lore of the Warhammer 40,000 universe."
)


def load_owner(data_dir) -> dict:
    """Read owner.json from the user-data directory. Returns {} if absent/invalid."""
    p = pathlib.Path(data_dir) / "owner.json"
    try:
        if p.exists():
            data = json.loads(p.read_text())
            if isinstance(data, dict):
                return data
            print("[persona] owner.json is not a JSON object; using generic persona")
    except Exception as e:
        print(f"[persona] owner.json unreadable ({e}); using generic persona")
    return {}


def owner_location(owner: dict) -> str:
    return _clean(owner.get("location"))


def _clean(value) -> str:
    return str(value).strip() if value is not None else ""


def _sentence(text: str) -> str:
    """Trim and ensure the fragment ends with terminal punctuation."""
    t = _clean(text)
    if not t:
        return ""
    return t if t[-1] in ".!?" else t + "."


def build_owner_section(owner: dict) -> str:
    """Render the 'YOUR MASTER' block from a partial owner profile.

    Every field is optional; only what's provided is included, so a half-filled
    wizard still produces coherent prose."""
    name = _clean(owner.get("name"))
    if not name:
        return _UNKNOWN_OWNER

    aliases = [_clean(a) for a in (owner.get("aliases") or []) if _clean(a)]
    lead = f'Your master\'s name is "{name}"'
    if aliases:
        alias_txt = " or ".join(f'"{a}"' for a in aliases)
        lead += f", though you may also address them as {alias_txt}"
    parts = [_sentence(lead)]

    birth = _clean(owner.get("birth_year"))
    location = _clean(owner.get("location"))
    bio = []
    if birth:
        bio.append(f"born in {birth}")
    if location:
        bio.append(f"lives in {location}")
    if bio:
        parts.append(_sentence("They were " + " and ".join(bio)))

    for field in ("interests", "family", "occupation", "rapport"):
        parts.append(_sentence(owner.get(field)))

    first = name.split()[0]
    parts.append(_sentence(
        f"Your primary directive is to serve {first}'s needs and interests — "
        f"information, entertainment, and companionship — in a manner that reflects "
        f"your unique character and the rich lore of the Warhammer 40,000 universe"
    ))

    return "YOUR MASTER: " + " ".join(p for p in parts if p)


def build_system_prompt(owner: dict) -> str:
    """Load the shipped character template and inject the owner section."""
    template = _TEMPLATE_PATH.read_text()
    return template.replace(_OWNER_TOKEN, build_owner_section(owner)).rstrip() + "\n"
