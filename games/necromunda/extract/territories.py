"""Campaign Territories: what a gang holds between battles.

Each Territory is printed as a card -- its name, a line of flavour, then its
Boons and its Battlefield Effect. The Boons are TYPED, and the type matters to
the rules rather than being decoration: a gang may take a Territory's Recruit
Boon *instead of* its Income Boon, so "which of my Territories can give me a
Rogue Doc?" is a question about types, not about prose.

The cards are printed two to a row, so the page is read a column at a time.
"""
from __future__ import annotations

import re

from . import layout, sections

# The Boon types the campaign rules name.
BOON_TYPES = ("Income", "Recruit", "Equipment", "Reputation", "Special")

_BOON = re.compile(rf"^({'|'.join(BOON_TYPES)}):\s*(.+)$")
_HEADING = re.compile(r"^(TERRITORY BOONS?|BATTLEFIELD EFFECT)$", re.I)
_BOILERPLATE = re.compile(
    r"^This Territory (grants the following|has the following)", re.I)
_FLAVOUR = re.compile(r'^[“"‘\']')
_PAGE_TITLE = re.compile(r"^(CAMPAIGN )?TERRITORIES$", re.I)


def card_split(lines: list[dict]) -> float | None:
    """Where the left card ends and the right one begins.

    Taken from where the cards' BODY text starts, not from the measured gutter.
    A card's name is centred over it while its rules are flush left, so the
    widest blank channel on the page runs between the two centred names and
    sits well right of the right-hand card's own text -- which put "Old Ruins"
    in one column and its rules in the other, and merged them into the card
    beside it.
    """
    starts: dict[int, int] = {}
    for line in lines:
        if len(line["text"]) < 25:        # names and headings are short
            continue
        key = int(line["x0"] / 8) * 8
        starts[key] = starts.get(key, 0) + 1
    common = sorted((x for x, n in starts.items() if n >= 3))
    if len(common) < 2:
        return None
    left, right = common[0], common[-1]
    if right - left < 120:
        return None
    return (left + right) / 2


def territory_pages(doc) -> list[int]:
    """Pages carrying Territory cards, found by the card's own headings."""
    found = []
    for page_no in range(doc.page_count):
        lines = layout.page_lines(doc.load_page(page_no))
        if any(l["text"].strip().upper() == "TERRITORY BOON"
               or l["text"].strip().upper() == "TERRITORY BOONS" for l in lines):
            found.append(page_no)
    return found


def extract(doc) -> list[dict]:
    """Every Territory, with its typed Boons and its battlefield effect."""
    out: list[dict] = []
    for page_no in territory_pages(doc):
        page = doc.load_page(page_no)
        lines = layout.page_lines(page)
        split = card_split(lines)
        if split is not None:
            lines = layout.page_lines(page, split=split)
        header = layout.running_header(lines)
        current: dict | None = None
        mode = ""
        buffer: list[str] = []

        def flush_section() -> None:
            nonlocal buffer
            if current is not None and mode == "effect" and buffer:
                current["battlefield_effect"] = sections._join_prose(buffer)
            buffer = []

        def flush_card() -> None:
            nonlocal current
            flush_section()
            if current is not None and (current["boons"] or current["battlefield_effect"]):
                out.append(current)
            current = None

        for line in lines:
            text = line["text"].strip()
            if not text or text == header or _PAGE_TITLE.match(text):
                continue

            if _HEADING.match(text):
                flush_section()
                mode = "effect" if text.upper().startswith("BATTLEFIELD") else "boon"
                continue

            # A card's name is the only other heading on these pages. The
            # allowance runs to 15pt because the scan sizes these inconsistently
            # -- "Mine Workings" came out 13pt and "Gambling Den" beside it 14pt,
            # and a 13pt ceiling silently merged the second card into the first.
            if (layout.is_named_entry(line, max_size=15, max_chars=34)
                    and not _BOON.match(text)):
                flush_card()
                current = {"name": text, "flavour": "", "boons": [],
                           "battlefield_effect": "", "page": page_no}
                mode = "flavour"
                continue

            if current is None or _BOILERPLATE.match(text):
                continue

            boon = _BOON.match(text)
            if boon:
                flush_section()
                mode = "boon"
                current["boons"].append({"type": boon.group(1), "text": boon.group(2)})
                continue

            if mode == "flavour" and (_FLAVOUR.match(text) or current["flavour"]):
                current["flavour"] = f"{current['flavour']} {text}".strip()
            elif mode == "boon" and current["boons"]:
                current["boons"][-1]["text"] += f" {text}"
            elif mode == "effect":
                buffer.append(text)
        flush_card()
    return out
