"""Named rules: a short name in display type with its description beneath.

Weapon traits, skills and conditions are all printed this way -- "RAPID FIRE
(X)" and then what it does -- and all three were missed by the section
extractor, which looks for chapter headings at 12pt and above. These are set at
the size of body text and told apart by their face, not their size.

Collecting them is what fills the ``rule_traits``, ``rule_skills`` and
``rule_conditions`` tables, so that "what does Blaze do" is a row lookup rather
than a search of prose that happens to mention it.
"""
from __future__ import annotations

import re

from . import layout, sections

# A name is upper case and may carry a bracketed value or a qualifier:
# "AMMO (X+)", "BLAST (3"/5")", "2. COMBAT MASTER".
_NAME = re.compile(r"^[0-9]*\.?\s*[A-Z][A-Z0-9 ()/&'’“”\"+\-.,]*$")
# A trailing qualifier printed on its own line under the name.
_QUALIFIER = re.compile(r"^\(.*\)$")


def _clean_name(text: str) -> str:
    """Drop the list number the book prints before a skill's name."""
    return re.sub(r"^\s*\d+\.\s*", "", text).strip()


def collect(doc, page_numbers, min_size: int = 9, max_size: int = 13,
            skip: tuple[str, ...] = ()) -> list[dict]:
    """Every named entry on the given pages, with the prose under each.

    ``skip`` names headings that introduce a page rather than an entry (a
    running header, a section title), which would otherwise be collected as a
    rule with the first paragraph of the next one as its description.
    """
    out: list[dict] = []
    for page_no in page_numbers:
        page = doc.load_page(page_no)
        lines = layout.page_lines(page)
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
            if not text or text == header or text.upper() in skip:
                continue
            if layout.is_named_entry(line, min_size, max_size) and _NAME.match(text):
                # A qualifier under the name belongs to it, not to a new rule.
                if current is not None and not body and _QUALIFIER.match(text):
                    current["name"] = f"{current['name']} {text}"
                    continue
                flush()
                current = {"name": _clean_name(text), "description": "",
                           "page": page_no}
                continue
            if current is None or sections._is_tabular(text):
                continue
            body.append(text)
        flush()
    return out


def pages_with_header(doc, needle: str, limit: int | None = None) -> list[int]:
    """Pages whose running header contains ``needle``.

    The section a rule belongs to is named at the top of its page, which is the
    only place this book says so -- it has no bookmark outline.
    """
    found = []
    for page_no in range(limit or doc.page_count):
        header = layout.running_header(layout.page_lines(doc.load_page(page_no)))
        if needle.upper() in header.upper():
            found.append(page_no)
    return found
