from core import search as _search
from core import config
from core import display as _display
from core import candles as _candles
import random
import math
import subprocess

def get_tools():
    return [
{
        "name": "necromunda_rules",
        "description": (
            "Look up Necromunda tabletop game rules from the local offline rules library (Rules as Written). "
            "Use for any question about Necromunda mechanics, gangs, weapons, skills, "
            "injuries, campaigns, scenarios, or equipment — including the Trading Post and "
            "Black Market: item availability, rarity, cost, exclusive/illegal items, and "
            "special ammunition. Always use this tool before answering a Necromunda rules "
            "question rather than relying on memory."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Rule, mechanic, or topic to look up (e.g. 'fighter activation', 'injury roll', 'House Goliath gang list')",
                }
            },
            "required": ["query"],
        },
    },
{
        "name": "warhammer40k_rules",
        "description": (
            "Look up Warhammer 40,000 (11th edition) tabletop rules from the local rules "
            "library — the core rules, faction packs (detachments, datasheets, stratagems, "
            "enhancements, wargear, unit stats), rules updates/FAQs, and event companions. "
            "Use for any 40k question: army rules, a specific unit's profile or abilities, "
            "weapon stats, stratagems, detachment rules, points, or matched-play/tournament "
            "rules. Always use this tool before answering a 40k rules question rather than "
            "relying on memory."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Unit, rule, weapon, stratagem, or topic to look up (e.g. 'Defiler stats', 'World Eaters Brazen Engines detachment', 'Blessings of Khorne', 'Lone Operative')",
                }
            },
            "required": ["query"],
        },
    },
{
        "name": "netepic_rules",
        "description": (
            "Look up NetEpic (also called Epic 2nd Edition) tabletop game rules from the local "
            "offline rules library — the NetEpic 5.0 core rules, optional rules, and army books "
            "(Adeptus Astartes/Space Marines, Adeptus Mechanicus, Adeptus Militaris/Imperial Guard, "
            "Adeptus Ministorum, Chaos, Tyranid, Squat, Ork, Slann, Tau). Use for any NetEpic "
            "question: game phases, movement, combat, unit stats and army cards, formations, "
            "titans, weapons, points, or army list building. This is a DIFFERENT game from Net "
            "Epic Armageddon / NetEA (use netea_rules for that) — disambiguate by the keywords "
            "'2nd edition' (NetEpic) versus 'Armageddon' or '3rd edition' (NetEA). Always use this "
            "tool before answering a NetEpic / Epic 2nd Edition question rather than relying on memory."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Rule, unit, army card, weapon, or topic to look up (e.g. 'orders phase', 'Space Marine Tactical Company', 'Warlord Titan', 'close combat resolution', 'Ork Gargant')",
                }
            },
            "required": ["query"],
        },
    },
{
        "name": "netea_rules",
        "description": (
            "Look up Net Epic Armageddon (NetEA — also called 'Armageddon' or 'Epic 3rd Edition') "
            "tabletop game rules from the local offline rules library: the NetEA rules, tournament "
            "pack, FAQ, and army lists (Space Marines, Chaos, Eldar, Dark Eldar, Imperial Guard, "
            "Adeptus Mechanicus, Orks, Necrons, Tyranids, Tau, Squats, Inquisition, and their many "
            "sub-factions). Use for any NetEA question: mechanics, blast markers, army lists, "
            "formations, units, special rules, or tournament regulations. This is a DIFFERENT game "
            "from NetEpic / Epic 2nd Edition (use netepic_rules for that) — disambiguate by the "
            "keywords 'Armageddon' or '3rd edition' (NetEA) versus '2nd edition' (NetEpic). Always "
            "use this tool before answering a NetEA question rather than relying on memory."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Rule, unit, formation, or topic to look up (e.g. 'blast markers', 'Space Marine Tactical formation', 'aerospace operations', 'Ork Gargant Mob army list')",
                }
            },
            "required": ["query"],
        },
    },
{
        "name": "play_ambient_hymn",
        "description": (
            f"Play a sacred hymn / ambient music snippet from {config.SKULL_NAME}'s sacred audio archive "
            "(sounds/Music/, e.g. Hymnos Ecclesianum). Call this when the user asks to play a hymn, "
            "sacred music, binary chant, or music snippet from the archive (e.g., 'play a hymn', "
            "'sing a sacred chant', 'play Hymnos Ecclesianum')."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "track_name": {
                    "type": "string",
                    "description": "Optional specific file/track name or keyword (e.g. 'Hymnos Ecclesianum').",
                },
            },
            "required": [],
        },
    },
{
        "name": "set_candles",
        "description": (
            f"Light or extinguish the flickering candles atop {config.SKULL_NAME}. "
            "Set lit=true when the user says 'light the candles', 'candles on', "
            "'ignite the candles'. Set lit=false when the user says 'dim the candles', "
            "'douse the candles', 'put out the candles', 'candles off', 'extinguish the "
            "candles'. The candles are either fully lit or fully out — they cannot be "
            "partially dimmed, so treat 'dim' as 'extinguish'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "lit": {
                    "type": "boolean",
                    "description": "true to light the candles; false to extinguish them.",
                },
            },
            "required": ["lit"],
        },
    },
{
        "name": "roll_dice",
        "description": (
            "Simulate dice rolls for Warhammer 40k or Necromunda attacks. "
            "Runs the complete roll sequence (hits, wounds, saves, and optionally Feel No Pain) "
            "and returns a detailed step-by-step result including rerolls."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "num_dice": {
                    "type": "integer",
                    "description": "The number of attacks/dice to roll initially.",
                },
                "hit_on": {
                    "type": "integer",
                    "minimum": 2,
                    "maximum": 6,
                    "description": "The target roll required to hit (e.g. 3 for 3+).",
                },
                "wound_on": {
                    "type": "integer",
                    "minimum": 2,
                    "maximum": 6,
                    "description": "The target roll required to wound (e.g. 4 for 4+).",
                },
                "save_on": {
                    "type": "integer",
                    "minimum": 2,
                    "maximum": 6,
                    "description": "Optional: Base armour save of the target (e.g. 3 for 3+). If omitted, saves are not rolled.",
                },
                "ap": {
                    "type": "integer",
                    "description": "Optional: Armour penetration value (e.g. 2 or -2). Will be added to the required save roll.",
                },
                "invul_save": {
                    "type": "integer",
                    "minimum": 2,
                    "maximum": 6,
                    "description": "Optional: Target's invulnerable save (e.g. 4 for 4++). Will cap the save required.",
                },
                "reroll_hits": {
                    "type": "string",
                    "enum": ["none", "ones", "failed"],
                    "description": "Optional: Reroll rules for hits. Defaults to 'none'.",
                },
                "reroll_wounds": {
                    "type": "string",
                    "enum": ["none", "ones", "failed"],
                    "description": "Optional: Reroll rules for wounds. Defaults to 'none'.",
                },
                "feel_no_pain": {
                    "type": "integer",
                    "minimum": 2,
                    "maximum": 6,
                    "description": "Optional: Feel No Pain value (e.g. 5 for 5+++). Will roll for unsaved wounds.",
                },
            },
            "required": ["num_dice", "hit_on", "wound_on"],
        },
    },
{
        "name": "roll_necromunda_dice",
        "description": "Roll specialized Necromunda dice (Firepower/Ammo checks, Injury dice, Scatter dice, Location dice, or standard D6 checks).",
        "input_schema": {
            "type": "object",
            "properties": {
                "dice_type": {
                    "type": "string",
                    "enum": ["firepower", "injury", "scatter", "location", "d6"],
                    "description": "The type of specialized Necromunda die to roll."
                },
                "count": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "The number of dice to roll."
                },
                "target": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 6,
                    "description": "Optional: For D6 checks, the target number required (e.g. 4 for 4+)."
                }
            },
            "required": ["dice_type"]
        }
    },
{
        "name": "roll_standard_dice",
        "description": "Roll standard multi-sided dice (e.g. D6, D10, D20, D100) and return the individual results and sum.",
        "input_schema": {
            "type": "object",
            "properties": {
                "count": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "The number of dice to roll."
                },
                "sides": {
                    "type": "integer",
                    "minimum": 2,
                    "description": "The number of sides per die (e.g. 6 for D6, 20 for D20)."
                },
                "target": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Optional: target number to succeed (e.g. roll >= target)."
                }
            },
            "required": ["count", "sides"]
        }
    },
{
        "name": "roll_epic_dice",
        "description": "Roll dice for NetEpic (2nd edition) or NetEpic Armageddon (NetEA/3rd edition) shooting or close combat/assault resolution.",
        "input_schema": {
            "type": "object",
            "properties": {
                "system": {
                    "type": "string",
                    "enum": ["NetEpic", "NetEA"],
                    "description": "Optional: The Epic rules system to use. Defaults to the active game if not specified."
                },
                "roll_type": {
                    "type": "string",
                    "enum": ["shooting", "combat_resolution", "save", "morale"],
                    "description": "The type of roll: shooting attacks, close combat/assault resolution, armor saves, or morale tests."
                },
                "count": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "The number of dice to roll."
                },
                "to_hit": {
                    "type": "integer",
                    "minimum": 2,
                    "maximum": 6,
                    "description": "Optional: The target number required to hit (e.g. 4 for 4+)."
                },
                "save_on": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 6,
                    "description": "Optional: The required save value (e.g. 5 for 5+)."
                },
                "tsm": {
                    "type": "integer",
                    "description": "Optional (NetEpic only): Target Save Modifier (negative value, e.g. -2). Modifies the save roll."
                },
                "macro_weapon": {
                    "type": "boolean",
                    "description": "Optional (NetEA only): If true, the attack is from a macro-weapon (MW), negating standard and cover saves."
                },
                "reinforced_armour": {
                    "type": "boolean",
                    "description": "Optional (NetEA only): If true, the target has reinforced armour (allows save reroll against non-macro hits, or normal save against macro hits)."
                },
                "caf": {
                    "type": "integer",
                    "description": "Optional (NetEpic close combat only): Close Assault Factor of the combatant."
                },
                "opponent_caf": {
                    "type": "integer",
                    "description": "Optional (NetEpic close combat only): Close Assault Factor of the opponent."
                },
                "opponent_count": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Optional: For NetEpic close combat or NetEA assaults, the number of dice rolled by the opponent."
                },
                "morales": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 6,
                    "description": "Optional (Morale test only): Morale threshold required."
                }
            },
            "required": ["roll_type", "count"]
        }
    },

    ]

def _tool_necromunda_rules(i):
    query = i.get("query", "")
    print(f"[skull] Looking up Necromunda rules: {query}")
    from core import display
    display.start_rules_lookup()
    try:
        return _search.necromunda_rules(query)
    finally:
        display.stop_rules_lookup()

def _tool_warhammer40k_rules(i):
    query = i.get("query", "")
    print(f"[skull] Looking up Warhammer 40k rules: {query}")
    from core import display
    display.start_rules_lookup()
    try:
        return _search.warhammer40k_rules(query)
    finally:
        display.stop_rules_lookup()

def _tool_netepic_rules(i):
    query = i.get("query", "")
    print(f"[skull] Looking up NetEpic rules: {query}")
    from core import display
    display.start_rules_lookup()
    try:
        return _search.netepic_rules(query)
    finally:
        display.stop_rules_lookup()

def _tool_netea_rules(i):
    query = i.get("query", "")
    print(f"[skull] Looking up NetEA rules: {query}")
    from core import display
    display.start_rules_lookup()
    try:
        return _search.netea_rules(query)
    finally:
        display.stop_rules_lookup()


def _tool_play_ambient_hymn(i):
    global _last_hymn_success
    from core import ambient_music
    track_name = i.get("track_name")
    res = ambient_music.play_random_snippet(specific_name=track_name, duration_sec=30.0, force=True)
    if res:
        _last_hymn_success = True
        return f"[SUCCESS] {res}. INSTRUCTION: Do NOT generate any spoken text. Output nothing so only the music plays."
    _last_hymn_success = False
    return "Unable to play sacred music track from the archive directory."





def _tool_set_candles(i):
    lit = bool(i.get("lit", True))
    if lit:
        _candles.on()
    else:
        _candles.off()
    print(f"[skull] Candles {'lit' if lit else 'extinguished'}")
    return "The candles are lit; their flame-glow flickers over the skull." if lit else "The candles are extinguished."

def _tool_roll_dice(i):
    num_dice = int(i.get("num_dice", 1))
    hit_on = int(i.get("hit_on", 3))
    wound_on = int(i.get("wound_on", 4))
    save_on = i.get("save_on")
    save_on = int(save_on) if save_on is not None else None
    ap = int(i.get("ap", 0))
    invul_save = i.get("invul_save")
    invul_save = int(invul_save) if invul_save is not None else None
    reroll_hits = str(i.get("reroll_hits", "none"))
    reroll_wounds = str(i.get("reroll_wounds", "none"))
    feel_no_pain = i.get("feel_no_pain")
    feel_no_pain = int(feel_no_pain) if feel_no_pain is not None else None
    print(f"[skull] Rolling {num_dice} dice (hits: {hit_on}+, wounds: {wound_on}+)")
    res = _simulate_dice(
        num_dice=num_dice,
        hit_on=hit_on,
        wound_on=wound_on,
        save_on=save_on,
        ap=ap,
        invul_save=invul_save,
        reroll_hits=reroll_hits,
        reroll_wounds=reroll_wounds,
        feel_no_pain=feel_no_pain
    )
    _trigger_dice_effects()
    return res

def _tool_roll_necromunda_dice(i):
    dice_type = str(i.get("dice_type", "d6")).strip()
    count = int(i.get("count", 1))
    target = i.get("target")
    target = int(target) if target is not None else None
    print(f"[brain] Rolling {count} Necromunda {dice_type} dice...")
    res = _simulate_necromunda(dice_type, count, target)
    _trigger_dice_effects()
    return res

def _tool_roll_standard_dice(i):
    count = int(i.get("count", 1))
    sides = int(i.get("sides", 6))
    target = i.get("target")
    target = int(target) if target is not None else None
    print(f"[brain] Rolling {count}d{sides}...")
    res = _simulate_standard_dice(count, sides, target)
    _trigger_dice_effects()
    return res

def _tool_roll_epic_dice(i):
    roll_type = str(i.get("roll_type", "shooting")).strip()
    count = int(i.get("count", 1))
    system = i.get("system")
    if system is None:
        active = get_current_game()
        if active == "NetEpic Armageddon":
            system = "NetEA"
        elif active == "NetEpic":
            system = "NetEpic"
        else:
            system = "NetEpic"
    else:
        system = str(system).strip()

    to_hit = i.get("to_hit")
    to_hit = int(to_hit) if to_hit is not None else None
    
    save_on = i.get("save_on")
    save_on = int(save_on) if save_on is not None else None
    
    tsm = int(i.get("tsm", 0))
    macro_weapon = bool(i.get("macro_weapon", False))
    reinforced_armour = bool(i.get("reinforced_armour", False))
    
    caf = int(i.get("caf", 0))
    opponent_caf = int(i.get("opponent_caf", 0))
    
    opponent_count = i.get("opponent_count")
    opponent_count = int(opponent_count) if opponent_count is not None else None
    
    morales = i.get("morales")
    morales = int(morales) if morales is not None else None

    print(f"[brain] Rolling {count} Epic {system} dice for {roll_type}...")
    res = _simulate_epic_dice(
        system=system,
        roll_type=roll_type,
        count=count,
        to_hit=to_hit,
        save_on=save_on,
        tsm=tsm,
        macro_weapon=macro_weapon,
        reinforced_armour=reinforced_armour,
        caf=caf,
        opponent_caf=opponent_caf,
        morales=morales,
        opponent_count=opponent_count,
    )
    _trigger_dice_effects()
    return res



def get_handlers():
    return {
        "necromunda_rules": _tool_necromunda_rules,
        "warhammer40k_rules": _tool_warhammer40k_rules,
        "netepic_rules": _tool_netepic_rules,
        "netea_rules": _tool_netea_rules,
        "play_ambient_hymn": _tool_play_ambient_hymn,
        "set_candles": _tool_set_candles,
        "roll_dice": _tool_roll_dice,
        "roll_necromunda_dice": _tool_roll_necromunda_dice,
        "roll_standard_dice": _tool_roll_standard_dice,
        "roll_epic_dice": _tool_roll_epic_dice,
    }
