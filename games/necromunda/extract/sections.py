"""Recovering the book's heading tree and the prose under each heading.

This PDF has no bookmark outline at all, so the tree is rebuilt from what the
page itself shows:

* the running header names the chapter and the section ("CORE RULES - MOVEMENT"),
  which is the only place a page's position in the book is stated;
* headings inside the page are bold caps, and give the subsections.

Type size alone is not enough to find a heading, because the OCR marks occasional
body lines bold at heading sizes; those lines are mixed case, so the caps test in
``layout.is_heading`` is what actually separates them.
"""
from __future__ import annotations

import re

from . import layout

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")
# A line of a stat table rather than a sentence: mostly values and dashes.
_VALUEISH = re.compile(r'^(?:[+-]?\d+\*?"?|-|—|T|E|S(?:\+\d+)?|D\d+|\d+D\d+|\d+\+|\|)$')
# A word broken across a line end, to be rejoined rather than left split.
_HYPHEN_BREAK = re.compile(r"(\w)-$")
# Equipment is headed by its name and then its price, each on its own line and
# often a point or two apart in the scan. A price is never the name of a rule,
# so it always belongs to the heading above it however the sizes came out.
_PRICE_LINE = re.compile(r"^\d+\s*CREDITS\b", re.I)


def slugify(text: str) -> str:
    return _SLUG_STRIP.sub("-", text.lower()).strip("-")[:80]


def _split_header(header: str) -> tuple[str, str]:
    """The running header's chapter and section halves."""
    for sep in (" - ", " -", "- "):
        if sep in header:
            chapter, _, section = header.partition(sep)
            return chapter.strip(), section.strip()
    return header.strip(), ""


def _is_tabular(text: str) -> bool:
    """True when a line is a table row rather than prose.

    Table content is already recovered as columns in the data layer; leaving the
    flattened version out of the prose keeps a quoted rule readable instead of
    interleaving it with rows of loose numbers.
    """
    tokens = text.split()
    if len(tokens) < 3:
        return False
    hits = sum(1 for t in tokens if _VALUEISH.match(t))
    return hits >= max(3, len(tokens) * 0.6)


def _join_prose(lines: list[str]) -> str:
    """Join wrapped lines into paragraphs, repairing hyphen breaks."""
    out: list[str] = []
    buf = ""
    for line in lines:
        text = line.strip()
        if not text:
            continue
        if not buf:
            buf = text
            continue
        match = _HYPHEN_BREAK.search(buf)
        if match:
            buf = buf[: match.start(1) + 1] + text
        else:
            buf = f"{buf} {text}"
        # A line ending a sentence closes the paragraph, which keeps quoted
        # rules from running together into one wall of text.
        if buf.endswith((".", ":", "!", "?")) and len(buf) > 200:
            out.append(buf)
            buf = ""
    if buf:
        out.append(buf)
    return "\n\n".join(out)


def page_sections(page, page_no: int) -> list[dict]:
    """The headings on one page, each with the prose that follows it.

    Returns dicts of ``chapter``, ``section``, ``title``, ``level``, ``body``
    and ``page``. A page whose prose precedes its first heading yields a lead
    entry titled for the running header's section, so no paragraph is orphaned.
    """
    lines = layout.page_lines(page)
    if not lines:
        return []
    header = layout.running_header(lines)
    chapter, section = _split_header(header)

    body_lines: list[str] = []
    current: dict | None = None
    out: list[dict] = []

    def flush() -> None:
        nonlocal current, body_lines
        text = _join_prose(body_lines)
        if current is not None:
            current["body"] = text
            if current["title"]:
                out.append(current)
        elif text:
            out.append({"chapter": chapter, "section": section,
                        "title": section or chapter, "level": 2,
                        "body": text, "page": page_no})
        current, body_lines = None, []

    for line in lines:
        text = line["text"].strip()
        if not text or text == header:
            continue
        if layout.is_heading(line):
            # The chapter plate repeats the chapter name in display type; it is
            # not a subsection of itself.
            if text in (chapter, section):
                continue
            # A heading too long for its column is printed over two or three
            # lines. Read separately they become sections titled "LINE OF
            # SIGHT &" and "SOLID TERRAIN FEATURES", and the rule is filed
            # under the second half of its own name.
            # A heading continued on a second line starts at the same margin
            # as the first. Two headings level with each other in facing
            # columns do not, and joining those produced a section called
            # "SINGLE ACTIONS FREE ACTIONS". Alignment is the test rather than
            # the column, because a page can be full width at the top and two
            # columns lower down, which leaves no gutter to measure.
            aligned = abs(line["x0"] - current.get("x0", 0)) < 20 if current else False
            if (current is not None and not body_lines and aligned
                    and (_PRICE_LINE.match(text)
                         or abs(line["size"] - current.get("size", 0)) <= 2)):
                current["title"] = f"{current['title']} {text}".strip()
                continue
            flush()
            current = {"chapter": chapter, "section": section, "title": text,
                       "level": 3, "body": "", "page": page_no,
                       "size": line["size"], "column": line["column"],
                       "x0": line["x0"]}
            continue
        if _is_tabular(text):
            continue
        body_lines.append(text)
    flush()
    return out


def build_tree(doc) -> list[dict]:
    """Every section in the book, in document order, with parents resolved.

    Consecutive pages under the same running header continue one section rather
    than starting a new one each page, so a rule that spans a spread is stored
    whole.
    """
    flat: list[dict] = []
    for page_no in range(doc.page_count):
        flat.extend(page_sections(doc.load_page(page_no), page_no))

    # Not every page carries a running header -- chapter plates, full-page
    # tables and art pages have none, and that is half the book. A chapter runs
    # unbroken until the next one is announced, so the last one seen still
    # applies; without this carry-forward those pages lose their place in the
    # tree even though their prose came through intact.
    chapter = section = ""
    for item in flat:
        if item["chapter"] and len(item["chapter"]) > 2:
            chapter = item["chapter"]
            section = item["section"]
        elif item["section"]:
            section = item["section"]
        else:
            item["chapter"] = chapter
            item["section"] = item["section"] or section

    # The index is the last thing in the book and is nothing but names against
    # page numbers. Left in, it answers rules questions with strings of digits --
    # a search for "rapid fire trait" matches the index line before the trait
    # itself. Everything from its heading to the back cover is dropped.
    for cut, item in enumerate(flat):
        if item["title"].strip().upper() in {"INDEX", "LNDEX"}:
            flat = flat[:cut]
            break

    merged: list[dict] = []
    for item in flat:
        # Prose before the first heading on a page is the previous section
        # running on across the page break, not a section of its own. Left
        # standing it becomes an untitled entry that search can surface with
        # no way to say what rule it belongs to.
        if not item["title"].strip() and merged:
            prev = merged[-1]
            prev["body"] = f"{prev['body']}\n\n{item['body']}".strip()
            prev["page_end"] = item["page"]
            continue
        if (merged and item["title"] == merged[-1]["title"]
                and item["chapter"] == merged[-1]["chapter"]
                and item["section"] == merged[-1]["section"]):
            prev = merged[-1]
            prev["body"] = f"{prev['body']}\n\n{item['body']}".strip()
            prev["page_end"] = item["page"]
            continue
        item["page_end"] = item["page"]
        merged.append(item)
    return merged
