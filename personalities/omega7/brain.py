from core import search as _search
from core import config
from core import display as _display
from core import candles as _candles
import random
import math
import subprocess


def _core_brain():
    """core.brain imports this personality module at load time, so it can only be
    imported lazily from inside the tool handlers."""
    from core import brain as _brain
    return _brain


def get_current_game() -> str:
    return _core_brain().get_current_game()


def set_current_game(game: str) -> None:
    _core_brain().set_current_game(game)


def _trigger_dice_effects(display_val=None) -> None:
    _core_brain()._trigger_dice_effects(display_val)


def _simulate_dice(**kwargs) -> str:
    return _core_brain()._simulate_dice(**kwargs)


def _simulate_necromunda(*args, **kwargs) -> str:
    return _core_brain()._simulate_necromunda(*args, **kwargs)


def _simulate_standard_dice(*args, **kwargs) -> str:
    return _core_brain()._simulate_standard_dice(*args, **kwargs)


def _simulate_epic_dice(*args, **kwargs) -> str:
    return _core_brain()._simulate_epic_dice(*args, **kwargs)


def get_tools():
    return [
{
        "name": "necromunda_rules",
        "description": (
            "Look up Necromunda rules in the local offline library, extracted from the "
            "Necromunda Skirmish core rulebook (2026 edition). Use it for any question "
            "about mechanics, phases, actions, model status, conditions, skills, wyrd "
            "powers, campaigns, scenarios, the Trading Post or equipment. This edition "
            "differs substantially from earlier Necromunda, so always consult this tool "
            "rather than answering from memory. This is the FALLBACK: use it for prose "
            "and for anything that does not fit a narrower tool. Prefer, in this order: "
            "necromunda_wound for the number needed to wound; necromunda_table for a "
            "roll or a lookup on any of the book's tables; necromunda_weapon for one "
            "weapon's printed numbers; necromunda_rule for 'what does X do' about a "
            "trait, skill or condition; necromunda_subtype for a model Subtype; "
            "necromunda_actions for what a model may do; necromunda_territory for a "
            "Territory. If a tool reports that the book does not contain something, "
            "say so - never fill the gap from memory."
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
            "Simulate a Warhammer 40,000 attack: the complete roll sequence of "
            "hits, wounds, saves and optionally Feel No Pain, with rerolls. This "
            "is the 40k sequence and is wrong for Necromunda, which rolls Wound "
            "against a Strength/Toughness table, saves with Armour Piercing and "
            "then Injury dice - use necromunda_attack for that."
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
        "name": "necromunda_rule",
        "description": (
            "Look up a named Necromunda rule by name: a weapon trait (Blaze, "
            "Rapid Fire, Knockback), a skill (Backstab, Overwatch), or a "
            "condition or model status (Suppressed, Webbed, Seriously Injured). "
            "Reads the rule's own entry, so prefer it over necromunda_rules "
            "whenever the question is 'what does X do'. The bracketed value is "
            "ignored, so 'Blaze (5+)' as printed on a weapon finds the trait."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string",
                         "description": "The trait, skill or condition name."},
            },
            "required": ["name"],
        },
    },
{
        "name": "necromunda_actions",
        "description": (
            "List the actions a Necromunda model may perform, given its status. "
            "Status is 'active' (the normal list), 'engaged' (in close combat), "
            "'seriously_injured' or 'seriously_damaged'. Optionally filter by "
            "cost: single, double or free. Use this for 'what can it do?' rather "
            "than searching the rules text."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string",
                           "description": "active | engaged | seriously_injured | seriously_damaged"},
                "cost": {"type": "string",
                         "description": "Optional: single, double or free."},
            },
            "required": ["status"],
        },
    },
{
        "name": "necromunda_territory",
        "description": (
            "A campaign Territory's Boons and its battlefield effect. Boons are "
            "typed - Income, Recruit, Equipment, Reputation or Special - and a "
            "gang takes one INSTEAD of another, so report the type. Call with no "
            "name to list every Territory."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string",
                         "description": "Territory name, e.g. 'Rogue Doc Shop'. Omit to list all."},
            },
        },
    },
{
        "name": "necromunda_fighter",
        "description": (
            "A gang fighter's datasheet from a gang book: credit cost, full "
            "statline, Type and Subtypes, starting XP, special rules, what "
            "equipment list they buy from and which Skill Sets they may take. "
            "Use it for 'what does a Cawdor Word-Keeper cost', 'what are a "
            "Delaque Nacht-Ghul's stats'. Give a gang and no name to list that "
            "gang's whole roster. The core rulebook has none of this, so if "
            "this tool says the gang is not installed, say so and do NOT "
            "supply a statline from memory."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string",
                         "description": "Fighter name, e.g. 'Nacht-Ghul'. Omit to list a gang."},
                "gang": {"type": "string",
                         "description": "Gang name, e.g. 'House Delaque'."},
            },
        },
    },
{
        "name": "necromunda_wound",
        "description": (
            "The D6 needed to wound: give the attacker's Strength and the "
            "target's Toughness and this returns the number off the printed "
            "table. Use it for 'what do I need to wound?' rather than working "
            "it out, and rather than resolving a whole attack."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "strength": {"type": "integer", "description": "Attacker's Strength."},
                "toughness": {"type": "integer", "description": "Target's Toughness."},
            },
            "required": ["strength", "toughness"],
        },
    },
{
        "name": "necromunda_setup",
        "description": (
            "Walk a player through Necromunda Battlefield Set-Up one stage at "
            "a time. Use action 'begin' to start (this rolls the four scenario "
            "tables), 'next' when the player says they have finished the "
            "current stage, 'repeat' to read the current stage again, 'status' "
            "for where they are, 'goto' with a stage name to go back over one, "
            "and 'abandon' to stop. Read out what the tool returns and then "
            "wait for the player - do not run ahead through the stages."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string",
                           "enum": ["begin", "next", "repeat", "status",
                                    "goto", "abandon"]},
                "stage": {"type": "string",
                          "description": "For 'goto': scenario, battlefield, "
                                         "pitch_black, crew, reinforcements "
                                         "or deployment."},
                "attacker": {"type": "string",
                             "description": "For 'begin': the attacking gang's name."},
                "defender": {"type": "string",
                             "description": "For 'begin': the defending gang's name."},
            },
            "required": ["action"],
        },
    },
{
        "name": "necromunda_subtype",
        "description": (
            "A Fighter's or Vehicle's Subtype rule - Champion, Mounted, Pet, "
            "Skimmer, Transport (X) and the rest. The book prints a Loner in "
            "both lists with different rules, so pass applies_to when the "
            "player has said which they mean. Call with no name to list them."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string",
                         "description": "Subtype name, e.g. 'Mounted'. Omit to list all."},
                "applies_to": {"type": "string", "enum": ["fighter", "vehicle"],
                               "description": "Which list, when it is known."},
            },
        },
    },
{
        "name": "necromunda_table",
        "description": (
            "Look up or roll on any of the book's tables: Lasting Injury, "
            "Lasting Damage, Advancement, Insanity, Objective, Side Job, Crew, "
            "Deployment, Pitch Black, Core Gang Tactics, Territory Selection, "
            "Model Ranks (which rank an XP total reaches), Perils of the Warp, "
            "Escape, Medical Escort, Wyrd Powers, Falling, Specialist "
            "Specialisations, Characteristic Limits and Panicked Pets. Several "
            "are looked up rather than rolled, so pass a roll only when one was "
            "made. Give a roll to resolve one that has already been made, omit "
            "it to have the table's own dice rolled, or ask for the table by "
            "name with no roll to list it. Results come from the printed table, "
            "never invented."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "table": {"type": "string",
                          "description": "Table name, e.g. 'Lasting Injury'."},
                "roll": {"type": "integer",
                         "description": "A roll already made. Omit to roll it."},
                "list_all": {"type": "boolean",
                             "description": "True to list the whole table."},
            },
            "required": ["table"],
        },
    },
{
        "name": "necromunda_skills",
        "description": (
            "List every skill in one of Necromunda's seven skill sets: Agility, "
            "Brawn, Combat, Cunning, Savant, Shooting or Inherent."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "skill_set": {"type": "string",
                              "description": "The set, e.g. 'Cunning'."},
            },
            "required": ["skill_set"],
        },
    },
{
        "name": "necromunda_attack",
        "description": (
            "Resolve a complete Necromunda attack and play it out on the eye, one "
            "step at a time: Hit roll, Wound roll, Save roll, then Injury dice if "
            "the target is taken to zero Wounds. Use this whenever someone is "
            "making an actual attack, rather than rolling the steps separately. "
            "Look the weapon up with necromunda_weapon first if you do not know "
            "its Strength, AP or Lethality. The tool returns one short line per "
            "step; read those lines out in order, briefly, and do not invent "
            "additional detail about the shot."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "shots": {"type": "integer", "minimum": 1,
                          "description": "Number of Hit rolls to make."},
                "ballistic_skill": {
                    "type": "integer", "minimum": 2, "maximum": 6,
                    "description": "The attacker's BS or WS as a target number (4 for 4+)."},
                "strength": {"type": "integer", "description": "The weapon's Strength."},
                "toughness": {"type": "integer", "description": "The target's Toughness."},
                "ap": {"type": "integer",
                       "description": "The weapon's Armour Piercing, e.g. -1. 0 if none."},
                "save": {"type": "integer", "minimum": 2, "maximum": 6,
                         "description": "The target's Save characteristic. Omit if it has none."},
                "lethality": {"type": "integer", "minimum": 1,
                              "description": "The weapon's Lethality (L): how many Injury dice."},
                "wounds": {"type": "integer", "minimum": 0,
                           "description": "The target's remaining Wounds. Defaults to 1."},
                "weapon": {"type": "string", "description": "Weapon name, for the report."},
            },
            "required": ["shots", "ballistic_skill", "strength", "toughness"],
        },
    },
{
        "name": "necromunda_weapon",
        "description": (
            "Get a Necromunda weapon's printed profile: short and long range, "
            "Strength, AP, Lethality, traits, cost in credits and Trading Post "
            "rarity, plus any special ammunition printed with it. Reads the "
            "rulebook's own table columns, so use this rather than necromunda_rules "
            "whenever the question is about a specific weapon's numbers. A cell the "
            "book leaves blank is reported as 'not printed' rather than as zero."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "The weapon's name, e.g. 'boltgun', 'heavy stubber'.",
                }
            },
            "required": ["name"],
        },
    },
{
        "name": "roll_necromunda_dice",
        "description": (
            "Roll Necromunda Skirmish dice and show the faces on the skull's eye. "
            "Types: 'injury' (results are Injured, Serious Injury or Out of Action; "
            "the count is the weapon's Lethality (L), and the ATTACKER then picks "
            "ONE of the rolled results to apply - use necromunda_weapon first if "
            "you do not know the weapon's Lethality), 'firepower' (bullet holes "
            "give Rapid Fire hits; an ammo symbol jams the weapon only if its "
            "Ammo (X+) roll also failed), 'scatter' (a Hit, plus a bearing in "
            "degrees read off however the dice landed), 'd66' (two D6 as tens then "
            "units, giving 11-66), 'd3', and plain 'd6'. Report the faces rolled, "
            "not just a total."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "dice_type": {
                    "type": "string",
                    "enum": ["firepower", "injury", "scatter", "d66", "d3", "d6"],
                    "description": "The type of Necromunda die to roll."
                },
                "count": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Number of dice. For Injury dice this is the weapon's Lethality (L)."
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

def _tool_necromunda_rule(i):
    name = i.get("name", "")
    print(f"[skull] Looking up Necromunda rule: {name}")
    from games.necromunda import rules_tools
    return rules_tools.named_rule(name)


def _tool_necromunda_actions(i):
    from games.necromunda import rules_tools
    status = i.get("status", "active")
    print(f"[skull] Necromunda actions for: {status}")
    return rules_tools.actions_available(status, i.get("cost", ""))


def _tool_necromunda_territory(i):
    from games.necromunda import rules_tools
    name = i.get("name", "")
    print(f"[skull] Necromunda territory: {name or '(all)'}")
    return rules_tools.territory(name)


def _tool_necromunda_fighter(i):
    from games.necromunda import rules_tools
    name, gang = i.get("name", ""), i.get("gang", "")
    print(f"[skull] Necromunda fighter: {name or '(roster)'} / {gang or 'any'}")
    return rules_tools.fighter_profile(name, gang)


def _tool_necromunda_wound(i):
    from games.necromunda import rules_tools
    print(f"[skull] Necromunda wound: S{i.get('strength')} vs T{i.get('toughness')}")
    return rules_tools.wound_roll(i.get("strength"), i.get("toughness"))


def _tool_necromunda_setup(i):
    from games.necromunda import setup
    action = (i.get("action") or "").strip().lower()
    print(f"[skull] Necromunda battlefield set-up: {action or '(none)'}")
    if action == "begin":
        return setup.begin(i.get("attacker", ""), i.get("defender", ""))
    if action == "next":
        return setup.advance()
    if action == "repeat":
        return setup.current()
    if action == "status":
        return setup.status()
    if action == "goto":
        return setup.go_to(i.get("stage", ""))
    if action == "abandon":
        return setup.abandon()
    return ("Name an action: begin, next, repeat, status, goto or abandon.")


def _tool_necromunda_subtype(i):
    from games.necromunda import rules_tools
    name = i.get("name", "")
    print(f"[skull] Necromunda subtype: {name or '(all)'}")
    return rules_tools.model_subtype(name, i.get("applies_to", ""))


def _tool_necromunda_table(i):
    table = i.get("table", "")
    roll = i.get("roll")
    from games.necromunda import rules_tools
    if i.get("list_all"):
        print(f"[skull] Listing Necromunda table: {table}")
        return rules_tools.table_result(table, None)
    if roll is not None:
        print(f"[skull] Necromunda {table} table, roll {roll}")
        return rules_tools.table_result(table, int(roll))
    print(f"[skull] Rolling on the Necromunda {table} table")
    result = rules_tools.roll_on_table(table)
    _trigger_dice_effects()
    return result


def _tool_necromunda_skills(i):
    skill_set = i.get("skill_set", "")
    print(f"[skull] Listing Necromunda {skill_set} skills")
    from games.necromunda import rules_tools
    return rules_tools.skills_in_set(skill_set)


def _tool_necromunda_attack(i):
    from games.necromunda import attack as _attack
    kwargs = {
        "shots": int(i.get("shots", 1)),
        "ballistic_skill": int(i.get("ballistic_skill", 4)),
        "strength": int(i.get("strength", 3)),
        "toughness": int(i.get("toughness", 3)),
        "ap": int(i.get("ap", 0)),
        "lethality": int(i.get("lethality", 1)),
        "wounds": int(i.get("wounds", 1)),
        "weapon": str(i.get("weapon", "")),
    }
    save = i.get("save")
    kwargs["save"] = int(save) if save is not None else None
    print(f"[skull] Necromunda attack: {kwargs['shots']} shot(s) at "
          f"{kwargs['ballistic_skill']}+, S{kwargs['strength']} vs T{kwargs['toughness']}")
    result = _attack.resolve(**kwargs)
    # The eye plays the steps on its own clock while the skull talks through
    # them, so this returns at once rather than sleeping between rolls.
    try:
        _display.start_die_sequence(_attack.display_steps(result))
    except Exception as e:
        print(f"[brain] Attack display failed: {e}")
    try:
        from core import sfx as _sfx
        _sfx.play("dice_roll")
    except Exception as e:
        print(f"[brain] SFX play failed: {e}")
    return _attack.narration(result)


def _tool_necromunda_weapon(i):
    name = i.get("name", "")
    print(f"[skull] Looking up Necromunda weapon: {name}")
    from games.necromunda import rules_tools
    return rules_tools.weapon_profile(name)


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
        "necromunda_weapon": _tool_necromunda_weapon,
        "necromunda_attack": _tool_necromunda_attack,
        "necromunda_rule": _tool_necromunda_rule,
        "necromunda_skills": _tool_necromunda_skills,
        "necromunda_table": _tool_necromunda_table,
        "necromunda_actions": _tool_necromunda_actions,
        "necromunda_territory": _tool_necromunda_territory,
        "necromunda_subtype": _tool_necromunda_subtype,
        "necromunda_setup": _tool_necromunda_setup,
        "necromunda_wound": _tool_necromunda_wound,
        "necromunda_fighter": _tool_necromunda_fighter,
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
