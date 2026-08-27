"""Parse the rulebook's 64 career entries, one to a page.

A career page carries three things worth keeping: the advance scheme, the four
career levels, and the prose around them.

The advance scheme is a one-row table that the book explains in its own words:
the ten characteristics are shown, "3 marked with h, 1 marked with [a symbol] on
a brass background, 1 marked on silver, and the last marked on gold" -- the
three ``h`` are advanced from the first level, and the brass, silver and gold
cells unlock at the second, third and fourth levels respectively.

That notation only half survives text extraction. The ``h`` are glyphs in a
dingbat face and can be read as spans, but the brass/silver/gold marks are
drawn: the cell has a filled background and the symbol inside it is vector art,
with no text at all. Both halves are therefore located by x-position instead,
matched against the x-positions of the characteristic headings above them, and
the drawn marks are told apart by their fill colour.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Optional

from ..layout import ModuleDocument, join_wrapped, normalise_font, split_paragraphs
from ..sections import Section, slugify

# Characteristics in printed order, as abbreviated in the scheme's header row.
CHARACTERISTIC_ORDER = ("ws", "bs", "s", "t", "i", "ag", "dex", "int", "wp", "fel")
_HEADER_LABELS = {
    "ws": "ws", "bs": "bs", "s": "s", "t": "t", "i": "i", "agi": "ag",
    "dex": "dex", "int": "int", "wp": "wp", "fel": "fel",
}

# The career level each background colour unlocks. Measured off the plates; the
# three are far enough apart in RGB that an exact match is unnecessary.
_TIER_FILLS = (
    ((0.764, 0.516, 0.346), 2),   # brass
    ((0.779, 0.785, 0.793), 3),   # silver
    ((1.000, 0.889, 0.000), 4),   # gold
)
_FILL_TOLERANCE = 0.08

_SCHEME_TITLE_RE = re.compile(r"^(?P<name>.+?)\s+Advance\s+Scheme$", re.IGNORECASE)
# Career levels print as "Rat Hunter — Brass 3": name, em-dash, status tier and
# standing. A few use a hyphen or en-dash instead.
_TIER_RE = re.compile(
    r"^(?P<name>.+?)\s*[—–-]\s*(?P<tier>Brass|Silver|Gold)\s+(?P<standing>\d+)$",
    re.IGNORECASE,
)
_TIER_LABELS = ("Skills", "Talents", "Trappings")
_TIER_LABEL_RE = re.compile(
    rf"^\s*(?P<label>{'|'.join(_TIER_LABELS)})\s*:\s*(?P<value>.*)$", re.IGNORECASE
)
# The chapter tab printed in the top margin of each spread's left page.
_TAB_RE = re.compile(r"^cl\s*ass and careers$", re.IGNORECASE)
# The species that may enter a career are listed alone beneath its name.
SPECIES = ("Dwarf", "Halfling", "High Elf", "Human", "Wood Elf", "Gnome")


@dataclass
class CareerTier:
    """One of a career's four levels."""

    level: int
    name: str
    status_tier: str
    status_standing: int
    skills: list = field(default_factory=list)
    talents: list = field(default_factory=list)
    trappings: list = field(default_factory=list)


@dataclass
class CareerEntry:
    name: str
    slug: str
    career_class: str
    page: int
    species: list = field(default_factory=list)
    summary: str = ""
    description_md: str = ""
    # Characteristic -> the career level from which it may be advanced.
    advances: dict = field(default_factory=dict)
    tiers: list = field(default_factory=list)


def _split_list(value: str) -> list:
    """Split a printed comma list, keeping parenthesised specialisations whole."""
    items: list = []
    depth = 0
    current = ""
    for char in value:
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        if char == "," and depth == 0:
            items.append(current)
            current = ""
            continue
        current += char
    items.append(current)
    return [item.strip(" .;") for item in items if item.strip(" .;")]


def _fill_level(fill) -> Optional[int]:
    if not fill:
        return None
    for colour, level in _TIER_FILLS:
        if all(abs(a - b) <= _FILL_TOLERANCE for a, b in zip(fill, colour)):
            return level
    return None


def _nearest(centre: float, columns: list) -> Optional[str]:
    """The characteristic whose heading is closest to a mark's centre."""
    if not columns:
        return None
    key, distance = min(
        ((key, abs(centre - x)) for key, x in columns), key=lambda item: item[1]
    )
    # Cells are about 23pt wide, so anything further out than half a cell is
    # not a mark belonging to this table.
    return key if distance <= 14.0 else None


def _scheme_header(page) -> tuple:
    """The scheme's heading row: its baseline y and each column's centre x."""
    title_y = None
    for block in page.get_text("dict")["blocks"]:
        if block.get("type"):
            continue
        for line in block["lines"]:
            for span in line["spans"]:
                if _SCHEME_TITLE_RE.match(span["text"].strip()):
                    title_y = span["bbox"][1]
    if title_y is None:
        return None, []

    best_y = None
    columns: list = []
    for block in page.get_text("dict")["blocks"]:
        if block.get("type"):
            continue
        for line in block["lines"]:
            for span in line["spans"]:
                key = _HEADER_LABELS.get(span["text"].strip().lower())
                if key is None or span["bbox"][1] <= title_y:
                    continue
                if best_y is None or span["bbox"][1] < best_y - 2:
                    best_y, columns = span["bbox"][1], []
                if abs(span["bbox"][1] - best_y) <= 2:
                    columns.append((key, (span["bbox"][0] + span["bbox"][2]) / 2))
    return best_y, columns


def parse_advance_scheme(page) -> dict:
    """Map each advanced characteristic to the career level that unlocks it."""
    header_y, columns = _scheme_header(page)
    if header_y is None or len(columns) != 10:
        return {}

    # The marks sit in the single row under the headings.
    top, bottom = header_y + 6.0, header_y + 34.0
    advances: dict = {}

    for block in page.get_text("dict")["blocks"]:
        if block.get("type"):
            continue
        for line in block["lines"]:
            for span in line["spans"]:
                if normalise_font(span["font"]) != "crossbatstfb":
                    continue
                if not span["text"].strip() or not top <= span["bbox"][1] <= bottom:
                    continue
                key = _nearest((span["bbox"][0] + span["bbox"][2]) / 2, columns)
                if key:
                    advances[key] = 1

    for drawing in page.get_drawings():
        level = _fill_level(drawing.get("fill"))
        if level is None:
            continue
        rect = drawing["rect"]
        if not (top <= rect.y0 <= bottom and rect.width > 15):
            continue
        key = _nearest((rect.x0 + rect.x1) / 2, columns)
        if key:
            advances[key] = level

    return advances


def _page_classes(doc: ModuleDocument, first: int, last: int) -> dict:
    """Each career page's class, read from the chapter tab in the top margin.

    The tab is printed once per spread, on the left-hand page, so its class
    carries forward until the next tab appears.
    """
    tabs: dict = {}
    for page_number in range(first, last + 1):
        page = doc.doc[page_number - 1]
        parts: list = []
        for block in page.get_text("dict")["blocks"]:
            if block.get("type"):
                continue
            for line in block["lines"]:
                texts = [span["text"].strip() for span in line["spans"]]
                if any(_TAB_RE.match(text) for text in texts):
                    parts = [text for text in texts if text and not _TAB_RE.match(text)]
        label = " ".join(parts).strip(" -–—")
        if label:
            tabs[page_number] = label.title()

    classes: dict = {}
    current = ""
    for page_number in range(first, last + 1):
        current = tabs.get(page_number, current)
        classes[page_number] = current
    return classes


def _tier_blocks(lines: Iterable) -> list:
    """Group a career's lines into its four levels, keyed by the level heading."""
    groups: list = []
    for line in lines:
        match = _TIER_RE.match(line.text.strip())
        if match:
            groups.append((match, []))
        elif groups:
            groups[-1][1].append(line)
    return groups


def _continues(line, previous) -> bool:
    """Whether a line carries on the run-in list started on ``previous``.

    A career's level lists sit in one column, but the page's remaining prose --
    in-world quotations, usually -- follows in the next column and is picked up
    straight after them in reading order. Without this the final level's
    trappings would swallow the rest of the page, since nothing else marks
    where the list ends.
    """
    if line.column != previous.column:
        return False
    gap = line.bbox[1] - previous.bbox[1]
    return 0 < gap <= 20.0


def _parse_tier(match, body: list, level: int) -> CareerTier:
    tier = CareerTier(
        level=level,
        name=match.group("name").strip(),
        status_tier=match.group("tier").title(),
        status_standing=int(match.group("standing")),
    )
    current: Optional[str] = None
    anchor = None
    values: dict = {label.lower(): "" for label in _TIER_LABELS}
    for line in body:
        found = _TIER_LABEL_RE.match(line.text)
        if found:
            current = found.group("label").lower()
            values[current] = found.group("value").strip()
            anchor = line
        elif current and anchor is not None and _continues(line, anchor):
            values[current] = f"{values[current]} {line.text.strip()}".strip()
            anchor = line
        else:
            current = None
    tier.skills = _split_list(values["skills"])
    tier.talents = _split_list(values["talents"])
    tier.trappings = _split_list(values["trappings"])
    return tier


def _read_species(lines: list, compounds: Optional[set] = None) -> tuple:
    """The career's species line and the one-line summary printed under it."""
    paragraphs = split_paragraphs(lines) if lines else []
    if not paragraphs:
        return [], ""
    items = _split_list(" ".join(line.text for line in paragraphs[0]))
    if not items or not all(item in SPECIES for item in items):
        return [], ""
    summary = ""
    if len(paragraphs) > 1:
        summary = join_wrapped([line.text for line in paragraphs[1]], compounds)
    return items, summary


def extract_careers(
    doc: ModuleDocument, sections: list, blocks: list
) -> list:
    """Build a `CareerEntry` for every career section in the outline."""
    careers = [section for section in sections if section.kind == "career"]
    if not careers:
        return []
    pages = [section.page_start or section.page for section in careers]
    classes = _page_classes(doc, min(pages), max(pages))

    out: list = []
    for section in careers:
        page_number = section.page_start or section.page
        lines: list = []
        for block in blocks[section.block_start:section.block_end]:
            lines.extend(block.lines)

        entry = CareerEntry(
            name=section.title.strip(),
            slug=slugify(section.title),
            career_class=classes.get(page_number, ""),
            page=page_number,
            advances=parse_advance_scheme(doc.doc[page_number - 1]),
        )
        entry.species, entry.summary = _read_species(lines, doc.compounds())

        for index, (match, body) in enumerate(_tier_blocks(lines), start=1):
            entry.tiers.append(_parse_tier(match, body, index))

        entry.description_md = section.body_md
        out.append(entry)
    return out
