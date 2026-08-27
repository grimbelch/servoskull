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
        "name": "whfrp_manage_npc",
        "description": "Find, create, or update an NPC in the campaign. Use this to actively track changing motivations, secrets, and dispositions towards the party as the game progresses.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name of the NPC"},
                "role_career": {"type": "string", "description": "NPC's role or career (optional)"},
                "disposition": {"type": "string", "description": "General disposition (Friendly, Neutral, Hostile, etc.)"},
                "party_disposition": {"type": "string", "description": "Specific disposition towards the party"},
                "motivations_goals": {"type": "string", "description": "Current motivations and goals"},
                "secrets_lore": {"type": "string", "description": "Hidden GM secrets about the NPC"},
                "notes": {"type": "string", "description": "General notes"},
                "status": {"type": "string", "description": "Alive, Dead, Missing, etc."}
            },
            "required": ["name"]
        }
    },
    {
        "name": "whfrp_manage_location",
        "description": "Find, create, or update a location in the campaign. Use this to track history of what happened at this site.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name of the Location"},
                "type": {"type": "string", "description": "City, Town, Inn, Dungeon, etc."},
                "region": {"type": "string", "description": "The Reikland, etc."},
                "description": {"type": "string", "description": "Physical description"},
                "history": {"type": "string", "description": "Chronicle of what the players did here or historical lore"},
                "danger_level": {"type": "string", "description": "Low, Medium, High"}
            },
            "required": ["name"]
        }
    },
    {
        "name": "whfrp_log_timeline_event",
        "description": "Log a major chronological event into the campaign timeline. Use this to permanently record key milestones, battles, or plot reveals.",
        "input_schema": {
            "type": "object",
            "properties": {
                "event_summary": {"type": "string", "description": "Summary of the event"},
                "in_game_date": {"type": "string", "description": "Optional: In-game date (e.g. '2502 IC')"}
            },
            "required": ["event_summary"]
        }
    },
    {
        "name": "whfrp_combat_start",
        "description": "Initialize a new WFRP combat encounter. Pass a list of combatants with their initiative values. This sets up the turn tracker.",
        "input_schema": {
            "type": "object",
            "properties": {
                "encounter_name": {"type": "string"},
                "combatants": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "initiative": {"type": "integer"},
                            "wounds_max": {"type": "integer"},
                            "is_npc": {"type": "boolean"}
                        }
                    }
                }
            },
            "required": ["combatants"]
        }
    },
    {
        "name": "whfrp_combat_status",
        "description": "Get the current turn and status of all combatants in the active encounter (Wounds, Advantage, Conditions). Call this before making tactical decisions.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "whfrp_combat_update",
        "description": "Update a combatant's status (apply damage, change advantage, or set conditions) and/or advance to the next turn.",
        "input_schema": {
            "type": "object",
            "properties": {
                "target_name": {"type": "string", "description": "Name of combatant to update"},
                "wounds_change": {"type": "integer", "description": "Negative for damage, positive for healing"},
                "advantage_set": {"type": "integer", "description": "New advantage value"},
                "conditions": {"type": "string", "description": "Current conditions (e.g. 'Bleeding', 'Stunned')"},
                "advance_turn": {"type": "boolean", "description": "Set to true to advance to the next combatant's turn"}
            }
        }
    },
    {
        "name": "whfrp_resolve_attack",
        "description": "Calculate exact WFRP 4E combat damage based on attacker SL, defender SL, weapon damage, SB, TB, and AP.",
        "input_schema": {
            "type": "object",
            "properties": {
                "attacker_sl": {"type": "integer"},
                "defender_sl": {"type": "integer"},
                "weapon_damage": {"type": "integer"},
                "attacker_sb": {"type": "integer", "description": "Attacker's Strength Bonus (0 for ranged)"},
                "defender_tb": {"type": "integer", "description": "Defender's Toughness Bonus"},
                "defender_ap": {"type": "integer", "description": "Defender's Armour Points on the hit location"},
                "is_melee": {"type": "boolean", "description": "True if melee attack, False if ranged"}
            },
            "required": ["attacker_sl", "defender_sl", "weapon_damage", "attacker_sb", "defender_tb", "defender_ap"]
        }
    },
    {
        "name": "whfrp_load_scene",
        "description": "Load a scene from the adventure module and mark it as the party's current location in the story. Returns the book's text for that section, the NPCs present, and the sub-scenes you can move to next. Call with no section_id to resume where the party left off.",
        "input_schema": {
            "type": "object",
            "properties": {
                "section_id": {"type": "integer", "description": "Section to load, from whfrp_lookup_module or whfrp_search_module. Omit to resume the current scene."},
                "slug": {"type": "string", "description": "Module slug, used when resuming. Defaults to the campaign's module."}
            },
            "required": []
        }
    },
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
            "required": ["query"]
        }
    },
    {
        "name": "whfrp_lookup_equipment",
        "description": "Look up official WFRP 4E equipment statistics from the SQLite Consumer's Guide database (Armour, Weapons, Containers, Tools, Clothing, Provisions, Books, Animals, Drugs, Trade Goods).",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The name of the item or equipment category to look up (e.g. 'Leather Jack', 'Crossbow', 'Backpack', 'Antitoxin Kit', 'Bugman's Ale')."}
            },
            "required": ["query"]
        }
    },
    {
        "name": "whfrp_lookup_character",
        "description": "Query the campaign database for a character's detailed sheet: characteristics, max/current wounds, AP per body location, equipped weapons, specific weapon names, weapon qualities/flaws, equipped trappings, carried inventory, skills, talents, and spells.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Character name to inspect (e.g. 'Tayla', 'Tayla Buttersnack')."
                }
            },
            "required": ["name"]
        }
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
                "age": {"type": "integer", "description": "Character age in years."},
                "height": {"type": "string", "description": "Character height string e.g. '5\\'9\"' or '3\\'6\"'."},
                "eye_color": {"type": "string", "description": "Eye colour."},
                "hair_color": {"type": "string", "description": "Hair colour."},
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
    },
    {
        "name": "get_class_trappings",
        "description": "Retrieve default Class Trappings for a WFRP 4E class (Academics, Burghers, Courtiers, Peasants, Rangers, Riverfolk, Rogues, Warriors).",
        "input_schema": {
            "type": "object",
            "properties": {
                "class_name": {
                    "type": "string",
                    "description": "Class name: 'Academics', 'Burghers', 'Courtiers', 'Peasants', 'Rangers', 'Riverfolk', 'Rogues', or 'Warriors'."
                }
            },
            "required": ["class_name"]
        }
    },
    {
        "name": "roll_starting_wealth",
        "description": "Roll starting wealth based on character's Status Tier ('Brass', 'Silver', 'Gold') and Status Level (1-5) per WFRP 4E Core Rulebook p.37 table (e.g. Brass 3 = 6d10 Brass Pennies, Silver 2 = 2d10 Silver Shillings, Gold 1 = 1 Gold Crown).",
        "input_schema": {
            "type": "object",
            "properties": {
                "status_tier": {
                    "type": "string",
                    "description": "Status Tier: 'Brass', 'Silver', or 'Gold'."
                },
                "status_level": {
                    "type": "integer",
                    "description": "Status Level number (e.g. 1, 2, 3, 4, 5)."
                }
            },
            "required": ["status_tier", "status_level"]
        }
    },
    {
        "name": "roll_physical_details",
        "description": "Roll random physical details (Age, Height, Eye Colour, Hair Colour) for a WFRP species per Rulebook p.39-40 tables.",
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
    },
    {
        "name": "whfrp_lookup_module",
        "description": "Look up an adventure module: its chapters, or one chapter's plots, timed events and NPCs, so that you can run the adventure and understand the chronological timeline.",
        "input_schema": {
            "type": "object",
            "properties": {
                "slug": {"type": "string", "description": "The slug of the module, e.g. rough-nights-and-hard-days"},
                "chapter": {"type": "string", "description": "Chapter title or 1-based number. If omitted, returns an overview of the whole module."}
            },
            "required": ["slug"]
        }
    },
    {
        "name": "whfrp_search_module",
        "description": "Full-text search the adventure module for a name, place, plot or rule, returning the matching sections and NPCs with page numbers. Use this when a player asks about something and you need the book's exact wording.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Words to search for, e.g. 'Glimbrin Oddsocks' or 'trapdoor cellar'"},
                "slug": {"type": "string", "description": "Restrict to one module by slug."},
                "limit": {"type": "integer", "description": "Maximum results, default 8."}
            },
            "required": ["query"]
        }
    },
    {
        "name": "whfrp_read_section",
        "description": "Read the full text of one module section by its id, as returned by whfrp_search_module or whfrp_lookup_module. Use this to get the book's complete description of a room, plot or event.",
        "input_schema": {
            "type": "object",
            "properties": {
                "section_id": {"type": "integer", "description": "The section id."}
            },
            "required": ["section_id"]
        }
    },
    {
        "name": "whfrp_show_module_image",
        "description": "Broadcast an image from a module to the player's web interface or ocular display. Use this to show players handouts, maps, or NPC portraits.",
        "input_schema": {
            "type": "object",
            "properties": {
                "image_path": {"type": "string", "description": "The path to the image, returned by whfrp_lookup_module or stored in module data."}
            },
            "required": ["image_path"]
        }
    },
    {
        "name": "whfrp_map_key",
        "description": "Look up what the numbered locations on a module map are. Call with no arguments to list every map and its numbered rooms. Give 'key' to answer a question like 'what is room 24?'. Give 'map' to narrow the search to one map by name, caption or page number.",
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "A callout number printed on the map, e.g. '24'."},
                "map": {"type": "string", "description": "Map name, caption fragment, or page number to restrict the lookup to."}
            },
            "required": []
        }
    }
]

def _tool_whfrp_manage_npc(i):
    active = _campaign.get_active_campaign()
    if not active:
        return {"error": "No active campaign. Call start_campaign first."}
    slug = active.get("slug")
    # See if NPC exists
    from . import db
    camp = db.get_campaign_dict(slug)
    if not camp:
        return {"error": "Campaign not found in DB."}
    
    existing = None
    for n in camp.get("npcs", []):
        if n["name"].lower() == i["name"].lower():
            existing = n
            break
            
    npc_dict = existing.copy() if existing else {}
    for k in ["name", "role_career", "disposition", "party_disposition", "motivations_goals", "secrets_lore", "notes", "status"]:
        if k in i:
            npc_dict[k] = i[k]
            
    db.upsert_npc(slug, npc_dict)
    _campaign.reload_active()
    return {"status": "success", "message": f"Updated NPC {i['name']}"}

def _tool_whfrp_manage_location(i):
    active = _campaign.get_active_campaign()
    if not active:
        return {"error": "No active campaign. Call start_campaign first."}
    slug = active.get("slug")
    from . import db
    camp = db.get_campaign_dict(slug)
    if not camp:
        return {"error": "Campaign not found in DB."}
        
    existing = None
    for l in camp.get("locations", []):
        if l["name"].lower() == i["name"].lower():
            existing = l
            break
            
    loc_dict = existing.copy() if existing else {}
    for k in ["name", "type", "region", "description", "history", "danger_level"]:
        if k in i:
            loc_dict[k] = i[k]
            
    db.upsert_location(slug, loc_dict)
    _campaign.reload_active()
    return {"status": "success", "message": f"Updated Location {i['name']}"}

def _tool_whfrp_log_timeline_event(i):
    active = _campaign.get_active_campaign()
    if not active:
        return {"error": "No active campaign. Call start_campaign first."}
    slug = active.get("slug")
    from . import db
    db.add_timeline_event(slug, i["event_summary"], i.get("in_game_date", ""))
    _campaign.reload_active()
    return {"status": "success", "message": "Event logged to timeline."}
def _tool_whfrp_rules(i):
    query = i.get("query", "")
    print(f"[skull] Looking up WFRP 4E rules: {query}")
    from core import display
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
    try:
        from core import brain
        brain.set_current_game(name)
    except Exception:
        pass
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
        "age": i.get("age", None),
        "height": i.get("height", ""),
        "eye_color": i.get("eye_color", ""),
        "hair_color": i.get("hair_color", ""),
        "money": i.get("money", {"gc": 0, "ss": 0, "bp": 0}),
        "ambitions": i.get("ambitions", {"short": "", "long": "", "party": ""}),
        "ten_questions": i.get("ten_questions", {
            "origin": "", "family": "", "childhood": "", "why_leave": "", "friends": "",
            "desire": "", "memories": "", "religion": "", "loyalty": "", "secret": ""
        }),
        "xp": i.get("xp", 0),
        "xp_spent": i.get("xp_spent", 0),
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


def _tool_get_class_trappings(i):
    class_name = i.get("class_name", "").strip()
    trappings = _campaign.get_class_trappings(class_name)
    if not trappings:
        return f"Unknown class name '{class_name}'. Available: Academics, Burghers, Courtiers, Peasants, Rangers, Riverfolk, Rogues, Warriors."
    return f"Class Trappings for {class_name.capitalize()}:\n  - " + "\n  - ".join(trappings)


def _tool_roll_starting_wealth(i):
    tier = i.get("status_tier", "Brass")
    level = int(i.get("status_level", 1))
    res = _campaign.roll_starting_wealth(tier, level)
    return f"Starting Wealth ({res['status_tier']} {res['status_level']}): {res['summary']}"


def _tool_roll_physical_details(i):
    race = i.get("race", "human").strip()
    res = _campaign.roll_physical_details(race)
    return f"Physical Details ({res['race_key']}): {res['summary']}"




def _tool_whfrp_lookup_character(i):
    name_query = i.get("name", "").strip().lower()
    active = _campaign.get_active_campaign()
    if not active:
        return "No active campaign database."
    chars = active.get("characters", [])
    matched = None
    for c in chars:
        if name_query in c.get("name", "").lower():
            matched = c
            break
    if not matched:
        c_names = [c.get("name") for c in chars]
        return f"Character '{name_query}' not found in active campaign. Party roster: {', '.join(c_names)}"

    lines = [f"=== CHARACTER SHEET: {matched.get('name')} ==="]
    lines.append(f"Species: {matched.get('race')} | Class: {matched.get('class')} | Career: {matched.get('career')} (Level {matched.get('career_level')})")
    lines.append(f"Status: {matched.get('status')} | Age: {matched.get('age')} | Height: {matched.get('height')}")

    w = matched.get("wounds", {})
    lines.append(f"Wounds: {w.get('current', '?')}/{w.get('max', '?')} | Fate: {matched.get('fate',{}).get('total','?')} | Fortune: {matched.get('fortune',{}).get('current','?')}")

    # Weapons
    weaps = matched.get("weapons", [])
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
        lines.append("Equipped Weapons:\n  - " + "\n  - ".join(w_lines))
    else:
        lines.append("Equipped Weapons: None")

    # Trappings
    traps = matched.get("trappings", [])
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
        lines.append(f"Equipped Trappings: {', '.join(t_eq) or 'None'}")
        lines.append(f"Carried Inventory: {', '.join(t_car) or 'None'}")

    # Armour Points
    arm = matched.get("armour", {})
    if isinstance(arm, dict) and arm:
        lines.append(f"Armour Points (AP): Head {arm.get('head',0)}, Body {arm.get('body',0)}, Left Arm {arm.get('l_arm',0)}, Right Arm {arm.get('r_arm',0)}, Left Leg {arm.get('l_leg',0)}, Right Leg {arm.get('r_leg',0)}, Shield {arm.get('shield',0)}")

    # Skills & Talents
    skills = matched.get("skills", [])
    if skills:
        lines.append("Skills: " + ", ".join([s if isinstance(s, str) else s.get("name","") for s in skills[:12]]))
    talents = matched.get("talents", [])
    if talents:
        lines.append("Talents: " + ", ".join([t if isinstance(t, str) else t.get("name","") for t in talents]))

    return "\n".join(lines)

def _tool_whfrp_lookup_equipment(i):
    query = i.get("query", "").strip()
    if not query:
        return "Please specify an item name or category to look up."
    
    from . import db
    armours = db.get_armour_catalog()
    matched_armour = [a for a in armours if query.lower() in a["name"].lower() or a["name"].lower() in query.lower()]
    
    weapons = db.get_weapons_catalog()
    matched_weapons = [w for w in weapons if query.lower() in w["name"].lower() or w["name"].lower() in query.lower()]
    
    trappings = db.get_trappings_catalog()
    matched_trappings = [t for t in trappings if query.lower() in t["name"].lower() or t["name"].lower() in query.lower() or query.lower() in t["category"].lower()]
    
    results = []
    for a in matched_armour:
        results.append(f"ARMOUR: {a['name']} ({a['category']}) | Cost: {a['price']} | Enc: {a['encumbrance']} | Avail: {a['availability']} | AP: {a['ap']} ({a['locations']}) | Penalty: {a['penalty']} | Qualities: {a['qualities']}")
    for w in matched_weapons:
        results.append(f"WEAPON: {w['name']} ({w['group_name']}) | Cost: {w['price']} | Enc: {w['encumbrance']} | Avail: {w['availability']} | Reach/Range: {w['reach_range']} | Damage: {w['damage']} | Qualities: {w['qualities']}")
    for t in matched_trappings:
        results.append(f"TRAPPING: {t['name']} ({t['category']}) | Cost: {t['price']} | Enc: {t['encumbrance']} | Avail: {t['availability']} | Carries: {t['carries'] or 'N/A'} | Info: {t['description']}")
        
    if not results:
        return f"No official Consumer's Guide equipment entry found matching '{query}' in the database."
    return "\n".join(results[:10])



def _tool_whfrp_combat_start(i):
    from . import combat
    c_id = _campaign.get_active_campaign().get("id") if _campaign.get_active_campaign() else 1
    enc_name = i.get("encounter_name", "Combat")
    combatants = i.get("combatants", [])
    return combat.start_combat(c_id, enc_name, combatants)

def _tool_whfrp_combat_status(i):
    from . import combat
    c_id = _campaign.get_active_campaign().get("id") if _campaign.get_active_campaign() else 1
    return combat.get_combat_status(c_id)

def _tool_whfrp_combat_update(i):
    from . import combat
    c_id = _campaign.get_active_campaign().get("id") if _campaign.get_active_campaign() else 1
    res = []
    target = i.get("target_name")
    if target:
        res.append(combat.update_combatant(
            c_id, target, 
            i.get("wounds_change", 0), 
            i.get("advantage_set"), 
            i.get("conditions")
        ))
    if i.get("advance_turn"):
        res.append(combat.next_turn(c_id))
    return "\n".join(res) if res else "No updates made."

def _tool_whfrp_resolve_attack(i):
    from . import combat
    return combat.calculate_attack(
        int(i.get("attacker_sl", 0)),
        int(i.get("defender_sl", 0)),
        int(i.get("weapon_damage", 0)),
        int(i.get("attacker_sb", 0)),
        int(i.get("defender_tb", 0)),
        int(i.get("defender_ap", 0)),
        bool(i.get("is_melee", True))
    )



def _tool_whfrp_load_scene(i):
    """Move the party to a section of the module and return it as a playable scene."""
    from . import db, modules_db
    active = _campaign.get_active_campaign()
    if not active:
        return {"error": "No active campaign. Call start_campaign first."}
    campaign_id = active["id"]
    section_id = i.get("section_id")

    conn = db.get_connection()
    try:
        if not section_id:
            resumed = conn.execute(
                "SELECT current_section_id FROM campaign_modules WHERE campaign_id = ?"
                " ORDER BY id DESC LIMIT 1",
                (campaign_id,),
            ).fetchone()
            section_id = resumed["current_section_id"] if resumed else None
        if not section_id:
            return {"error": "No current scene. Pass a section_id from whfrp_lookup_module."}

        row = conn.execute(
            "SELECT * FROM module_sections WHERE id = ?", (section_id,)
        ).fetchone()
        if not row:
            return {"error": f"Section {section_id} not found."}
        section = dict(row)

        children = [
            dict(child)
            for child in conn.execute(
                "SELECT id, title, kind, page_start FROM module_sections"
                " WHERE parent_id = ? ORDER BY doc_order",
                (section_id,),
            ).fetchall()
        ]
        npcs = [
            dict(npc)
            for npc in conn.execute(
                "SELECT n.id, n.name, n.title, n.faction FROM module_npcs n"
                "  JOIN module_npc_appearances a ON a.npc_id = n.id"
                " WHERE a.section_id = ?",
                (section_id,),
            ).fetchall()
        ]
        assets = [
            dict(asset)
            for asset in conn.execute(
                "SELECT id, kind, path, caption FROM module_assets"
                " WHERE section_id = ? OR (kind = 'map' AND page BETWEEN ? AND ?)",
                (section_id, section["page_start"], section["page_end"]),
            ).fetchall()
        ]

        # Remember where the party is so the next call can resume without an id.
        conn.execute(
            "UPDATE campaign_modules SET current_section_id = ?"
            "  WHERE campaign_id = ? AND module_id ="
            "        (SELECT module_id FROM module_sections WHERE id = ?)",
            (section_id, campaign_id, section_id),
        )
        conn.commit()
    finally:
        conn.close()

    modules_db.set_section_state(campaign_id, section_id, status="active", revealed=True)

    return {
        "section_id": section["id"],
        "title": section["title"],
        "kind": section["kind"],
        "pages": [section["page_start"], section["page_end"]],
        "text": section["body_md"],
        "npcs_present": npcs,
        "images": assets,
        "next_scenes": children,
    }


def _tool_whfrp_lookup_module(i):
    slug = i.get("slug")
    wanted = i.get("chapter")
    from . import modules_db
    mod = modules_db.get_module(slug)
    if not mod:
        return {"error": f"Module {slug} not found."}

    chapters = mod.get("chapters", [])
    if wanted not in (None, ""):
        chapter = None
        if str(wanted).isdigit() and 1 <= int(wanted) <= len(chapters):
            chapter = chapters[int(wanted) - 1]
        else:
            needle = str(wanted).lower()
            chapter = next(
                (c for c in chapters if needle in c["title"].lower()), None
            )
        if not chapter:
            return {"error": f"Chapter {wanted!r} not found in {slug}."}
        return {
            "chapter": {
                "id": chapter["id"],
                "title": chapter["title"],
                "pages": [chapter["page_start"], chapter["page_end"]],
                "summary": chapter.get("body_md", "")[:2000],
            },
            "plots": [
                {"number": p["plot_number"], "title": p["title"],
                 "description": p["description"], "page": p["page"]}
                for p in chapter.get("plots", [])
            ],
            # Already ordered along the in-fiction timeline, including the
            # rollover past midnight into the next morning.
            "timeline": [
                {"id": e["id"], "time": e["time_label"],
                 "description": e["description"], "page": e["page"]}
                for e in chapter.get("events", [])
            ],
            "npcs": [
                {"id": n["id"], "name": n["name"], "title": n["title"],
                 "faction": n["faction"], "page": n["page"]}
                for n in chapter.get("npcs", [])
            ],
        }

    return {
        "title": mod.get("title"),
        "slug": mod.get("slug"),
        "pages": mod.get("page_count"),
        "chapters": [
            {"number": index + 1, "id": c["id"], "title": c["title"],
             "pages": [c["page_start"], c["page_end"]]}
            for index, c in enumerate(chapters)
        ],
        "maps": [
            {"caption": a["caption"], "page": a["page"], "path": a["path"]}
            for a in mod.get("maps", [])
        ],
        "npc_count": len(mod.get("npcs", [])),
    }


def _tool_whfrp_search_module(i):
    from . import modules_db
    query = (i.get("query") or "").strip()
    if not query:
        return {"error": "A query is required."}
    module_id = None
    if i.get("slug"):
        mod = modules_db.get_module(i["slug"])
        if not mod:
            return {"error": f"Module {i['slug']} not found."}
        module_id = mod["id"]
    results = modules_db.search_module(query, module_id, int(i.get("limit") or 8))
    if not results:
        return {"results": [], "message": f"Nothing in the module matches {query!r}."}
    return {"results": results}


def _tool_whfrp_read_section(i):
    from . import db as _db
    conn = _db.get_connection()
    try:
        row = conn.execute(
            "SELECT id, title, kind, body_md, page_start, page_end"
            "  FROM module_sections WHERE id = ?",
            (i.get("section_id"),),
        ).fetchone()
        if not row:
            return {"error": "Section not found."}
        section = dict(row)
        section["children"] = [
            dict(child)
            for child in conn.execute(
                "SELECT id, title, kind, page_start FROM module_sections"
                " WHERE parent_id = ? ORDER BY doc_order",
                (section["id"],),
            ).fetchall()
        ]
        return section
    finally:
        conn.close()


def _tool_whfrp_show_module_image(i):
    img = i.get("image_path")
    if not img:
        return {"error": "image_path is required"}
    from pathlib import Path
    img_path = Path(__file__).resolve().parent.parent.parent / img.lstrip("/")
    if not img_path.exists():
        return {"error": "Image not found"}

    from core import web
    web._command_queue.put({"type": "show_image", "url": img})
    return {"status": "success", "message": f"Image {img} broadcasted to players.", "url": img}



def _tool_whfrp_map_key(i):
    """Translate the numbered circles printed on a module map into room names."""
    from . import db as _db

    key = str(i.get("key") or "").strip()
    map_hint = str(i.get("map") or "").strip()

    sql = [
        "SELECT k.key_label, k.label, k.detail, k.section_id,",
        "       a.caption, a.page, a.path",
        "  FROM module_map_keys k",
        "  JOIN module_assets a ON a.id = k.asset_id",
        " WHERE 1 = 1",
    ]
    params = []
    if key:
        sql.append("   AND k.key_label = ?")
        params.append(key)
    if map_hint:
        if map_hint.isdigit():
            sql.append("   AND a.page = ?")
            params.append(int(map_hint))
        else:
            sql.append("   AND LOWER(a.caption) LIKE ?")
            params.append(f"%{map_hint.lower()}%")
    sql.append(" ORDER BY a.page, CAST(k.key_label AS INTEGER), k.key_label")

    conn = _db.get_connection()
    try:
        rows = [dict(r) for r in conn.execute("\n".join(sql), params).fetchall()]
    finally:
        conn.close()

    if not rows:
        if key:
            return {"error": f"No map callout numbered {key!r} was found."}
        return {"error": "No map keys are available for the loaded module."}

    maps: dict[int, dict] = {}
    for row in rows:
        entry = maps.setdefault(
            row["page"],
            {"map": row["caption"], "page": row["page"],
             "image_path": row["path"], "keys": []},
        )
        entry["keys"].append(
            {
                "key": row["key_label"],
                "label": row["label"],
                "detail": row["detail"] or "",
                "section_id": row["section_id"],
            }
        )
    return {"maps": list(maps.values())}


HANDLERS = {
    "whfrp_load_scene": _tool_whfrp_load_scene,
    "whfrp_combat_start": _tool_whfrp_combat_start,
    "whfrp_combat_status": _tool_whfrp_combat_status,
    "whfrp_combat_update": _tool_whfrp_combat_update,
    "whfrp_resolve_attack": _tool_whfrp_resolve_attack,
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
    "get_class_trappings": _tool_get_class_trappings,
    "roll_starting_wealth": _tool_roll_starting_wealth,
    "roll_physical_details": _tool_roll_physical_details,
    "whfrp_lookup_character": _tool_whfrp_lookup_character,
    "whfrp_lookup_equipment": _tool_whfrp_lookup_equipment,
    "whfrp_lookup_module": _tool_whfrp_lookup_module,
    "whfrp_show_module_image": _tool_whfrp_show_module_image,
    "whfrp_search_module": _tool_whfrp_search_module,
    "whfrp_read_section": _tool_whfrp_read_section,
    "whfrp_map_key": _tool_whfrp_map_key,
}


# Foundry VTT bridge. Only contributes tools when FOUNDRY_MCP_ENABLED is set,
# so a table running purely off the offline rules database is unaffected.
try:
    from . import foundry as _foundry

    if _foundry.TOOLS:
        TOOLS.extend(_foundry.TOOLS)
        HANDLERS.update(_foundry.HANDLERS)
        SLOW_TOOLS.update(_foundry.SLOW_TOOLS)
except Exception:  # pragma: no cover - never block game start on the bridge
    import logging

    logging.getLogger(__name__).exception("Foundry bridge unavailable; continuing without it")
