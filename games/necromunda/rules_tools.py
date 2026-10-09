"""Deterministic Necromunda lookups.

These read the extracted columns rather than searching prose, so a stat question
is answered by the value the book printed and not by whatever a text match
happened to surface. ``search.necromunda_rules`` remains the right tool for "how
does this work" questions; these are for "what is this weapon's AP".
"""
from __future__ import annotations

import json
import re
import sqlite3

from . import db as necro_db
from . import attack
from . import dice
from .search import (_NOT_INSTALLED, _format_weapon, current_rulebook,
                     not_in_book, printed_page)

# The weaponry chapter prints one profile as a worked example, under its own
# explanatory heading, and the Trading Post lists the same weapon again. The
# two agree, but the Trading Post entry is the one to quote: it sits with the
# rest of the armoury rather than inside a passage explaining what a column is.
_EXAMPLE_CATEGORY = "WEAPON PROFILES"


def _open() -> sqlite3.Connection | None:
    try:
        conn = necro_db.connect(create=False)
    except (FileNotFoundError, sqlite3.Error):
        return None
    try:
        if conn.execute("SELECT 1 FROM rulebooks LIMIT 1").fetchone():
            return conn
    except sqlite3.Error:
        pass
    conn.close()
    return None


def weapon_profile(name: str) -> str:
    """The printed profile for a weapon, matched on its name.

    An exact name wins over a partial one, so asking for "boltgun" does not come
    back with the bolt pistol. When several weapons share a name -- the book
    prints a worked example of the boltgun as well as its Trading Post entry --
    the Trading Post listing is preferred, because that is the one with the
    complete profile and the price.
    """
    conn = _open()
    if conn is None:
        return _NOT_INSTALLED
    try:
        book = current_rulebook(conn)
        wanted = (name or "").strip().lower()
        if not wanted:
            return "Name a weapon to look up."
        # Across every book this unit holds: a gang's own weapons are in its
        # supplement, and scoping this to the core rulebook made the whole
        # gang book invisible to it -- an Executioner's axe came back as
        # "the core rulebook does not contain a weapon called that".
        rows = conn.execute(
            "SELECT w.*, b.title AS book, b.page_offset FROM rule_weapons w"
            " JOIN rulebooks b ON b.id = w.rulebook_id WHERE LOWER(w.name) = ?"
            " ORDER BY (w.rulebook_id != ?), w.needs_review, (w.creds IS NULL),"
            " (w.category = ?), w.id",
            (wanted, book["id"], _EXAMPLE_CATEGORY)).fetchall()
        if not rows:
            rows = conn.execute(
                "SELECT w.*, b.title AS book, b.page_offset FROM rule_weapons w"
                " JOIN rulebooks b ON b.id = w.rulebook_id"
                " WHERE LOWER(w.name) LIKE ?"
                " ORDER BY (w.rulebook_id != ?), w.needs_review,"
                " (w.creds IS NULL), (w.category = ?), LENGTH(w.name), w.id",
                (f"%{wanted}%", book["id"], _EXAMPLE_CATEGORY)).fetchall()
        if not rows:
            return not_in_book(f"a weapon called '{name}'", book)

        best = rows[0]
        if "book" in best.keys() and best["book"] != book["title"]:
            book = {"title": best["book"], "page_offset": best["page_offset"],
                    "id": book["id"]}
        out = [_format_weapon(best, book)]
        # Special-ammunition lines are printed directly beneath their weapon, so
        # they are the rows that immediately follow it -- and they stop at the
        # next full entry. Taking every variant on the page instead would hand
        # the autopistol the stub gun's warp round as well.
        following = conn.execute(
            "SELECT * FROM rule_weapons WHERE rulebook_id = ? AND page = ? AND id > ?"
            " ORDER BY id LIMIT 8", (book["id"], best["page"], best["id"])).fetchall()
        for row in following:
            if not row["is_variant"]:
                break
            out.append(_format_weapon(row, book))
        # A profile that names traits and explains none of them is half an
        # answer, and the traits are the half that decides how the attack is
        # resolved.
        explained = weapon_traits(best["traits"])
        if explained:
            out.append(f"Traits in full:\n{explained}")
        if len(rows) > 1:
            others = ", ".join(f"{r['name']} (p{printed_page(r['page'], book)})"
                               for r in rows[1:4])
            out.append(f"Also printed as: {others}")
        return "\n\n".join(out)
    finally:
        conn.close()


def weapons_in_category(category: str) -> str:
    """Every weapon printed under one of the book's table headings."""
    conn = _open()
    if conn is None:
        return _NOT_INSTALLED
    try:
        book = current_rulebook(conn)
        wanted = (category or "").strip().lower()
        rows = conn.execute(
            "SELECT name, sr_text, lr_text, str_text, ap_text, lethality_text,"
            " creds_text, tp_text, traits, is_variant, page FROM rule_weapons"
            " WHERE rulebook_id = ? AND LOWER(category) LIKE ? ORDER BY id",
            (book["id"], f"%{wanted}%")).fetchall()
        if not rows:
            cats = conn.execute(
                "SELECT DISTINCT category FROM rule_weapons WHERE rulebook_id = ?"
                " AND category != '' ORDER BY category", (book["id"],)).fetchall()
            listed = ", ".join(c["category"].title() for c in cats)
            return f"No weapon category matching '{category}'. The book lists: {listed}."
        lines = [f"{len(rows)} profiles under '{category}':"]
        for row in rows:
            prefix = "  - " if row["is_variant"] else "  "
            lines.append(
                f"{prefix}{row['name']}: SR {row['sr_text'] or '-'}, LR "
                f"{row['lr_text'] or '-'}, Str {row['str_text'] or '-'}, AP "
                f"{row['ap_text'] or '-'}, L {row['lethality_text'] or '-'}, "
                f"{row['traits'] or 'no traits'}, {row['creds_text'] or '-'} creds "
                f"(TP {row['tp_text'] or '-'}), p{printed_page(row['page'], book)}")
        return "\n".join(lines)
    finally:
        conn.close()


def weapon_lethality(name: str) -> int | None:
    """A weapon's Lethality, for rolling the right number of Injury dice."""
    conn = _open()
    if conn is None:
        return None
    try:
        book = current_rulebook(conn)
        row = conn.execute(
            "SELECT lethality FROM rule_weapons WHERE LOWER(name) = ?"
            " AND lethality IS NOT NULL"
            " ORDER BY (rulebook_id != ?), needs_review, id LIMIT 1",
            ((name or "").strip().lower(), book["id"])).fetchone()
        if row is None:
            row = conn.execute(
                "SELECT lethality FROM rule_weapons WHERE LOWER(name) LIKE ?"
                " AND lethality IS NOT NULL"
                " ORDER BY (rulebook_id != ?), needs_review, LENGTH(name), id"
                " LIMIT 1",
                (f"%{(name or '').strip().lower()}%", book["id"])).fetchone()
        return row["lethality"] if row else None
    finally:
        conn.close()


def describe_injury_roll(lethality: int, weapon: str = "") -> str:
    """Roll Injury dice and report the result the way the rule reads.

    The attacker rolls one die per point of the weapon's Lethality and then
    chooses which single result to apply, so this reports every face and names
    the choice instead of totalling them.
    """
    result = dice.injury(lethality)
    faces = ", ".join(result["faces"])
    lead = f"{result['dice']} Injury {'die' if result['dice'] == 1 else 'dice'}"
    if weapon:
        lead += f" for the {weapon} (Lethality {result['dice']})"
    lines = [f"{lead}: {faces}."]
    if result["dice"] > 1:
        lines.append(
            f"The attacking player selects one result to apply - most severe "
            f"available is {result['most_severe']}, least severe is "
            f"{result['least_severe']}.")
    else:
        lines.append(f"Result: {result['faces'][0]}.")
    return " ".join(lines)


# ── named rules: traits, skills, conditions ───────────────────────────────────

_NAMED_TABLES = (
    ("rule_traits", "weapon trait", "takes_value"),
    ("rule_skills", "skill", "skill_set"),
    ("rule_conditions", "condition", "kind"),
    ("rule_equipment", "equipment", "creds_text"),
    ("rule_actions", "action", "cost"),
)


def _strip_value(name: str) -> str:
    """"Blaze (5+)" as printed on a weapon is the trait "Blaze (X+)"."""
    return re.sub(r"\s*\(.*\)\s*$", "", name or "").strip()


def named_rule(name: str) -> str:
    """Look up a weapon trait, skill or condition by name.

    A weapon profile names its traits and explains none of them, so a profile
    is only half an answer until the trait can be read. Matching ignores the
    bracketed value, because a weapon prints "Blaze (5+)" while the trait is
    printed "Blaze (X+)".
    """
    conn = _open()
    if conn is None:
        return _NOT_INSTALLED
    try:
        book = current_rulebook(conn)
        wanted = (name or "").strip().lower()
        if not wanted:
            return "Name a trait, skill or condition to look up."
        bare = _strip_value(wanted)
        out = []
        for table, label, extra in _NAMED_TABLES:
            rows = conn.execute(
                f"SELECT t.name, t.description, t.page, t.{extra} AS extra,"
                f" b.title AS book, b.page_offset FROM {table} t"
                f" JOIN rulebooks b ON b.id = t.rulebook_id"
                f" WHERE (LOWER(t.name) = ? OR LOWER(t.name) LIKE ?"
                f" OR LOWER(t.name) LIKE ?)"
                f" ORDER BY (t.rulebook_id != ?), LENGTH(t.name) LIMIT 3",
                (wanted, f"{bare}%", f"%{wanted}%", book["id"])).fetchall()
            for row in rows:
                detail = ""
                # A gang's own wargear carries no credits here -- its price is
                # on that gang's Equipment List -- so do not print an empty
                # bracket for it.
                if not str(row["extra"] or "").strip():
                    detail = ""
                elif table == "rule_skills":
                    detail = f", {row['extra']} skill"
                elif table == "rule_conditions":
                    detail = f", {row['extra']}"
                elif table == "rule_equipment":
                    detail = f", {row['extra']}"
                elif table == "rule_actions":
                    detail = f", {row['extra']} action"
                source = {"title": row["book"], "page_offset": row["page_offset"]}
                out.append(
                    f"{row['name']} ({label}{detail} — {source['title']}, "
                    f"p{printed_page(row['page'], source)})\n{row['description']}")
        if not out:
            return not_in_book(f"a trait, skill or condition called '{name}'",
                               book)
        return "\n\n".join(out[:3])
    finally:
        conn.close()


def skills_in_set(skill_set: str) -> str:
    """Every skill in one of the book's seven sets."""
    conn = _open()
    if conn is None:
        return _NOT_INSTALLED
    try:
        book = current_rulebook(conn)
        wanted = (skill_set or "").strip().lower()
        rows = conn.execute(
            "SELECT name, skill_set, description, page FROM rule_skills"
            " WHERE rulebook_id = ? AND LOWER(skill_set) LIKE ? ORDER BY name",
            (book["id"], f"%{wanted}%")).fetchall()
        if not rows:
            sets = conn.execute(
                "SELECT DISTINCT skill_set FROM rule_skills WHERE rulebook_id = ?"
                " ORDER BY skill_set", (book["id"],)).fetchall()
            listed = ", ".join(r["skill_set"] for r in sets)
            return f"No skill set matching '{skill_set}'. The sets are: {listed}."
        lines = [f"{rows[0]['skill_set']} skills ({len(rows)}):"]
        for row in rows:
            lines.append(f"  {row['name']} (p{printed_page(row['page'], book)}): "
                         f"{row['description']}")
        return "\n".join(lines)
    finally:
        conn.close()


def weapon_traits(traits: str) -> str:
    """The rules for the traits a weapon carries, in the order printed."""
    conn = _open()
    if conn is None:
        return ""
    try:
        book = current_rulebook(conn)
        out = []
        for printed in [t.strip() for t in (traits or "").split(",") if t.strip()]:
            bare = _strip_value(printed)
            row = conn.execute(
                "SELECT name, description FROM rule_traits WHERE rulebook_id = ?"
                " AND (LOWER(name) = ? OR LOWER(name) LIKE ?)"
                " ORDER BY LENGTH(name) LIMIT 1",
                (book["id"], printed.lower(), f"{bare.lower()}%")).fetchone()
            if row:
                out.append(f"  {printed}: {row['description']}")
        return "\n".join(out)
    finally:
        conn.close()


# ── random tables ─────────────────────────────────────────────────────────────

def _find_table(conn, book_id: int, name: str):
    wanted = (name or "").strip().lower()
    return conn.execute(
        "SELECT t.id, t.title, t.dice, t.notes, t.page, b.title AS book,"
        " b.page_offset FROM rule_tables t"
        " JOIN rulebooks b ON b.id = t.rulebook_id"
        " WHERE (LOWER(t.title) = ? OR LOWER(t.title) LIKE ?)"
        " ORDER BY (t.rulebook_id != ?), LENGTH(t.title) LIMIT 1",
        (wanted, f"%{wanted}%", book_id)).fetchone()


def table_result(name: str, roll: int | None = None) -> str:
    """Resolve a roll on one of the book's tables, rolling it if not given.

    The row's span is stored parsed, so a 54 is found by index rather than by
    reading "51-56" at the table. Without a roll the whole table is listed.
    """
    conn = _open()
    if conn is None:
        return _NOT_INSTALLED
    try:
        book = current_rulebook(conn)
        table = _find_table(conn, book["id"], name)
        if table is None:
            listed = ", ".join(
                r["title"] for r in conn.execute(
                    "SELECT title FROM rule_tables WHERE rulebook_id = ?"
                    " ORDER BY title", (book["id"],)).fetchall()[:12])
            return (not_in_book(f"a table called '{name}'", book)
                    + f" The book has: {listed}.")

        if "book" in table.keys():
            book = {"title": table["book"], "page_offset": table["page_offset"],
                    "id": book["id"]}
        cite = f"{book['title']}, p{printed_page(table['page'], book)}"
        # Not every table is rolled on. The Panicked Pets table is looked up by
        # a Pet's Status, so naming dice it does not use would be wrong.
        dice_note = f" ({table['dice']})" if table["dice"] else ""
        if roll is None:
            rows = conn.execute(
                "SELECT roll_label, result FROM rule_table_rows WHERE table_id = ?"
                " ORDER BY ordinal", (table["id"],)).fetchall()
            lines = [f"{table['title']}{dice_note} — {cite}"]
            lines += [f"  {r['roll_label']}: {r['result']}" for r in rows]
            return "\n".join(lines)

        row = conn.execute(
            "SELECT roll_label, result FROM rule_table_rows WHERE table_id = ?"
            " AND roll_min <= ? AND roll_max >= ? ORDER BY ordinal LIMIT 1",
            (table["id"], int(roll), int(roll))).fetchone()
        if row is None:
            # Say when the row is missing from OUR copy rather than from the
            # book: answering "not on the table" for a result that is printed
            # there is worse than admitting the gap.
            caveat = f" {table['notes']}." if table["notes"] else ""
            return (f"{roll} is not on the {table['title']}{dice_note} — "
                    f"{cite}.{caveat}")
        label = f"{table['dice']} {roll}" if table["dice"] else str(roll)
        return f"{table['title']}, {label}: {row['result']} ({cite})"
    finally:
        conn.close()


def roll_on_table(name: str) -> str:
    """Roll the table's own dice and report the result."""
    conn = _open()
    if conn is None:
        return _NOT_INSTALLED
    try:
        book = current_rulebook(conn)
        table = _find_table(conn, book["id"], name)
        spec = (table["dice"] if table else "D6").upper()
        title = table["title"] if table else name
    finally:
        conn.close()
    # Some tables are read, not rolled: the Panicked Pets table is looked up by
    # a Pet's Status. Rolling a D6 on one would invent a result.
    if table is not None and not spec:
        return (f"The {title} is not rolled on -- it is looked up. "
                f"Ask for it by name instead.")
    if spec == "D66":
        value = dice.d66(1)[0]
    elif spec == "D3":
        value = dice.d3(1)[0]
    elif spec == "2D6":
        value = sum(dice.d6(2))
    elif spec == "3D6":
        value = sum(dice.d6(3))
    elif spec == "D100":
        value = dice.d6(1)[0] * 10 + dice.d6(1)[0]
    else:
        value = dice.d6(1)[0]
    return table_result(name, value)


# ── actions and territories ───────────────────────────────────────────────────

def actions_available(status: str = "active", cost: str = "") -> str:
    """What a model may do, given its status and how much it can spend.

    The question at the table is "it is Seriously Injured, what can it do?" --
    which needs the status and the cost as columns, not as words inside a
    heading.
    """
    conn = _open()
    if conn is None:
        return _NOT_INSTALLED
    try:
        book = current_rulebook(conn)
        wanted = (status or "active").strip().lower().replace(" ", "_")
        sql = ("SELECT name, cost, usable_by, description, page FROM rule_actions"
               " WHERE rulebook_id = ? AND status LIKE ?")
        args: list = [book["id"], f"%{wanted}%"]
        if cost:
            sql += " AND cost = ?"
            args.append(cost.strip().lower())
        rows = conn.execute(sql + " ORDER BY name", args).fetchall()
        if not rows:
            states = ", ".join(r["status"] for r in conn.execute(
                "SELECT DISTINCT status FROM rule_actions WHERE rulebook_id = ?",
                (book["id"],)))
            return f"No actions for '{status}'. The book covers: {states}."
        lines = [f"{len(rows)} action(s) for a {wanted.replace('_', ' ')} model"
                 + (f", {cost}" if cost else "") + ":"]
        for row in rows:
            who = f" [{row['usable_by']}]" if row["usable_by"] else ""
            lines.append(f"  {row['name']} ({row['cost']}){who}: "
                         f"{row['description']} (p{printed_page(row['page'], book)})")
        return "\n".join(lines)
    finally:
        conn.close()


def territory(name: str) -> str:
    """A Territory's Boons and its battlefield effect.

    Boons are reported by type, because the campaign rules act on the type: a
    gang takes the Recruit Boon INSTEAD of the Income Boon.
    """
    conn = _open()
    if conn is None:
        return _NOT_INSTALLED
    try:
        book = current_rulebook(conn)
        wanted = (name or "").strip().lower()
        if not wanted:
            listed = ", ".join(r["name"].title() for r in conn.execute(
                "SELECT name FROM rule_territories WHERE rulebook_id = ? ORDER BY name",
                (book["id"],)))
            return f"The campaign Territories are: {listed}."
        row = conn.execute(
            "SELECT * FROM rule_territories WHERE rulebook_id = ? AND"
            " (LOWER(name) = ? OR LOWER(name) LIKE ?) ORDER BY LENGTH(name) LIMIT 1",
            (book["id"], wanted, f"%{wanted}%")).fetchone()
        if row is None:
            listed = ", ".join(r["name"].title() for r in conn.execute(
                "SELECT name FROM rule_territories WHERE rulebook_id = ? ORDER BY name",
                (book["id"],)))
            return (not_in_book(f"a Territory called '{name}'", book)
                    + f" The book has: {listed}.")
        out = [f"{row['name']} ({book['title']}, p{printed_page(row['page'], book)})"]
        for boon in json.loads(row["boons_json"] or "[]"):
            out.append(f"  {boon['type']} Boon: {boon['text']}")
        if row["battlefield_effect"]:
            out.append(f"  Battlefield effect: {row['battlefield_effect']}")
        return "\n".join(out)
    finally:
        conn.close()


def model_subtype(name: str = "", applies_to: str = "") -> str:
    """A Fighter's or Vehicle's subtype rule, or the list of them.

    ``applies_to`` matters: the book prints a Loner in both lists with
    different rules, so the name alone does not identify one. Asked for a name
    carried by both and told neither list, this returns both rather than
    picking one.
    """
    conn = _open()
    if conn is None:
        return _NOT_INSTALLED
    try:
        book = current_rulebook(conn)
        wanted = (name or "").strip().lower()
        which = (applies_to or "").strip().lower()
        if which.startswith("vehicle"):
            which = "vehicle"
        elif which.startswith("fighter"):
            which = "fighter"
        else:
            which = ""

        def listing(scope: str) -> str:
            rows = conn.execute(
                "SELECT name FROM rule_subtypes WHERE rulebook_id = ?"
                " AND (? = '' OR applies_to = ?) ORDER BY applies_to, name",
                (book["id"], scope, scope)).fetchall()
            return ", ".join(r["name"] for r in rows)

        if not wanted:
            if which:
                return f"The {which} Subtypes are: {listing(which)}."
            return ("The Fighter Subtypes are: " + listing("fighter")
                    + ". The Vehicle Subtypes are: " + listing("vehicle") + ".")
        rows = conn.execute(
            "SELECT * FROM rule_subtypes WHERE rulebook_id = ?"
            " AND (? = '' OR applies_to = ?)"
            " AND (LOWER(name) = ? OR LOWER(name) LIKE ?)"
            " ORDER BY LENGTH(name) LIMIT 2",
            (book["id"], which, which, wanted, f"%{wanted}%")).fetchall()
        if not rows:
            return (not_in_book(f"a Subtype called '{name}'", book)
                    + f" The book has: {listing(which)}.")
        out = []
        for row in rows:
            title = f"{row['name']} (X)" if row["takes_value"] else row["name"]
            out.append(
                f"{title} — {row['applies_to']} Subtype ({book['title']}, "
                f"p{printed_page(row['page'], book)})\n{row['description']}")
        return "\n\n".join(out)
    finally:
        conn.close()


def wound_roll(strength, toughness) -> str:
    """The D6 needed to wound, looked up rather than reasoned about.

    "What do I need to wound Toughness 4 with Strength 3?" is the question
    asked most often at the table. The number was only reachable by resolving
    a whole attack, which rolls dice nobody asked for, or by reading the five
    rows of the table and doing the comparison in your head -- and a comparison
    done in your head is exactly the step this database exists to remove.
    """
    try:
        s, t = int(strength), int(toughness)
    except (TypeError, ValueError):
        return "Give a Strength and a Toughness, both numbers."
    if not (1 <= s <= 20 and 1 <= t <= 20):
        return "Strength and Toughness are between 1 and 20."
    need = attack.wound_target(s, t)
    conn = _open()
    cite = ""
    if conn is not None:
        try:
            book = current_rulebook(conn)
            cite = f" ({book['title']}, p{printed_page(77, book)})"
        finally:
            conn.close()
    reason = ("Strength is twice the Toughness or greater" if s >= 2 * t
              else "Strength is greater than the Toughness" if s > t
              else "Strength is equal to the Toughness" if s == t
              else "Strength is half the Toughness or lower" if 2 * s <= t
              else "Strength is lower than the Toughness")
    return f"Strength {s} against Toughness {t} wounds on {need}+ - {reason}.{cite}"


def gang_variants(gang: str = "", kind: str = "") -> str:
    """The choices a gang makes when it is founded, and what each one grants.

    An Outcast gang picks an Affiliation and its Leader an Archetype, and the
    Archetype decides the Skill Sets every model in the gang may take.
    """
    conn = _open()
    if conn is None:
        return _NOT_INSTALLED
    try:
        want_gang, want_kind = (gang or "").strip().lower(), (kind or "").strip().lower()
        rows = conn.execute(
            "SELECT v.kind, v.name, v.description, v.page, g.name AS gang,"
            " b.title AS book, b.page_offset FROM rule_gang_variants v"
            " JOIN rule_gangs g ON g.id = v.gang_id"
            " JOIN rulebooks b ON b.id = v.rulebook_id"
            " WHERE (? = '' OR LOWER(g.name) LIKE ?)"
            "   AND (? = '' OR LOWER(v.kind) = ?)"
            " ORDER BY g.name, v.kind, v.id",
            (want_gang, f"%{want_gang}%", want_kind, want_kind)).fetchall()
        if not rows:
            listed = ", ".join(sorted({r[0] for r in conn.execute(
                "SELECT DISTINCT g.name FROM rule_gang_variants v"
                " JOIN rule_gangs g ON g.id = v.gang_id")}))
            if not listed:
                return "No gang in the books this unit holds has founding choices."
            return (f"No founding choices recorded for '{gang}'. The gangs that "
                    f"have them: {listed}.")
        out = []
        for row in rows:
            page = row["page"] - row["page_offset"]
            out.append(f"{row['gang']} {row['kind']}: {row['name']} "
                       f"({row['book']}, p{page})\n{row['description']}")
        return "\n\n".join(out)
    finally:
        conn.close()


def fighter_profile(name: str = "", gang: str = "") -> str:
    """A gang fighter's datasheet: cost, statline, Type and what it may take.

    This is the question the core rulebook could not answer at all, because it
    leaves every gang's fighters to their supplement. Asked with a gang and no
    name it lists that gang's roster with costs.
    """
    conn = _open()
    if conn is None:
        return _NOT_INSTALLED
    try:
        wanted, want_gang = (name or "").strip().lower(), (gang or "").strip().lower()
        rows = conn.execute(
            "SELECT f.*, g.name AS gang, b.title AS book, b.page_offset"
            " FROM rule_fighters f"
            " JOIN rule_gangs g ON g.id = f.gang_id"
            " JOIN rulebooks b ON b.id = f.rulebook_id"
            " WHERE (? = '' OR LOWER(f.name) = ? OR LOWER(f.name) LIKE ?)"
            "   AND (? = '' OR LOWER(g.name) LIKE ?)"
            " ORDER BY LENGTH(f.name) LIMIT 6",
            (wanted, wanted, f"%{wanted}%", want_gang, f"%{want_gang}%")).fetchall()
        if not rows:
            installed = [r["name"] for r in conn.execute(
                "SELECT name FROM rule_gangs ORDER BY name")]
            if not installed:
                return ("No gang book is installed on this unit, so this unit "
                        "has no fighter datasheets. Do not supply one from "
                        "memory.")
            listed = ", ".join(installed)
            return (f"No fighter called '{name}' in the gang books this unit "
                    f"holds. Do not supply a profile from memory. Installed "
                    f"gangs: {listed}.")
        if not wanted:
            lines = [f"{rows[0]['gang']} roster ({rows[0]['book']}):"]
            every = conn.execute(
                "SELECT f.name, f.cost, f.type_text FROM rule_fighters f"
                " JOIN rule_gangs g ON g.id = f.gang_id"
                " WHERE LOWER(g.name) LIKE ? ORDER BY f.cost DESC",
                (f"%{want_gang}%",)).fetchall()
            for r in every:
                lines.append(f"  {r['name']} - {r['cost']} credits, {r['type_text']}")
            return "\n".join(lines)
        out = []
        for row in rows[:2]:
            page = row["page"] - row["page_offset"]
            out.append(
                f"{row['name']} - {row['cost']} credits ({row['book']}, p{page})\n"
                f"  {row['type_text']}, starting XP {row['starting_xp']}\n"
                f"  M {row['m_text']}  WS {row['ws_text']}  BS {row['bs_text']}  "
                f"S {row['s_text']}  T {row['t_text']}  W {row['w_text']}  "
                f"I {row['i_text']}  A {row['a_text']}  Sv {row['sv_text']}\n"
                f"  Ld {row['ld_text']}  Cl {row['cl_text']}  "
                f"Wil {row['wil_text']}  Int {row['int_text']}")
            if row["skills_text"]:
                out[-1] += f"\n  {row['skills_text']}"
            if row["equipment_text"]:
                out[-1] += f"\n  Equipment: {row['equipment_text']}"
            for option in json.loads(row["options_json"] or "[]"):
                out[-1] += f"\n    - {option['text']} {option['cost']}"
            access = conn.execute(
                "SELECT variant, skill_set, access FROM rule_skill_access"
                " WHERE gang_id = ? AND (LOWER(?) LIKE '%' || LOWER(fighter) || '%')"
                " AND access != 'none' ORDER BY variant, access, skill_set",
                (row["gang_id"], row["name"])).fetchall()
            # A gang whose Skill Access is printed once lists it flat. One that
            # prints a grid per Archetype lists it per Archetype, because the
            # answer genuinely depends on which was chosen.
            grouped: dict[str, list[str]] = {}
            for a in access:
                grouped.setdefault(a["variant"], []).append(
                    f"{a['skill_set']} ({a['access']})")
            for variant, sets in grouped.items():
                label = "Skills" if not variant else f"Skills as {variant}"
                out[-1] += f"\n  {label}: " + ", ".join(sets)
        return "\n\n".join(out)
    finally:
        conn.close()
