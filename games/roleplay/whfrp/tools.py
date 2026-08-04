"""WFRP 4E tool definitions, schemas, and execution handlers."""
from __future__ import annotations

from . import campaign as _campaign
from . import search as _search

SLOW_TOOLS = {
    "whfrp_rules",
    "start_campaign",
    "save_campaign_state",
    "roll_character_stats",
    "save_character",
    "get_species_info",
}

TOOLS = [
    {
        "name": "whfrp_rules",
        "description": (
            "Look up Warhammer Fantasy Roleplay 4th Edition (WFRP 4E) rules from the local offline "
            "rules library — the full Core Rulebook and the Quick Reference guide. Use for ANY "
            "WFRP 4E question: characteristics and tests, Success Levels (SL), opposed/extended tests, "
            "combat (hit locations, damage, criticals, Advantage), careers and advances, skills and "
            "talents, fate/fortune/resilience points, corruption/mutation, magic and spells, "
            "bestiary entries, travel/encumbrance, social encounters, and all other mechanics. "
            "Always call this tool before ruling on any WFRP mechanic rather than relying on memory. "
            "IMPORTANT: When searching for a career's starting skills, talents, or trappings, ALWAYS include "
            "the specific career name in your query (e.g. 'Scout career skills talents trappings' or "
            "'Apothecary career skills'). Generic queries like 'starting skills' without the career name "
            "will return general chapter overviews instead of the specific career page."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Rule, mechanic, career, spell, creature, or topic to look up (e.g. 'characteristic test', 'hit location table', 'Warrior career', 'Fireball spell', 'Troll')",
                }
            },
            "required": ["query"],
        },
    },
    {
        "name": "roll_whfrp_dice",
        "description": (
            "Roll dice for WFRP 4E (d100 percentile, d10, d6, d4). Use for NPC/monster characteristic "
            "tests, attack rolls, damage, critical hits, spellcasting, random tables, and event outcomes. "
            "Pass die_type ('d100', 'd10', 'd6', 'd4') and optionally target characteristic value to compute "
            "Success Levels (SL = characteristic//10 - roll//10)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "die_type": {
                    "type": "string",
                    "description": "Die type: 'd100' (default), 'd10', 'd6', 'd4'.",
                },
                "count": {
                    "type": "integer",
                    "description": "Number of dice to roll (default 1).",
                },
                "characteristic": {
                    "type": "integer",
                    "description": "Optional: Target characteristic value to test against (e.g. 45 for WS 45).",
                },
                "modifier": {
                    "type": "integer",
                    "description": "Optional: Test difficulty modifier to add to characteristic (e.g. +20 or -10).",
                },
                "label": {
                    "type": "string",
                    "description": "Optional: Description of what is being rolled (e.g. 'Goblin Weapon Skill test').",
                },
            },
        },
    },
    {
        "name": "start_campaign",
        "description": (
            "Start a new named WFRP 4E RPG campaign or resume an existing one by name. "
            "Sets the campaign as the active session in memory and returns a summary of characters, "
            "current location, scene description, and recent session notes. Call at the start of any WFRP session."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "campaign_name": {
                    "type": "string",
                    "description": "The name of the campaign to start or resume (e.g. 'The Enemy Within', 'Ubersreik Adventures')."
                },
                "character_name": {
                    "type": "string",
                    "description": "Optional: Player character name if starting a new campaign."
                },
                "character_race": {
                    "type": "string",
                    "description": "Optional: Player character race if starting a new campaign."
                },
                "character_career": {
                    "type": "string",
                    "description": "Optional: Player character career if starting a new campaign."
                }
            },
            "required": ["campaign_name"]
        }
    },
    {
        "name": "list_campaigns",
        "description": "List all saved WFRP RPG campaigns with their last modified dates and character names.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "get_campaign_state",
        "description": "Read the current state of the active WFRP campaign: character info, current location, scene description, active NPCs, and recent session notes.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "save_campaign_state",
        "description": (
            "Save GM notes or update the active campaign's state. Use to persist important events: "
            "scene changes, NPC interactions, wounds taken, fate points spent, decisions made."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "note": {
                    "type": "string",
                    "description": "A session note to append."
                },
                "field": {
                    "type": "string",
                    "description": "Optional: A specific campaign field to update."
                },
                "value": {
                    "type": "string",
                    "description": "Optional: The new value for the specified field."
                }
            }
        }
    },
    {
        "name": "roll_character_stats",
        "description": (
            "Roll starting characteristics and calculate derived attributes (Wounds, Movement, Fate, Fortune, "
            "Resilience, Resolve) for a new WFRP 4E character of a given species/race ('human', 'dwarf', 'halfling', 'high_elf', 'wood_elf')."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "race": {
                    "type": "string",
                    "description": "The chosen species/race: 'human', 'dwarf', 'halfling', 'high_elf', or 'wood_elf'."
                }
            },
            "required": ["race"]
        }
    },
    {
        "name": "save_character",
        "description": (
            "Save a fully created or updated player character to the active WFRP campaign. "
            "Persists character name, race, career, career level, characteristic scores, max/current wounds, "
            "fate/fortune, resilience/resolve, movement, skills, talents, trappings, and XP."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Character name."},
                "race": {"type": "string", "description": "Character species/race."},
                "career": {"type": "string", "description": "Character career."},
                "career_level": {"type": "string", "description": "Optional: Career level title e.g. 'Guide (Brass 3)'."},
                "characteristics": {"type": "object", "description": "Dict of characteristics e.g. {'WS': 35}."},
                "wounds_max": {"type": "integer", "description": "Maximum wound total."},
                "fate": {"type": "integer", "description": "Starting Fate points."},
                "fortune": {"type": "integer", "description": "Starting Fortune points."},
                "resilience": {"type": "integer", "description": "Starting Resilience points."},
                "resolve": {"type": "integer", "description": "Starting Resolve points."},
                "move": {"type": "integer", "description": "Movement score."},
                "skills": {"type": "array", "items": {"type": "string"}, "description": "List of starting skills."},
                "talents": {"type": "array", "items": {"type": "string"}, "description": "List of starting talents."},
                "trappings": {"type": "array", "items": {"type": "string"}, "description": "List of starting equipment."},
                "xp": {"type": "integer", "description": "Starting experience points."}
            },
            "required": ["name", "race", "career"]
        }
    },
    {
        "name": "roll_random_talent",
        "description": "Roll 1 or more times on the official WFRP 4E Random Talent Table (d100) during character creation.",
        "input_schema": {
            "type": "object",
            "properties": {
                "count": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 5,
                    "description": "Number of random talent rolls to make (default 1)."
                }
            }
        }
    },
    {
        "name": "get_species_info",
        "description": "Retrieve species skills list, species talent options, and random talent roll count for a given WFRP species.",
        "input_schema": {
            "type": "object",
            "properties": {
                "race": {
                    "type": "string",
                    "description": "Species key: 'human', 'dwarf', 'halfling', 'high_elf', or 'wood_elf'."
                }
            },
            "required": ["race"]
        }
    }
]


def _tool_whfrp_rules(i):
    query = i.get("query", "")
    print(f"[skull] Looking up WFRP 4E rules: {query}")
    from skull import display
    display.start_rules_lookup()
    try:
        return _search.whfrp_rules(query)
    finally:
        display.stop_rules_lookup()


def _tool_roll_whfrp_dice(i):
    import random
    die_type = i.get("die_type", "d100")
    count = max(1, int(i.get("count", 1)))
    characteristic = i.get("characteristic")
    modifier = int(i.get("modifier", 0))
    label = i.get("label", "")

    if die_type == "d100":
        rolls = [random.randint(1, 100) for _ in range(count)]
        lines = []
        for roll in rolls:
            prefix = f"{label}: " if label else ""
            if characteristic is not None:
                effective = max(1, min(100, int(characteristic) + modifier))
                sl_raw = (effective // 10) - (roll // 10)
                if roll <= effective:
                    outcome = f"SUCCESS (SL +{sl_raw})"
                else:
                    outcome = f"FAILURE (SL {sl_raw})"
                mod_str = f" (modified {effective})" if modifier != 0 else ""
                lines.append(f"{prefix}Rolled {roll} vs {characteristic}{mod_str} \u2192 {outcome}")
            else:
                lines.append(f"{prefix}Rolled {roll}")
        return "\n".join(lines)
    elif die_type == "d10":
        rolls = [random.randint(1, 10) for _ in range(count)]
        return f"d10 \u00d7 {count}: {rolls} (total {sum(rolls)})"
    elif die_type == "d6":
        rolls = [random.randint(1, 6) for _ in range(count)]
        return f"d6 \u00d7 {count}: {rolls} (total {sum(rolls)})"
    elif die_type == "d4":
        rolls = [random.randint(1, 4) for _ in range(count)]
        return f"d4 \u00d7 {count}: {rolls} (total {sum(rolls)})"
    return f"Unknown die type: {die_type}"


def _tool_start_campaign(i):
    name = i.get("campaign_name", "").strip()
    if not name:
        return "Error: campaign_name is required."
    existing = _campaign.load_campaign(name)
    if existing:
        summary = _campaign.campaign_summary(existing)
        return f"Resumed existing campaign.\n{summary}"
    char_name = i.get("character_name", "")
    char_race = i.get("character_race", "")
    char_career = i.get("character_career", "")
    characters = []
    if char_name:
        characters.append({
            "name": char_name, "race": char_race, "career": char_career,
            "characteristics": {}, "wounds": {"max": 0, "current": 0},
            "fate": {"total": 0, "current": 0}, "fortune": {"total": 0, "current": 0},
            "skills": [], "talents": [], "xp": 0,
        })
    created = _campaign.new_campaign(name, adventure=name, characters=characters)
    return f"Created and started new campaign '{name}'.\n" + _campaign.campaign_summary(created)


def _tool_list_campaigns(i):
    campaigns = _campaign.list_campaigns()
    if not campaigns:
        return "No saved campaigns found. Use start_campaign to create one."
    active = _campaign.get_active_campaign()
    active_slug = active.get("slug") if active else None
    lines = []
    for c in campaigns:
        adv = f" ({c['adventure']})" if c.get("adventure") else ""
        chars = ", ".join(c.get("characters", [])) or "None"
        is_act = " [ACTIVE]" if c["slug"] == active_slug else ""
        lines.append(f"- {c['name']}{adv}{is_act} | Characters: {chars}")
    return "Saved campaigns:\n" + "\n".join(lines)


def _tool_get_campaign_state(i):
    active = _campaign.get_active_campaign()
    if not active:
        return "No active campaign. Use start_campaign to begin or resume one."
    return _campaign.campaign_summary(active)


def _tool_save_campaign_state(i):
    active = _campaign.get_active_campaign()
    if not active:
        return "No active campaign. Use start_campaign first."
    note = i.get("note", "").strip()
    field = i.get("field", "").strip()
    value = i.get("value", "").strip()
    if note:
        _campaign.add_session_note(note)
    if field and value:
        _campaign.update_field(field, value)
    if not note and not field:
        _campaign.save_campaign()
    return f"Campaign '{active['name']}' saved."


def _tool_roll_character_stats(i):
    race_input = i.get("race", "human").strip()
    race_key = _campaign.resolve_race(race_input)
    if not race_key:
        valid = ", ".join(sorted({v["display"] for v in _campaign.RACIAL_DATA.values()}))
        return f"Unknown race '{race_input}'. Valid races: {valid}"
    char_block = _campaign.roll_characteristics(race_key)
    summary = _campaign.format_characteristics_for_speech(char_block)
    return summary


def _tool_save_character(i):
    active = _campaign.get_active_campaign()
    if not active:
        return "No active campaign. Use start_campaign first, then save_character."
    name = i.get("name", "").strip()
    if not name:
        return "Error: character name is required."
    race_input = i.get("race", "").strip()
    race_key = _campaign.resolve_race(race_input) if race_input else None
    racial = _campaign.RACIAL_DATA.get(race_key, {}) if race_key else {}
    char = {
        "name": name,
        "race": i.get("race", ""),
        "career": i.get("career", ""),
        "career_level": i.get("career_level", ""),
        "characteristics": i.get("characteristics", {}),
        "wounds": {
            "max": i.get("wounds_max", 0),
            "current": i.get("wounds_max", 0),
        },
        "fate": {
            "total": i.get("fate", racial.get("fate", 0)),
            "current": i.get("fate", racial.get("fate", 0)),
        },
        "fortune": {
            "total": i.get("fortune", racial.get("fortune", 0)),
            "current": i.get("fortune", racial.get("fortune", 0)),
        },
        "resilience": i.get("resilience", racial.get("resilience", 0)),
        "resolve": i.get("resolve", racial.get("resolve", 0)),
        "move": i.get("move", racial.get("move", 4)),
        "skills": i.get("skills", []),
        "talents": i.get("talents", []),
        "trappings": i.get("trappings", []),
        "xp": i.get("xp", 0),
        "xp_spent": 0,
        "doomed": i.get("doomed", ""),
        "star_sign": i.get("star_sign", ""),
        "motivation": i.get("motivation", ""),
    }
    _campaign.upsert_character(char)
    return (f"Character '{name}' saved to campaign '{active['name']}'. "
            f"Race: {char['race']}, Career: {char['career']}, "
            f"Wounds: {char['wounds']['max']}, Fate: {char['fate']['total']}.")


def _tool_roll_random_talent(i):
    count = int(i.get("count", 1))
    return _campaign.roll_random_talent(count)


def _tool_get_species_info(i):
    race_input = i.get("race", "human").strip()
    race_key = _campaign.resolve_race(race_input)
    if not race_key:
        return f"Unknown race '{race_input}'."
    return _campaign.get_species_info(race_key)


HANDLERS = {
    "whfrp_rules": _tool_whfrp_rules,
    "roll_whfrp_dice": _tool_roll_whfrp_dice,
    "start_campaign": _tool_start_campaign,
    "list_campaigns": _tool_list_campaigns,
    "get_campaign_state": _tool_get_campaign_state,
    "save_campaign_state": _tool_save_campaign_state,
    "roll_character_stats": _tool_roll_character_stats,
    "save_character": _tool_save_character,
    "roll_random_talent": _tool_roll_random_talent,
    "get_species_info": _tool_get_species_info,
}
