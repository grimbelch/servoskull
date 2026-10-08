"""Deterministic Necromunda lookups.

These read the extracted columns rather than searching prose, so a stat question
is answered by the value the book printed and not by whatever a text match
happened to surface. ``search.necromunda_rules`` remains the right tool for "how
does this work" questions; these are for "what is this weapon's AP".
"""
from __future__ import annotations

import sqlite3

from . import db as necro_db
from . import dice
from .search import _NOT_INSTALLED, _format_weapon, printed_page

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
        book = conn.execute(
            "SELECT title, edition, page_offset FROM rulebooks ORDER BY id LIMIT 1").fetchone()
        wanted = (name or "").strip().lower()
        if not wanted:
            return "Name a weapon to look up."
        rows = conn.execute(
            "SELECT * FROM rule_weapons WHERE LOWER(name) = ?"
            " ORDER BY needs_review, (creds IS NULL), (category = ?), id",
            (wanted, _EXAMPLE_CATEGORY)).fetchall()
        if not rows:
            rows = conn.execute(
                "SELECT * FROM rule_weapons WHERE LOWER(name) LIKE ?"
                " ORDER BY needs_review, (creds IS NULL), (category = ?),"
                " LENGTH(name), id", (f"%{wanted}%", _EXAMPLE_CATEGORY)).fetchall()
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
            "SELECT * FROM rule_weapons WHERE page = ? AND id > ? ORDER BY id LIMIT 8",
            (best["page"], best["id"])).fetchall()
        for row in following:
            if not row["is_variant"]:
                break
            out.append(_format_weapon(row, book))
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
        book = conn.execute(
            "SELECT title, edition, page_offset FROM rulebooks ORDER BY id LIMIT 1").fetchone()
        wanted = (category or "").strip().lower()
        rows = conn.execute(
            "SELECT name, sr_text, lr_text, str_text, ap_text, lethality_text,"
            " creds_text, tp_text, traits, is_variant, page FROM rule_weapons"
            " WHERE LOWER(category) LIKE ? ORDER BY id", (f"%{wanted}%",)).fetchall()
        if not rows:
            cats = conn.execute(
                "SELECT DISTINCT category FROM rule_weapons WHERE category != ''"
                " ORDER BY category").fetchall()
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
        row = conn.execute(
            "SELECT lethality FROM rule_weapons WHERE LOWER(name) = ? AND lethality"
            " IS NOT NULL ORDER BY needs_review, id LIMIT 1",
            ((name or "").strip().lower(),)).fetchone()
        if row is None:
            row = conn.execute(
                "SELECT lethality FROM rule_weapons WHERE LOWER(name) LIKE ? AND"
                " lethality IS NOT NULL ORDER BY needs_review, LENGTH(name), id LIMIT 1",
                (f"%{(name or '').strip().lower()}%",)).fetchone()
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
