"""Character creation for WFRP 4th Edition.

This is the rules engine behind the "Roll an Adventurer" wizard. It follows the
eight-step procedure from Chapter 2 of the Core Rulebook, and it exists as its
own module because character creation is the one place where the rules are a
*process* rather than a lookup: each step offers a choice between rolling and
choosing, and the experience points a character starts with are a record of how
many of those choices they left to the dice.

The XP awards are the whole reason the wizard cannot just roll everything at
once:

===========  ==========================================  =======
Step         Choice                                      XP
===========  ==========================================  =======
Species      accept the d100 roll                        +20
Career       accept the first d100 roll                  +50
Career       pick one of three rolls                     +25
Attributes   accept the 2d10s in the order rolled        +50
Attributes   rearrange the ten numbers rolled            +25
===========  ==========================================  =======

Everything else — choosing a species outright, re-rolling, or allocating 100
points across the characteristics by hand — is worth nothing, which is the
game's way of pricing certainty.

The static species data lives here because it is small, fixed, and needed
before a database is open. Careers, by contrast, are read from the ``rule_*``
tables: there are 64 of them with four tiers each, and they came out of the
Foundry compendia already parsed into skills, talents and trappings.
"""
from __future__ import annotations

import json
import random
import re
import sqlite3
from typing import Any, Dict, List, Optional, Sequence

from . import db

CHARACTERISTICS = ["WS", "BS", "S", "T", "I", "Ag", "Dex", "Int", "WP", "Fel"]

CHARACTERISTIC_NAMES = {
    "WS": "Weapon Skill", "BS": "Ballistic Skill", "S": "Strength",
    "T": "Toughness", "I": "Initiative", "Ag": "Agility", "Dex": "Dexterity",
    "Int": "Intelligence", "WP": "Willpower", "Fel": "Fellowship",
}

# XP awarded for leaving a decision to the dice. See the table above.
XP_SPECIES_RANDOM = 20
XP_CAREER_FIRST_ROLL = 50
XP_CAREER_FROM_THREE = 25
XP_CHARACTERISTICS_AS_ROLLED = 50
XP_CHARACTERISTICS_REARRANGED = 25

# Point-buy bounds from step 3 option 3: 100 points across ten characteristics.
POINT_BUY_TOTAL = 100
POINT_BUY_MIN = 4
POINT_BUY_MAX = 18

# Career advances from step 4: 40 advances over the 8 first-tier career skills.
CAREER_ADVANCE_TOTAL = 40
CAREER_ADVANCE_MAX_PER_SKILL = 10

# Species skills from step 4: three at five advances, three at three.
SPECIES_SKILL_MAJOR = 5
SPECIES_SKILL_MINOR = 3
SPECIES_SKILL_MAJOR_COUNT = 3
SPECIES_SKILL_MINOR_COUNT = 3


# --------------------------------------------------------------- species ---

# The Attributes Table (Chapter 2, step 3). Both Elf species share the "Elf"
# column of that table; they differ in skills and talents, not attributes.
#
# ``wounds_includes_sb`` exists for Halflings alone: their Wounds are
# (2 x TB) + WPB, without the Strength Bonus every other species adds.
#
# ``extra_points`` are the free points distributed between Fate and Resilience
# at creation, which is a step the old roller skipped entirely.
_ELF_BASE = {"WS": 30, "BS": 30, "S": 20, "T": 20, "I": 40,
             "Ag": 30, "Dex": 30, "Int": 30, "WP": 30, "Fel": 20}

SPECIES: Dict[str, Dict[str, Any]] = {
    "human": {
        "key": "human",
        "display": "Human (Reiklander)",
        "table_name": "Human",
        "base": {"WS": 20, "BS": 20, "S": 20, "T": 20, "I": 20,
                 "Ag": 20, "Dex": 20, "Int": 20, "WP": 20, "Fel": 20},
        "fate": 2, "resilience": 1, "extra_points": 3,
        "move": 4, "wounds_includes_sb": True,
        "skills": [
            "Animal Care", "Charm", "Cool", "Evaluate", "Gossip", "Haggle",
            "Language (Bretonnian)", "Language (Wastelander)", "Leadership",
            "Lore (Reikland)", "Melee (Basic)", "Ranged (Bow)",
        ],
        "talents_fixed": ["Doomed"],
        "talents_choices": [["Savvy", "Suave"]],
        "talents_random": 3,
    },
    "dwarf": {
        "key": "dwarf",
        "display": "Dwarf",
        "table_name": "Dwarf",
        "base": {"WS": 30, "BS": 20, "S": 20, "T": 30, "I": 20,
                 "Ag": 10, "Dex": 30, "Int": 20, "WP": 40, "Fel": 10},
        "fate": 0, "resilience": 2, "extra_points": 2,
        "move": 3, "wounds_includes_sb": True,
        "skills": [
            "Consume Alcohol", "Cool", "Endurance", "Entertain (Storytelling)",
            "Evaluate", "Intimidate", "Language (Khazalid)", "Lore (Dwarfs)",
            "Lore (Geology)", "Lore (Metallurgy)", "Melee (Basic)",
            "Trade (any one)",
        ],
        "talents_fixed": ["Magic Resistance", "Night Vision", "Sturdy"],
        "talents_choices": [["Read/Write", "Relentless"],
                            ["Resolute", "Strong-minded"]],
        "talents_random": 0,
    },
    "halfling": {
        "key": "halfling",
        "display": "Halfling",
        "table_name": "Halfling",
        "base": {"WS": 10, "BS": 30, "S": 10, "T": 20, "I": 20,
                 "Ag": 20, "Dex": 30, "Int": 20, "WP": 30, "Fel": 30},
        "fate": 0, "resilience": 2, "extra_points": 3,
        "move": 3, "wounds_includes_sb": False,
        "skills": [
            "Charm", "Consume Alcohol", "Dodge", "Gamble", "Haggle",
            "Intuition", "Language (Mootish)", "Lore (Reikland)", "Perception",
            "Sleight of Hand", "Stealth (Any)", "Trade (Cook)",
        ],
        "talents_fixed": ["Acute Sense (Taste)", "Night Vision",
                          "Resistance (Chaos)", "Small"],
        "talents_choices": [],
        "talents_random": 2,
    },
    "high_elf": {
        "key": "high_elf",
        "display": "High Elf (Asur)",
        "table_name": "High Elf",
        "base": dict(_ELF_BASE),
        "fate": 0, "resilience": 0, "extra_points": 2,
        "move": 5, "wounds_includes_sb": True,
        "skills": [
            "Cool", "Entertain (Singing)", "Evaluate", "Language (Eltharin)",
            "Leadership", "Melee (Basic)", "Navigation", "Perception",
            "Play (any one)", "Ranged (Bow)", "Sail", "Swim",
        ],
        "talents_fixed": ["Acute Sense (Sight)", "Night Vision", "Read/Write"],
        "talents_choices": [["Coolheaded", "Savvy"],
                            ["Second Sight", "Sixth Sense"]],
        "talents_random": 0,
    },
    "wood_elf": {
        "key": "wood_elf",
        "display": "Wood Elf (Asrai)",
        "table_name": "Wood Elf",
        "base": dict(_ELF_BASE),
        "fate": 0, "resilience": 0, "extra_points": 2,
        "move": 5, "wounds_includes_sb": True,
        "skills": [
            "Athletics", "Climb", "Endurance", "Entertain (Singing)",
            "Intimidate", "Language (Eltharin)", "Melee (Basic)",
            "Outdoor Survival", "Perception", "Ranged (Bow)",
            "Stealth (Rural)", "Track",
        ],
        "talents_fixed": ["Acute Sense (Sight)", "Night Vision", "Rover"],
        "talents_choices": [["Hardy", "Second Sight"],
                            ["Read/Write", "Very Resilient"]],
        "talents_random": 0,
    },
}

SPECIES_ORDER = ["human", "dwarf", "halfling", "high_elf", "wood_elf"]

# Class trappings from step 5. Dice expressions are rolled when the character
# is finalised so the sheet records a number rather than a formula.
CLASS_TRAPPINGS: Dict[str, List[str]] = {
    "Academics": ["Clothing", "Dagger", "Pouch",
                  "Sling Bag containing Writing Kit and 1d10 sheets of Parchment"],
    "Burghers": ["Cloak", "Clothing", "Dagger", "Hat", "Pouch",
                 "Sling Bag containing Lunch"],
    "Courtiers": ["Dagger", "Fine Clothing",
                  "Pouch containing Tweezers, Ear Pick, and a Comb"],
    "Peasants": ["Cloak", "Clothing", "Dagger", "Pouch",
                 "Sling Bag containing Rations (1 day)"],
    "Rangers": ["Cloak", "Clothing", "Dagger", "Pouch",
                "Backpack containing Tinderbox, Blanket, Rations (1 day)"],
    "Riverfolk": ["Cloak", "Clothing", "Dagger", "Pouch",
                  "Sling Bag containing a Flask of Spirits"],
    "Rogues": ["Clothing", "Dagger", "Pouch",
               "Sling Bag containing 2 Candles, 1d10 Matches, a Hood or Mask"],
    "Warriors": ["Clothing", "Hand Weapon", "Dagger", "Pouch"],
}

# Starting wealth per point of Status Standing (step 5).
STATUS_WEALTH = {
    "Brass": {"dice": "2d10", "coin": "brass pennies", "field": "brass"},
    "Silver": {"dice": "1d10", "coin": "silver shillings", "field": "silver"},
    "Gold": {"dice": "", "coin": "gold crowns", "field": "gold"},
}

# Detail tables offered in step 6, keyed by the suffix the rulebook gives them.
# Those marked per-species have one table for each.
DETAIL_TABLES = [
    {"key": "hair", "label": "Hair Colour", "per_species": True},
    {"key": "eyes", "label": "Eye Colour", "per_species": True},
    {"key": "motivation", "label": "Character Motivation", "per_species": False},
    {"key": "quirk", "label": "Character Quirk", "per_species": False},
    {"key": "trait", "label": "Character Trait", "per_species": False},
    {"key": "ambition", "label": "Character Ambition", "per_species": False},
    {"key": "dooming", "label": "Dooming", "per_species": False},
]


class CharGenError(ValueError):
    """A draft that does not obey the rules."""


# ------------------------------------------------------------------ dice ---

def roll_die(sides: int) -> int:
    return random.randint(1, sides)


def roll_dice(expression: str) -> int:
    """Evaluate a simple NdM(+K) expression, as printed in the trappings lists."""
    match = re.fullmatch(r"\s*(\d*)d(\d+)\s*(?:([+-])\s*(\d+))?\s*",
                         expression or "", re.I)
    if not match:
        raise CharGenError(f"Not a dice expression: {expression!r}")
    count = int(match.group(1) or 1)
    sides = int(match.group(2))
    total = sum(roll_die(sides) for _ in range(count))
    if match.group(3):
        modifier = int(match.group(4))
        total += modifier if match.group(3) == "+" else -modifier
    return total


def _expand_dice_in_text(text: str) -> str:
    """Replace dice expressions inside a trapping with their rolled value."""
    def replace(match: "re.Match[str]") -> str:
        try:
            return str(roll_dice(match.group(0)))
        except CharGenError:
            return match.group(0)
    return re.sub(r"\b\d*d\d+\b", replace, text or "")


# --------------------------------------------------------------- lookups ---

def _conn(conn: Optional[sqlite3.Connection]) -> sqlite3.Connection:
    return conn if conn is not None else db.get_connection()


def _table_rows(conn: sqlite3.Connection, title: str) -> List[sqlite3.Row]:
    row = conn.execute(
        "SELECT id FROM rule_tables WHERE lower(title) = lower(?) LIMIT 1",
        (title,)).fetchone()
    if row is None:
        return []
    return conn.execute(
        "SELECT roll_min, roll_max, roll_label, result, detail "
        "FROM rule_table_rows WHERE table_id = ? ORDER BY roll_min", (row[0],)
    ).fetchall()


def _roll_on(conn: sqlite3.Connection, title: str,
             exclude: Sequence[str] = ()) -> Optional[Dict[str, Any]]:
    """Roll on a named rule table, optionally rerolling excluded results.

    The rulebook allows a reroll when a random talent duplicates one already
    held, so ``exclude`` is how that is expressed.
    """
    rows = _table_rows(conn, title)
    if not rows:
        return None
    highest = max(int(r["roll_max"] or 0) for r in rows) or 100
    blocked = {e.lower() for e in exclude}
    for _ in range(40):
        value = roll_die(highest)
        for row in rows:
            if int(row["roll_min"] or 0) <= value <= int(row["roll_max"] or 0):
                if (row["result"] or "").lower() in blocked:
                    break
                return {"roll": value, "label": row["roll_label"],
                        "result": row["result"], "detail": row["detail"] or ""}
    # Every remaining result was excluded; give back whatever is left.
    for row in rows:
        if (row["result"] or "").lower() not in blocked:
            return {"roll": 0, "label": "", "result": row["result"],
                    "detail": row["detail"] or ""}
    return None


def list_careers(conn: Optional[sqlite3.Connection] = None,
                 species: str = "") -> List[Dict[str, Any]]:
    """Every career, with its first tier, optionally filtered by species."""
    connection = _conn(conn)
    try:
        rows = connection.execute(
            "SELECT c.id, c.name, c.class, c.species_json, c.description, "
            "       t.name AS tier_name, t.status_tier, t.status_standing, "
            "       t.advances_json, t.skills_json, t.talents_json, "
            "       t.trappings_json "
            "FROM rule_careers c "
            "LEFT JOIN rule_career_tiers t "
            "       ON t.career_id = c.id AND t.tier = 1 "
            "ORDER BY c.class, c.name").fetchall()
    except sqlite3.OperationalError:
        return []

    wanted = SPECIES.get(species, {}).get("table_name", "") if species else ""
    careers: List[Dict[str, Any]] = []
    for row in rows:
        allowed = _load_json(row["species_json"], [])
        if wanted and allowed and wanted not in allowed:
            continue
        careers.append({
            "id": row["id"],
            "name": row["name"],
            "class": row["class"] or "",
            "species": allowed,
            "description": row["description"] or "",
            "tier1": {
                "name": row["tier_name"] or row["name"],
                "status_tier": row["status_tier"] or "",
                "status_standing": row["status_standing"] or 0,
                "advances": _load_json(row["advances_json"], []),
                "skills": _load_json(row["skills_json"], []),
                "talents": _load_json(row["talents_json"], []),
                "trappings": _load_json(row["trappings_json"], []),
            },
        })
    return careers


def _load_json(raw: Any, fallback: Any) -> Any:
    try:
        value = json.loads(raw or "")
    except (TypeError, ValueError):
        return fallback
    return value if value is not None else fallback


def get_career(conn: Optional[sqlite3.Connection], name: str) -> Optional[Dict[str, Any]]:
    for career in list_careers(conn):
        if career["name"].lower() == (name or "").lower():
            return career
    return None


# ----------------------------------------------------------------- steps ---

def roll_species(conn: Optional[sqlite3.Connection] = None) -> Dict[str, Any]:
    """Step 1: d100 on the Random Species Table."""
    connection = _conn(conn)
    result = _roll_on(connection, "Species")
    if result is None:
        # The table is only missing if the rulebook was never ingested; fall
        # back to the printed spread so creation still works.
        value = roll_die(100)
        name = ("Human" if value <= 90 else "Halfling" if value <= 94
                else "Dwarf" if value <= 98 else "High Elf" if value == 99
                else "Wood Elf")
        result = {"roll": value, "label": "", "result": name, "detail": ""}
    result["species"] = species_key_for(result["result"])
    return result


def species_key_for(name: str) -> str:
    target = (name or "").strip().lower().replace("-", " ")
    for key, data in SPECIES.items():
        if target in (key, data["table_name"].lower(), data["display"].lower()):
            return key
    if "wood" in target:
        return "wood_elf"
    if "high" in target or target == "elf":
        return "high_elf"
    if target.startswith("dwarf") or target.startswith("dwarve"):
        return "dwarf"
    if target.startswith("halfling"):
        return "halfling"
    return "human"


def roll_career(conn: Optional[sqlite3.Connection], species: str) -> Dict[str, Any]:
    """Step 2: d100 on the career table for this species."""
    data = SPECIES.get(species)
    if not data:
        raise CharGenError(f"Unknown species: {species!r}")
    connection = _conn(conn)
    result = _roll_on(connection, "Career - " + data["table_name"])
    if result is None:
        available = list_careers(connection, species)
        if not available:
            raise CharGenError("No careers available; is the rulebook ingested?")
        pick = random.choice(available)
        return {"roll": 0, "label": "", "result": pick["name"], "detail": ""}
    return result


def roll_characteristic_dice() -> List[Dict[str, Any]]:
    """Step 3: 2d10 for each of the ten characteristics, in order."""
    rolls = []
    for key in CHARACTERISTICS:
        first, second = roll_die(10), roll_die(10)
        rolls.append({"characteristic": key, "dice": [first, second],
                      "total": first + second})
    return rolls


def roll_random_talents(conn: Optional[sqlite3.Connection], count: int,
                        already_held: Sequence[str] = ()) -> List[Dict[str, Any]]:
    """Roll on the creation talent table, rerolling anything already held."""
    connection = _conn(conn)
    held = list(already_held)
    results = []
    for _ in range(max(0, count)):
        rolled = _roll_on(connection, "Talents - Character Creation", exclude=held)
        if rolled is None:
            break
        results.append(rolled)
        held.append(rolled["result"])
    return results


def roll_detail(conn: Optional[sqlite3.Connection], key: str,
                species: str) -> Optional[Dict[str, Any]]:
    """Step 6: roll on one of the descriptive tables."""
    spec = next((d for d in DETAIL_TABLES if d["key"] == key), None)
    if spec is None:
        raise CharGenError(f"Unknown detail table: {key!r}")
    title = spec["label"]
    if spec["per_species"]:
        data = SPECIES.get(species)
        if not data:
            raise CharGenError(f"Unknown species: {species!r}")
        title = f"{title} - {data['table_name']}"
    return _roll_on(_conn(conn), title)


def roll_starting_wealth(status_tier: str, standing: int) -> Dict[str, Any]:
    """Step 5: wealth is rolled per point of Status Standing."""
    rule = STATUS_WEALTH.get((status_tier or "").title())
    standing = max(0, int(standing or 0))
    if rule is None or standing == 0:
        return {"amount": 0, "coin": "", "detail": "No starting wealth."}
    if not rule["dice"]:
        return {"amount": standing, "coin": rule["coin"], "field": rule["field"],
                "detail": f"{standing} {rule['coin']}"}
    count = int(rule["dice"][0]) * standing
    sides = int(rule["dice"].split("d")[1])
    amount = sum(roll_die(sides) for _ in range(count))
    return {"amount": amount, "coin": rule["coin"], "field": rule["field"],
            "detail": f"{count}d{sides} = {amount} {rule['coin']}"}


# ------------------------------------------------------------ assembling ---

def characteristics_from(species: str, allocation: Dict[str, int],
                         mode: str) -> Dict[str, Dict[str, int]]:
    """Combine rolled or allocated numbers with the species modifiers."""
    data = SPECIES.get(species)
    if not data:
        raise CharGenError(f"Unknown species: {species!r}")

    if mode == "points":
        total = sum(int(allocation.get(k, 0)) for k in CHARACTERISTICS)
        if total != POINT_BUY_TOTAL:
            raise CharGenError(
                f"Allocate exactly {POINT_BUY_TOTAL} points across the ten "
                f"characteristics ({total} allocated).")
        for key in CHARACTERISTICS:
            value = int(allocation.get(key, 0))
            if not POINT_BUY_MIN <= value <= POINT_BUY_MAX:
                raise CharGenError(
                    f"{CHARACTERISTIC_NAMES[key]} must be between "
                    f"{POINT_BUY_MIN} and {POINT_BUY_MAX} (got {value}).")

    result: Dict[str, Dict[str, int]] = {}
    for key in CHARACTERISTICS:
        rolled = int(allocation.get(key, 0))
        initial = data["base"][key] + rolled
        result[key] = {"rolled": rolled, "modifier": data["base"][key],
                       "initial": initial, "advances": 0, "total": initial}
    return result


def derive_attributes(species: str, characteristics: Dict[str, Dict[str, int]],
                      fate_extra: int = 0,
                      resilience_extra: int = 0) -> Dict[str, Any]:
    """Wounds, Fate, Resilience and Movement, once characteristics are known."""
    data = SPECIES.get(species)
    if not data:
        raise CharGenError(f"Unknown species: {species!r}")

    def bonus(key: str) -> int:
        return int(characteristics[key]["initial"]) // 10

    wounds = (2 * bonus("T")) + bonus("WP")
    if data["wounds_includes_sb"]:
        wounds += bonus("S")

    extra = int(fate_extra or 0) + int(resilience_extra or 0)
    if extra != data["extra_points"]:
        raise CharGenError(
            f"{data['display']} has {data['extra_points']} extra points to "
            f"split between Fate and Resilience ({extra} allocated).")
    if fate_extra < 0 or resilience_extra < 0:
        raise CharGenError("Extra points cannot be negative.")

    fate = data["fate"] + int(fate_extra or 0)
    resilience = data["resilience"] + int(resilience_extra or 0)
    return {
        "wounds": wounds,
        "fate": fate,
        "fortune": fate,
        "resilience": resilience,
        "resolve": resilience,
        "move": data["move"],
    }


def _validate_species_skills(species: str, major: Sequence[str],
                             minor: Sequence[str]) -> None:
    available = set(SPECIES[species]["skills"])
    major, minor = list(major or []), list(minor or [])
    if len(major) != SPECIES_SKILL_MAJOR_COUNT or len(minor) != SPECIES_SKILL_MINOR_COUNT:
        raise CharGenError(
            f"Choose {SPECIES_SKILL_MAJOR_COUNT} species skills at "
            f"+{SPECIES_SKILL_MAJOR} and {SPECIES_SKILL_MINOR_COUNT} at "
            f"+{SPECIES_SKILL_MINOR}.")
    chosen = major + minor
    if len(set(chosen)) != len(chosen):
        raise CharGenError("A species skill cannot be chosen twice.")
    unknown = [s for s in chosen if s not in available]
    if unknown:
        raise CharGenError(f"Not a {SPECIES[species]['display']} skill: "
                           f"{', '.join(unknown)}.")


def _validate_career_advances(career: Dict[str, Any],
                              advances: Dict[str, int]) -> None:
    skills = career["tier1"]["skills"]
    total = 0
    for name, value in (advances or {}).items():
        amount = int(value or 0)
        if amount < 0:
            raise CharGenError("Career advances cannot be negative.")
        if amount > CAREER_ADVANCE_MAX_PER_SKILL:
            raise CharGenError(
                f"No more than {CAREER_ADVANCE_MAX_PER_SKILL} advances to a "
                f"single skill at this stage ({name} has {amount}).")
        if name not in skills:
            raise CharGenError(f"{name} is not a career skill for "
                               f"{career['name']}.")
        total += amount
    if total != CAREER_ADVANCE_TOTAL:
        raise CharGenError(
            f"Allocate exactly {CAREER_ADVANCE_TOTAL} advances across the "
            f"career skills ({total} allocated).")


def build_character(draft: Dict[str, Any],
                    conn: Optional[sqlite3.Connection] = None) -> Dict[str, Any]:
    """Validate a finished wizard draft and shape it into a character record.

    Raises :class:`CharGenError` with a message meant for the player if any
    step of the draft breaks the rules.
    """
    connection = _conn(conn)

    species = draft.get("species") or ""
    if species not in SPECIES:
        raise CharGenError("Choose a species.")
    data = SPECIES[species]

    career_name = draft.get("career") or ""
    career = get_career(connection, career_name)
    if career is None:
        raise CharGenError(f"Unknown career: {career_name or '(none)'}.")
    if career["species"] and data["table_name"] not in career["species"]:
        raise CharGenError(
            f"{career['name']} is not open to {data['display']}.")

    mode = draft.get("characteristics_mode") or "rolled"
    characteristics = characteristics_from(
        species, draft.get("characteristics") or {}, mode)

    attributes = derive_attributes(
        species, characteristics,
        int(draft.get("fate_extra") or 0),
        int(draft.get("resilience_extra") or 0))

    major = draft.get("species_skills_major") or []
    minor = draft.get("species_skills_minor") or []
    _validate_species_skills(species, major, minor)

    career_advances = draft.get("career_advances") or {}
    _validate_career_advances(career, career_advances)

    career_talent = draft.get("career_talent") or ""
    if career_talent and career_talent not in career["tier1"]["talents"]:
        raise CharGenError(f"{career_talent} is not a talent offered by "
                           f"{career['name']}.")

    # Species talent choices: one from each "X or Y" pair.
    chosen_options = list(draft.get("talent_choices") or [])
    if len(chosen_options) != len(data["talents_choices"]):
        raise CharGenError("Choose one talent from each species option.")
    for picked, options in zip(chosen_options, data["talents_choices"]):
        if picked not in options:
            raise CharGenError(f"{picked} is not one of {' or '.join(options)}.")

    random_talents = list(draft.get("random_talents") or [])
    if len(random_talents) != data["talents_random"]:
        raise CharGenError(
            f"{data['display']} rolls {data['talents_random']} random "
            f"talent(s); {len(random_talents)} recorded.")

    # ---- skills, merging species advances with career advances -----------
    skills: Dict[str, int] = {}
    for name in major:
        skills[name] = skills.get(name, 0) + SPECIES_SKILL_MAJOR
    for name in minor:
        skills[name] = skills.get(name, 0) + SPECIES_SKILL_MINOR
    for name, value in career_advances.items():
        amount = int(value or 0)
        if amount:
            skills[name] = skills.get(name, 0) + amount

    talents = (list(data["talents_fixed"]) + chosen_options
               + [t for t in random_talents if t]
               + ([career_talent] if career_talent else []))

    # ---- trappings and money --------------------------------------------
    trappings = [_expand_dice_in_text(t)
                 for t in CLASS_TRAPPINGS.get(career["class"], [])]
    trappings += [_expand_dice_in_text(t)
                  for t in career["tier1"]["trappings"]]

    wealth = roll_starting_wealth(career["tier1"]["status_tier"],
                                  career["tier1"]["status_standing"])

    # ---- experience -------------------------------------------------------
    xp = 0
    if draft.get("species_random"):
        xp += XP_SPECIES_RANDOM
    career_source = draft.get("career_source") or "chosen"
    if career_source == "first_roll":
        xp += XP_CAREER_FIRST_ROLL
    elif career_source == "one_of_three":
        xp += XP_CAREER_FROM_THREE
    if mode == "rolled":
        xp += XP_CHARACTERISTICS_AS_ROLLED
    elif mode == "rearranged":
        xp += XP_CHARACTERISTICS_REARRANGED

    details = draft.get("details") or {}
    wounds = attributes["wounds"]

    character = {
        "name": (draft.get("name") or "").strip() or "Unnamed Adventurer",
        "race": data["display"],
        "species": data["display"],
        "career": career["name"],
        # `class` is the column the character store actually persists;
        # `career_class` is kept as the friendlier alias used elsewhere.
        "class": career["class"],
        "career_class": career["class"],
        "career_level": 1,
        "status": (f"{career['tier1']['status_tier']} "
                   f"{career['tier1']['status_standing']}").strip(),
        "characteristics": {
            key: {"initial": value["initial"], "advances": 0,
                  "total": value["initial"]}
            for key, value in characteristics.items()
        },
        "wounds": {"max": wounds, "current": wounds},
        "fate": {"total": attributes["fate"], "current": attributes["fate"]},
        "fortune": {"total": attributes["fortune"],
                    "current": attributes["fortune"]},
        "resilience": {"total": attributes["resilience"],
                       "current": attributes["resilience"]},
        "resolve": {"total": attributes["resolve"],
                    "current": attributes["resolve"]},
        "corruption": {"current": 0, "max": 0},
        "move": {"walk": attributes["move"], "run": attributes["move"] * 2},
        "xp": {"total": xp, "spent": 0, "current": xp},
        "skills": [{"name": name, "advances": advances}
                   for name, advances in sorted(skills.items())],
        "talents": [{"name": name} for name in talents],
        "trappings": [{"name": name} for name in trappings],
        "wealth": {wealth.get("field", "brass"): wealth.get("amount", 0)},
        "money": _purse(wealth),
        "notes": _summarise(details, wealth, xp),
    }

    # The detail tables map onto columns of their own rather than free text,
    # so the rolled results survive a round trip through the character store.
    detail_columns = {
        "hair": "hair_color",
        "eyes": "eye_color",
        "motivation": "motivation",
        "dooming": "doomed",
    }
    for key, value in details.items():
        if not value:
            continue
        character[detail_columns.get(key, key)] = value
    if details.get("ambition"):
        character["ambitions"] = {"short": details["ambition"],
                                  "long": "", "party": ""}
    return character


def _purse(wealth: Dict[str, Any]) -> Dict[str, int]:
    """Starting money in the gold/silver/brass shape the sheet stores."""
    field = wealth.get("field", "brass")
    amount = int(wealth.get("amount", 0) or 0)
    return {
        "gc": amount if field == "gold" else 0,
        "ss": amount if field == "silver" else 0,
        "bp": amount if field == "brass" else 0,
    }


def _summarise(details: Dict[str, Any], wealth: Dict[str, Any],
               xp: int) -> str:
    lines = []
    for spec in DETAIL_TABLES:
        value = details.get(spec["key"])
        if value:
            lines.append(f"{spec['label']}: {value}")
    if wealth.get("detail"):
        lines.append(f"Starting wealth: {wealth['detail']}")
    lines.append(f"Starting XP: {xp}")
    return "\n".join(lines)


# ------------------------------------------------------------------ data ---

def wizard_data(conn: Optional[sqlite3.Connection] = None) -> Dict[str, Any]:
    """Everything the wizard needs to render without further round trips."""
    connection = _conn(conn)
    careers = list_careers(connection)
    return {
        "characteristics": [
            {"key": key, "name": CHARACTERISTIC_NAMES[key]}
            for key in CHARACTERISTICS
        ],
        "species": [
            {
                "key": key,
                "display": SPECIES[key]["display"],
                "base": SPECIES[key]["base"],
                "fate": SPECIES[key]["fate"],
                "resilience": SPECIES[key]["resilience"],
                "extra_points": SPECIES[key]["extra_points"],
                "move": SPECIES[key]["move"],
                "wounds_formula": ("SB + (2 x TB) + WPB"
                                   if SPECIES[key]["wounds_includes_sb"]
                                   else "(2 x TB) + WPB"),
                "skills": SPECIES[key]["skills"],
                "talents_fixed": SPECIES[key]["talents_fixed"],
                "talents_choices": SPECIES[key]["talents_choices"],
                "talents_random": SPECIES[key]["talents_random"],
            }
            for key in SPECIES_ORDER
        ],
        "careers": careers,
        "classes": sorted({c["class"] for c in careers if c["class"]}),
        "class_trappings": CLASS_TRAPPINGS,
        "detail_tables": DETAIL_TABLES,
        "rules": {
            "point_buy_total": POINT_BUY_TOTAL,
            "point_buy_min": POINT_BUY_MIN,
            "point_buy_max": POINT_BUY_MAX,
            "career_advance_total": CAREER_ADVANCE_TOTAL,
            "career_advance_max": CAREER_ADVANCE_MAX_PER_SKILL,
            "species_skill_major": SPECIES_SKILL_MAJOR,
            "species_skill_minor": SPECIES_SKILL_MINOR,
            "species_skill_major_count": SPECIES_SKILL_MAJOR_COUNT,
            "species_skill_minor_count": SPECIES_SKILL_MINOR_COUNT,
            "xp": {
                "species_random": XP_SPECIES_RANDOM,
                "career_first_roll": XP_CAREER_FIRST_ROLL,
                "career_one_of_three": XP_CAREER_FROM_THREE,
                "characteristics_rolled": XP_CHARACTERISTICS_AS_ROLLED,
                "characteristics_rearranged": XP_CHARACTERISTICS_REARRANGED,
            },
        },
    }
