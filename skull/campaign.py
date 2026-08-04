"""Campaign memory manager for Omega-7's RPG Gamemaster mode.

Each named campaign (e.g. "The Enemy Within") is persisted as a JSON file:
    <data_dir>/campaigns/<slug>.json

The "active" campaign is tracked in memory for the current process; it resets
on restart (intentional — the GM asks at session start which campaign to resume).

Public API
----------
list_campaigns()                    -> list[dict]
new_campaign(name)                  -> dict           (creates and sets active)
load_campaign(name)                 -> dict | None    (sets active)
get_active_campaign()               -> dict | None
set_active_campaign(name)           -> dict | None
save_campaign(data)                 -> None           (write active campaign to disk)
update_field(key, value)            -> None           (update + autosave)
add_session_note(note)              -> None           (append + autosave)
roll_characteristics(race, rolls)   -> dict           (calculate full char block)
upsert_character(char_dict)         -> None           (add/replace char in active)
"""
from __future__ import annotations

import json
import os
import pathlib
import random
import re
from datetime import datetime
from typing import Any, Optional


# ── storage ──────────────────────────────────────────────────────────────────

def _campaigns_dir() -> pathlib.Path:
    repo_root = pathlib.Path(__file__).resolve().parent.parent
    repo_campaigns = repo_root / "campaigns"
    if repo_campaigns.exists():
        return repo_campaigns
    data_dir = pathlib.Path(
        os.getenv("OMEGA7_DATA_DIR", "~/.config/omega7")
    ).expanduser()
    d = data_dir / "campaigns"
    d.mkdir(parents=True, exist_ok=True)
    return d



def _slug(name: str) -> str:
    s = name.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:60] or "unnamed"


def _campaign_path(name: str) -> pathlib.Path:
    return _campaigns_dir() / f"{_slug(name)}.json"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ── WFRP 4E racial characteristic data ───────────────────────────────────────
# Source: WFRP 4E Core Rulebook p.33-37, Attributes Table
# Formula: characteristic = race_base_modifier + sum_of_2d10
# Wounds = SB + 2*TB + WPB  (Bonus = characteristic // 10)

CHARACTERISTICS = ["WS", "BS", "S", "T", "I", "Ag", "Dex", "Int", "WP", "Fel"]

CHAR_FULL_NAMES = {
    "WS": "Weapon Skill", "BS": "Ballistic Skill", "S": "Strength",
    "T": "Toughness", "I": "Initiative", "Ag": "Agility",
    "Dex": "Dexterity", "Int": "Intelligence", "WP": "Willpower",
    "Fel": "Fellowship",
}

RACIAL_DATA = {
    "human": {
        "display": "Human (Reiklander)",
        "base": {"WS": 20, "BS": 20, "S": 20, "T": 20, "I": 20,
                 "Ag": 20, "Dex": 20, "Int": 20, "WP": 20, "Fel": 20},
        "wounds_bonus": 0,
        "fate": 2, "fortune": 2, "resilience": 1, "resolve": 1,
        "move": 4, "xp_bonus": 20,
    },
    "dwarf": {
        "display": "Dwarf",
        "base": {"WS": 30, "BS": 20, "S": 20, "T": 30, "I": 20,
                 "Ag": 10, "Dex": 30, "Int": 20, "WP": 40, "Fel": 10},
        "wounds_bonus": 0,
        "fate": 0, "fortune": 0, "resilience": 2, "resolve": 2,
        "move": 3, "xp_bonus": 0,
    },
    "halfling": {
        "display": "Halfling",
        "base": {"WS": 10, "BS": 30, "S": 10, "T": 20, "I": 20,
                 "Ag": 20, "Dex": 30, "Int": 20, "WP": 30, "Fel": 30},
        "wounds_bonus": 0,
        "fate": 3, "fortune": 3, "resilience": 0, "resolve": 0,
        "move": 3, "xp_bonus": 0,
    },
    "high_elf": {
        "display": "High Elf (Asur)",
        "base": {"WS": 30, "BS": 30, "S": 20, "T": 20, "I": 40,
                 "Ag": 30, "Dex": 30, "Int": 30, "WP": 30, "Fel": 20},
        "wounds_bonus": 0,
        "fate": 0, "fortune": 0, "resilience": 2, "resolve": 2,
        "move": 5, "xp_bonus": 0,
    },
    "wood_elf": {
        "display": "Wood Elf (Asrai)",
        "base": {"WS": 30, "BS": 30, "S": 20, "T": 20, "I": 50,
                 "Ag": 40, "Dex": 30, "Int": 30, "WP": 30, "Fel": 10},
        "wounds_bonus": 0,
        "fate": 0, "fortune": 0, "resilience": 2, "resolve": 2,
        "move": 5, "xp_bonus": 0,
    },
}

RACE_ALIASES = {
    "human": "human", "reiklander": "human", "humans": "human",
    "dwarf": "dwarf", "dwarfs": "dwarf", "dwarves": "dwarf",
    "halfling": "halfling", "halflings": "halfling",
    "high elf": "high_elf", "high elves": "high_elf", "asur": "high_elf",
    "wood elf": "wood_elf", "wood elves": "wood_elf", "asrai": "wood_elf",
    "elf": "high_elf",
}


def resolve_race(race_input: str) -> Optional[str]:
    """Resolve a user-supplied race name to a RACIAL_DATA key."""
    return RACE_ALIASES.get(race_input.strip().lower())


def roll_characteristics(race_key: str) -> dict:
    """Roll 2d10 for each of the 10 characteristics and build a full character block.

    Returns a dict with rolls, final characteristic values, derived stats, and
    a formatted speech string for Omega-7 to read aloud.
    """
    racial = RACIAL_DATA.get(race_key)
    if not racial:
        raise ValueError(f"Unknown race key: {race_key}")

    base = racial["base"]
    rolls_used: dict = {}
    roll_totals: dict = {}

    for char in CHARACTERISTICS:
        d1, d2 = random.randint(1, 10), random.randint(1, 10)
        rolls_used[char] = [d1, d2]
        roll_totals[char] = d1 + d2

    characteristics: dict = {}
    for char in CHARACTERISTICS:
        characteristics[char] = base[char] + roll_totals[char]

    sb = characteristics["S"] // 10
    tb = characteristics["T"] // 10
    wpb = characteristics["WP"] // 10
    wounds = sb + (2 * tb) + wpb + racial.get("wounds_bonus", 0)

    return {
        "race_key": race_key,
        "race_display": racial["display"],
        "rolls": rolls_used,
        "roll_totals": roll_totals,
        "characteristics": characteristics,
        "wounds_max": wounds,
        "wounds_current": wounds,
        "fate": racial["fate"],
        "fortune": racial["fortune"],
        "resilience": racial["resilience"],
        "resolve": racial["resolve"],
        "move": racial["move"],
        "xp_bonus": racial.get("xp_bonus", 0),
    }


def format_characteristics_for_speech(char_block: dict) -> str:
    """Format a rolled characteristic block into a readable spoken/text summary."""
    chars = char_block["characteristics"]
    rolls = char_block["roll_totals"]
    base_vals = RACIAL_DATA[char_block["race_key"]]["base"]
    race = char_block["race_display"]
    lines = [
        f"Race: {race}  |  Move: {char_block['move']}",
        f"Wounds: {char_block['wounds_max']}  |  Fate: {char_block['fate']}  "
        f"Fortune: {char_block['fortune']}  "
        f"Resilience: {char_block['resilience']}  Resolve: {char_block['resolve']}",
        "",
        "Characteristics (base + 2d10 roll = final):",
    ]
    for char in CHARACTERISTICS:
        full = CHAR_FULL_NAMES[char]
        b = base_vals[char]
        r = rolls[char]
        v = chars[char]
        lines.append(f"  {char:4s} ({full:17s}): {b:2d} + {r:2d} = {v:2d}")
    if char_block.get("xp_bonus"):
        lines.append(f"\nBonus: +{char_block['xp_bonus']} XP for keeping these random rolls.")
    return "\n".join(lines)


def swap_characteristics(char_block: dict, char1: str, char2: str) -> dict:
    """Swap the roll totals (not bases) between two characteristics and recalculate."""
    base_vals = RACIAL_DATA[char_block["race_key"]]["base"]
    rolls = dict(char_block["roll_totals"])
    rolls[char1], rolls[char2] = rolls[char2], rolls[char1]
    char_block["roll_totals"] = rolls
    for char in CHARACTERISTICS:
        char_block["characteristics"][char] = base_vals[char] + rolls[char]
    # Recalculate wounds
    sb = char_block["characteristics"]["S"] // 10
    tb = char_block["characteristics"]["T"] // 10
    wpb = char_block["characteristics"]["WP"] // 10
    racial = RACIAL_DATA[char_block["race_key"]]
    char_block["wounds_max"] = sb + (2 * tb) + wpb + racial.get("wounds_bonus", 0)
    char_block["wounds_current"] = char_block["wounds_max"]
    return char_block


def upsert_character(char_dict: dict) -> None:
    """Add or replace a character in the active campaign by name, then autosave."""
    global _active_campaign
    if _active_campaign is None:
        print("[campaign] No active campaign — cannot upsert character.")
        return
    name = char_dict.get("name", "").strip()
    existing = _active_campaign.setdefault("characters", [])
    for i, c in enumerate(existing):
        if c.get("name", "").lower() == name.lower():
            existing[i] = char_dict
            save_campaign()
            return
    existing.append(char_dict)
    save_campaign()


# ── in-process active campaign ────────────────────────────────────────────────

_active_campaign: Optional[dict] = None


def get_active_campaign() -> Optional[dict]:
    return _active_campaign


def set_active_campaign(name: str) -> Optional[dict]:
    global _active_campaign
    data = load_campaign(name, set_active=False)
    _active_campaign = data
    return data


# ── CRUD ──────────────────────────────────────────────────────────────────────

def list_campaigns() -> list:
    results = []
    for f in sorted(_campaigns_dir().glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            results.append({
                "name": data.get("name", f.stem),
                "slug": f.stem,
                "adventure": data.get("adventure", ""),
                "last_modified": data.get("last_modified", ""),
                "characters": [c.get("name", "?") for c in data.get("characters", [])],
            })
        except Exception:
            continue
    return results


def load_campaign(name: str, set_active: bool = True) -> Optional[dict]:
    global _active_campaign
    p = _campaign_path(name)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if set_active:
            _active_campaign = data
        return data
    except Exception as e:
        print(f"[campaign] Failed to load {p}: {e}")
        return None


def new_campaign(name: str, adventure: str = "", characters: Optional[list] = None) -> dict:
    global _active_campaign
    slug = _slug(name)
    now = _now()
    data: dict[str, Any] = {
        "name": name, "slug": slug, "created": now, "last_modified": now,
        "adventure": adventure or name, "characters": characters or [],
        "current_location": "", "current_scene": "",
        "active_npcs": [], "session_notes": [],
    }
    _save_to_disk(data)
    _active_campaign = data
    return data


def save_campaign(data: Optional[dict] = None) -> None:
    if data is None:
        data = _active_campaign
    if data is None:
        return
    data["last_modified"] = _now()
    _save_to_disk(data)


def _save_to_disk(data: dict) -> None:
    p = _campaign_path(data["name"])
    try:
        p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[campaign] Saved campaign '{data['name']}' -> {p}")
    except Exception as e:
        print(f"[campaign] Save error: {e}")


def update_field(key: str, value: Any) -> None:
    global _active_campaign
    if _active_campaign is None:
        return
    _active_campaign[key] = value
    save_campaign()


def add_session_note(note: str) -> None:
    global _active_campaign
    if _active_campaign is None:
        return
    entry = {"timestamp": _now(), "note": note.strip()}
    _active_campaign.setdefault("session_notes", []).append(entry)
    save_campaign()


# ── summary helpers ───────────────────────────────────────────────────────────

def campaign_summary(data: dict) -> str:
    lines = [f"Campaign: {data.get('name', '?')}"]
    if data.get("adventure"):
        lines.append(f"Adventure: {data['adventure']}")
    chars = data.get("characters", [])
    if chars:
        for c in chars:
            name = c.get("name", "Unknown")
            career = c.get("career", "")
            race = c.get("race", "")
            wounds = c.get("wounds", {})
            fate_pts = c.get("fate", {})
            w_str = f"Wounds {wounds.get('current', '?')}/{wounds.get('max', '?')}" if wounds else ""
            f_str = f"Fate {fate_pts.get('current', '?')}/{fate_pts.get('total', '?')}" if fate_pts else ""
            parts = [p for p in [race, career, w_str, f_str] if p]
            lines.append(f"  Character: {name}" + (f" ({', '.join(parts)})" if parts else ""))
    if data.get("current_location"):
        lines.append(f"Location: {data['current_location']}")
    if data.get("current_scene"):
        lines.append(f"Scene: {data['current_scene']}")
    notes = data.get("session_notes", [])
    if notes:
        last = notes[-1]
        lines.append(f"Last note ({last.get('timestamp', '')[:10]}): {last.get('note', '')}")
    return "\n".join(lines)
