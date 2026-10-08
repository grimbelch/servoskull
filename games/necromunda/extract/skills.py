"""Skills, grouped under the seven sets the book prints them in.

A skill is a short ALL CAPS name in display type with its rule beneath, like a
weapon trait, but each belongs to a set -- Agility, Brawn, Combat, Cunning,
Savant, Shooting, Inherent -- and the set is printed as a chapter heading above
the run of skills in it. Knowing the set is most of the value: the question at
a table is "what are the Cunning skills?" as often as "what does Backstab do?".
"""
from __future__ import annotations

import re

from . import entries, layout, sections

# The seven sets this edition has, as the contents lists them. The previous
# edition's Ferocity, Leadership and Driving are gone.
SKILL_SETS = ("AGILITY", "BRAWN", "COMBAT", "CUNNING", "SAVANT", "SHOOTING",
              "INHERENT")

_NUMBERED = re.compile(r"^\s*\d+\.\s")
# A weapon profile is printed inside some skills, and its column headers are
# set in the same type as a skill's name.
_TABLE_TOKENS = {"SR", "LR", "STR", "AP", "L", "TRAITS", "CREDS", "TP", "NAME"}


def skill_pages(doc) -> list[int]:
    """The pages the skills run across, found from the sets printed on them.

    Taken as the longest unbroken run of such pages. "SHOOTING" is also the
    heading of the shooting rules ninety pages earlier, and reading that page
    as a skill set turns "Declare the Shot" and "Measure Range" into Shooting
    skills. The skills themselves are consecutive; a lone page is not them.
    """
    candidates = []
    for page_no in range(doc.page_count):
        lines = layout.page_lines(doc.load_page(page_no))
        if any(l["text"].strip().upper() in SKILL_SETS and layout.is_heading(l)
               for l in lines):
            candidates.append(page_no)

    best: list[int] = []
    run: list[int] = []
    for page_no in candidates:
        if run and page_no == run[-1] + 1:
            run.append(page_no)
        else:
            run = [page_no]
        if len(run) > len(best):
            best = list(run)
    # The set that opens the run is often named on the page before it.
    if best and best[0] > 0:
        best = [best[0] - 1] + best
    return best


def extract(doc) -> list[dict]:
    """Every skill, with its set and its rule."""
    out: list[dict] = []
    current_set = ""
    for page_no in skill_pages(doc):
        lines = layout.page_lines(doc.load_page(page_no))
        header = layout.running_header(lines)
        body: list[str] = []
        current: dict | None = None

        def flush() -> None:
            nonlocal current, body
            if current is not None:
                current["description"] = sections._join_prose(body)
                if current["description"]:
                    out.append(current)
            current, body = None, []

        for line in lines:
            text = line["text"].strip()
            if not text or text == header:
                continue
            if text.upper() in SKILL_SETS and layout.is_heading(line):
                flush()
                current_set = text.upper()
                continue
            # Most sets number their skills, but the Inherent ones are listed
            # alphabetically with no numbers at all, so numbering cannot be
            # required -- insisting on it dropped that whole set. The set
            # heading is matched above, so anything else named here is a skill.
            if layout.is_named_entry(line) and current_set:
                # A skill's qualifier is sometimes printed on its own line
                # beneath the name. Read as a name it starts a new skill,
                # which both loses the real name and invents a rule called
                # "(Fighter or Walker Only)".
                if (current is not None and not body
                        and entries._QUALIFIER.match(text)):
                    current["name"] = f"{current['name']} {text}"
                    continue
                # Stat table headers sit in the same type as a name.
                if len(text) < 4 or text.upper() in _TABLE_TOKENS:
                    continue
                flush()
                bare, usable_by = entries.split_qualifier(entries._clean_name(text))
                current = {"name": bare, "usable_by": usable_by,
                           "skill_set": current_set.title(),
                           "description": "", "page": page_no}
                continue
            if current is None or sections._is_tabular(text):
                continue
            body.append(text)
        flush()
    return out
