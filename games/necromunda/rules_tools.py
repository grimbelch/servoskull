"""Deterministic Necromunda lookups.

These read the extracted columns rather than searching prose, so a stat question
is answered by the value the book printed and not by whatever a text match
happened to surface. ``search.necromunda_rules`` remains the right tool for "how
does this work" questions; these are for "what is this weapon's AP".
"""
from __future__ import annotations

import re
import sqlite3

from . import db as necro_db
from . import dice
from .search import _NOT_INSTALLED, _format_weapon, current_rulebook, printed_page

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
        rows = conn.execute(
            "SELECT * FROM rule_weapons WHERE rulebook_id = ? AND LOWER(name) = ?"
            " ORDER BY needs_review, (creds IS NULL), (category = ?), id",
            (book["id"], wanted, _EXAMPLE_CATEGORY)).fetchall()
        if not rows:
            rows = conn.execute(
                "SELECT * FROM rule_weapons WHERE rulebook_id = ? AND LOWER(name) LIKE ?"
                " ORDER BY needs_review, (creds IS NULL), (category = ?),"
                " LENGTH(name), id",
                (book["id"], f"%{wanted}%", _EXAMPLE_CATEGORY)).fetchall()
        if not rows:
            return (f"No weapon called '{name}' in {book['title']}. It may belong to a "
                    "gang's own equipment list, which is in that gang's supplement "
                    "rather than the core rulebook.")

        best = rows[0]
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
            "SELECT lethality FROM rule_weapons WHERE rulebook_id = ? AND"
            " LOWER(name) = ? AND lethality IS NOT NULL"
            " ORDER BY needs_review, id LIMIT 1",
            (book["id"], (name or "").strip().lower())).fetchone()
        if row is None:
            row = conn.execute(
                "SELECT lethality FROM rule_weapons WHERE rulebook_id = ? AND"
                " LOWER(name) LIKE ? AND lethality IS NOT NULL"
                " ORDER BY needs_review, LENGTH(name), id LIMIT 1",
                (book["id"], f"%{(name or '').strip().lower()}%")).fetchone()
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
                f"SELECT name, description, page, {extra} AS extra FROM {table}"
                f" WHERE rulebook_id = ? AND (LOWER(name) = ? OR LOWER(name) LIKE ?"
                f" OR LOWER(name) LIKE ?)"
                f" ORDER BY LENGTH(name) LIMIT 3",
                (book["id"], wanted, f"{bare}%", f"%{wanted}%")).fetchall()
            for row in rows:
                detail = ""
                if table == "rule_skills":
                    detail = f", {row['extra']} skill"
                elif table == "rule_conditions":
                    detail = f", {row['extra']}"
                out.append(
                    f"{row['name']} ({label}{detail} — {book['title']}, "
                    f"p{printed_page(row['page'], book)})\n{row['description']}")
        if not out:
            return (f"No trait, skill or condition called '{name}' in "
                    f"{book['title']}.")
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
