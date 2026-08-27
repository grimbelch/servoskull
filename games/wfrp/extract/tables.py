"""Extract the module's rules tables (random generators, pub game charts).

These are distinct from NPC characteristic tables, which `statblocks` claims
first. What remains are the genuine lookup tables — gnome careers, eye colour,
darts scoring — that the GM needs to roll on at the table.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from .layout import Block, ModuleDocument
from .sections import Section, slugify
from .statblocks import _normalise_header


@dataclass
class RulesTable:
    """A lookup table as printed in the book."""

    page: int
    slug: str
    title: str
    headers: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)
    section_slug: str = ""
    chapter_slug: str = ""
    bbox: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)


def _clean(cell: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (cell or "").replace("\n", " ")).strip()


def _is_meaningful(headers: list[str], rows: list[list[str]]) -> bool:
    """Reject the decorative title text that the table finder reports as tables.

    A real table has more than one column and at least two body rows; the false
    positives on the title page are single cells of display type.
    """
    if len(headers) < 2 or len(rows) < 2:
        return False
    filled = sum(1 for row in rows for cell in row if cell)
    return filled >= len(headers)


def extract_tables(
    doc: ModuleDocument, blocks: list[Block], roots: list[Section]
) -> list[RulesTable]:
    sections = [node for root in roots for node in root.walk()]
    page_section: dict[int, Section] = {}
    for section in sorted(sections, key=lambda s: (s.page_start or s.page, s.level)):
        for page in range(
            section.page_start or section.page, (section.page_end or section.page) + 1
        ):
            page_section[page] = section

    heading_by_page: dict[int, list[Block]] = {}
    for block in blocks:
        if block.is_heading or block.style == "SIDEBAR_TITLE":
            heading_by_page.setdefault(block.page, []).append(block)

    tables: list[RulesTable] = []
    for page_number in range(1, doc.page_count + 1):
        page = doc.doc[page_number - 1]
        for ordinal, found in enumerate(page.find_tables().tables):
            grid = found.extract()
            if not grid:
                continue
            headers = [_clean(cell) for cell in grid[0]]
            # Characteristic profiles belong to NPCs, not here.
            if _normalise_header(grid[0]) is not None:
                continue
            rows = [[_clean(cell) for cell in row] for row in grid[1:]]
            if not _is_meaningful(headers, rows):
                continue

            bbox = tuple(found.bbox)
            title = ""
            above = [
                b
                for b in heading_by_page.get(page_number, [])
                if b.bbox[3] <= bbox[1] + 2
            ]
            if above:
                title = max(above, key=lambda b: b.bbox[3]).text.strip()

            section = page_section.get(page_number)
            chapter = section.ancestor_of_kind("chapter") if section else None
            tables.append(
                RulesTable(
                    page=page_number,
                    slug=slugify(f"p{page_number:03d}-{ordinal + 1}-{title or 'table'}"),
                    title=title,
                    headers=headers,
                    rows=rows,
                    section_slug=section.slug if section else "",
                    chapter_slug=chapter.slug if chapter else "",
                    bbox=bbox,
                )
            )
    return tables
