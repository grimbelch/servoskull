"""Conditions and model statuses: the things that gate what a model may do.

Both are printed as a short name in display type with its rule beneath, and
both answer the same kind of question at a table -- "what does Suppressed stop
me doing?" -- so they share a table and are told apart by ``kind``.

Status is a new-edition concept (Active, Engaged, Suppressed, Seriously
Injured/Damaged) and is what the injury resolver moves a model between.
"""
from __future__ import annotations

import re

from . import entries, layout

# The spread after the statuses shows the physical markers used to track them.
# Those are components, not rules: "Suppressed Marker" is a piece of card.
_NOT_A_RULE = re.compile(r"\b(MARKER|MARKERS|TABLE)$|^LAYING\b")


def _section_pages(doc, needle: str) -> list[int]:
    """Pages whose running header names the section, plus any continuation.

    A spread's second page frequently carries no running header of its own, so
    following pages are taken until one announces a different section.
    """
    pages: list[int] = []
    for page_no in range(doc.page_count):
        header = layout.running_header(layout.page_lines(doc.load_page(page_no)))
        if needle.upper() in header.upper():
            pages.append(page_no)
        elif pages and not header and page_no == pages[-1] + 1:
            pages.append(page_no)
        elif pages and header:
            break
    return pages


def extract(doc) -> list[dict]:
    """Every condition and model status, with its rule."""
    out: list[dict] = []
    seen: set[str] = set()
    for needle, kind, skip in (
            ("MODEL STATUS", "status",
             ("MODEL STATUS", "SHOWING CONDITIONS & STATUSES",
              "MULTIPLE STATUSES")),
            ("CONDITIONS", "condition", ("CONDITIONS",))):
        pages = _section_pages(doc, needle)
        for entry in entries.collect(doc, pages, max_size=15, skip=skip):
            name = entry["name"].strip()
            key = name.upper()
            if len(name) < 3 or key in seen or _NOT_A_RULE.search(key):
                continue
            seen.add(key)
            out.append({"name": name, "kind": kind,
                        "description": entry["description"],
                        "page": entry["page"]})
    return out
