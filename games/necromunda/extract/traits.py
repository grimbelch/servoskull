"""Weapon traits, pulled out as rules in their own right.

Every weapon profile names its traits and nothing else explains them, so a
profile is only half an answer until "Rapid Fire (X)" can be looked up. The
traits are printed alphabetically, each a short name in display type with its
rule beneath, which is the shape ``entries.collect`` reads.

The section is bounded by its own content rather than by page numbers: it runs
from the first trait alphabetically to the start of the index. The contents
list misprints this entry, and the running header is not on every page of it,
so neither can be relied on to find it.
"""
from __future__ import annotations

import re

from . import entries, layout

# The first trait alphabetically, as the traits list prints it. Matching a
# bare "AMMO" instead picks up "AMMO SYMBOL" in the shooting rules ninety
# pages earlier and swallows half the book.
_FIRST_TRAIT = re.compile(r"^AMMO\s*\(X\+?\)")
# Equipment is printed with its price as a heading; traits never are.
_PRICE_HEADING = re.compile(r"\d+\s*CREDITS")
_TAKES_VALUE = re.compile(r"\(.*[X0-9].*\)")
# A trait's rule is a sentence. The weapon accessories printed on the same page
# carry only a shouted qualifier -- "(LAS WEAPONS ONLY)" -- so requiring real
# prose tells the two apart without hard-coding either list.
_HAS_PROSE = re.compile(r"[a-z]{3,}")


def trait_pages(doc, index_page: int | None = None) -> list[int]:
    """The pages the weapon traits run across."""
    start = None
    # The traits are reference material at the back, after the Trading Post.
    for page_no in range(int(doc.page_count * 0.8), doc.page_count):
        for line in layout.page_lines(doc.load_page(page_no)):
            if layout.is_named_entry(line) and _FIRST_TRAIT.match(line["text"].strip()):
                start = page_no
                break
        if start is not None:
            break
    if start is None:
        return []
    end = index_page if index_page is not None else doc.page_count
    return list(range(start, end))


def find_index_page(doc) -> int:
    """Where the index begins; the rules stop there."""
    for page_no in range(doc.page_count - 1, 0, -1):
        for line in layout.page_lines(doc.load_page(page_no)):
            if line["text"].strip().upper() in {"INDEX", "LNDEX"}:
                return page_no
    return doc.page_count


def extract(doc) -> list[dict]:
    """Every weapon trait, with its rule and whether it takes a value."""
    index_page = find_index_page(doc)
    pages = trait_pages(doc, index_page)
    if not pages:
        return []
    found = entries.collect(
        doc, pages,
        skip=("WEAPON TRAITS", "GANG EQUIPMENT", "WEAPON ACCESSORIES",
              "TRADING POST", "GANG EQUIPMENT & WEAPON TRAITS"))
    out = []
    for entry in found:
        name = entry["name"].strip()
        # Equipment shares these pages and is headed by its price.
        if _PRICE_HEADING.search(name) or len(name) < 3:
            continue
        if not _HAS_PROSE.search(entry["description"]):
            continue
        out.append({
            "name": name,
            "description": entry["description"],
            "takes_value": bool(_TAKES_VALUE.search(name)),
            "page": entry["page"],
        })
    return out
