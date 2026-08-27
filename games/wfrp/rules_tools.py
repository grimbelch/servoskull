"""Tools that let Omega-7 consult and apply the WFRP rules.

The rulebook is extracted into the campaign database, so a rule can be quoted
from the book and a roll can be resolved by `rules_engine` rather than
improvised. These handlers are the seam between the two: they take what the
model knows about the scene, resolve the mechanics deterministically, and hand
back a result that is already correct rather than a rule for it to apply.
"""
from __future__ import annotations

import json
import re
from typing import Optional

from . import rules_engine as engine

RULEBOOK_SLUG = "wfrp-4e-core"

_KIND_LABELS = {
    "skill": "Skill", "talent": "Talent", "career": "Career",
    "creature": "Creature", "condition": "Condition", "table": "Table",
    "petty": "Petty Spell", "arcane": "Arcane Spell", "lore": "Spell",
    "blessing": "Blessing", "miracle": "Miracle", "sidebar": "Sidebar",
    "creature_trait": "Creature Trait",
}


def _lookup() -> engine.RulesLookup:
    return engine.RulesLookup(rulebook=RULEBOOK_SLUG)


def _trim(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    stop = cut.rfind(". ")
    return (cut[: stop + 1] if stop > limit * 0.5 else cut) + " […]"


# ── rules lookup ─────────────────────────────────────────────────────────────


def tool_rules(payload: dict) -> str:
    """Search the extracted rulebook, prose and structured entries alike."""
    query = (payload.get("query") or "").strip()
    if not query:
        return "Error: query is required."

    with _lookup() as lookup:
        if not lookup.available():
            # The rulebook has not been ingested on this device; fall back to
            # the markdown library rather than answering from nothing.
            from . import search as _search
            return _search.whfrp_rules(query)

        rows = lookup.search(query, limit=int(payload.get("limit", 5)))
        if not rows:
            return "Nothing in the WFRP 4E rulebook matches %r." % query

        out = []
        for row in rows:
            label = _KIND_LABELS.get(row["kind"], "Rule")
            out.append("## %s — %s (p%s)\n%s"
                       % (row["title"], label, row["page"], _trim(row["body"], 1200)))
        return "\n\n".join(out)


def tool_bestiary(payload: dict) -> dict:
    """Return a creature's full profile, ready to drop into an encounter."""
    name = (payload.get("name") or "").strip()
    if not name:
        return {"error": "name is required."}

    with _lookup() as lookup:
        row = lookup.creature(name)
        if row is None:
            matches = lookup.search(name, limit=5, kind="creature")
            if not matches:
                return {"error": "No creature named %r in the bestiary." % name}
            row = lookup.creature(matches[0]["title"])
            if row is None:
                return {"error": "No creature named %r in the bestiary." % name}

        profile = {key: row[key] for key in engine.CHARACTERISTICS if key in row.keys()}
        profile["m"] = row["m"]
        profile["w"] = row["w"]
        return {
            "name": row["name"],
            "category": row["category"],
            "page": row["page"],
            "characteristics": profile,
            "traits": json.loads(row["traits_json"] or "[]"),
            "optional_traits": json.loads(row["optional_traits_json"] or "[]"),
            "description": _trim(row["description"], 900),
        }


# ── resolution ───────────────────────────────────────────────────────────────


def tool_test(payload: dict) -> str:
    """Resolve a Test, opposed when a second target is supplied."""
    try:
        target = int(payload.get("target"))
    except (TypeError, ValueError):
        return "Error: target (the tested Characteristic or Skill value) is required."

    difficulty = payload.get("difficulty", 0)
    label = payload.get("skill") or payload.get("label") or "Test"
    roll = payload.get("roll")

    opposing = payload.get("opposing_target")
    if opposing in (None, ""):
        result = engine.test(target, difficulty, roll, label,
                             above_hundred=bool(payload.get("above_hundred")))
        return result.summary()

    return engine.opposed_test(
        target, int(opposing),
        difficulty, payload.get("opposing_difficulty", 0),
        roll, payload.get("opposing_roll"),
        label, payload.get("opposing_label") or "opponent",
    ).summary()


def tool_resolve_attack(payload: dict) -> str:
    """Resolve an attack from the roll to hit through to the Critical Wound."""
    try:
        skill = int(payload.get("attacker_skill"))
        damage = int(payload.get("weapon_damage"))
    except (TypeError, ValueError):
        return "Error: attacker_skill and weapon_damage are required."

    melee = bool(payload.get("is_melee", True))
    with _lookup() as lookup:
        return engine.resolve_attack(
            attacker_skill=skill,
            weapon_damage=damage,
            defender_skill=int(payload.get("defender_skill", 0) or 0),
            defender_toughness_bonus=int(payload.get("defender_tb", 0) or 0),
            defender_armour=int(payload.get("defender_ap", 0) or 0),
            defender_wounds=payload.get("defender_wounds"),
            strength_bonus=int(payload.get("attacker_sb", 0) or 0),
            melee=melee,
            difficulty=payload.get("difficulty", 0),
            defender_difficulty=payload.get("defender_difficulty", 0),
            attacker_roll=payload.get("attacker_roll"),
            defender_roll=payload.get("defender_roll"),
            attacker_name=payload.get("attacker_name") or "attacker",
            defender_name=payload.get("defender_name") or "defender",
            lookup=lookup,
        ).summary()


def tool_cast(payload: dict) -> str:
    """Resolve a Casting or Channelling Test, including any Miscast."""
    spell_name = (payload.get("spell") or "").strip()
    channelling = bool(payload.get("channelling"))

    with _lookup() as lookup:
        casting_number = payload.get("casting_number")
        if casting_number in (None, "") and spell_name:
            row = lookup.spell(spell_name)
            if row is not None:
                casting_number = row["cn"]
        try:
            casting_number = int(casting_number)
        except (TypeError, ValueError):
            return ("Error: casting_number is required when the spell is not in "
                    "the rulebook.")

        try:
            skill = int(payload.get("skill"))
        except (TypeError, ValueError):
            return ("Error: skill is required — the caster's Language (Magick) "
                    "value, or Channelling when channelling.")

        if channelling:
            return engine.channel(
                channelling=skill,
                casting_number=casting_number,
                accumulated_sl=int(payload.get("accumulated_sl", 0) or 0),
                difficulty=payload.get("difficulty", 0),
                roll=payload.get("roll"),
                aethyric_attunement=bool(payload.get("aethyric_attunement")),
                lookup=lookup,
            ).summary()

        return engine.cast_spell(
            language_magick=skill,
            casting_number=casting_number,
            spell_name=spell_name,
            difficulty=payload.get("difficulty", 0),
            roll=payload.get("roll"),
            channelled_sl=int(payload.get("channelled_sl", 0) or 0),
            instinctive_diction=bool(payload.get("instinctive_diction")),
            lookup=lookup,
        ).summary()


def tool_roll_table(payload: dict) -> str:
    """Roll on one of the book's tables and report the row."""
    title = (payload.get("table") or "").strip()
    kind = (payload.get("kind") or "").strip()
    if not title and not kind:
        return "Error: table (its title) or kind is required."

    with _lookup() as lookup:
        table = lookup.find_table(kind, title)
        if table is None:
            return "No table in the rulebook matches %r." % (title or kind)

        value = payload.get("roll")
        value = engine.roll_d100() if value in (None, "") else int(value)
        row = lookup.roll_on(table["id"], value)
        if row is None:
            return "%s (p%s): %d is not on the table." % (
                table["title"], table["page"], value)
        detail = (" — " + row["detail"]) if row["detail"] else ""
        return "%s (p%s), rolled %d → %s: %s%s" % (
            table["title"], table["page"], value,
            row["roll_label"], row["result"], detail)


HANDLERS = {
    "whfrp_rules": tool_rules,
    "whfrp_bestiary": tool_bestiary,
    "whfrp_test": tool_test,
    "whfrp_resolve_attack": tool_resolve_attack,
    "whfrp_cast": tool_cast,
    "whfrp_roll_table": tool_roll_table,
}

_DIFFICULTY_HELP = (
    "Difficulty as a name (Very Easy, Easy, Average, Challenging, Difficult, "
    "Hard, Very Hard) or a raw modifier such as -20. Defaults to Challenging (+0)."
)

TOOLS = [
    {
        "name": "whfrp_rules",
        "description": (
            "Look up Warhammer Fantasy Roleplay 4th Edition rules in the extracted Core "
            "Rulebook. Covers every mechanic — tests and Success Levels, combat, hit "
            "locations, criticals, Advantage, careers and advances, skills, talents, "
            "spells, magic and miscasts, conditions, corruption, trade and travel — as "
            "well as the bestiary. Consult this before ruling on any mechanic. Include "
            "the specific name you want (e.g. 'Rat Catcher career', 'Dodge skill', "
            "'Aethyric Armour') rather than a generic phrase. To actually resolve a "
            "roll, use whfrp_test, whfrp_resolve_attack, whfrp_cast or whfrp_roll_table "
            "instead — they apply the rules for you."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Rule, mechanic, career, skill, spell, creature or topic to look up."},
                "limit": {"type": "integer", "description": "How many entries to return (default 5)."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "whfrp_bestiary",
        "description": (
            "Fetch a creature's full statistics from the WFRP 4E bestiary: its "
            "characteristics, Wounds, traits and optional traits. Use this when placing "
            "a creature in an encounter so its profile matches the book."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Creature name, e.g. 'Trolls', 'Gors', 'Skeletons'."},
            },
            "required": ["name"],
        },
    },
    {
        "name": "whfrp_test",
        "description": (
            "Roll and resolve a WFRP 4E Test. Handles the d100 roll, the difficulty "
            "modifier, Success Levels, automatic successes and failures, and Criticals "
            "and Fumbles on doubles. Supply opposing_target to make it an Opposed Test. "
            "Use this for every skill or characteristic test rather than working out SL "
            "yourself."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "target": {"type": "integer", "description": "The tested Characteristic or Skill value, before difficulty."},
                "skill": {"type": "string", "description": "What is being tested, for the readout, e.g. 'Climb' or 'Perception'."},
                "difficulty": {"type": "string", "description": _DIFFICULTY_HELP},
                "opposing_target": {"type": "integer", "description": "The opponent's tested value. Supply this to make the test Opposed."},
                "opposing_difficulty": {"type": "string", "description": "Difficulty applied to the opponent, if it differs."},
                "opposing_label": {"type": "string", "description": "Who or what opposes the test."},
                "above_hundred": {"type": "boolean", "description": "Apply the optional rule granting +1 SL per full 10% a target exceeds 100."},
                "roll": {"type": "integer", "description": "Use a specific d100 result instead of rolling. Leave unset to roll."},
                "opposing_roll": {"type": "integer", "description": "Use a specific d100 result for the opponent."},
            },
            "required": ["target"],
        },
    },
    {
        "name": "whfrp_resolve_attack",
        "description": (
            "Resolve one WFRP 4E attack end to end: the roll to hit (Opposed in melee), "
            "the hit location from the reversed roll, damage, Wounds suffered, and any "
            "Critical Wound or Fumble looked up on the book's own tables. Use this for "
            "every attack in combat."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "attacker_skill": {"type": "integer", "description": "Attacker's Melee or Ranged skill value."},
                "weapon_damage": {"type": "integer", "description": "The weapon's Damage rating."},
                "attacker_sb": {"type": "integer", "description": "Attacker's Strength Bonus, added for melee weapons rated 'SB+X'."},
                "defender_skill": {"type": "integer", "description": "Defender's Melee or Dodge value, for the opposed melee test."},
                "defender_tb": {"type": "integer", "description": "Defender's Toughness Bonus."},
                "defender_ap": {"type": "integer", "description": "Armour Points on the location struck."},
                "defender_wounds": {"type": "integer", "description": "Defender's current Wounds, so the result reports what remains and whether they are exceeded."},
                "is_melee": {"type": "boolean", "description": "True for melee (Opposed), false for ranged. Defaults to true."},
                "difficulty": {"type": "string", "description": _DIFFICULTY_HELP},
                "defender_difficulty": {"type": "string", "description": "Difficulty applied to the defender's test, if it differs."},
                "attacker_name": {"type": "string", "description": "Who is attacking, for the readout."},
                "defender_name": {"type": "string", "description": "Who is defending, for the readout."},
                "attacker_roll": {"type": "integer", "description": "Use a specific d100 result instead of rolling."},
                "defender_roll": {"type": "integer", "description": "Use a specific d100 result for the defender."},
            },
            "required": ["attacker_skill", "weapon_damage"],
        },
    },
    {
        "name": "whfrp_cast",
        "description": (
            "Resolve a WFRP 4E Casting Test, or a Channelling Test when channelling is "
            "true. Compares Success Levels against the spell's Casting Number, reports "
            "overcasts, and rolls any Minor or Major Miscast on the book's tables. The "
            "Casting Number is looked up from the spell name when it is in the rulebook."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "skill": {"type": "integer", "description": "The caster's Language (Magick) value, or Channelling when channelling."},
                "spell": {"type": "string", "description": "Spell name, used to look up its Casting Number."},
                "casting_number": {"type": "integer", "description": "The spell's CN, if it is not in the rulebook."},
                "channelling": {"type": "boolean", "description": "True to make a Channelling Test instead of a Casting Test."},
                "accumulated_sl": {"type": "integer", "description": "SL already channelled towards the spell, for an extended Channelling Test."},
                "channelled_sl": {"type": "integer", "description": "When casting, the SL that was successfully channelled; this sets the effective CN to 0."},
                "instinctive_diction": {"type": "boolean", "description": "The caster has the Instinctive Diction Talent, avoiding the Miscast on a Critical cast."},
                "aethyric_attunement": {"type": "boolean", "description": "The caster has the Aethyric Attunement Talent, avoiding the Miscast on a Critical channel."},
                "difficulty": {"type": "string", "description": _DIFFICULTY_HELP},
                "roll": {"type": "integer", "description": "Use a specific d100 result instead of rolling."},
            },
            "required": ["skill"],
        },
    },
    {
        "name": "whfrp_roll_table",
        "description": (
            "Roll on one of the WFRP 4E rulebook's tables and return the row: hit "
            "locations, Critical Wounds by location, Minor and Major Miscasts, the "
            "Oops! fumble table, and any other table printed in the book."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "table": {"type": "string", "description": "Table title or part of it, e.g. 'Head Critical Wounds', 'Minor Miscast', 'Hit Locations'."},
                "kind": {"type": "string", "description": "Table kind: critical, miscast, hit_location, fumble or reference."},
                "roll": {"type": "integer", "description": "Use a specific result instead of rolling."},
            },
            "required": [],
        },
    },
]
