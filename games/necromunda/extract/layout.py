"""Page primitives for the Necromunda rulebook PDF.

The source is a scan with an OCR text layer, which constrains everything here:

* Spans are fragmented, often one glyph each, and their reported size is noisy.
  Nothing may depend on a single span; sizes are taken as the max over a line
  and only ever compared coarsely.
* The page is two columns. Reading order is therefore not y order -- two
  unrelated headings share a y -- so lines are split by column first.
* An empty table cell leaves NO token in the text layer. Reading a row as a
  sequence of values silently shifts every later value one column left, which
  on the weapon tables turns an autopistol's Lethality into its AP. Columns are
  recovered from word x positions against anchors instead (see ``columns``).
"""
from __future__ import annotations

import re
import statistics

# A heading is set in bold caps. Size alone is not enough: OCR marks occasional
# body lines bold at 14pt, and those are mixed case, so the caps test is what
# actually separates "SERIOUSLY INJURED FIGHTERS" from "Note that a Seriously
# Injured/Damaged model...".
# 9, because the book headings go all the way down to it. There are three
# tiers: a chapter at 28pt, a section at 11-14pt, and then sidebars, the steps
# of a sequence and the names of equipment at 9-10pt. A floor of 11 left that
# last tier invisible -- "Single Actions" and "Free Actions" had no heading of
# their own, the Arbitrator's Toolkit sidebars attached to whatever came
# before them, and an item called "Bio-booster" at 10pt was filed under its
# own price line at 12pt. Dropping to 9 finds 444 more headings.
_MIN_HEADING_SIZE = 9
# A stat table's column headers are set in the same type as a heading. "SR",
# "AP" and "TP" are not sections.
_MIN_HEADING_CHARS = 4
_MIN_BOLD_RATIO = 0.6
_MIN_CAPS_RATIO = 0.75
_MAX_HEADING_CHARS = 70

_WS = re.compile(r"\s+")

# Body text is set in Frutiger Light or plain Arial. Anything else -- bold, or
# the condensed face the OCR reports on some pages -- is display type, and that
# is what marks a name in this book. Testing for the word "Bold" in the font
# alone misses every trait on the two pages the scan read as Franklin Gothic.
_DISPLAY_FONTS = ("Bold", "Franklin", "Black", "Heavy")


def _is_display_font(font: str) -> bool:
    return any(marker in font for marker in _DISPLAY_FONTS)


def _caps_ratio(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if c.isupper()) / len(letters)


def _raw_lines(page) -> list[dict]:
    """Text lines with their type attributes, before columns are worked out."""
    raw: list[dict] = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            spans = [s for s in line.get("spans", []) if s["text"].strip()]
            if not spans:
                continue
            text = _WS.sub(" ", "".join(s["text"] for s in spans)).strip()
            if not text:
                continue
            chars = sum(len(s["text"]) for s in spans) or 1
            bold = sum(len(s["text"]) for s in spans if "Bold" in s["font"]) / chars
            display = sum(len(s["text"]) for s in spans
                          if _is_display_font(s["font"])) / chars
            raw.append({
                "text": text,
                "bold": bold,
                "display": display,
                "size": max(round(s["size"]) for s in spans),
                "x0": line["bbox"][0],
                "x1": line["bbox"][2],
                "y": line["bbox"][1],
            })
    return raw


def page_lines(page) -> list[dict]:
    """Every text line on the page with the attributes the parsers need.

    Returned in reading order: column, then y, then x.
    """
    raw = _raw_lines(page)
    split = column_split(page, raw)
    for item in raw:
        item["column"] = 1 if split and item["x0"] >= split else 0
    raw.sort(key=lambda d: (d["column"], round(d["y"]), d["x0"]))
    return raw


def column_split(page, lines: list[dict] | None = None) -> float | None:
    """The x where the right column starts, or None on a single-column page.

    Found by looking for the gutter: the widest vertical band near the middle of
    the page that no line's own extent crosses. That is a direct measurement of
    the white channel between the columns, so it works whatever the columns
    contain.

    An earlier version judged it by how tightly the right-hand lines' left edges
    clustered, and that misread a third of the book -- indented list items and
    inset headings widen the spread without there being any doubt about where
    the gutter is. Where the columns are not separated, the two are read as one
    and their lines interleave by y, which is how the dice section came out as
    "INJURY DICE For example, a roll of 2 then 4 would give a result Another
    dice unique to Necromunda".
    """
    if lines is None:
        lines = _raw_lines(page)
    if len(lines) < 8:
        return None
    width = page.rect.width
    # Coverage is measured per WORD, not per line. The OCR frequently groups a
    # line's text right across the gutter, so a line's own extent spans both
    # columns and hides the very gap being looked for; a word never does.
    words = page.get_text("words")
    if len(words) < 20:
        return None
    covered = bytearray(int(width) + 2)
    for word in words:
        start = max(0, int(word[0]))
        end = min(len(covered) - 1, int(word[2]) + 1)
        for x in range(start, end):
            covered[x] = 1

    # Only a gap spanning the middle of the page can be the gutter; a gap at the
    # margins is just the page edge.
    low, high = int(width * 0.3), int(width * 0.7)
    best_start = best_len = 0
    run_start = None
    for x in range(low, high):
        if not covered[x]:
            if run_start is None:
                run_start = x
        else:
            if run_start is not None and x - run_start > best_len:
                best_start, best_len = run_start, x - run_start
            run_start = None
    if run_start is not None and high - run_start > best_len:
        best_start, best_len = run_start, high - run_start

    # A true gutter is a clear channel. Narrower than this and it is more likely
    # word spacing in a full-width line.
    if best_len >= 12:
        return float(best_start + best_len)
    return _split_by_line_starts(lines)


def _split_by_line_starts(lines: list[dict]) -> float | None:
    """Fall back to where lines begin when no blank gutter can be measured.

    Anything that reaches across the columns -- a full-width heading, or the
    captions under the dice illustration -- fills the gutter in a coverage
    histogram and hides it, even though the page is plainly in two columns.
    What survives that is where lines START: two columns of body text give two
    tight, well-separated, similarly-sized clusters of left edges.
    """
    buckets: dict[int, int] = {}
    for item in lines:
        key = int(item["x0"] / 3) * 3
        buckets[key] = buckets.get(key, 0) + 1
    total = len(lines)
    # A column holds a real share of the page's lines; anything less is an
    # indent or a stray inset.
    candidates = sorted(x for x, n in buckets.items() if n >= total * 0.18)
    best: tuple[int, int] | None = None
    for i, left in enumerate(candidates):
        for right in candidates[i + 1:]:
            # Two columns sit far apart and carry comparable numbers of lines;
            # an indented block sits close to its parent and carries fewer.
            if right - left < 100:
                continue
            support = buckets[left] + buckets[right]
            ratio = min(buckets[left], buckets[right]) / max(buckets[left], buckets[right])
            if ratio < 0.5:
                continue
            if best is None or support > best[1]:
                best = (right, support)
    return float(best[0] - 4) if best else None

def is_heading(line: dict) -> bool:
    """True when a line is a printed heading rather than body text."""
    text = line["text"].strip()
    return (
        line.get("display", line["bold"]) >= _MIN_BOLD_RATIO
        and line["size"] >= _MIN_HEADING_SIZE
        and _MIN_HEADING_CHARS <= len(text) <= _MAX_HEADING_CHARS
        and _caps_ratio(text) >= _MIN_CAPS_RATIO
    )


def is_named_entry(line: dict, min_size: int = 9, max_size: int = 13,
                   max_chars: int = 52) -> bool:
    """True when a line names a rule rather than being part of one.

    Weapon traits, skills and conditions are each printed as a short ALL CAPS
    name in display type, at the size of body text rather than above it, with
    their description running on beneath. ``is_heading`` will not see them: it
    asks for 12pt and for the word "Bold" in the font, and these are 9-10pt and
    sometimes a condensed face. That is the whole reason the trait, skill and
    condition tables stood empty.
    """
    text = line["text"].strip()
    if not text or len(text) > max_chars:
        return False
    if line.get("display", line["bold"]) < _MIN_BOLD_RATIO:
        return False
    if not (min_size <= line["size"] <= max_size):
        return False
    return _caps_ratio(text) >= _MIN_CAPS_RATIO


def running_header(lines: list[dict]) -> str:
    """The repeated page header ("CORE RULES - MOVEMENT"), or "".

    It is the topmost line, is set in caps, and names the chapter and section,
    which is how the heading tree recovers a page's place in a book that has no
    bookmark outline at all.
    """
    if not lines:
        return ""
    top = min(lines, key=lambda d: d["y"])
    if top["y"] > 80 and len(lines) > 2:
        return ""
    text = top["text"].strip()
    if len(text) > 70 or _caps_ratio(text) < _MIN_CAPS_RATIO:
        return ""
    return text


def word_rows(page, tol: float = 2.5,
              split: float | None = None) -> list[list[tuple[float, float, str]]]:
    """Page words grouped into printed rows, each sorted left to right.

    Rows are grouped on each word's VERTICAL CENTRE, not its top edge. The OCR
    baseline wanders within a line, and it wanders much further at the top than
    through the middle: on the heavy bolter's row the tops span 5.3pt while the
    centres span 1.9pt. Grouping on tops splits such a row in two and drops the
    cells that land in the offcut -- which is how that weapon lost its Strength
    and Lethality. Centres hold the row together.
    """
    words = page.get_text("words")
    if not words:
        return []

    # With a ``split``, words are grouped within a column and never across the
    # gutter. A table set in one column sits at the same heights as whatever is
    # printed beside it, so grouping by y alone welds the two together: the Wyrd
    # power profile came out as "Force Blast 8\" 12\" 2 -1 1 Knockback
    # Initiative characteristic by 2", half of it the neighbouring paragraph.
    #
    # The caller supplies the split rather than this function measuring one,
    # because a full-width table defeats any measurement: its own narrow, often
    # empty columns leave a blank channel that looks exactly like a gutter, and
    # splitting there cuts every row of the table in half. Only the caller knows
    # whether it is looking at a page of prose or a page of table.
    bands: list[list[tuple[float, float, float, str]]] = [[], []]
    for word in words:
        side = 1 if split and word[0] >= split else 0
        bands[side].append(((word[1] + word[3]) / 2, word[0], word[2], word[4]))

    rows: list[list[tuple[float, float, str]]] = []
    for band in bands:
        if not band:
            continue
        band.sort(key=lambda t: (t[0], t[1]))
        current: list[tuple[float, float, str]] = []
        centres: list[float] = []
        for yc, x0, x1, text in band:
            # Compare against the row's mean centre so a long row tracks a gentle
            # drift instead of being cut once it strays from its first word.
            if current and abs(yc - (sum(centres) / len(centres))) > tol:
                rows.append(sorted(current))
                current, centres = [], []
            current.append((x0, x1, text))
            centres.append(yc)
        if current:
            rows.append(sorted(current))
    return rows


def column_bounds(anchors: list[float], max_slack: float = 10.0) -> list[float]:
    """Left edges of each column, derived from its header anchor.

    A printed value sits slightly right of where its header starts, so a column
    owns everything from a little left of its anchor up to the next column's
    edge. Midway between two anchors would be wrong: Traits is a wide free-text
    column sitting beside the narrow numeric Creds column, and its later words
    ("Rapid Fire (2)") reach well past the midpoint. A small fixed inset keeps
    those words in Traits while still catching Creds' own left-aligned number.
    """
    gaps = [b - a for a, b in zip(anchors, anchors[1:])]
    slack = min(max_slack, min(gaps) / 2) if gaps else max_slack
    return [a - slack for a in anchors]


def columns(row: list[tuple[float, float, str]], anchors: list[float],
            bounds: list[float] | None = None, tail_boundary: int = 0) -> list[str]:
    """Assign a row's words to columns by x, returning one cell per anchor.

    The result is ``[label] + [cell per anchor]``: everything left of the first
    column's edge is the row's label.

    An empty cell survives either way, which is the point of doing this by
    geometry at all: a value the book did not print leaves its own column empty
    instead of letting the next value slide into it -- the difference between
    reading an autopistol's Lethality as its AP and reading AP as not printed.

    The book sets these tables to two different alignments, and they need
    different treatment:

    * The Trading Post lists are LEFT aligned, and their Traits column is wide
      free text sitting beside the narrow numeric cost columns. Its later words
      ("Rapid Fire (2)") reach past the midpoint, so nearest-anchor would file
      them under Creds and price a heavy bolter at "Fire (2) 100".
    * The worked example in the weaponry chapter is CENTRE aligned -- each
      value's centre sits on its header's centre. There the trait text as a
      whole is centred under "Traits" while its first word begins left of that,
      so a left-edge rule reads "Rapid" as the Lethality.

    So the leading columns go to the nearest anchor, which is right for centred
    values and still right for left-aligned ones, while the last
    ``tail_boundary`` columns -- the numeric costs -- are claimed by left edge,
    which keeps a long trait list out of them.
    """
    if bounds is None:
        bounds = column_bounds(anchors)
    count = len(anchors)
    tail_start = max(0, count - tail_boundary)
    cells: list[list[str]] = [[] for _ in range(count + 1)]
    for x0, x1, text in row:
        centre = (x0 + x1) / 2
        if centre < bounds[0]:
            cells[0].append(text)
            continue
        tail_index = None
        for i in range(tail_start, count):
            if centre >= bounds[i]:
                tail_index = i
        if tail_index is not None:
            cells[tail_index + 1].append(text)
            continue
        nearest = min(range(tail_start) or range(count),
                      key=lambda i: abs(centre - anchors[i]))
        cells[nearest + 1].append(text)
    return [" ".join(c).strip() for c in cells]


def anchor_set(samples: list[list[float]]) -> list[float]:
    """Collapse repeated observations of a column's x into one stable anchor.

    Header rows are not individually trustworthy: OCR drops a header token here
    and there, so one page's header can be missing ``L`` and another's ``Str``.
    Taking the median of every observation across the book gives an anchor per
    column that no single dropout can move.
    """
    return [round(statistics.median(xs), 1) for xs in samples if xs]
