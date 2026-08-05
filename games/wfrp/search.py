"""WFRP 4E offline rules search engine."""
from __future__ import annotations

import pathlib
from skull.search import _search_rules_library, _rules_dir

_WHFRP_DIR = (pathlib.Path(__file__).resolve().parent / "rules") if (pathlib.Path(__file__).resolve().parent / "rules").exists() else (_rules_dir() / "whfrp")

_WHFRP_ROUTES = [
    ("characteristic", ["ws", "bs", "strength", "toughness", "initiative", "agility",
                        "dexterity", "intelligence", "willpower", "fellowship",
                        "characteristic", "characteristics"]),
    ("skill", ["skill test", "sl", "success level", "success levels", "opposed test",
               "extended test", "assist", "group test", "average difficulty",
               "challenging", "difficult", "easy", "routine"]),
    ("combat", ["attack", "attacks", "hit", "wound", "wounds", "damage", "armour",
                "hit location", "critical", "criticals", "advantage", "initiative order",
                "surprise", "ranged", "melee", "unarmed", "fumble", "free attack"]),
    ("fortune", ["fate", "fortune", "fate point", "fortune point", "resilience",
                 "resolve", "doomed", "blessing"]),
    ("corruption", ["corruption", "mutation", "taint", "sin", "chaos", "insanity",
                    "disorder", "trauma", "psychology"]),
    ("career", ["career", "careers", "advance", "advances", "xp", "experience",
                "career path", "career change", "trapping", "trappings", "class",
                "scout", "apothecary", "witch hunter", "soldier", "rat catcher",
                "slayer", "engineer", "wizard", "priest", "bailiff", "knight",
                "road warden", "hunter", "herbalist", "flagellant", "scholar"]),
    ("magic", ["spell", "spells", "casting", "miscast", "wind", "winds of magic",
               "channelling", "prayer", "miracle", "petty magic", "arcane lore",
               "overcasting", "ingredient"]),
    ("bestiary", ["creature", "monster", "beast", "npc", "enemy", "goblin", "orc",
                  "skaven", "undead", "demon", "daemon", "troll", "giant", "dragon"]),
    ("travel", ["travel", "journey", "encumbrance", "carrying", "weather", "night",
                "rest", "recovery", "healing", "physician", "medicine"]),
    ("social", ["gossip", "haggle", "charm", "intimidate", "bribery", "rumour",
                "social", "rapport", "entertain", "fellowship test"]),
    ("rough-nights-and-hard-days", [
        "rough night", "three feathers", "day at the trials", "night at the opera",
        "nastassia", "wedding", "grauenburg", "staatsoper", "ubersreik", "lord of ubersreik",
        "gnome", "gnomes", "pub game", "pub games", "al-zahr", "alvatafl", "middenball",
        "dwile flonking", "beast among the tailors", "scarlet empress",
    ]),
]


def whfrp_rules(query: str) -> str:
    """Look up Warhammer Fantasy Roleplay 4E rules from the local offline library."""
    result = _search_rules_library(_WHFRP_DIR, query, routes=_WHFRP_ROUTES,
                                   label="WFRP 4E", top_k=3, max_chars=3200)
    if not result:
        return ("The WFRP 4E rules library isn't installed on this device. "
                "Ingest the rulebook PDFs with Rules/ingest_pdf.py.")
    return result
