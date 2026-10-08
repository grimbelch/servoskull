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

from . import sections

# "25 CREDITS - TP 0", with the dash in whatever form the scan produced.
_PRICE = re.compile(
    r"(?P<creds>[+-]?\d+)\s*CREDITS\s*[-–—:]?\s*TP\s*(?P<tp>\d+)", re.I)
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
        match = _PRICE.search(title)
        if not match:
            continue
        # The name is whatever precedes the price, with any category heading
        # that merged into it stripped back off.
        name = title[:match.start()].strip(" -–—:")
        for heading in _CATEGORIES:
            if name.upper().startswith(heading):
                name = name[len(heading):].strip(" -–—:")
        if not name:
            continue
        out.append({
            "name": name,
            "category": category,
            "creds": int(match.group("creds")),
            "creds_text": f"{match.group('creds')} credits",
            "trading_post": int(match.group("tp")),
            "tp_text": match.group("tp"),
            "description": item["body"],
            "page": item["page"],
        })
    return out
