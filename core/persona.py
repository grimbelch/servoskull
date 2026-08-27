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

_OWNER_TOKEN = "{owner_section}"
_NAME_TOKEN = "{skull_name}"




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


def build_owner_section(owner: dict, skull_name: str = "Omega-7") -> str:
    """Render the 'YOUR MASTER' block from a partial owner profile.

    Every field is optional; only what's provided is included, so a half-filled
    wizard still produces coherent prose."""
    p_config = get_personality_config(skull_name)
    name = _clean(owner.get("name"))
    if not name:
        directive = p_config.get("owner_directive", "YOUR MASTER: You do not yet know your master's name or history.")
        # Some directives might expect a format, but if name is unknown we use it as is or fallback
        if "{first}" in directive:
            return directive.replace("{first}", "them")
        return directive

    aliases = [_clean(a) for a in (owner.get("aliases") or []) if _clean(a)]
    first = name.split()[0]
    title = _clean(owner.get("title") or owner.get("honorific")) or "Master"

    lead = f'Your master\'s name is "{name}". You MUST address them using the honorific "{title}" or "{title} {first}" (e.g. "{title}" or "{title} {first}"). Never address them as "Mistress", "Lady", or any other unassigned title'
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

    directive = p_config.get("owner_directive", "Your primary directive is to serve {first}.")
    parts.append(_sentence(directive.format(first=first)))

    return "YOUR MASTER: " + " ".join(p for p in parts if p)


def get_personality_config(skull_name: str = "Omega-7") -> dict:
    from core import config
    key = config.get_personality_key(skull_name)
    base_dir = pathlib.Path(__file__).parent.parent / "personalities"
    p_dir = base_dir / key
    cfg_path = p_dir / "config.json"
    if cfg_path.exists():
        try:
            return json.loads(cfg_path.read_text())
        except Exception:
            pass
    return {}


def build_system_prompt(owner: dict, skull_name: str = "Omega-7") -> str:
    """Load the shipped character template and inject the skull's name + owner section."""
    from core import config
    name = (skull_name or "Omega-7").strip()
    key = config.get_personality_key(name)
    base_dir = pathlib.Path(__file__).parent.parent / "personalities"
    
    p_dir = base_dir / key
    if not p_dir.exists():
        p_dir = base_dir / "omega7" if (base_dir / "omega7").exists() else base_dir / "skull"
        
    t_path = p_dir / "persona.txt"
    if not t_path.exists():
        t_path = base_dir / "skull" / "persona.txt"
        
    template = t_path.read_text()
    template = template.replace(_NAME_TOKEN, name)
    return template.replace(_OWNER_TOKEN, build_owner_section(owner, skull_name)).rstrip() + "\n"
