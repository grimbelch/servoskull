"""Model subtypes: the keywords on a card that carry rules of their own.

A model's subtypes are printed on its Model Card -- Champion, Mounted, Skimmer,
Transport (X) -- and each is a rule. They decide what the model may do (a
Walker ignores the turning limits a Wheeled vehicle obeys), so "what does
Mounted do?" is asked constantly and must not be answered from memory.

Two things make this worth a table of its own rather than the heading tree:

* FIGHTER SUBTYPES and VEHICLE SUBTYPES both contain a **Loner**, with
  different rules. The name alone is not a key; ``applies_to`` is.
* Some entries carry a boxed sidebar with its own heading (Pet's Panicked
  table). In the heading tree that box reads as a sibling entry, and the body
  of the entry it interrupts gets attached to the one before it. Here a real
  entry is told from a sidebar by geometry: a subtype's name is flush with its
  column's left edge, and a sidebar's heading is indented inside its box.
"""
from __future__ import annotations

import re

from . import layout, sections

# The two lists, and the heading that opens each.
_LIST_HEADINGS = {
    "FIGHTER SUBTYPES": "fighter",
    "VEHICLE SUBTYPES": "vehicle",
}

# "TRANSPORT (X)" takes a value from the model's card.
_TAKES_VALUE = re.compile(r"\s*\((?:X|N)\)\s*$", re.I)

# A name sitting this far right of its column's left edge is inside a box.
_INDENT_TOLERANCE = 4.0


def column_lefts(lines: list[dict], split: float | None) -> list[float]:
    """Where each column's body text begins.

    Measured from the body rather than assumed, because the margins differ from
    page to page across this spread (64pt on one, 48pt on the next). Short
    lines are ignored: a name, a heading and a table cell all start wherever
    they like, and only running prose reliably marks the column edge.

    Only the LEFTMOST run of text in each column counts. A boxed sidebar is
    indented inside its column and its own body is long enough to look like a
    column of its own; taking the minimum keeps the box's edge from being
    mistaken for the page's, which is the whole basis for telling a subtype's
    name from a sidebar's heading.
    """
    starts: dict[int, int] = {}
    for line in lines:
        if len(line["text"]) < 25:
            continue
        key = int(line["x0"] / 4) * 4
        starts[key] = starts.get(key, 0) + 1
    common = sorted(x for x, n in starts.items() if n >= 4)
    if not common:
        return []
    if split is None:
        return [common[0]]
    left = [x for x in common if x < split]
    right = [x for x in common if x >= split]
    return [edge[0] for edge in (left, right) if edge]


def _is_flush(x0: float, lefts: list[float]) -> bool:
    """True when a heading starts at one of the column edges."""
    return any(abs(x0 - left) <= _INDENT_TOLERANCE + 4 for left in lefts)


def subtype_pages(doc) -> list[int]:
    """The pages the two subtype lists run across."""
    found: list[int] = []
    for page_no in range(doc.page_count):
        lines = layout.page_lines(doc.load_page(page_no))
        header = layout.running_header(lines)
        if "SUBTYPE" in header.upper():
            found.append(page_no)
        elif found and page_no == found[-1] + 1 and not header:
            found.append(page_no)      # a spread's second page carries no header
    return found


def extract(doc) -> list[dict]:
    """Every fighter and vehicle subtype, with the list it belongs to."""
    out: list[dict] = []
    applies_to = ""
    for page_no in subtype_pages(doc):
        page = doc.load_page(page_no)
        split = layout.column_split(page)
        lines = layout.page_lines(page, split=split)
        header = layout.running_header(lines)
        lefts = column_lefts(lines, split)
        body: list[str] = []
        current: dict | None = None

        def flush() -> None:
            nonlocal current, body
            if current is not None:
                current["description"] = sections._join_prose(body)
                out.append(current)
            current, body = None, []

        for line in lines:
            text = line["text"].strip()
            if not text or text == header:
                continue
            if text.upper() in _LIST_HEADINGS:
                flush()
                applies_to = _LIST_HEADINGS[text.upper()]
                continue
            # Before the first list heading the pages carry the MODEL TYPES
            # prose, which is sections' to hold, not ours.
            if not applies_to:
                continue
            if (layout.is_named_entry(line, max_chars=52)
                    and text == text.upper() and _is_flush(line["x0"], lefts)):
                flush()
                current = {
                    "name": _TAKES_VALUE.sub("", text).strip() or text,
                    "applies_to": applies_to,
                    "takes_value": bool(_TAKES_VALUE.search(text)),
                    "description": "",
                    "page": page_no,
                }
                continue
            if current is None or sections._is_tabular(text):
                continue
            body.append(text)
        flush()
    return out


# The Panicked Pets table is printed inside the Pet entry as a two-column grid
# of words, "Ready | Dash" down to "Engaged | Retreat". Flattened into prose in
# reading order it comes out as "... Seriously Injured Crawl Retreat Engaged",
# which pairs Retreat with the wrong Status and would have Omega-7 tell a player
# that an Engaged Panicked Pet must Crawl. The cells are clean in the word rows,
# so it is recovered as a table and answered by lookup.
_PANICKED_HEADER = ("Status", "Action")


def panicked_table(doc) -> dict | None:
    """The Status-to-Action table printed inside the Pet subtype."""
    for page_no in subtype_pages(doc):
        rows = layout.word_rows(doc.load_page(page_no))
        status_x: float | None = None
        action_x: float | None = None
        out: list[dict] = []
        for row in rows:
            words = [(x0, text) for x0, _x1, text in row]
            # The table sits in the right-hand column, so its header row also
            # carries the last line of the left column's prose. Take the two
            # headings by name and let their positions bound the table.
            found = {t: x0 for x0, t in words if t in _PANICKED_HEADER}
            if len(found) == len(_PANICKED_HEADER):
                status_x, action_x = found["Status"], found["Action"]
                out = []
                continue
            if action_x is None or status_x is None:
                continue
            # Anything left of the Status column belongs to the other column.
            cells = [(x0, t) for x0, t in words if x0 >= status_x - 20]
            left = [t for x0, t in cells if x0 < action_x - 20]
            right = [t for x0, t in cells if x0 >= action_x - 20]
            # The table ends where the prose below it resumes. Every cell in
            # it is a Status or an action name -- one word, or two for
            # "Seriously Injured" -- while the prose that follows wraps the
            # full width of the column and splits into long halves.
            if (not left or not right
                    or len(left) > 2 or len(right) > 2):
                if out:
                    break
                continue
            out.append({"roll_label": " ".join(left), "roll_min": None,
                        "roll_max": None, "result": " ".join(right)})
        if len(out) >= 3:
            return {"title": "PANICKED PETS", "kind": "reference", "dice": "",
                    "columns": list(_PANICKED_HEADER), "page": page_no,
                    "rows": out, "missing": []}
    return None
