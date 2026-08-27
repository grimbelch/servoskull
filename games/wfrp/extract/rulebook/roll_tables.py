"""Turn the rulebook's printed lookup tables into roll-indexed rows.

The generic table finder recovers the grids; what it cannot do is tell a
d100 table from a price list, or say which number a row answers to. That is
what the engine needs: given a roll of 47 on the Head Critical Wounds table,
return exactly one row, without parsing "45-49" at the table.

Three things about the printed tables get in the way.

Many have no header row -- the miscast tables open straight onto "01-05" --
so the finder takes the first result as column names and the table silently
loses a row. Some pack two independent tables side by side into one grid, as
the creature hit locations do for snakes and spiders. And a table's title is
frequently typeset *inside* its own frame, so it is dropped with the rest of
the table's text and never reaches the prose; those titles are recovered from
the book's outline instead, where they appear as sections that had nothing to
anchor to.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from ..layout import ModuleDocument
from ..sections import Section, slugify
from ..tables import RulesTable, extract_tables

# Rolls print as "01-10", "01–10" (en dash), "96+", "00" or a bare number.
# "00" reads as 100, being the zero of a d100.
_RANGE_RE = re.compile(r"^(\d{1,3})\s*[-–—]\s*(\d{1,3})$")
_OPEN_RE = re.compile(r"^(\d{1,3})\s*\+$")
_SINGLE_RE = re.compile(r"^(\d{1,3})$")

_KINDS = (
    ("critical", re.compile(r"criticalwounds?", re.IGNORECASE)),
    ("miscast", re.compile(r"miscast", re.IGNORECASE)),
    ("hit_location", re.compile(r"hitlocations?", re.IGNORECASE)),
    ("fumble", re.compile(r"fumble|misfire|oops", re.IGNORECASE)),
)


@dataclass
class RollRow:
    ordinal: int
    roll_min: Optional[int]
    roll_max: Optional[int]
    roll_label: str
    result: str
    detail: str
    cells: list = field(default_factory=list)


@dataclass
class RollTable:
    page: int
    slug: str
    title: str
    kind: str = "reference"
    dice: str = ""
    columns: list = field(default_factory=list)
    section_slug: str = ""
    chapter_slug: str = ""
    rows: list = field(default_factory=list)


def parse_roll(label: str) -> tuple:
    """Resolve a printed roll label to the inclusive span of rolls it covers."""
    text = (label or "").strip()
    if not text:
        return None, None

    match = _RANGE_RE.match(text)
    if match:
        low, high = int(match.group(1)), int(match.group(2))
        # A range ending "00" runs to 100: "20-00" means 20 to 100.
        if high == 0:
            high = 100
        if low == 0:
            low = 100
        return (low, high) if low <= high else (high, low)

    match = _OPEN_RE.match(text)
    if match:
        return int(match.group(1)), 100

    match = _SINGLE_RE.match(text)
    if match:
        value = int(match.group(1))
        value = 100 if value == 0 else value
        return value, value

    return None, None


def _is_roll(cell: str) -> bool:
    return parse_roll(cell) != (None, None)


def _is_roll_range(cell: str) -> bool:
    """Whether a cell is a span of rolls rather than a bare number.

    Bare numbers are not evidence of a roll column: a critical wound table's
    "Wounds" column is a run of 1s and 2s, and reading that as a second set of
    rolls would split the table down the middle.
    """
    text = (cell or "").strip()
    return bool(_RANGE_RE.match(text) or _OPEN_RE.match(text))


def _column_cells(index: int, rows: list) -> list:
    return [row[index] for row in rows if index < len(row) and row[index]]


def _roll_columns(headers: list, rows: list, strict: bool = False) -> list:
    """Indices of columns that read as rolls down the body of the table."""
    width = max([len(headers)] + [len(row) for row in rows]) if rows else len(headers)
    test = _is_roll_range if strict else _is_roll
    found: list = []
    for index in range(width):
        cells = _column_cells(index, rows)
        if cells and sum(1 for cell in cells if test(cell)) >= max(2, len(cells) * 0.6):
            found.append(index)
    return found


def _outline_titles(sections: list) -> dict:
    """Titles the outline knows about but the page's text never yielded.

    A table's caption is often set inside the table's own frame, so it is
    dropped along with the cells and cannot be found in the prose. The outline
    still lists it, as a section that failed to anchor.
    """
    titles: dict = {}
    for section in sections:
        if section.anchor is None and section.page:
            titles.setdefault(section.page, []).append(section)
    return titles


def _classify(title: str) -> str:
    # The publisher's own headings carry stray spaces -- "Arm Critica l Wounds"
    # -- so matching ignores whitespace entirely.
    squashed = re.sub(r"\s+", "", title or "")
    for kind, pattern in _KINDS:
        if pattern.search(squashed):
            return kind
    return "reference"


def _caption(table: RulesTable, page_lines: list) -> str:
    """The heading that names a table, which may sit inside its own frame.

    Captions are typeset within the table's border as often as above it, and
    anything inside the frame is stripped from the prose along with the cells.
    The nearest heading to the table's top edge, on either side of it, is the
    caption; anything further up the page belongs to the surrounding text.
    """
    top = table.bbox[1]
    left, right = table.bbox[0], table.bbox[2]
    best = None
    for line in page_lines:
        if line.bbox[2] < left - 12 or line.bbox[0] > right + 12:
            continue
        distance = line.bbox[3] - top
        if not -60.0 <= distance <= 40.0:
            continue
        if best is None or abs(distance) < abs(best[0]):
            best = (distance, line.text.strip())
    return best[1] if best else ""


def _split_side_by_side(table: RulesTable, roll_columns: list) -> list:
    """Break a grid that prints two independent tables next to each other."""
    if len(roll_columns) < 2:
        return [(table.title, table.headers, table.rows)]

    bounds = roll_columns + [len(table.headers)]
    parts: list = []
    for position, start in enumerate(roll_columns):
        stop = bounds[position + 1]
        headers = table.headers[start:stop]
        rows = [row[start:stop] for row in table.rows]
        rows = [row for row in rows if any(cell for cell in row)]
        # The sub-table's name sits in its roll column's header; when the
        # columns are unnamed the parent's title is the only one there is.
        name = (table.headers[start] or "").strip()
        title = table.title if not name or _is_roll(name) else name
        parts.append((title, headers, rows))
    return parts


def _demote_header(headers: list, rows: list) -> tuple:
    """Recover a first row that the table finder mistook for column names."""
    if not headers or not _is_roll(headers[0]):
        return headers, rows
    width = len(headers)
    names = ["Roll"] + [f"Column {index + 1}" for index in range(1, width)]
    if width == 2:
        names = ["Roll", "Effect"]
    return names, [list(headers)] + rows


def extract_roll_tables(
    doc: ModuleDocument, blocks: list, roots: list
) -> list:
    """Every printed table, with roll-indexed rows wherever the book uses them."""
    sections = [node for root in roots for node in root.walk()]
    spare_titles = _outline_titles(sections)
    found = extract_tables(doc, blocks, roots)
    by_page: dict = {}
    for block in blocks:
        if not (block.is_heading or block.style in ("SIDEBAR_TITLE", "STATHEAD")):
            continue
        # A block can straddle a page break -- both critical wound captions of
        # a spread merge into one -- so captions are filed by their own line's
        # page rather than the block's.
        for line in block.lines:
            by_page.setdefault(line.page, []).append(line)

    out: list = []
    for table in found:
        headers, rows = _demote_header(table.headers, table.rows)
        roll_columns = _roll_columns(headers, rows, strict=True)

        title = _caption(table, by_page.get(table.page, [])) or table.title
        # Prefer an outline title from the same page when the heading above the
        # table is a sidebar banner rather than the table's own caption.
        candidates = spare_titles.get(table.page, [])
        if candidates and (not title or _classify(title) == "reference"):
            better = next(
                (s for s in candidates if _classify(s.title) != "reference"), None
            )
            if better is not None:
                title = better.title
            elif not title:
                title = candidates[0].title

        for part_title, part_headers, part_rows in _split_side_by_side(
            RulesTable(
                page=table.page,
                slug=table.slug,
                title=title,
                headers=headers,
                rows=rows,
                section_slug=table.section_slug,
                chapter_slug=table.chapter_slug,
                bbox=table.bbox,
            ),
            roll_columns,
        ):
            local_rolls = _roll_columns(part_headers, part_rows, strict=True)
            if not local_rolls:
                local_rolls = _roll_columns(part_headers, part_rows)
            roll_at = local_rolls[0] if local_rolls else None
            built = RollTable(
                page=table.page,
                slug=slugify(f"p{table.page:03d}-{part_title or table.slug}"),
                title=part_title,
                kind=_classify(part_title),
                dice="d100" if roll_at is not None else "",
                columns=part_headers,
                section_slug=table.section_slug,
                chapter_slug=table.chapter_slug,
            )
            for ordinal, row in enumerate(part_rows):
                label = row[roll_at] if roll_at is not None and roll_at < len(row) else ""
                low, high = parse_roll(label)
                rest = [
                    (part_headers[index] if index < len(part_headers) else "", cell)
                    for index, cell in enumerate(row)
                    if index != roll_at and cell
                ]
                built.rows.append(
                    RollRow(
                        ordinal=ordinal,
                        roll_min=low,
                        roll_max=high,
                        roll_label=label if low is not None else "",
                        result=rest[0][1] if rest else "",
                        detail=" | ".join(_labelled(header, cell)
                                          for header, cell in rest[1:]),
                        cells=list(row),
                    )
                )
            out.append(built)

    _stitch(out)
    _dedupe_slugs(out)
    return out


def _labelled(header: str, cell: str) -> str:
    """Keep a short value tied to its column, e.g. the Wounds a Critical costs.

    Prose cells read better bare, but a lone "1" is meaningless without the
    "Wounds" heading it sat under.
    """
    header = (header or "").strip()
    if header and len(cell) <= 20:
        return "%s: %s" % (header, cell)
    return cell


def _rolled(table: RollTable) -> list:
    return [row for row in table.rows if row.roll_min is not None]


def _stitch(tables: list) -> None:
    """Join tables that a page break split in two.

    The critical wound tables each run over a spread, and the half on the
    second page carries neither caption nor column names -- only rows picking
    up where the previous page stopped. Contiguity is the evidence: a fragment
    that opens on the roll after the previous table closed, and does not open
    the d100 itself, is the rest of that table.
    """
    merged: list = []
    for table in tables:
        rows = _rolled(table)
        previous = merged[-1] if merged else None
        if previous is not None and rows:
            tail = _rolled(previous)
            if (
                tail
                and rows[0].roll_min != 1
                and rows[0].roll_min == tail[-1].roll_max + 1
                and 0 <= table.page - previous.page <= 1
            ):
                for row in table.rows:
                    row.ordinal = len(previous.rows)
                    previous.rows.append(row)
                continue
        merged.append(table)
    tables[:] = merged


def _dedupe_slugs(tables: list) -> None:
    seen: dict = {}
    for table in tables:
        count = seen.get(table.slug, 0) + 1
        seen[table.slug] = count
        if count > 1:
            table.slug = f"{table.slug}-{count}"
