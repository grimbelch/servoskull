"""Column-aware, font-driven text extraction for WFRP module PDFs.

PyMuPDF's ``get_text("text")`` returns content in raw PDF drawing order. On a
two-column layout that interleaves the columns, so an event from column one can
land in the middle of an NPC biography from column two. Any regex run over that
output is parsing scrambled prose, which is what made the previous extraction
attempt unreliable.

This module rebuilds the true reading order instead:

1. Every text block is assigned to a column by its horizontal position.
2. Blocks are ordered by (column, vertical position) so column one is fully
   consumed before column two begins.
3. Each line is classified by its font and size, which in this book maps
   cleanly onto a heading hierarchy.
4. Page furniture, and any text sitting inside a detected table, is dropped so
   it cannot pollute the prose.

The font map below was derived from a census of the source PDF; sizes are
matched with a tolerance because the typesetting varies by a few tenths.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Iterable, Iterator, Optional, Sequence

import fitz


# (style, font name, nominal size, tolerance)
_STYLE_RULES: list[tuple[str, str, float, float]] = [
    ("H1", "CaslonAntique-Bold", 38.0, 6.0),
    ("H2", "CaslonAntique-Bold", 19.0, 3.0),
    ("H3", "CaslonAntique-Bold-SC700", 18.0, 1.5),
    ("H3", "CaslonAntique-Bold-SC700", 12.6, 1.5),
    ("STATHEAD", "CaslonAntique-Bold", 9.7, 1.2),
    ("SIDEBAR_TITLE", "CaslonAntique", 15.0, 2.0),
    ("H4", "ACaslonPro-Bold", 12.0, 1.0),
    ("RUNIN", "ACaslonPro-Bold", 9.0, 0.6),
    ("EM", "ACaslonPro-Italic", 9.0, 1.2),
    ("BODY", "ACaslonPro-Regular", 9.0, 1.5),
    ("BODY", "ACaslonPro-Regular", 8.0, 0.6),
]

# Fonts that only ever carry running heads, folios and decorative numerals.
_JUNK_FONTS = {"DwarvenAxeBB", "IM_FELL_Great_Primer_Rom"}

# Running header text that appears on nearly every page.
_JUNK_TEXT = re.compile(
    r"^(warhammer\s+fantasy\s+rolepl\s*ay|\d{1,3})$",
    re.IGNORECASE,
)

_HEADING_STYLES = {"H1", "H2", "H3", "H4"}


def _norm(text: str) -> str:
    """Normalise the ligatures and smart punctuation the book is typeset with."""
    text = unicodedata.normalize("NFKC", text)
    return (
        text.replace("\u2019", "'")
        .replace("\u2018", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
        .replace("\u2013", "-")
        .replace("\xa0", " ")
    )


@dataclass
class Line:
    """One visual line of text with its resolved style and position."""

    text: str
    style: str
    page: int
    column: int
    bbox: tuple[float, float, float, float]

    @property
    def is_heading(self) -> bool:
        return self.style in _HEADING_STYLES


@dataclass
class Block:
    """A paragraph-level run of lines sharing a style."""

    style: str
    text: str
    page: int
    lines: list[Line] = field(default_factory=list)

    @property
    def is_heading(self) -> bool:
        return self.style in _HEADING_STYLES

    @property
    def column(self) -> int:
        return self.lines[0].column if self.lines else 0

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        if not self.lines:
            return (0.0, 0.0, 0.0, 0.0)
        return (
            min(line.bbox[0] for line in self.lines),
            min(line.bbox[1] for line in self.lines),
            max(line.bbox[2] for line in self.lines),
            max(line.bbox[3] for line in self.lines),
        )


def classify_span(font: str, size: float) -> str:
    """Resolve a span's font and size to a logical style name."""
    if font in _JUNK_FONTS:
        return "JUNK"
    best: Optional[tuple[float, str]] = None
    for style, rule_font, rule_size, tol in _STYLE_RULES:
        if font != rule_font:
            continue
        delta = abs(size - rule_size)
        if delta <= tol and (best is None or delta < best[0]):
            best = (delta, style)
    if best is not None:
        return best[1]
    if font == "CaslonAntique":
        # Small CaslonAntique is the running head; larger is a sidebar heading.
        return "JUNK" if size < 9.0 else "SIDEBAR_TITLE"
    return "BODY"


def _line_style(spans: Sequence[dict]) -> str:
    """Pick the dominant style of a line, weighted by visible characters."""
    weights: dict[str, int] = {}
    for span in spans:
        text = span["text"].strip()
        if not text:
            continue
        style = classify_span(span["font"], round(span["size"], 1))
        weights[style] = weights.get(style, 0) + len(text)
    if not weights:
        return "JUNK"
    # A run-in label such as "Skills:" shares its line with body text; the line
    # as a whole should read as body so the label stays attached to its list.
    if "RUNIN" in weights and len(weights) > 1:
        weights.pop("RUNIN")
    return max(weights.items(), key=lambda kv: kv[1])[0]


def _bbox_contains(outer: Sequence[float], inner: Sequence[float]) -> bool:
    cx = (inner[0] + inner[2]) / 2
    cy = (inner[1] + inner[3]) / 2
    return outer[0] <= cx <= outer[2] and outer[1] <= cy <= outer[3]


def table_bboxes(page: "fitz.Page") -> list[tuple[float, float, float, float]]:
    """Bounding boxes of tables on the page, so their cells can be excluded."""
    try:
        return [tuple(table.bbox) for table in page.find_tables().tables]
    except Exception:
        return []


def _column_of(bbox: Sequence[float], mid: float, tol: float = 24.0) -> int:
    """Assign a block to column 0 or 1, or -1 when it spans the full width."""
    x0, x1 = bbox[0], bbox[2]
    if x1 <= mid + tol:
        return 0
    if x0 >= mid - tol:
        return 1
    return -1


def page_lines(page: "fitz.Page", page_number: int) -> list[Line]:
    """Return the page's lines in true reading order, free of furniture."""
    mid = page.rect.width / 2
    tables = table_bboxes(page)
    ordered: list[tuple[int, float, float, dict]] = []
    for block in page.get_text("dict")["blocks"]:
        if block["type"] != 0:
            continue
        column = _column_of(block["bbox"], mid)
        ordered.append((column, block["bbox"][1], block["bbox"][0], block))
    ordered.sort(key=lambda item: (item[0], item[1], item[2]))

    lines: list[Line] = []
    for column, _, _, block in ordered:
        for raw_line in block["lines"]:
            spans = raw_line["spans"]
            text = _norm("".join(span["text"] for span in spans)).strip()
            if not text:
                continue
            style = _line_style(spans)
            if style == "JUNK" or _JUNK_TEXT.match(text):
                continue
            if any(_bbox_contains(tb, raw_line["bbox"]) for tb in tables):
                continue
            lines.append(
                Line(
                    text=text,
                    style=style,
                    page=page_number,
                    column=max(column, 0),
                    bbox=tuple(raw_line["bbox"]),
                )
            )
    return lines


def join_wrapped(parts: Sequence[str], compounds: Optional[set[str]] = None) -> str:
    """Join wrapped lines, healing words broken across a line break.

    A trailing hyphen is ambiguous: it may be a soft hyphen inserted by
    justification ("immedi-" + "ately") or a real one in a compound word
    ("stand-" + "alone"). They are textually identical, so the caller supplies
    the set of hyphenated compounds seen *mid-line* elsewhere in the same book.
    If the rejoined token is one of those, the hyphen is genuine and kept.
    """
    compounds = compounds or set()
    out = ""
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if not out:
            out = part
            continue
        if out.endswith("-") and len(out) > 1:
            left = re.split(r"[\s]", out)[-1][:-1]
            right = re.split(r"[\s]", part)[0]
            candidate = f"{left}-{right}".strip(".,;:!?)(\"'").lower()
            # A hyphen never has a space after it, so the only question is
            # whether the hyphen itself survives.
            if candidate in compounds or not (out[-2].islower() and part[:1].islower()):
                out = f"{out}{part}"
            else:
                out = out[:-1] + part
            continue
        out = f"{out} {part}"
    return out


def merge_lines(lines: Iterable[Line], compounds: Optional[set[str]] = None) -> list[Block]:
    """Group consecutive lines of the same style into paragraph blocks.

    Multi-line headings are merged, which matters because names such as "Gravin
    Maria-Ulrike von Liebwitz of Ambosstein" are typeset across three lines.
    """
    blocks: list[Block] = []
    buffer: list[Line] = []
    style: Optional[str] = None

    def flush() -> None:
        nonlocal buffer, style
        if buffer and style is not None:
            text = join_wrapped([line.text for line in buffer], compounds)
            if text:
                blocks.append(
                    Block(style=style, text=text, page=buffer[0].page, lines=list(buffer))
                )
        buffer = []

    for line in lines:
        effective = "BODY" if line.style == "EM" else line.style
        if effective != style:
            flush()
            style = effective
        buffer.append(line)
    flush()
    return blocks


class ModuleDocument:
    """A module PDF with reading-order text and its bookmark outline."""

    def __init__(self, path: str):
        self.path = path
        self.doc = fitz.open(path)
        self._lines: dict[int, list[Line]] = {}
        self._compounds: Optional[set[str]] = None

    @property
    def page_count(self) -> int:
        return self.doc.page_count

    def toc(self) -> list[tuple[int, str, int]]:
        """The PDF bookmark outline as (level, title, page) with clean text."""
        return [(lvl, _norm(title).strip(), page) for lvl, title, page in self.doc.get_toc()]

    def lines(self, page_number: int) -> list[Line]:
        """Reading-order lines for a 1-based page number, memoised."""
        if page_number not in self._lines:
            index = page_number - 1
            if 0 <= index < self.doc.page_count:
                self._lines[page_number] = page_lines(self.doc[index], page_number)
            else:
                self._lines[page_number] = []
        return self._lines[page_number]

    def lines_in_range(self, first_page: int, last_page: int) -> Iterator[Line]:
        for page_number in range(first_page, last_page + 1):
            yield from self.lines(page_number)

    def blocks_in_range(self, first_page: int, last_page: int) -> list[Block]:
        return merge_lines(self.lines_in_range(first_page, last_page), self.compounds())

    def compounds(self) -> set[str]:
        """Hyphenated words seen mid-line, used to resolve wrap-point hyphens.

        A hyphen that survives inside a single typeset line was never a soft
        hyphen, so it is reliable evidence that the compound is genuine.
        """
        if self._compounds is None:
            found: set[str] = set()
            pattern = re.compile(r"[A-Za-z]+(?:-[A-Za-z]+)+")
            for page_number in range(1, self.page_count + 1):
                for line in self.lines(page_number):
                    # Trailing hyphens are wrap points, not evidence.
                    text = line.text[:-1] if line.text.endswith("-") else line.text
                    for match in pattern.finditer(text):
                        found.add(match.group(0).lower())
            self._compounds = found
        return self._compounds

    def close(self) -> None:
        self.doc.close()

    def __enter__(self) -> "ModuleDocument":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
