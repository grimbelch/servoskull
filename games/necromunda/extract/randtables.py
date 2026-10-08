"""The book's random tables, as rows that can be rolled on.

A table is printed as a title, a header row naming the dice ("D66 | Lasting
Injury"), and then one row per result with its roll in the left column: 11, 12,
then spans like 21-26 and 63-65. Stored as prose it is a wall of text and "I
rolled 54" cannot be answered; stored as rows with the span parsed out, it is
an index lookup.

Rows wrap, and a continuation line simply carries no roll of its own, which is
how it is told from the start of the next result.
"""
from __future__ import annotations

import re

from . import layout

# The dice a table is rolled on, as printed in its header cell.
_DICE = re.compile(r"^(D3|D6|D66|D100|2D6|3D6)$", re.I)
# A roll: a single result, a span, or an open top end.
_ROLL = re.compile(r"^(?P<lo>\d{1,3})\s*(?:[-–—]\s*(?P<hi>\d{1,3})|(?P<plus>\+))?$")
_TITLE = re.compile(r"\bTABLE\b", re.I)


def _parse_roll(label: str):
    """(min, max) for a printed roll, or None when it is not one."""
    match = _ROLL.match(label.strip())
    if not match:
        return None
    low = int(match.group("lo"))
    if match.group("hi"):
        return low, int(match.group("hi"))
    if match.group("plus"):
        return low, 999
    return low, low


def extract(doc) -> list[dict]:
    """Every random table in the book, with its rows."""
    out: list[dict] = []
    for page_no in range(doc.page_count):
        page = doc.load_page(page_no)
        rows = layout.word_rows(page)
        title = ""
        current: dict | None = None

        for row in rows:
            words = [t for _, _, t in row]
            if not words:
                continue
            text = " ".join(words).strip()

            # A heading naming a table applies to the next header row seen.
            if _TITLE.search(text) and len(text) < 60:
                title = text
                continue

            # The header row opens a table and names its dice.
            if _DICE.match(words[0]):
                if current and current["rows"]:
                    out.append(current)
                current = {
                    "title": title or f"{words[0].upper()} table",
                    "dice": words[0].upper(),
                    "columns": words[1:],
                    "page": page_no,
                    "rows": [],
                }
                continue

            if current is None:
                continue

            span = _parse_roll(words[0])
            if span is None:
                # No roll of its own: the previous result running on.
                if current["rows"] and len(text) < 120:
                    current["rows"][-1]["result"] += f" {text}"
                    continue
                # Anything else ends the table.
                if current["rows"]:
                    out.append(current)
                current = None
                continue

            current["rows"].append({
                "roll_label": words[0],
                "roll_min": span[0],
                "roll_max": span[1],
                "result": " ".join(words[1:]).strip(),
            })
        if current and current["rows"]:
            out.append(current)
    return [t for t in out if len(t["rows"]) >= 3]
