"""Equipment, armour and weapon accessories from the Trading Post.

Each item is printed as its name, then its price on the next line, then what it
does -- "BIO-BOOSTER / 25 CREDITS - TP 0 / The first time in each battle...".
The two heading lines are joined back together by the section builder, so an
item is simply a section whose title carries a price, and this reads the name,
the cost and the Trade Points back out of it.

Extracting them as rows is what makes "what does a medicae kit cost" a lookup
rather than a search, and lets the whole Trading Post be listed by category.
"""
from __future__ import annotations

import re

from . import entries, sections

# "25 CREDITS - TP 0", with the dash in whatever form the scan produced.
_PRICE = re.compile(
    r"(?P<creds>[+-]?\d+)\s*CREDITS\s*[-–—:]?\s*TP\s*(?P<tp>\d+)", re.I)
# Some wargear prints two prices under one name, each labelled: carapace
# armour is "LIGHT: 100 CREDITS - TP 1 / HEAVY: 140 CREDITS - TP 3". Read as a
# single price the second is lost and the label ends up inside the item's name.
_VARIANT = re.compile(r"(?P<label>[A-Z][A-Za-z]*)\s*:\s*$")

# Category headings the Trading Post prints above a run of items.
_CATEGORIES = {
    "PERSONAL EQUIPMENT": "personal",
    "GANG EQUIPMENT": "gang",
    "ARMOUR": "armour",
    "FIELD ARMOUR": "field_armour",
    "WEAPON ACCESSORIES": "accessory",
    "ARMOUR & FIELD ARMOUR": "armour",
}


def _category_for(title: str, current: str) -> str:
    """The category a heading announces, or the one still in force."""
    upper = title.upper().strip()
    for name, slug in _CATEGORIES.items():
        if upper.startswith(name):
            return slug
    return current


def extract(doc, tree: list[dict] | None = None) -> list[dict]:
    """Every priced item, with its cost, Trade Points and rules."""
    tree = tree if tree is not None else sections.build_tree(doc)
    out: list[dict] = []
    category = ""
    for item in tree:
        title = item["title"].strip()
        category = _category_for(title, category)
        prices = list(_PRICE.finditer(title))
        if not prices:
            continue
        # The name is whatever precedes the first price, with any category
        # heading that merged into it stripped back off.
        raw_name = title[:prices[0].start()].strip()
        name = raw_name.strip(" -\u2013\u2014:")
        for heading in _CATEGORIES:
            if name.upper().startswith(heading):
                name = name[len(heading):].strip(" -\u2013\u2014:")
        # The first variant's own label sits in front of its price and so
        # lands on the end of the base name: "Carapace Armour Light".
        # Matched on the raw title but removed by text, not by offset: the
        # category prefix is stripped in between, so the offsets no longer line
        # up and "Carapace Armour Light" kept its label.
        first_label = _VARIANT.search(raw_name)
        if first_label:
            label = first_label.group("label")
            if name.upper().endswith(label.upper()):
                name = name[: -len(label)].strip(" -\u2013\u2014:")
        name, usable_by = entries.split_qualifier(name)
        if not name:
            continue

        for index, match in enumerate(prices):
            # A label printed just before a price names that variant, so
            # carapace armour becomes Light and Heavy rather than one row with
            # the second price thrown away and "Light" stuck in its name.
            before = title[prices[index - 1].end() if index else 0:match.start()]
            label = _VARIANT.search(before.strip())
            variant = label.group("label").title() if label else ""
            if index == 0 and not variant and first_label:
                variant = first_label.group("label").title()
            if not variant and index:
                variant = f"option {index + 1}"
            out.append({
                "name": f"{name} ({variant})" if variant else name,
                "base_name": name,
                "variant": variant,
                "usable_by": usable_by,
                "category": category,
                "creds": int(match.group("creds")),
                "creds_text": f"{match.group('creds')} credits",
                "trading_post": int(match.group("tp")),
                "tp_text": match.group("tp"),
                "description": item["body"],
                "page": item["page"],
            })
    return out
