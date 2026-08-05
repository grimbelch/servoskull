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
from . import db

import json
import os
import pathlib
import random
import re
from datetime import datetime
from typing import Any, Optional


# ── storage ──────────────────────────────────────────────────────────────────

def _campaigns_dir() -> pathlib.Path:
    roleplay_campaigns = pathlib.Path(__file__).resolve().parent.parent / "campaigns"
    if roleplay_campaigns.exists():
        return roleplay_campaigns
    repo_root = pathlib.Path(__file__).resolve().parent.parent.parent.parent
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

RANDOM_TALENTS_TABLE = [
    (3, "Acute Sense (any one)"), (6, "Ambidextrous"), (9, "Animal Affinity"),
    (12, "Artistic"), (15, "Attractive"), (18, "Coolheaded"),
    (21, "Craftsman (any one)"), (24, "Flee!"), (28, "Hardy"),
    (31, "Lightning Reflexes"), (34, "Linguistics"), (38, "Luck"),
    (41, "Marksman"), (44, "Mimic"), (45, "Night Vision"),
    (50, "Nimble Fingered"), (52, "Noble Blood"), (55, "Orientation"),
    (58, "Perfect Pitch"), (62, "Pure Soul"), (65, "Read/Write"),
    (68, "Resistance (any one)"), (71, "Savvy"), (74, "Sharp"),
    (78, "Sixth Sense"), (81, "Strong Legs"), (84, "Sturdy"),
    (87, "Suave"), (91, "Super Numerate"), (94, "Very Resilient"),
    (97, "Very Strong"), (100, "Warrior Born"),
]

SPECIES_SKILLS = {
    "human": [
        "Animal Care", "Charm", "Cool", "Evaluate", "Gossip", "Haggle",
        "Language (Bretonnian)", "Language (Wastelander)", "Leadership",
        "Lore (Reikland)", "Melee (Basic)", "Ranged (Bow)"
    ],
    "dwarf": [
        "Consume Alcohol", "Cool", "Endurance", "Entertain (Storytelling)",
        "Evaluate", "Intimidate", "Language (Khazalid)", "Lore (Dwarfs)",
        "Lore (Geology)", "Lore (Metallurgy)", "Melee (Basic)", "Trade (any one)"
    ],
    "halfling": [
        "Charm", "Consume Alcohol", "Dodge", "Gamble", "Haggle", "Intuition",
        "Language (Mootish)", "Lore (Reikland)", "Perception", "Sleight of Hand",
        "Stealth", "Trade (Cook)"
    ],
    "high_elf": [
        "Cool", "Entertain (Sing)", "Evaluate", "Language (Eltharin)", "Leadership",
        "Melee (Basic)", "Navigation", "Perception", "Play (any one)", "Ranged (Bow)",
        "Sail", "Swim"
    ],
    "wood_elf": [
        "Athletics", "Climb", "Endurance", "Entertain (Sing)", "Intimidate",
        "Language (Eltharin)", "Melee (Basic)", "Outdoor Survival", "Perception",
        "Ranged (Bow)", "Stealth (Rural)", "Track"
    ],
}

SPECIES_TALENTS = {
    "human": {
        "fixed": ["Doomed"],
        "choices": [["Savvy", "Suave"]],
        "random_count": 3
    },
    "dwarf": {
        "fixed": ["Magic Resistance", "Night Vision", "Sturdy"],
        "choices": [["Read/Write", "Relentless"], ["Resolute", "Strong-minded"]],
        "random_count": 0
    },
    "halfling": {
        "fixed": ["Acute Sense (Taste)", "Night Vision", "Resistance (Chaos)", "Small"],
        "choices": [],
        "random_count": 2
    },
    "high_elf": {
        "fixed": ["Acute Sense (Sight)", "Night Vision", "Read/Write"],
        "choices": [["Coolheaded", "Savvy"], ["Second Sight", "Sixth Sense"]],
        "random_count": 0
    },
    "wood_elf": {
        "fixed": ["Acute Sense (Sight)", "Night Vision", "Rover"],
        "choices": [["Hardy", "Second Sight"], ["Read/Write", "Very Resilient"]],
        "random_count": 0
    },
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

CLASS_TRAPPINGS = {
    "academics": ["Clothing", "Dagger", "Pouch", "Sling Bag containing Writing Kit and 1d10 sheets of Parchment"],
    "burghers": ["Cloak", "Clothing", "Dagger", "Hat", "Pouch", "Sling Bag containing Lunch"],
    "courtiers": ["Courtly Garb", "Dagger", "Pouch containing Tweezers, Ear Pick, and a Comb"],
    "peasants": ["Cloak", "Clothing", "Dagger", "Pouch", "Sling Bag containing Rations (1 day)"],
    "rangers": ["Cloak", "Clothing", "Dagger", "Pouch", "Backpack containing Tinderbox, Blanket, Rations (1 day)"],
    "riverfolk": ["Cloak", "Clothing", "Dagger", "Pouch", "Sling Bag containing a Flask of Spirits"],
    "rogues": ["Clothing", "Dagger", "Pouch", "Sling Bag containing 2 Candles, 1d10 Matches, a Hood or Mask"],
    "warriors": ["Clothing", "Hand Weapon", "Dagger", "Pouch"],
}

def get_class_trappings(class_name: str) -> list[str]:
    """Return initial Class Trappings for a given WFRP 4E Class."""
    key = class_name.strip().lower()
    return CLASS_TRAPPINGS.get(key, [])


EYE_COLOUR_TABLE = {
    2: ("Free Choice", "Coal", "Light Grey", "Jet", "Ivory"),
    3: ("Green", "Lead", "Grey", "Amethyst", "Charcoal"),
    4: ("Pale Blue", "Steel", "Pale Blue", "Aquamarine", "Ivy Green"),
    5: ("Blue", "Blue", "Blue", "Sapphire", "Mossy Green"),
    6: ("Blue", "Blue", "Blue", "Sapphire", "Mossy Green"),
    7: ("Blue", "Blue", "Blue", "Sapphire", "Mossy Green"),
    8: ("Pale Grey", "Earth Brown", "Green", "Turquoise", "Chestnut"),
    9: ("Pale Grey", "Earth Brown", "Green", "Turquoise", "Chestnut"),
    10: ("Pale Grey", "Earth Brown", "Green", "Turquoise", "Chestnut"),
    11: ("Pale Grey", "Earth Brown", "Green", "Turquoise", "Chestnut"),
    12: ("Grey", "Dark Brown", "Hazel", "Emerald", "Chestnut"),
    13: ("Grey", "Dark Brown", "Hazel", "Emerald", "Chestnut"),
    14: ("Grey", "Dark Brown", "Hazel", "Emerald", "Chestnut"),
    15: ("Brown", "Hazel", "Brown", "Amber", "Dark Brown"),
    16: ("Brown", "Hazel", "Brown", "Amber", "Dark Brown"),
    17: ("Brown", "Hazel", "Brown", "Amber", "Dark Brown"),
    18: ("Hazel", "Green", "Copper", "Copper", "Tan"),
    19: ("Dark Brown", "Copper", "Dark Brown", "Citrine", "Sandy Brown"),
    20: ("Black", "Gold", "Dark Brown", "Gold", "Violet"),
}

HAIR_COLOUR_TABLE = {
    2: ("White Blond", "White", "Grey", "Silver", "Birch Silver"),
    3: ("Golden Blond", "Grey", "Flaxen", "White", "Ash Blond"),
    4: ("Red Blond", "Pale Blond", "Russet", "Pale Blond", "Rose Gold"),
    5: ("Golden Brown", "Golden", "Honey", "Blond", "Honey Blond"),
    6: ("Golden Brown", "Golden", "Honey", "Blond", "Honey Blond"),
    7: ("Golden Brown", "Golden", "Honey", "Blond", "Honey Blond"),
    8: ("Light Brown", "Copper", "Chestnut", "Yellow Blond", "Brown"),
    9: ("Light Brown", "Copper", "Chestnut", "Yellow Blond", "Brown"),
    10: ("Light Brown", "Copper", "Chestnut", "Yellow Blond", "Brown"),
    11: ("Light Brown", "Copper", "Chestnut", "Yellow Blond", "Brown"),
    12: ("Dark Brown", "Bronze", "Ginger", "Copper Blond", "Mahogany Brown"),
    13: ("Dark Brown", "Bronze", "Ginger", "Copper Blond", "Mahogany Brown"),
    14: ("Dark Brown", "Bronze", "Ginger", "Copper Blond", "Mahogany Brown"),
    15: ("Black", "Brown", "Mustard", "Red Blond", "Dark Brown"),
    16: ("Black", "Brown", "Mustard", "Red Blond", "Dark Brown"),
    17: ("Black", "Brown", "Mustard", "Red Blond", "Dark Brown"),
    18: ("Auburn", "Dark Brown", "Almond", "Auburn", "Sienna"),
    19: ("Red", "Reddish Brown", "Chocolate", "Red", "Ebony"),
    20: ("Grey", "Black", "Liquorice", "Black", "Blue-Black"),
}

def roll_physical_details(race_input: str) -> dict:
    """Calculate Age, Height, Eye Colour, and Hair Colour based on WFRP 4E Rulebook p.39-40 tables."""
    race_key = resolve_race(race_input) or "human"
    idx_map = {"human": 0, "dwarf": 1, "halfling": 2, "high_elf": 3, "wood_elf": 4}
    spec_idx = idx_map.get(race_key, 0)
    
    # 1. Age
    if race_key == "human":
        age = 15 + random.randint(1, 10)
    elif race_key == "dwarf":
        age = 15 + sum([random.randint(1, 10) for _ in range(10)])
    elif race_key in ["high_elf", "wood_elf"]:
        age = 30 + sum([random.randint(1, 10) for _ in range(10)])
    elif race_key == "halfling":
        age = 15 + sum([random.randint(1, 10) for _ in range(5)])
    else:
        age = 15 + random.randint(1, 10)

    # 2. Height
    if race_key == "human":
        d1, d2 = random.randint(1, 10), random.randint(1, 10)
        inches_bonus = d1 + d2
        if d1 == 10 or d2 == 10:
            inches_bonus += random.randint(1, 10)
        total_inches = 57 + inches_bonus  # 4'9" = 57 in
    elif race_key == "dwarf":
        total_inches = 51 + random.randint(1, 10)  # 4'3" = 51 in
    elif race_key in ["high_elf", "wood_elf"]:
        total_inches = 71 + random.randint(1, 10)  # 5'11" = 71 in
    elif race_key == "halfling":
        total_inches = 37 + random.randint(1, 10)  # 3'1" = 37 in
    else:
        total_inches = 57 + random.randint(1, 10)

    feet = total_inches // 12
    inches = total_inches % 12
    height_str = f"{feet}'{inches}\""

    # 3. Eye Colour
    eye_roll = random.randint(1, 10) + random.randint(1, 10)
    eye_color = EYE_COLOUR_TABLE.get(eye_roll, EYE_COLOUR_TABLE[10])[spec_idx]

    # 4. Hair Colour
    hair_roll = random.randint(1, 10) + random.randint(1, 10)
    hair_color = HAIR_COLOUR_TABLE.get(hair_roll, HAIR_COLOUR_TABLE[10])[spec_idx]

    return {
        "race_key": race_key,
        "age": age,
        "height": height_str,
        "eye_color": eye_color,
        "hair_color": hair_color,
        "summary": f"Age: {age} years | Height: {height_str} | Eyes: {eye_color} | Hair: {hair_color}"
    }


def roll_starting_wealth(status_tier: str, status_level: int) -> dict:
    """Calculate starting wealth based on WFRP 4E Rulebook p.37 table:
    - Brass Tier (Status Level L): L * 2d10 Brass Pennies
    - Silver Tier (Status Level L): L * 1d10 Silver Shillings
    - Gold Tier (Status Level L): L Gold Crowns
    """
    tier = status_tier.strip().capitalize()
    level = max(1, min(10, status_level))
    rolls = []
    total = 0
    coin_type = ""

    if tier == "Brass":
        dice_count = level * 2
        rolls = [random.randint(1, 10) for _ in range(dice_count)]
        total = sum(rolls)
        coin_type = "Brass Pennies (d)"
    elif tier == "Silver":
        dice_count = level
        rolls = [random.randint(1, 10) for _ in range(dice_count)]
        total = sum(rolls)
        coin_type = "Silver Shillings (s)"
    elif tier == "Gold":
        dice_count = 0
        total = level
        coin_type = "Gold Crowns (GC)"
    else:
        dice_count = 2
        rolls = [random.randint(1, 10), random.randint(1, 10)]
        total = sum(rolls)
        coin_type = "Brass Pennies (d)"
        tier = "Brass"

    roll_desc = f" (rolled {dice_count}d10: {rolls})" if rolls else ""
    return {
        "status_tier": tier,
        "status_level": level,
        "rolls": rolls,
        "total": total,
        "coin_type": coin_type,
        "summary": f"{total} {coin_type}{roll_desc}"
    }


def roll_random_talent(count: int = 1) -> str:
    """Roll count times on the WFRP 4E Random Talent Table and return formatted string."""
    count = max(1, min(10, count))
    results = []
    for _ in range(count):
        roll = random.randint(1, 100)
        talent = "Unknown"
        for max_roll, name in RANDOM_TALENTS_TABLE:
            if roll <= max_roll:
                talent = name
                break
        results.append(f"d100 roll {roll:02d} \u2192 {talent}")
    return "\n".join(results)


def get_species_info(race_key: str) -> str:
    """Return species skills list, species talent choices, and random talent count for a species."""
    racial = RACIAL_DATA.get(race_key)
    skills = SPECIES_SKILLS.get(race_key, [])
    talents = SPECIES_TALENTS.get(race_key, {})
    if not racial or not skills:
        return f"Unknown race key '{race_key}'."
    display = racial["display"]
    lines = [f"=== Species Info: {display} ==="]
    lines.append("Species Skills (choose 3 for +5 Advances, 3 for +3 Advances):")
    lines.append("  " + ", ".join(skills))
    lines.append("\nSpecies Talents:")
    if talents.get("fixed"):
        lines.append("  Fixed: " + ", ".join(talents["fixed"]))
    for choice in talents.get("choices", []):
        lines.append("  Choice: " + " OR ".join(choice))
    if talents.get("random_count"):
        lines.append(f"  Random Talents: Roll {talents['random_count']} times on Random Talent Table")
    return "\n".join(lines)



def resolve_race(race_input: str) -> Optional[str]:
    """Resolve a user-supplied race name to a RACIAL_DATA key."""
    return RACE_ALIASES.get(race_input.strip().lower())


def roll_characteristics(race_key: str, rolls: Any = None) -> dict:
    """Roll 2d10 for each of the 10 characteristics and build a full character block."""
    racial = RACIAL_DATA.get(race_key)
    if not racial:
        raise ValueError(f"Unknown race key: {race_key}")

    base = racial["base"]
    rolls_used: dict = {}
    roll_totals: dict = {}

    for char in CHARACTERISTICS:
        if isinstance(rolls, dict) and char in rolls:
            val = rolls[char]
            if isinstance(val, list) and len(val) == 2:
                d1, d2 = val[0], val[1]
            elif isinstance(val, int):
                d1, d2 = val // 2, val - (val // 2)
            else:
                d1, d2 = random.randint(1, 10), random.randint(1, 10)
        else:
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


def normalize_character(char_dict: dict) -> dict:
    """Ensure all fields from WFRP 4E Character Sheet (pages 344-345) exist."""
    c = dict(char_dict)
    c.setdefault("name", "Unnamed Adventurer")
    c.setdefault("race", "Human")
    c.setdefault("class", "Peasants")
    c.setdefault("career", "Villager")
    c.setdefault("career_level", "Villager (Brass 2)")
    c.setdefault("career_path", "")
    c.setdefault("status", "Brass 2")
    c.setdefault("age", None)
    c.setdefault("height", "")
    c.setdefault("hair_color", "")
    c.setdefault("eye_color", "")
    c.setdefault("doomed", "")
    c.setdefault("star_sign", "")
    c.setdefault("motivation", "")
    
    # Characteristics
    chars = c.get("characteristics", {})
    normalized_chars = {}
    for stat in ["WS", "BS", "S", "T", "I", "Ag", "Dex", "Int", "WP", "Fel"]:
        val = chars.get(stat, 30)
        if isinstance(val, dict):
            normalized_chars[stat] = val
        else:
            normalized_chars[stat] = {"initial": val, "advances": 0, "total": val}
    c["characteristics"] = normalized_chars

    # Pools
    if "wounds" not in c or not isinstance(c["wounds"], dict):
        c["wounds"] = {"max": 10, "current": 10}
    if "fate" not in c or not isinstance(c["fate"], dict):
        c["fate"] = {"total": 3, "current": 3}
    if "fortune" not in c or not isinstance(c["fortune"], dict):
        c["fortune"] = {"total": 3, "current": 3}
    if "resilience" not in c or not isinstance(c["resilience"], dict):
        res_val = c.get("resilience", 0)
        c["resilience"] = {"total": res_val if isinstance(res_val, int) else 0, "current": res_val if isinstance(res_val, int) else 0}
    if "resolve" not in c or not isinstance(c["resolve"], dict):
        res_val = c.get("resolve", 0)
        c["resolve"] = {"total": res_val if isinstance(res_val, int) else 0, "current": res_val if isinstance(res_val, int) else 0}
    if "move" not in c or not isinstance(c["move"], dict):
        m = c.get("move", 4)
        if isinstance(m, int):
            c["move"] = {"walk": m, "run": m * 2}
        else:
            c["move"] = {"walk": 4, "run": 8}
            
    # XP
    if "xp" not in c or not isinstance(c["xp"], dict):
        xp_val = c.get("xp", 0)
        spent_val = c.get("xp_spent", 0)
        if isinstance(xp_val, int):
            c["xp"] = {"total": xp_val, "spent": spent_val, "current": max(0, xp_val - spent_val)}
        else:
            c["xp"] = {"total": 0, "spent": 0, "current": 0}

    # Lists
    c.setdefault("skills", [])
    c.setdefault("talents", [])
    c.setdefault("trappings", [])
    c.setdefault("weapons", [])

    # Armour & Encumbrance
    if "armour" not in c or not isinstance(c["armour"], dict):
        c["armour"] = {"head": 0, "body": 0, "l_arm": 0, "r_arm": 0, "l_leg": 0, "r_leg": 0, "items": []}
    if "encumbrance" not in c or not isinstance(c["encumbrance"], dict):
        s_tot = c["characteristics"]["S"].get("total", 30) if isinstance(c["characteristics"]["S"], dict) else 30
        t_tot = c["characteristics"]["T"].get("total", 30) if isinstance(c["characteristics"]["T"], dict) else 30
        c["encumbrance"] = {"current": 0, "max": (s_tot // 10) + (t_tot // 10)}

    # Money
    if "money" not in c or not isinstance(c["money"], dict):
        c["money"] = {"gc": 0, "ss": 0, "bp": 0}

    # Ambitions
    if "ambitions" not in c or not isinstance(c["ambitions"], dict):
        c["ambitions"] = {"short": "", "long": "", "party": ""}

    # Ten Questions
    if "ten_questions" not in c or not isinstance(c["ten_questions"], dict):
        c["ten_questions"] = {
            "origin": "", "family": "", "childhood": "", "why_leave": "", "friends": "",
            "desire": "", "memories": "", "religion": "", "loyalty": "", "secret": ""
        }

    # Psychology & Spells
    if "psychology" not in c or not isinstance(c["psychology"], dict):
        c["psychology"] = {"corruption": 0, "mutations": "", "notes": ""}
    c.setdefault("spells", [])

    return c


def upsert_character(char_dict: dict) -> None:
    """Add or replace a character in the active campaign by unique ID (or original_name/name fallback), then autosave."""
    global _active_campaign
    if _active_campaign is None:
        print("[campaign] No active campaign — cannot upsert character.")
        return
    norm_char = normalize_character(char_dict)
    char_id = norm_char.get("id") or char_dict.get("id")
    name = norm_char.get("name", "").strip()
    orig_name = (char_dict.get("original_name") or name).strip()
    existing = _active_campaign.setdefault("characters", [])

    if char_id:
        for i, c in enumerate(existing):
            if c.get("id") == char_id or str(c.get("id")) == str(char_id):
                existing[i] = norm_char
                save_campaign()
                return

    for i, c in enumerate(existing):
        c_name = c.get("name", "").strip().lower()
        if c_name == orig_name.lower() or c_name == name.lower():
            existing[i] = norm_char
            save_campaign()
            return

    existing.append(norm_char)
    save_campaign()



# ── IN-PROCESS ACTIVE CAMPAIGN & DB AGGREGATION ──────────────────────────────
_active_campaign: Optional[dict] = None


def get_active_campaign() -> Optional[dict]:
    global _active_campaign
    if _active_campaign is None:
        c_list = db.list_all_campaigns()
        if c_list:
            first_name = c_list[0].get("slug") or c_list[0].get("name")
            if first_name:
                _active_campaign = db.get_campaign_dict(first_name)
    return _active_campaign


def set_active_campaign(name: str) -> Optional[dict]:
    global _active_campaign
    data = db.get_campaign_dict(name)
    if data:
        _active_campaign = data
    return data


def list_campaigns() -> list:
    return db.list_all_campaigns()


def load_campaign(name: str, set_active: bool = True) -> Optional[dict]:
    global _active_campaign
    data = db.get_campaign_dict(name)
    if data and set_active:
        _active_campaign = data
    return data


def new_campaign(name: str, adventure: str = "", characters: Optional[list] = None) -> dict:
    global _active_campaign
    slug = _slug(name)
    camp_dict = {
        "name": name,
        "slug": slug,
        "adventure": adventure or name,
        "characters": characters or [],
        "current_location": "The Reikland",
        "current_scene": "",
        "notes": ""
    }
    saved = db.save_or_upsert_campaign(camp_dict)
    _active_campaign = saved
    return saved


def save_campaign(data: Optional[dict] = None) -> None:
    global _active_campaign
    if data is None:
        data = _active_campaign
    if data is None:
        return
    saved = db.save_or_upsert_campaign(data)
    _active_campaign = saved


def update_field(key: str, value: Any) -> None:
    global _active_campaign
    if _active_campaign is None:
        return
    _active_campaign[key] = value
    save_campaign(_active_campaign)


def add_session_note(note: str) -> None:
    global _active_campaign
    if _active_campaign is None:
        return
    db.add_timeline_event(_active_campaign.get("slug", "shadows-over-reikland"), note)
    _active_campaign = db.get_campaign_dict(_active_campaign.get("slug", "shadows-over-reikland"))


def upsert_character(char_dict: dict) -> None:
    global _active_campaign
    if _active_campaign is None:
        print("[campaign] No active campaign — cannot upsert character.")
        return
    norm_char = normalize_character(char_dict)
    slug = _active_campaign.get("slug", _slug(_active_campaign.get("name", "campaign")))
    db.upsert_character_record(slug, norm_char)
    _active_campaign = db.get_campaign_dict(slug)


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

            # Weapons summary
            weaps = c.get("weapons", [])
            if weaps:
                w_lines = []
                for w_item in weaps:
                    if isinstance(w_item, dict):
                        w_base = w_item.get("name", "Weapon")
                        w_spec = w_item.get("type", w_base)
                        w_dmg = w_item.get("damage", "+SB+4")
                        w_qual = w_item.get("qualities", "")
                        w_lines.append(f"{w_base} (Specific: {w_spec}, Damage: {w_dmg}" + (f", Qualities: {w_qual})" if w_qual else ")"))
                    else:
                        w_lines.append(str(w_item))
                lines.append(f"    Equipped Weapons: {', '.join(w_lines)}")

            # Trappings summary
            traps = c.get("trappings", [])
            if traps:
                t_eq = []
                t_car = []
                for t in traps:
                    if isinstance(t, dict):
                        t_name = t.get("name", "")
                        if t.get("equipped") or t_name in ["Hand Weapon", "Leather Jack", "Sturdy Boots and Cloak", "Shield"]:
                            t_eq.append(t_name)
                        else:
                            t_car.append(t_name)
                    else:
                        t_str = str(t)
                        if t_str in ["Hand Weapon", "Leather Jack", "Sturdy Boots and Cloak", "Shield"]:
                            t_eq.append(t_str)
                        else:
                            t_car.append(t_str)
                lines.append(f"    Equipped Trappings: {', '.join(t_eq) or 'None'}")
                lines.append(f"    Carried Inventory: {', '.join(t_car) or 'None'}")

            # Armour AP Summary
            arm = c.get("armour", {})
            if isinstance(arm, dict) and arm:
                ap_str = f"Head {arm.get('head',0)}, Body {arm.get('body',0)}, L.Arm {arm.get('l_arm',0)}, R.Arm {arm.get('r_arm',0)}, L.Leg {arm.get('l_leg',0)}, R.Leg {arm.get('r_leg',0)}, Shield {arm.get('shield',0)}"
                lines.append(f"    Armour AP: {ap_str}")

    if data.get("current_location"):
        lines.append(f"Location: {data['current_location']}")
    if data.get("current_scene"):
        lines.append(f"Scene: {data['current_scene']}")
    notes = data.get("session_notes", [])
    if notes:
        last = notes[-1]
        lines.append(f"Last note ({last.get('timestamp', '')[:10]}): {last.get('note', '')}")
    return "\n".join(lines)

def delete_character(char_name: str) -> None:
    global _active_campaign
    if _active_campaign is None:
        return
    slug = _active_campaign.get("slug", _slug(_active_campaign.get("name", "campaign")))
    db.delete_character_record(slug, char_name)
    _active_campaign = db.get_campaign_dict(slug)
