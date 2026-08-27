"""Deterministic WFRP 4th Edition mechanics.

Every roll the game needs resolved is worked out here rather than described to
the language model, so a Test always follows the printed rules: the same roll
always gives the same Success Levels, a double always triggers the Critical or
Fumble it should, and a Critical Wound is looked up in the book's own table
rather than invented.

Rules text is quoted by page in the docstrings so a reading can be checked
against the source. Anything rolled on a table -- hit locations, criticals,
miscasts, fumbles -- is read from ``rule_tables``/``rule_table_rows``, which are
extracted from the rulebook PDF, so this module holds no table data of its own.
"""
from __future__ import annotations

import random
import re
import sqlite3
from dataclasses import dataclass, field
from typing import Optional

from . import db

# Difficulty Table, page 153. Challenging is the assumed difficulty when none
# is stated, including for Opposed Tests.
DIFFICULTIES = {
    "very easy": 60,
    "easy": 40,
    "average": 20,
    "challenging": 0,
    "difficult": -10,
    "hard": -20,
    "very hard": -30,
}

# Outcomes Table, page 152.
_OUTCOMES = (
    (6, "Astounding Success"),
    (4, "Impressive Success"),
    (2, "Success"),
    (0, "Marginal Success"),
    (-2, "Marginal Failure"),
    (-4, "Failure"),
    (-6, "Impressive Failure"),
)

# Automatic Failure and Success, page 150.
AUTO_SUCCESS_MAX = 5
AUTO_FAILURE_MIN = 96

CHARACTERISTICS = {
    "ws": "Weapon Skill", "bs": "Ballistic Skill", "s": "Strength",
    "t": "Toughness", "i": "Initiative", "ag": "Agility", "dex": "Dexterity",
    "int": "Intelligence", "wp": "Willpower", "fel": "Fellowship",
}

# Words a GM's question is phrased with rather than about. Dropping them keeps
# "how does advantage work" from ranking on "does" and "work".
_STOPWORDS = frozenset("""
about and any are can does doing for from get gets has have how its
into much not the their them then there these this those use used using
was were what when where which who why will with work works you your
rule rules game
""".split())


def difficulty_modifier(difficulty) -> int:
    """Accept either a named difficulty or a raw modifier."""
    if difficulty is None or difficulty == "":
        return 0
    if isinstance(difficulty, (int, float)):
        return int(difficulty)
    text = str(difficulty).strip().lower()
    if text in DIFFICULTIES:
        return DIFFICULTIES[text]
    match = re.match(r"^([+-]?\d+)$", text)
    if match:
        return int(match.group(1))
    # "Hard (-20)" and "-20 (Hard)" both appear in published adventures.
    named = re.search(r"[a-z ]+", text)
    if named and named.group(0).strip() in DIFFICULTIES:
        return DIFFICULTIES[named.group(0).strip()]
    match = re.search(r"([+-]?\d+)", text)
    return int(match.group(1)) if match else 0


def outcome_label(success_levels: int) -> str:
    for threshold, label in _OUTCOMES:
        if success_levels >= threshold:
            return label
    return "Astounding Failure"


def is_double(roll: int) -> bool:
    """A double is a roll whose tens and units match; 100 is printed as 00."""
    return roll % 11 == 0 or roll == 100


@dataclass
class TestResult:
    """One d100 Test resolved under the rules on pages 150-153."""

    roll: int
    target: int
    base_target: int
    modifier: int
    success: bool
    success_levels: int
    critical: bool = False
    fumble: bool = False
    automatic: bool = False
    label: str = ""

    @property
    def outcome(self) -> str:
        return outcome_label(self.success_levels)

    def summary(self) -> str:
        parts = ["%s vs %d" % (self.roll, self.target)]
        if self.modifier:
            parts[0] += " (%d %+d)" % (self.base_target, self.modifier)
        parts.append("%s, SL %+d" % ("SUCCESS" if self.success else "FAILURE",
                                     self.success_levels))
        parts.append(self.outcome)
        if self.critical:
            parts.append("CRITICAL")
        if self.fumble:
            parts.append("FUMBLE")
        if self.automatic:
            parts.append("automatic")
        prefix = "%s: " % self.label if self.label else ""
        return prefix + " | ".join(parts)


def roll_d100(rng: Optional[random.Random] = None) -> int:
    return (rng or random).randint(1, 100)


def test(
    target: int,
    difficulty=0,
    roll: Optional[int] = None,
    label: str = "",
    criticals: bool = True,
    above_hundred: bool = False,
    rng: Optional[random.Random] = None,
) -> TestResult:
    """Resolve a Test.

    Success Levels are the tens of the modified target less the tens of the
    roll (page 152). A roll of 01-05 always succeeds and 96-00 always fails
    (page 150); in those cases the SL floors at +1 or ceilings at -1 rather
    than being overridden, "or the SL you rolled, whichever is higher" (Fast
    SL, page 152).

    ``above_hundred`` applies the optional rule on page 151 granting +1 SL for
    each full 10% a target exceeds 100.
    """
    modifier = difficulty_modifier(difficulty)
    modified = int(target) + modifier
    roll = roll_d100(rng) if roll is None else int(roll)

    # The target is capped for the comparison but not for the SL calculation,
    # so an exceptional character still profits from a target above 100.
    if roll <= AUTO_SUCCESS_MAX:
        success, automatic = True, True
    elif roll >= AUTO_FAILURE_MIN:
        success, automatic = False, True
    else:
        success, automatic = roll <= modified, False

    success_levels = (modified // 10) - (roll // 10)
    if automatic and success:
        success_levels = max(1, success_levels)
    elif automatic and not success:
        success_levels = min(-1, success_levels)

    if above_hundred and success and modified > 100:
        success_levels += (modified - 100) // 10

    double = criticals and is_double(roll)
    return TestResult(
        roll=roll, target=max(0, modified), base_target=int(target),
        modifier=modifier, success=success, success_levels=success_levels,
        critical=bool(double and success), fumble=bool(double and not success),
        automatic=automatic, label=label,
    )


@dataclass
class OpposedResult:
    attacker: TestResult
    defender: TestResult
    winner: str            # "attacker", "defender" or "tie"
    net_sl: int = 0
    tie_broken_by: str = ""

    def summary(self) -> str:
        lines = ["Attacker: " + self.attacker.summary(),
                 "Defender: " + self.defender.summary()]
        if self.winner == "tie":
            lines.append("Result: stalemate - re-roll or nothing happens (p153)")
        else:
            note = " (%s)" % self.tie_broken_by if self.tie_broken_by else ""
            lines.append("Result: %s wins by %+d SL%s"
                         % (self.winner, self.net_sl, note))
        return "\n".join(lines)


def opposed_test(
    attacker_target: int,
    defender_target: int,
    attacker_difficulty=0,
    defender_difficulty=0,
    attacker_roll: Optional[int] = None,
    defender_roll: Optional[int] = None,
    attacker_label: str = "attacker",
    defender_label: str = "defender",
    rng: Optional[random.Random] = None,
) -> OpposedResult:
    """Both sides Test; the higher SL wins (page 153).

    A failure does not lose automatically: the book's own example has Salundra
    win an Opposed Endurance Test at -1 SL against -3 SL. Only when SL ties can
    a success beat a failure, and a remaining tie is broken by the higher
    tested Skill or Characteristic. The book leaves a full tie to the GM, as
    either a stalemate or a re-roll.
    """
    first = test(attacker_target, attacker_difficulty, attacker_roll,
                 attacker_label, rng=rng)
    second = test(defender_target, defender_difficulty, defender_roll,
                  defender_label, rng=rng)

    if first.success_levels != second.success_levels:
        winner = ("attacker" if first.success_levels > second.success_levels
                  else "defender")
        return OpposedResult(first, second, winner,
                             abs(first.success_levels - second.success_levels))

    if first.success != second.success:
        winner = "attacker" if first.success else "defender"
        return OpposedResult(first, second, winner, 0,
                             "equal SL, success beats failure")

    if first.target != second.target:
        winner = "attacker" if first.target > second.target else "defender"
        return OpposedResult(first, second, winner, 0,
                             "equal SL, higher tested value wins")

    return OpposedResult(first, second, "tie", 0)


# ── table lookups ────────────────────────────────────────────────────────────


class RulesLookup:
    """Reads the extracted rulebook tables.

    The engine never stores table data itself; a Critical Wound or Miscast is
    always the row the book prints for that roll.
    """

    def __init__(self, conn: Optional[sqlite3.Connection] = None,
                 rulebook: str = "wfrp-4e-core"):
        self._conn = conn
        self._owned = conn is None
        self.rulebook = rulebook

    def __enter__(self) -> "RulesLookup":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = db.get_connection()
        return self._conn

    def close(self) -> None:
        if self._owned and self._conn is not None:
            self._conn.close()
            self._conn = None

    def find_table(self, kind: str = "", title: str = "") -> Optional[sqlite3.Row]:
        sql = ["SELECT t.* FROM rule_tables t JOIN rulebooks b ON b.id = t.rulebook_id",
               "WHERE b.slug = ?"]
        args = [self.rulebook]
        if kind:
            sql.append("AND t.kind = ?")
            args.append(kind)
        if title:
            sql.append("AND t.title LIKE ?")
            args.append("%" + title + "%")
        sql.append("ORDER BY t.page LIMIT 1")
        return self.conn.execute(" ".join(sql), args).fetchone()

    def roll_on(self, table_id: int, value: int) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM rule_table_rows WHERE table_id = ?"
            " AND roll_min IS NOT NULL AND ? BETWEEN roll_min AND roll_max"
            " ORDER BY ordinal LIMIT 1",
            (table_id, value),
        ).fetchone()

    def hit_location(self, value: int, table_title: str = "") -> Optional[sqlite3.Row]:
        table = self.find_table("hit_location", table_title)
        return self.roll_on(table["id"], value) if table else None

    def critical_wound(self, location: str, value: int) -> Optional[sqlite3.Row]:
        """The Critical table for a Hit Location, page 174."""
        key = (location or "").lower()
        for word in ("head", "arm", "body", "leg"):
            if word in key:
                table = self.find_table("critical", word.title())
                return self.roll_on(table["id"], value) if table else None
        return None

    def miscast(self, value: int, major: bool = False) -> Optional[sqlite3.Row]:
        table = self.find_table("miscast", "Major" if major else "Minor")
        return self.roll_on(table["id"], value) if table else None

    def fumble(self, value: int) -> Optional[sqlite3.Row]:
        """The Oops! Table rolled on a fumbled combat Test, page 160."""
        table = self.find_table("fumble") or self.find_table("", "Oops")
        return self.roll_on(table["id"], value) if table else None

    def skill(self, name: str) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT s.* FROM rule_skills s JOIN rulebooks b ON b.id = s.rulebook_id"
            " WHERE b.slug = ? AND lower(s.name) = ? LIMIT 1",
            (self.rulebook, (name or "").strip().lower()),
        ).fetchone()

    def spell(self, name: str) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT s.* FROM rule_spells s JOIN rulebooks b ON b.id = s.rulebook_id"
            " WHERE b.slug = ? AND lower(s.name) = ? LIMIT 1",
            (self.rulebook, (name or "").strip().lower()),
        ).fetchone()

    def creature(self, name: str) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT c.* FROM rule_creatures c JOIN rulebooks b ON b.id = c.rulebook_id"
            " WHERE b.slug = ? AND lower(c.name) = ? LIMIT 1",
            (self.rulebook, (name or "").strip().lower()),
        ).fetchone()

    def available(self) -> bool:
        """Whether an extracted rulebook is present to be consulted."""
        try:
            row = self.conn.execute(
                "SELECT 1 FROM rulebooks WHERE slug = ?", (self.rulebook,)
            ).fetchone()
        except sqlite3.Error:
            return False
        return row is not None

    def search(self, query: str, limit: int = 6, kind: str = "") -> list:
        """Full-text search across both the prose and the structured entries.

        Titles are weighted far above bodies so that asking for "Dodge" returns
        the Skill rather than every paragraph that mentions dodging. Questions
        are asked conversationally, so the words that carry no meaning for
        retrieval are dropped before matching.
        """
        terms = [
            term for term in re.findall(r"[\w']+", (query or "").lower())
            if len(term) > 2 and term not in _STOPWORDS
        ]
        if not terms:
            return []
        # Prefix matching, so asking about a "Troll" finds the "Trolls" entry
        # and "casting" finds "cast".
        match = " OR ".join('"%s"*' % term.replace('"', "") for term in terms)
        sql = [
            "SELECT title, body, kind, ref_table, ref_id, section_id, page,",
            "       bm25(rule_search, 10.0, 1.0) AS score",
            "FROM rule_search WHERE rule_search MATCH ? AND rulebook_id = ?",
        ]
        args = [match, self._rulebook_id()]
        if kind:
            sql.append("AND kind = ?")
            args.append(kind)
        sql.append("ORDER BY score LIMIT ?")
        args.append(int(limit))
        try:
            return self.conn.execute(" ".join(sql), args).fetchall()
        except sqlite3.Error:
            return []

    def _rulebook_id(self) -> int:
        row = self.conn.execute(
            "SELECT id FROM rulebooks WHERE slug = ?", (self.rulebook,)
        ).fetchone()
        return row[0] if row else -1


def _row_text(row) -> str:
    if row is None:
        return ""
    parts = [row["result"] or "", row["detail"] or ""]
    return " - ".join(part for part in parts if part).strip()


# ── combat ───────────────────────────────────────────────────────────────────


def reverse_roll(roll: int) -> int:
    """Swap the tens and units of a d100 result (page 150).

    Hit Locations are read from the reversed roll to hit (page 159). 100 is
    printed as 00 and so reverses to itself.
    """
    if roll >= 100:
        return 100
    tens, units = divmod(roll, 10)
    reversed_value = units * 10 + tens
    return 100 if reversed_value == 0 else reversed_value


@dataclass
class AttackResult:
    hit: bool
    opposed: Optional[OpposedResult] = None
    to_hit: Optional[TestResult] = None
    hit_location: str = ""
    location_roll: int = 0
    damage: int = 0
    wounds: int = 0
    wounds_remaining: Optional[int] = None
    critical: bool = False
    critical_wound: str = ""
    critical_roll: int = 0
    fumble: bool = False
    fumble_effect: str = ""
    advantage: str = ""
    notes: list = field(default_factory=list)

    def summary(self) -> str:
        lines = []
        if self.opposed is not None:
            lines.append(self.opposed.summary())
        elif self.to_hit is not None:
            lines.append(self.to_hit.summary())
        if not self.hit:
            if self.fumble:
                lines.append("FUMBLE (%d): %s" % (self.critical_roll, self.fumble_effect))
            lines.append("Miss. " + self.advantage)
            lines.extend(self.notes)
            return "\n".join(line for line in lines if line)
        lines.append("Hit location: %s (reversed roll %d)"
                     % (self.hit_location, self.location_roll))
        lines.append("Damage %d, %d Wounds suffered" % (self.damage, self.wounds))
        if self.wounds_remaining is not None:
            lines.append("Wounds remaining: %d" % self.wounds_remaining)
        if self.critical:
            lines.append("CRITICAL WOUND (%d on %s): %s"
                         % (self.critical_roll, self.hit_location, self.critical_wound))
        if self.advantage:
            lines.append(self.advantage)
        lines.extend(self.notes)
        return "\n".join(lines)


def resolve_attack(
    attacker_skill: int,
    weapon_damage: int,
    defender_skill: int = 0,
    defender_toughness_bonus: int = 0,
    defender_armour: int = 0,
    defender_wounds: Optional[int] = None,
    strength_bonus: int = 0,
    melee: bool = True,
    difficulty=0,
    defender_difficulty=0,
    attacker_roll: Optional[int] = None,
    defender_roll: Optional[int] = None,
    lookup: Optional[RulesLookup] = None,
    rng: Optional[random.Random] = None,
) -> AttackResult:
    """Resolve one attack end to end, pages 158-159.

    Melee is an Opposed Test and ranged is a straight Test. Damage is Weapon
    Damage plus the SL of the winning Test, less the target's Toughness Bonus
    and Armour Points, to a minimum of 1 Wound. Melee Weapon Damage already
    includes the attacker's Strength Bonus in the printed profile, so
    ``strength_bonus`` is added only when a bare weapon rating is supplied.
    """
    owned = lookup is None
    lookup = lookup or RulesLookup()
    try:
        result = AttackResult(hit=False)
        if melee:
            opposed = opposed_test(
                attacker_skill, defender_skill, difficulty, defender_difficulty,
                attacker_roll, defender_roll, "attacker", "defender", rng=rng,
            )
            result.opposed = opposed
            to_hit = opposed.attacker
            won = opposed.winner == "attacker"
            net_sl = opposed.net_sl if won else 0
        else:
            to_hit = test(attacker_skill, difficulty, attacker_roll, "ranged", rng=rng)
            result.to_hit = to_hit
            won = to_hit.success
            net_sl = to_hit.success_levels

        # A Critical happens on any successful combat Test that rolls a double,
        # "even when you are the defender in an opposed Test" (page 159).
        result.fumble = to_hit.fumble
        if to_hit.fumble:
            value = roll_d100(rng)
            result.critical_roll = value
            result.fumble_effect = _row_text(lookup.fumble(value)) or \
                "Roll on the Oops! Table (p160)"

        # A Critical is scored by any successful combat Test that rolls a
        # double, "even when you are the defender in an opposed Test" (p159),
        # so a defender who succeeds on a double wounds the attacker whether or
        # not they win the exchange.
        if result.opposed is not None and result.opposed.defender.critical:
            result.notes.append(
                "Defender rolled a Critical (%d): the attacker takes a Critical "
                "Wound as well." % result.opposed.defender.roll
            )

        if not won:
            result.advantage = ("Defender gains +1 Advantage." if melee
                                else "No Advantage is gained on a missed shot.")
            return result

        result.hit = True
        result.advantage = "Attacker gains +1 Advantage."
        result.location_roll = reverse_roll(to_hit.roll)
        location = lookup.hit_location(result.location_roll)
        result.hit_location = (location["result"] if location else "Body")

        base = int(weapon_damage) + (int(strength_bonus) if melee else 0)
        result.damage = base + net_sl
        result.wounds = max(1, result.damage
                            - int(defender_toughness_bonus) - int(defender_armour))

        if defender_wounds is not None:
            remaining = int(defender_wounds) - result.wounds
            result.wounds_remaining = max(0, remaining)
            if remaining < 0:
                # Losing more Wounds than remain causes a Critical Wound and
                # the Prone Condition (page 159).
                result.critical = True
                result.notes.append("Wounds exceeded: target gains the Prone Condition.")

        if to_hit.critical:
            result.critical = True

        if result.critical:
            value = roll_d100(rng)
            result.critical_roll = value
            row = lookup.critical_wound(result.hit_location, value)
            result.critical_wound = _row_text(row) or \
                "Roll on the %s Critical Wounds table (p174)" % result.hit_location
        return result
    finally:
        if owned:
            lookup.close()


# ── magic ────────────────────────────────────────────────────────────────────


@dataclass
class CastResult:
    test: TestResult
    spell: str = ""
    casting_number: int = 0
    cast: bool = False
    overcasts: int = 0
    miscast: str = ""
    miscast_roll: int = 0
    miscast_major: bool = False
    notes: list = field(default_factory=list)

    def summary(self) -> str:
        lines = [self.test.summary()]
        head = "%s (CN %d): " % (self.spell or "Spell", self.casting_number)
        if self.cast:
            extra = (" with %d overcast(s) available" % self.overcasts
                     if self.overcasts else "")
            lines.append(head + "CAST" + extra)
        else:
            lines.append(head + "not cast")
        if self.miscast:
            lines.append("MISCAST (%s, %d): %s"
                         % ("Major" if self.miscast_major else "Minor",
                            self.miscast_roll, self.miscast))
        lines.extend(self.notes)
        return "\n".join(lines)


def cast_spell(
    language_magick: int,
    casting_number: int,
    spell_name: str = "",
    difficulty=0,
    roll: Optional[int] = None,
    channelled_sl: int = 0,
    instinctive_diction: bool = False,
    lookup: Optional[RulesLookup] = None,
    rng: Optional[random.Random] = None,
) -> CastResult:
    """Make a Casting Test, pages 234-238.

    The spell is cast when the Test succeeds and its SL reaches the Casting
    Number. Channelled magic sets the effective CN to 0 (page 237). A Critical
    forces a roll on the Minor Miscast Table unless the caster has Instinctive
    Diction, and a Fumble forces one regardless. Every +2 SL above the CN buys
    one overcast (page 238).
    """
    owned = lookup is None
    lookup = lookup or RulesLookup()
    try:
        effective_cn = 0 if channelled_sl else int(casting_number)
        outcome = test(language_magick, difficulty, roll,
                       spell_name or "Language (Magick)", rng=rng)
        result = CastResult(test=outcome, spell=spell_name,
                            casting_number=effective_cn)

        if outcome.success and outcome.success_levels >= effective_cn:
            result.cast = True
            result.overcasts = max(0, (outcome.success_levels - effective_cn) // 2)

        if outcome.fumble:
            value = roll_d100(rng)
            result.miscast_roll = value
            result.miscast = _row_text(lookup.miscast(value, major=False))
            result.notes.append("Fumbled Casting: Minor Miscast (p236).")
        elif outcome.critical and not instinctive_diction:
            value = roll_d100(rng)
            result.miscast_roll = value
            result.miscast = _row_text(lookup.miscast(value, major=False))
            result.notes.append(
                "Critical Casting (p234): choose Critical Cast, Total Power, "
                "or Unstoppable Force."
            )
        elif outcome.critical:
            result.notes.append(
                "Critical Casting (p234): Instinctive Diction avoids the Miscast; "
                "choose Critical Cast, Total Power, or Unstoppable Force."
            )

        if channelled_sl and not result.cast:
            result.notes.append(
                "Channelled energy is lost and a Minor Miscast is suffered (p237)."
            )
            if not result.miscast:
                value = roll_d100(rng)
                result.miscast_roll = value
                result.miscast = _row_text(lookup.miscast(value, major=False))
        return result
    finally:
        if owned:
            lookup.close()


@dataclass
class ChannelResult:
    test: TestResult
    accumulated_sl: int = 0
    casting_number: int = 0
    ready: bool = False
    miscast: str = ""
    miscast_roll: int = 0
    notes: list = field(default_factory=list)

    def summary(self) -> str:
        lines = [self.test.summary(),
                 "Channelled SL: %d / CN %d%s"
                 % (self.accumulated_sl, self.casting_number,
                    " - ready to cast next Round" if self.ready else "")]
        if self.miscast:
            lines.append("MAJOR MISCAST (%d): %s" % (self.miscast_roll, self.miscast))
        lines.extend(self.notes)
        return "\n".join(lines)


def channel(
    channelling: int,
    casting_number: int,
    accumulated_sl: int = 0,
    difficulty=0,
    roll: Optional[int] = None,
    aethyric_attunement: bool = False,
    lookup: Optional[RulesLookup] = None,
    rng: Optional[random.Random] = None,
) -> ChannelResult:
    """Make an Extended Channelling Test, page 237.

    Channelling fumbles more readily than other Tests: "any double or any roll
    ending in a 0 over your Skill" is a Fumble, and a Fumble is a Major Miscast
    rather than a Minor one.
    """
    owned = lookup is None
    lookup = lookup or RulesLookup()
    try:
        outcome = test(channelling, difficulty, roll, "Channelling", rng=rng)
        if not outcome.success and outcome.roll % 10 == 0:
            outcome.fumble = True

        total = int(accumulated_sl)
        if outcome.success:
            total += outcome.success_levels
        total = max(0, total)

        result = ChannelResult(test=outcome, accumulated_sl=total,
                               casting_number=int(casting_number))
        result.ready = total >= int(casting_number)

        if outcome.critical:
            result.ready = True
            result.notes.append(
                "Critical Channelling (p237): the spell may be cast next Round "
                "regardless of accumulated SL."
            )
            if not aethyric_attunement:
                value = roll_d100(rng)
                result.miscast_roll = value
                result.miscast = _row_text(lookup.miscast(value, major=False))
                result.notes.append("Minor Miscast from the backlash.")
        elif outcome.fumble:
            value = roll_d100(rng)
            result.miscast_roll = value
            result.miscast = _row_text(lookup.miscast(value, major=True))
            result.accumulated_sl = 0
        return result
    finally:
        if owned:
            lookup.close()
