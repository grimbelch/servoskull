"""Recovering the rulebook's printed tables as real columns.

The Trading Post profiles are the reason this module exists. In the PDF's text
layer an empty cell leaves no token at all, so reading a row as a flat sequence
shifts every later value one column to the left -- an autopistol prints no AP,
and a linear read duly reports its Lethality as its AP. Columns are recovered
from word geometry instead (see ``layout.columns``).

Header rows are not individually trustworthy either: the OCR drops a header
token here and there, so one page's header is missing ``L`` and another's
``Str``. Anchors are therefore the median of every observation of each header
token across the whole book, which no single dropout can move.
"""
from __future__ import annotations

import re

from . import layout

# The Trading Post weapon profile, in printed order.
WEAPON_COLUMNS = ["SR", "LR", "Str", "AP", "L", "Traits", "Creds", "TP"]

# A cell that holds a profile value rather than prose: a number, a range in
# inches, a dash for "not printed", a credit delta, or the Template marker.
_VALUE = re.compile(r'^(?:[+-]?\d+\*?"?|-|—|T|E|D\d+|\d+D\d+|\d+\+)$')

# OCR renders the printed footnote marker on some weapon names as a stray
# quote, backtick or interpunct. It is not part of the name.
_NAME_NOISE = re.compile(r"^[\s·•.*'\"`]+|[\s·•.*'\"`]+$")

_CATEGORY = re.compile(r"^[A-Z0-9][A-Z0-9 /&'\-]{3,40}$")

# A weapon header spanning at least this many points runs the width of the page,
# so the table is the page's own content rather than an inset beside prose.
_FULL_WIDTH_HEADER = 250.0

# A weapon name: a few words, starting with a capital or the variant dash. Body
# text in the same x range reads as a sentence instead, which is what keeps
# prose out of the profile rows now that a single printed stat is enough.
_NAME_BODY = r"""[A-Za-z0-9 '/&()+\-."\u201d*]*$"""
_NAMEISH = re.compile(r"^[A-Z]" + _NAME_BODY)
# Special-ammunition lines are printed beneath their weapon as "- warp round",
# in lower case, so the dash is what marks them as a name rather than a capital.
_VARIANT_NAMEISH = re.compile(r"^[-\u2022\u00b7\s]+[A-Za-z]" + _NAME_BODY)


def _looks_like_a_name(label: str) -> bool:
    label = label.strip()
    if not label or len(label) > 42 or len(label.split()) > 5:
        return False
    if label.rstrip().endswith((".", ":", ";", ",")):
        return False
    return bool(_NAMEISH.match(label) or _VARIANT_NAMEISH.match(label))

# Creds and TP: narrow numeric columns at the right edge, claimed by their left
# edge so a long trait list cannot spill into them.
_COST_COLUMNS = 2

# A printed trait list is comma-separated title-case names, each optionally
# carrying a bracketed value: "Ammo (3+), Heavy, Rapid Fire (2)". Running prose
# in the same cell gives it a sentence's shape instead.
_PROSE_IN_CELL = re.compile(r"[a-z]{3,}\s+[a-z]{3,}\s+[a-z]{3,}|\.\s+[A-Z]")


# A wrapped trait list continues with Title-case names and bracketed values.
# Anything else -- a lowercase word, a numbered entry, a shouted heading -- is
# the start of the next thing on the page, not more of this weapon's traits.
_TRAIT_FRAGMENT_MAX = 44
_NUMBERED_ENTRY = re.compile(r"^\d+\s*[.)]")
# A trait name is Title case; a trait's value is bracketed or purely numeric.
# A bare lowercase word belongs to a sentence, so it ends the trait list -- an
# earlier version allowed any alphanumeric token here and so kept reading
# "Rapid Fire (1) have one or more traits, and how many Trade in more detail".
_TRAIT_TOKEN = re.compile(
    r"""^(?: [A-Z][A-Za-z'\-]*           # a Title-case trait name
           | \( [^()]* \)                 # a bracketed value, "(3+)", "(3\"/5\")"
           | [0-9+\-/"'\u201d]+           # a bare number or measure
           | &
        )[,.;:]?$""", re.VERBOSE)


def is_trait_fragment(text: str) -> bool:
    """True when a cell is the continuation of a wrapped trait list.

    The merge this guards used to accept any following row, and so swallowed
    whole columns: a Wyrd power's traits ran on into the next power's rules, and
    a Combat skill's into five more skills.
    """
    text = (text or "").strip()
    if not text or len(text) > _TRAIT_FRAGMENT_MAX:
        return False
    if _NUMBERED_ENTRY.match(text):
        return False
    for token in text.split():
        # A shouted word is a heading ("CUNNING"), not a trait name.
        if len(token) >= 4 and token.isupper():
            return False
        if not _TRAIT_TOKEN.match(token):
            return False
    return True


def looks_contaminated(traits: str) -> bool:
    """True when a traits cell has absorbed body text from around the table."""
    return bool(traits) and (len(traits) > 80 or bool(_PROSE_IN_CELL.search(traits)))


def clean_name(text: str) -> tuple[str, bool]:
    """A weapon/equipment name with OCR noise stripped, and whether it was marked.

    The trailing marker is the book's own footnote symbol (unwieldy, or
    restricted to certain fighters), so the fact that it was present is kept even
    though the glyph itself is unreliable.
    """
    stripped = _NAME_NOISE.sub("", text)
    return re.sub(r"\s+", " ", stripped).strip(), stripped != text.strip()


def row_anchors(row: list[tuple[float, float, str]], tokens: list[str]) -> dict[str, float]:
    """The x-centre of each header token present in one header row."""
    found: dict[str, float] = {}
    for x0, x1, text in row:
        if text in tokens and text not in found:
            found[text] = (x0 + x1) / 2
    return found


def header_anchors(doc, tokens: list[str], require: list[str]) -> list[float]:
    """Median x-centre of each header token over every header row in the book.

    ``require`` is the subset that identifies a header row, so prose that
    happens to contain one of the words is not mistaken for one.
    """
    obs: dict[str, list[float]] = {t: [] for t in tokens}
    for page_no in range(doc.page_count):
        for row in layout.word_rows(doc.load_page(page_no)):
            words = [t for _, _, t in row]
            if not all(r in words for r in require):
                continue
            for token, centre in row_anchors(row, tokens).items():
                obs[token].append(centre)
    return layout.anchor_set([obs[t] for t in tokens])


def _resolve_anchors(found: dict[str, float], tokens: list[str],
                     fallback: list[float]) -> list[float] | None:
    """Anchors for one printed table, from its own header where possible.

    The book prints these profiles at more than one scale -- the worked example
    in the weaponry chapter and the Wyrd power profiles are narrower than the
    Trading Post lists -- so one global set of anchors cannot read them all.
    A table's own header is used for the columns it names, and the book-wide
    median only fills what that header dropped. Returns None when the header is
    too sparse to trust, leaving the table to the global anchors.
    """
    if len(found) < 4:
        return None
    anchors = [found.get(t, fallback[i]) for i, t in enumerate(tokens)]
    # The fill-ins are only usable if they keep the columns in printed order.
    if any(b <= a for a, b in zip(anchors, anchors[1:])):
        return None
    return anchors


def _is_header_row(words: list[str], require: list[str]) -> bool:
    return all(r in words for r in require)


def _value_count(cells: list[str], numeric_slice: slice) -> int:
    return sum(1 for c in cells[numeric_slice] if c and _VALUE.match(c))


def weapon_rows(doc, anchors: list[float]) -> list[dict]:
    """Every weapon profile line in the book, with its columns recovered.

    A row is taken as a profile only when it has a name and at least two cells
    in the numeric columns that actually look like values. That test is what
    keeps the surrounding prose out: body text sprawls across the same x range
    and would otherwise be shredded into columns and stored as weapons.
    """
    # SR..L are the numeric columns; Traits is free text, Creds/TP numeric.
    numeric = slice(1, 6)
    out: list[dict] = []

    for page_no in range(doc.page_count):
        page = doc.load_page(page_no)
        rows = layout.word_rows(page)
        headers = [r for r in rows if _is_header_row([t for _, _, t in r], ["SR", "LR"])]
        if not headers:
            continue

        # A full-width table owns the page, and its rows must be read straight
        # across. A narrow one is set in a column beside prose, and its rows have
        # to be kept out of whatever is printed alongside -- so for those, and
        # only those, the page is split into columns first.
        #
        # The span is measured over the HEADER TOKENS alone. These rows were
        # grouped without a split, so a narrow table's header has already had the
        # neighbouring column's words welded onto it and its raw extent reaches
        # right across the page -- which is the very thing being tested for.
        widest = 0.0
        for row in headers:
            found = row_anchors(row, WEAPON_COLUMNS)
            if len(found) >= 2:
                widest = max(widest, max(found.values()) - min(found.values()))
        if widest and widest < _FULL_WIDTH_HEADER:
            split = layout.column_split(page)
            if split:
                rows = layout.word_rows(page, split=split)

        category = ""
        in_table = False
        merging = False
        active = anchors
        bounds = layout.column_bounds(active)
        for row in rows:
            words = [t for _, _, t in row]
            if _is_header_row(words, ["SR", "LR"]):
                in_table = True
                own = _resolve_anchors(row_anchors(row, WEAPON_COLUMNS),
                                       WEAPON_COLUMNS, anchors)
                active = own or anchors
                bounds = layout.column_bounds(active)
                # The category is printed on, or just above, the header row.
                label = layout.columns(row, active, bounds, _COST_COLUMNS)[0].strip()
                if label and _CATEGORY.match(label):
                    category = label
                continue

            cells = layout.columns(row, active, bounds, _COST_COLUMNS)
            label = cells[0].strip()
            if not label:
                # A trait list too long for its cell wraps onto the next printed
                # line, which has no name of its own. Joining it back is the
                # difference between storing "Ammo (6+), Cursed," and the whole
                # trait list. Once a line stops looking like a trait list the
                # weapon's entry is over, and nothing further is taken.
                if (merging and in_table and out and cells[6]
                        and not _value_count(cells, numeric)):
                    if is_trait_fragment(cells[6]):
                        prev = out[-1]
                        if prev["page"] == page_no:
                            prev["cells"][5] = f"{prev['cells'][5]} {cells[6]}".strip()
                    else:
                        merging = False
                continue
            flat = " ".join(words)
            if _CATEGORY.match(flat.strip()) and not _value_count(cells, numeric):
                category = flat.strip()
                continue
            # One printed stat is enough. Photon flash grenades print only a
            # range -- no Strength, AP or Lethality -- so demanding two dropped
            # the weapon outright and then glued its wrapped trait line onto
            # whatever came before it. Prose is kept out by the name test and by
            # requiring the row to carry traits or a price.
            # Test the name with its OCR footnote marker already stripped: the
            # marker is rendered as a stray bullet, quote or asterisk, and
            # "Multi-melta\u2022" is a weapon name however it came out of the scan.
            if not in_table or not _looks_like_a_name(clean_name(label)[0]):
                continue
            if _value_count(cells, numeric) < 1:
                continue
            if not (cells[6].strip() or cells[7].strip() or cells[8].strip()):
                continue

            name, marked = clean_name(label)
            if not name:
                continue
            is_variant = label.lstrip(" ·•").startswith("-") or name.startswith("-")
            out.append({
                "page": page_no,
                "category": category,
                "name": clean_name(name.lstrip("- "))[0] if is_variant else name,
                "is_variant": is_variant,
                "marked": marked,
                "cells": cells[1:],
                "raw_label": label,
                "needs_review": False,
            })
            merging = True

    for row in out:
        row["needs_review"] = looks_contaminated(row["cells"][5])
    return out
