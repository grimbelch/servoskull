"""Actions: what a model may do when it activates.

An action is the unit of play. Each costs Single, Double or Free, and which
actions are open to a model depends on its status -- Active models have the
full list, Engaged models may only Fight or Retreat, Seriously Injured Fighters
may only Crawl, Desperate Escape or Tend Wounds.

All of that is printed in headings: the cost in brackets after the name, the
status as the heading above the run. Held as prose it cannot be asked for, and
"what can I do while Seriously Injured?" is a question asked every other turn.
"""
from __future__ import annotations

import re

from . import entries, layout, sections

# Most actions carry their restriction in the first line of their rules rather
# than in the heading: "This action may only be performed by Fighters."
_RESTRICTION = re.compile(
    r"may only be performed by (?:a |an )?([A-Z][A-Za-z]*)s?\b")

# The heading above a run of actions says which models they are open to.
_STATUS_HEADINGS = {
    "MODEL ACTIONS": "active",
    "ENGAGED MODELS": "engaged",
    "SERIOUSLY INJURED FIGHTERS": "seriously_injured",
    "SERIOUSLY DAMAGED VEHICLES": "seriously_damaged",
}


def action_pages(doc) -> list[int]:
    """The pages the action list runs across."""
    found = []
    for page_no in range(doc.page_count):
        header = layout.running_header(layout.page_lines(doc.load_page(page_no)))
        if "ACTIONS" in header.upper():
            found.append(page_no)
        elif found and page_no == found[-1] + 1 and not header:
            found.append(page_no)      # a spread's second page carries no header
    return found


def extract(doc) -> list[dict]:
    """Every action, with its cost, who may take it and when."""
    out: list[dict] = []
    status = "active"
    for page_no in action_pages(doc):
        lines = layout.page_lines(doc.load_page(page_no))
        header = layout.running_header(lines)
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
            if text.upper() in _STATUS_HEADINGS:
                flush()
                status = _STATUS_HEADINGS[text.upper()]
                continue
            name, cost = entries.split_cost(text)
            # Only a bracketed cost makes a heading an action; everything else
            # on these pages is ordinary prose or a sidebar.
            if cost and layout.is_named_entry(line, max_chars=52):
                flush()
                bare, usable_by = entries.split_qualifier(name)
                current = {"name": bare or name, "cost": cost,
                           "usable_by": usable_by, "status": status,
                           "description": "", "page": page_no}
                continue
            if current is None or sections._is_tabular(text):
                continue
            body.append(text)
        flush()

    for action in out:
        if not action["usable_by"]:
            match = _RESTRICTION.search(action["description"])
            if match:
                action["usable_by"] = f"{match.group(1)} only"
    return out
