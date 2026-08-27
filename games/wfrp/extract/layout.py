"""Column-aware, font-driven text extraction for WFRP PDFs.

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

The font map below was derived from a census of the source PDFs. Sizes are
matched with a tolerance because the typesetting varies by a few tenths, and the
map is per-book: the same face at the same size means different things in
different Cubicle 7 books. ``CaslonAntique`` at 10pt is a collective stat-block
name in *Rough Nights & Hard Days* but the body copy of a boxed sidebar in the
core rulebook, so each book supplies its own :class:`StyleSheet`.
"""
from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Iterable, Iterator, Optional, Sequence

import fitz


# PDF font names carry a subset prefix ("ABCDEF+Caslon") and spell the weight
# inconsistently between books -- the module says "CaslonAntique-Bold" where the
# rulebook says "CaslonAntique,Bold" for the identical face. Normalising here
# means one style rule matches both.
_SUBSET_PREFIX = re.compile(r"^[A-Z]{6}\+")


def normalise_font(font: str) -> str:
    return _SUBSET_PREFIX.sub("", font or "").replace(",", "-")


# (style, font name, nominal size, tolerance)
StyleRule = tuple[str, str, float, float]


@dataclass(frozen=True)
class StyleSheet:
    """How one book's fonts map onto logical styles.

    ``rules`` are matched first, by exact (normalised) font name and nearest
    size within tolerance. ``fallbacks`` then catch faces used at many sizes for
    different purposes, as ascending ``(upper_bound, style)`` bands. Anything
    still unmatched is body copy.
    """

    rules: tuple[StyleRule, ...]
    junk_fonts: frozenset = frozenset({"DwarvenAxeBB", "IM_FELL_Great_Primer_Rom"})
    # Faces whose every glyph is a decoration rather than a character. Their
    # spans are stripped from the text outright, where the remaining junk faces
    # are ordinary text faces that merely happen to be used for furniture: when
    # one of those turns up mid-line it is carrying real characters, so its text
    # is kept even though it never votes on the line's style.
    ornament_fonts: frozenset = frozenset({"DwarvenAxeBB", "crossbatstfb"})
    fallbacks: tuple[tuple[str, tuple[tuple[float, str], ...]], ...] = ()
    junk_text: "re.Pattern" = re.compile(
        r"^(warhammer\s+fantasy\s+rolepl\s*ay|\d{1,3})$", re.IGNORECASE
    )
    skip_pages: frozenset = frozenset()

    def classify(self, font: str, size: float) -> str:
        font = normalise_font(font)
        if font in self.junk_fonts:
            return "JUNK"
        best: Optional[tuple[float, str]] = None
        for style, rule_font, rule_size, tol in self.rules:
            if font != rule_font:
                continue
            delta = abs(size - rule_size)
            if delta <= tol and (best is None or delta < best[0]):
                best = (delta, style)
        if best is not None:
            return best[1]
        for fallback_font, bands in self.fallbacks:
            if font != fallback_font:
                continue
            for upper, style in bands:
                if size < upper:
                    return style
        return "BODY"


_MODULE_RULES: tuple[StyleRule, ...] = (
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
)

# Small CaslonAntique is the running head; larger is a sidebar heading.
MODULE_STYLESHEET = StyleSheet(
    rules=_MODULE_RULES,
    fallbacks=(("CaslonAntique", ((9.0, "JUNK"), (math.inf, "SIDEBAR_TITLE"))),),
)

# The core rulebook shares the Caslon family but adds boxed sidebars set in
# CaslonAntique 10, in-world handwritten letters in GourdieCursive, and dingbat
# advance markers in crossbatstfb that carry no readable text of their own.
_RULEBOOK_RULES: tuple[StyleRule, ...] = (
    ("H1", "CaslonAntique-Bold", 38.0, 6.0),
    ("H2", "CaslonAntique-Bold", 19.0, 3.0),
    ("H2", "CaslonAntique-Bold", 17.0, 1.0),
    ("H3", "CaslonAntique-Bold-SC700", 18.0, 1.5),
    ("H3", "CaslonAntique-Bold-SC700", 12.6, 1.5),
    ("STATHEAD", "CaslonAntique-Bold", 10.0, 1.2),
    ("SIDEBAR_TITLE", "CaslonAntique-Bold", 14.0, 0.6),
    ("H4", "ACaslonPro-Bold", 12.0, 1.0),
    ("H4", "ACaslonPro-Bold", 10.0, 0.55),
    ("RUNIN", "ACaslonPro-Bold", 9.0, 0.6),
    ("RUNIN", "ACaslonPro-Bold", 8.3, 0.4),
    ("EM", "ACaslonPro-Italic", 9.0, 1.2),
    ("EM", "ACaslonPro-BoldItalic", 9.5, 1.0),
    ("BODY", "ACaslonPro-Regular", 9.0, 1.2),
    ("BODY", "ACaslonPro-Regular", 8.0, 0.6),
    ("LETTER", "GourdieCursive", 12.0, 4.5),
)

RULEBOOK_STYLESHEET = StyleSheet(
    rules=_RULEBOOK_RULES,
    # TreasureMapDeadhand and Jefferson letter in the fiction's maps and
    # signatures; crossbatstfb is the advance-scheme dingbat, read separately by
    # geometry in careers.py. ACaslonPro-Regular 7.5 is the back-of-book index.
    junk_fonts=frozenset({
        "DwarvenAxeBB", "IM_FELL_Great_Primer_Rom", "TreasureMapDeadhand",
        "Jefferson", "GoudyOldStyle", "ArialMT", "Arial-BoldMT",
        "TimesNewRomanPSMT", "crossbatstfb",
    }),
    fallbacks=(
        ("CaslonAntique", ((9.0, "JUNK"), (11.5, "SIDEBAR"), (math.inf, "SIDEBAR_TITLE"))),
        ("CaslonAntique-SC700", ((math.inf, "DROPCAP"),)),
    ),
    junk_text=re.compile(
        r"^(warhammer\s+fantasy\s+rolepl\s*ay|\d{1,3}|"
        r"a\s+grim\s+world\s+of\s+perilous\s+adventure)$",
        re.IGNORECASE,
    ),
    # The printed contents, the blank character-sheet form and the
    # back-of-book index are navigation aids, not rules. Left in, the index
    # alone would add 65,000 characters of page-number noise to the corpus.
    skip_pages=frozenset({2, 3, 4} | set(range(344, 353))),
)

# Retained for callers that predate the stylesheet split.
_STYLE_RULES = list(_MODULE_RULES)
_JUNK_FONTS = MODULE_STYLESHEET.junk_fonts
_JUNK_TEXT = MODULE_STYLESHEET.junk_text

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


def classify_span(font: str, size: float, sheet: Optional[StyleSheet] = None) -> str:
    """Resolve a span's font and size to a logical style name."""
    return (sheet or MODULE_STYLESHEET).classify(font, size)


def content_spans(spans: Sequence[dict], sheet: StyleSheet) -> list[dict]:
    """The spans of a line that carry text, with ornament glyphs removed.

    Ornaments are set in display faces and sit on the same line as the text they
    decorate -- a career's tier heading is preceded by a dingbat bullet, for
    instance -- so they neither contribute characters nor get a vote on the
    line's style.
    """
    return [
        span
        for span in spans
        if span["text"].strip()
        and normalise_font(span["font"]) not in sheet.ornament_fonts
    ]


def _line_style(spans: Sequence[dict], sheet: StyleSheet) -> str:
    """Pick the dominant style of a line, weighted by visible characters."""
    weights: dict[str, int] = {}
    furniture = 0
    content = 0
    for span in spans:
        text = span["text"].strip()
        if not text:
            continue
        style = sheet.classify(span["font"], round(span["size"], 1))
        if style == "JUNK":
            # Ornaments decorate real text, so they are not evidence that the
            # line as a whole is furniture; other junk faces are.
            if normalise_font(span["font"]) not in sheet.ornament_fonts:
                furniture += len(text)
            continue
        content += len(text)
        weights[style] = weights.get(style, 0) + len(text)
    # A running header can pick up a stray glyph in a text face -- the rulebook's
    # chapter tabs set their dash in the body font -- which would otherwise let
    # one character carry a line of furniture into the prose.
    if not weights or furniture > content:
        return "JUNK"
    # A run-in label such as "Skills:" shares its line with body text; the line
    # as a whole should read as body so the label stays attached to its list.
    if "RUNIN" in weights and len(weights) > 1:
        weights.pop("RUNIN")
    # A dropped capital is one glyph in a display face opening a body
    # paragraph; the paragraph, not the glyph, decides the style.
    if "DROPCAP" in weights and len(weights) > 1:
        weights.pop("DROPCAP")
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


def page_lines(
    page: "fitz.Page", page_number: int, sheet: Optional[StyleSheet] = None
) -> list[Line]:
    """Return the page's lines in true reading order, free of furniture."""
    sheet = sheet or MODULE_STYLESHEET
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
            kept = content_spans(spans, sheet)
            text = _norm("".join(span["text"] for span in kept)).strip()
            if not text:
                continue
            style = _line_style(spans, sheet)
            if style == "JUNK" or sheet.junk_text.match(text):
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


def split_paragraphs(lines: list[Line]) -> list[list[Line]]:
    """Split a run of same-styled lines into its typeset paragraphs.

    The book separates paragraphs with a blank line rather than a first-line
    indent, so a paragraph break shows up as roughly double the normal leading.
    The leading itself varies by style, so it is measured from the run instead
    of hard-coded: the median gap is the body leading, and anything markedly
    larger is a blank line.

    A change of left edge also starts a paragraph, which is what separates an
    indented stat line such as "Talents: Weapon (Fist) +5" from the prose above
    it. Gaps are only meaningful within one column of one page; where text
    flows on to the next column the paragraph simply continues.
    """
    if not lines:
        return []

    gaps = [
        b.bbox[1] - a.bbox[1]
        for a, b in zip(lines, lines[1:])
        if a.page == b.page and a.column == b.column and b.bbox[1] > a.bbox[1]
    ]
    leading = sorted(gaps)[len(gaps) // 2] if gaps else 0.0

    paragraphs: list[list[Line]] = [[lines[0]]]
    for prev, line in zip(lines, lines[1:]):
        same_column = prev.page == line.page and prev.column == line.column
        if same_column and leading > 0 and line.bbox[1] - prev.bbox[1] > leading * 1.5:
            paragraphs.append([line])
        elif same_column and abs(line.bbox[0] - prev.bbox[0]) > 2.0:
            paragraphs.append([line])
        else:
            paragraphs[-1].append(line)
    return paragraphs


def merge_lines(lines: Iterable[Line], compounds: Optional[set[str]] = None) -> list[Block]:
    """Group consecutive lines of the same style into paragraph blocks.

    Multi-line headings are merged, which matters because names such as "Gravin
    Maria-Ulrike von Liebwitz of Ambosstein" are typeset across three lines.
    Body runs keep their paragraph breaks as blank lines in the block text.
    """
    blocks: list[Block] = []
    buffer: list[Line] = []
    style: Optional[str] = None

    def flush() -> None:
        nonlocal buffer, style
        if buffer and style is not None:
            if style in _HEADING_STYLES:
                paragraphs = [buffer]
            else:
                paragraphs = split_paragraphs(buffer)
            text = "\n\n".join(
                filter(
                    None,
                    (
                        join_wrapped([line.text for line in para], compounds)
                        for para in paragraphs
                    ),
                )
            )
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
    """A book PDF with reading-order text and its bookmark outline."""

    def __init__(self, path: str, sheet: Optional[StyleSheet] = None):
        self.path = path
        self.sheet = sheet or MODULE_STYLESHEET
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
            if 0 <= index < self.doc.page_count and page_number not in self.sheet.skip_pages:
                self._lines[page_number] = page_lines(
                    self.doc[index], page_number, self.sheet
                )
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
