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

from . import layout, sections

# The dice a table is rolled on, as printed in its header cell.
_DICE = re.compile(r"^(D3|D6|D66|D100|2D6|3D6)$", re.I)
# A roll: a single result, a span, or an open top end.
_ROLL = re.compile(r"^(?P<lo>\d{1,3})\s*(?:[-–—]\s*(?P<hi>\d{1,3})|(?P<plus>\+))?$")
# A table's title is a heading, not any sentence that happens to mention one.
# Matching prose gave a table called "the Perils of the Warp table." -- lifted
# out of "...must roll on the Perils of the Warp table below".
_TITLE = re.compile(r"^[A-Z0-9][A-Z0-9 '’&()/\-]*\bTABLE\b[A-Z0-9 '’&()/\-]*$")


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


# Kept as a local name: the table reader asks this about a row, and the prose
# reader asks it about a line, but it is one question.
_is_rubble = layout.is_rubble


def _side_by_side_split(rows) -> float | None:
    """Where to cut a page that prints two tables beside each other.

    A header naming its dice twice -- "D6 Deployment Zone D6 Deployment Zone"
    -- is two tables level with each other, and read as one row their results
    merge into each other. The second dice token marks the second table's left
    edge. The Deployment table was lost to this entirely: merged, it had a
    single row and fell under the minimum.
    """
    for row in rows:
        dice_at = [x0 for x0, _x1, text in row if _DICE.match(text)]
        if len(dice_at) >= 2:
            return dice_at[1] - 4
    return None


def extract(doc) -> list[dict]:
    """Every random table in the book, with its rows."""
    out: list[dict] = []
    previous: dict | None = None
    for page_no in range(doc.page_count):
        page = doc.load_page(page_no)
        rows = layout.word_rows(page)
        split = _side_by_side_split(rows)
        if split is not None:
            rows = layout.word_rows(page, split=split)
        title = ""
        heading = ""
        current: dict | None = None
        row_index = -1

        for row in rows:
            row_index += 1
            words = [t for _, _, t in row]
            if not words:
                continue
            text = " ".join(words).strip()

            # A heading naming a table applies to the next header row seen;
            # any other heading is remembered as a fallback, because plenty of
            # tables are introduced by a heading that does not say "table".
            if _TITLE.search(text) and len(text) < 60:
                title = text
                continue
            # Only real words can title a table. The dict handed to is_heading
            # claims display type, because word_rows carries no font, so
            # without this any short line at all became a heading.
            if (not _is_rubble(text) and text == text.upper()
                    and layout.is_heading({"text": text, "size": 12,
                                           "bold": 1.0, "display": 1.0})
                    and len(text) < 60):
                heading = text
                continue

            # The header row opens a table and names its dice.
            if _DICE.match(words[0]):
                if current and current["rows"]:
                    out.append(current)
                    previous = current
                columns = words[1:]
                # A table running on over the page break repeats its header and
                # is given no title of its own; without this the second half
                # becomes a separate, nameless table.
                # A repeated header continues the table before it only while
                # no new heading has intervened. The Deployment table is five
                # headers under one heading -- printed two cards to a row over
                # two pages -- and must come back as one table of six. The
                # Escape and Medical Escort tables are also both "D6 | Result",
                # but each sits under its own heading, and merging those put
                # one table's results under the other's name.
                # Either no heading has been seen on this page -- the Gang
                # Tactics table simply repeats its header at the top of the
                # next page -- or the heading is still the one the previous
                # table sat under, which is the Deployment table printed as
                # five side-by-side blocks beneath a single heading.
                same_heading = previous is not None and (
                    heading == "" or heading == previous.get("heading", ""))
                # Where this block's result column begins, for telling its own
                # wrapped lines from a neighbour's. The cards are printed side
                # by side, so each repeat of the header moves it.
                result_x = row[1][0] if len(row) > 1 else None
                if (not title and same_heading and previous is not None
                        and previous["dice"] == words[0].upper()
                        and previous["columns"] == columns):
                    current = previous
                    current["result_x"] = result_x
                    out.remove(previous) if previous in out else None
                    continue
                current = {
                    "title": title or heading or f"{words[0].upper()} table",
                    "dice": words[0].upper(),
                    "columns": columns,
                    "heading": heading,
                    "page": page_no,
                    "result_x": result_x,
                    "rows": [],
                }
                continue

            if current is None:
                continue

            span = _parse_roll(words[0])
            if span is None:
                # No roll of its own: the previous result running on. Diagram
                # debris sits between the cards and is not part of either.
                if _is_rubble(text):
                    continue
                # A wrapped line of a result sits under the result column. Text
                # starting well away from it belongs to another block: the
                # Deployment table's first result ran on into the right-hand
                # half of the page's own two-column introduction.
                anchor = current.get("result_x")
                if anchor is not None and abs(row[0][0] - anchor) > 20:
                    continue
                if current["rows"] and len(text) < 120:
                    previous_result = current["rows"][-1]["result"]
                    match = sections._HYPHEN_BREAK.search(previous_result)
                    current["rows"][-1]["result"] = (
                        previous_result[: match.end()] + text
                        if match else f"{previous_result} {text}")
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
                "result": sections.repair_scan(" ".join(words[1:]).strip()),
            })
        if current and current["rows"]:
            out.append(current)
            # A table running on to the next page needs this as its anchor; the
            # end-of-page flush used not to set it, so the Gang Tactics table's
            # second half became a separate, nameless table.
            previous = current
    return _merge_fragments([t for t in out if t["rows"]])


def _is_generic(title: str) -> bool:
    return title.endswith(" table") and title.split()[0].upper() == title.split()[0]


def _merge_fragments(tables: list[dict]) -> list[dict]:
    """Join the pieces of a table printed as several blocks.

    The Deployment table is six results printed two to a row across a spread,
    so it arrives as six one-row tables. Pieces are joined when they share
    their dice and columns, sit on the same page or the next, and do not each
    carry a title of their own. A partially recovered table is worse than none:
    a lookup would confidently answer "not on the table" for the rolls that
    went missing.
    """
    merged: list[dict] = []
    for table in tables:
        host = merged[-1] if merged else None
        if (host is not None
                and host["dice"] == table["dice"]
                and host["columns"] == table["columns"]
                and 0 <= table["page"] - host["page"] <= 1
                and (_is_generic(table["title"]) or table["title"] == host["title"])):
            seen = {r["roll_label"] for r in host["rows"]}
            host["rows"] += [r for r in table["rows"] if r["roll_label"] not in seen]
            continue
        merged.append(table)
    kept = [t for t in merged if len(t["rows"]) >= 3]
    for table in kept:
        # Side-by-side blocks arrive in band order, not roll order, so the
        # Deployment table came back 1, 2, 3, 5, 4, 6.
        table["rows"].sort(
            key=lambda r: (r["roll_min"] if r["roll_min"] is not None else 0))
    for table in kept:
        table["missing"] = _missing_results(table)
    return kept


# What each dice can actually produce, for checking a table covers it.
_RANGES = {"D3": range(1, 4), "D6": range(1, 7), "2D6": range(2, 13)}


def _missing_results(table: dict) -> list[int]:
    """Results the dice can roll that the table has no row for.

    A partly recovered table is the dangerous kind: asked for a roll that went
    missing it answers "not on the table" with as much confidence as a real
    answer. Recording the gap lets a lookup say so instead. D66 is left alone
    -- its tables are legitimately sparse and span ranges.
    """
    span = _RANGES.get(table["dice"].upper())
    if not span:
        return []
    covered = set()
    for row in table["rows"]:
        covered.update(range(row["roll_min"], min(row["roll_max"], max(span)) + 1))
    return [value for value in span if value not in covered]


# The Pitch Black table is printed with its roll centred beside a result that
# runs over two lines, so the roll sits on a line of its own between them:
# "Full Night Cycle: The Visibility (3")", then "1", then "rule is in effect."
# Read as rows that is three unrelated fragments, and the flattened prose came
# out "Full Night Cycle: The Visibility (3") 1 rule is in effect." -- the roll
# buried mid-sentence and nothing to look up. The roll is centred ON its own
# result, so each line of result text belongs to the roll nearest it.
_PITCH_BLACK_TITLE = "PITCH BLACK TABLE"


def pitch_black_table(doc) -> dict | None:
    """The Visibility a battle is fought in, by a D6 roll."""
    for page_no in range(doc.page_count):
        page = doc.load_page(page_no)
        words = page.get_text("words")
        heading = [w for w in words if w[4] == "PITCH"]
        if not heading or not any(w[4] == "TABLE" for w in words):
            continue
        header = [w for w in words if w[4] == "D6"]
        results = [w for w in words if w[4] == "Result"]
        if not header or not results:
            continue
        roll_x, result_x = header[-1][0], results[-1][0]
        if result_x <= roll_x:
            continue
        top = max(w[3] for w in heading)

        def centre(word) -> float:
            return (word[1] + word[3]) / 2

        rolls: dict[float, str] = {}
        body: list = []
        for word in words:
            if centre(word) <= top or word[4] in ("D6", "Result"):
                continue
            if roll_x - 8 <= word[0] < result_x - 20:
                if _parse_roll(word[4]) is not None:
                    rolls[centre(word)] = word[4]
            elif word[0] >= result_x - 8:
                body.append(word)
        if len(rolls) < 3:
            continue

        # Group the result text into lines by baseline. Bucketing to a fixed
        # width split a line wherever the scan's baseline jitter crossed a
        # bucket edge, which shuffled "Full Night Cycle: The Visibility (3")"
        # into "Visibility (3") Full Night Cycle: The".
        lines: list[list] = []
        for word in sorted(body, key=centre):
            if lines and abs(centre(word) - centre(lines[-1][0])) <= 2.5:
                lines[-1].append(word)
            else:
                lines.append([word])

        # Each line of result text joins the roll centred nearest it.
        collected: dict[str, list[tuple[float, str]]] = {}
        for line in lines:
            row = sorted(line, key=lambda w: w[0])
            y = sum(centre(w) for w in row) / len(row)
            nearest = min(rolls, key=lambda ry: abs(ry - y))
            if abs(nearest - y) > 24:
                continue
            collected.setdefault(rolls[nearest], []).append(
                (y, " ".join(w[4] for w in row)))
        out = []
        for label, parts in collected.items():
            span = _parse_roll(label)
            out.append({"roll_label": label, "roll_min": span[0],
                        "roll_max": span[1],
                        "result": " ".join(t for _y, t in sorted(parts))})
        if len(out) < 3:
            continue
        out.sort(key=lambda r: r["roll_min"])
        return {"title": _PITCH_BLACK_TITLE, "kind": "scenario", "dice": "D6",
                "columns": ["D6", "Result"], "page": page_no, "rows": out,
                "missing": []}
    return None
