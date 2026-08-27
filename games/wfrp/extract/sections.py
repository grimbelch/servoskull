"""Build the module section tree from the PDF bookmark outline.

The source PDF carries a complete hierarchical outline — 442 entries for Rough
Nights & Hard Days — giving the exact title, nesting level and page of every
section in the book. That outline is the authoritative structure, so it is used
directly rather than inferred from prose.

The outline alone is not enough, though: it locates sections only to the page,
and several sections can share a page. So each outline entry is *anchored* to
the real heading block in the reading-order flow, which gives an exact position.
Body text for a section is then everything between its anchor and the next one.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Optional

from .layout import Block, ModuleDocument


@dataclass
class Section:
    """One node of the module's section tree."""

    level: int
    title: str
    page: int
    kind: str = "section"
    slug: str = ""
    parent: Optional["Section"] = None
    children: list["Section"] = field(default_factory=list)
    body_md: str = ""
    page_start: int = 0
    page_end: int = 0
    doc_order: int = 0
    ordinal: int = 0
    anchor: Optional[int] = None  # index into the flat block list
    # Half-open span of the flat block list holding this section's own prose,
    # i.e. everything after its heading and before the next section's. Callers
    # that need the typographic style of the text (to tell a run-in "CN:" label
    # from the description that follows it) read the blocks directly.
    block_start: int = 0
    block_end: int = 0

    @property
    def word_count(self) -> int:
        return len(self.body_md.split())

    def walk(self):
        yield self
        for child in self.children:
            yield from child.walk()

    def ancestor_of_kind(self, kind: str) -> Optional["Section"]:
        node = self.parent
        while node is not None:
            if node.kind == kind:
                return node
            node = node.parent
        return None


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:80] or "section"


def _match_key(text: str) -> str:
    """Collapse a title to a comparable key, ignoring punctuation and case."""
    return re.sub(r"[^a-z0-9]+", "", text.lower())


# Section titles whose children are rooms rather than generic subsections.
_LOCATION_TITLES = {
    "theinn", "thecourthouse", "theoperahouse", "thecastle", "themansion",
}
_RESOLUTION_TITLES = {"resolution", "concludingtheadventure"}
_TIME_RE = re.compile(
    r"^(?:\d{1,2}[:.]\d{2}\s*(?:a\.?m\.?|p\.?m\.?)?|midnight|noon|\d{1,2}\s*(?:a\.?m\.?|p\.?m\.?)"
    r"|(?:angestag|festag|marktag|backertag|bezahltag|konigstag|wellentag)\b.*"
    r"|two\s+rounds\s+later.*)$",
    re.IGNORECASE,
)


def infer_kind(section: Section, chapter_titles: set[str]) -> str:
    """Classify a section from its title, depth and parent."""
    key = _match_key(section.title)
    parent_kind = section.parent.kind if section.parent else ""
    parent_key = _match_key(section.parent.title) if section.parent else ""

    if section.level == 1:
        if key in chapter_titles:
            return "chapter"
        if key.startswith("appendix"):
            return "appendix"
        return "front_matter"

    if "map" in key and ("mapof" in key or key.endswith("map")):
        return "map"
    if key == "nonplayercharacters":
        return "npc_index"
    if parent_kind == "npc_index":
        return "npc_group"
    if parent_kind == "npc_group":
        return "npc_entry"
    if key == "plotsummaries":
        return "plot_index"
    if parent_kind == "plot_index":
        return "plot"
    if key == "events":
        return "event_index"
    if parent_kind == "event_index":
        return "event" if _TIME_RE.match(section.title) else "event_note"
    if key in _RESOLUTION_TITLES:
        return "resolution"
    if parent_kind == "resolution":
        return "resolution_detail"
    if key in _LOCATION_TITLES:
        return "location"
    if parent_kind == "location":
        return "room"
    if key in {"location", "gettingthere"}:
        return "location_intro"
    if key == "theadventure":
        return "adventure"
    if key.startswith("playersintroduction"):
        return "intro"
    if parent_kind in {"appendix", "rules"} or section.ancestor_of_kind("appendix"):
        return "rules"
    return "section"


def classify_module_sections(roots: list[Section]) -> None:
    """Assign a `kind` to every node of an adventure-module outline."""
    chapter_titles = {
        _match_key(node.title)
        for node in roots
        if node.level == 1 and any(c.title.lower() == "the adventure" for c in node.children)
    }
    for root in roots:
        for node in root.walk():
            node.kind = infer_kind(node, chapter_titles)


def build_tree(doc: ModuleDocument, classifier=classify_module_sections) -> list[Section]:
    """Assemble the outline into a tree of Section nodes.

    ``classifier`` sets each node's ``kind`` and is supplied by the caller,
    because what a section *is* depends on the kind of book: an adventure has
    plots and events where a rulebook has careers and spell lists.
    """
    toc = doc.toc()
    roots: list[Section] = []
    stack: list[Section] = []
    order = 0

    for level, title, page in toc:
        section = Section(level=level, title=title, page=page, doc_order=order)
        order += 1
        while stack and stack[-1].level >= level:
            stack.pop()
        if stack:
            section.parent = stack[-1]
            section.ordinal = len(stack[-1].children)
            stack[-1].children.append(section)
        else:
            section.ordinal = len(roots)
            roots.append(section)
        stack.append(section)

    classifier(roots)
    for root in roots:
        for node in root.walk():
            node.slug = slugify(node.title)
    return roots


def _flatten(roots: list[Section]) -> list[Section]:
    out: list[Section] = []
    for root in roots:
        out.extend(root.walk())
    out.sort(key=lambda s: s.doc_order)
    return out


def anchor_sections(doc: ModuleDocument, roots: list[Section]) -> list[Block]:
    """Locate each section's heading in the reading-order block flow.

    Returns the flat block list so callers can slice body text from it. Matching
    walks forward monotonically, so a title that repeats across chapters (such
    as "Following the Campaign") binds to the correct occurrence.
    """
    blocks = doc.blocks_in_range(1, doc.page_count)
    heading_index: list[tuple[int, str, int]] = [
        (i, _match_key(b.text), b.page)
        for i, b in enumerate(blocks)
        if b.is_heading or b.style in {"SIDEBAR_TITLE", "STATHEAD"}
    ]

    sections = _flatten(roots)
    claimed: set[int] = set()
    cursor = 0
    for section in sections:
        key = _match_key(section.title)
        if not key:
            continue
        # A printed heading often carries a qualifier the outline omits: the
        # skill listed as "Art" is set as "Art (Dex) basic, grouped". Exact
        # matches are still preferred, so a prefix only wins when nothing
        # matches the title outright.
        exact: list[int] = []
        prefixed: list[int] = []
        for position, (block_i, block_key, block_page) in enumerate(heading_index):
            if block_i in claimed or abs(block_page - section.page) > 2:
                continue
            if block_key == key:
                exact.append(position)
            elif len(key) >= 3 and block_key.startswith(key):
                prefixed.append(position)
        candidates = exact or prefixed
        if not candidates:
            continue
        # Prefer the next unclaimed match at or after the cursor so repeated
        # titles bind in order. The outline sometimes lists a sidebar before the
        # point where it is actually printed, so fall back to the closest match
        # behind the cursor rather than giving up.
        ahead = [position for position in candidates if position >= cursor]
        best = ahead[0] if ahead else candidates[-1]
        section.anchor = heading_index[best][0]
        claimed.add(section.anchor)
        cursor = max(cursor, best + 1)

    _fallback_anchor(sections, heading_index)
    return blocks


def _fallback_anchor(
    sections: list[Section], heading_index: list[tuple[int, str, int]]
) -> None:
    """Second pass for sections the strict matcher missed.

    Printed headings sometimes differ from the outline in wording or case, so a
    looser substring match is tried, then a fuzzy one -- the publisher's own
    bookmarks contain typos ("Clases", "Warior Priest", "Sucess Levels") that
    never appear in the printed heading. Both are confined to the gap between
    the neighbouring anchored sections, which keeps a loose match from binding
    to a similarly titled heading elsewhere in the book.
    """
    claimed = {s.anchor for s in sections if s.anchor is not None}

    for position, section in enumerate(sections):
        if section.anchor is not None:
            continue
        key = _match_key(section.title)
        if len(key) < 3:
            continue

        lo = next(
            (
                sections[i].anchor
                for i in range(position - 1, -1, -1)
                if sections[i].anchor is not None
            ),
            -1,
        )
        hi = next(
            (
                sections[i].anchor
                for i in range(position + 1, len(sections))
                if sections[i].anchor is not None
            ),
            None,
        )
        if hi is None:
            hi = heading_index[-1][0] + 1 if heading_index else 0

        window = [
            (block_i, block_key)
            for block_i, block_key, _page in heading_index
            if lo < block_i < hi and block_i not in claimed
        ]

        match = next(
            (
                block_i
                for block_i, block_key in window
                if key in block_key or block_key in key
            ),
            None,
        )
        if match is None:
            scored = [
                (SequenceMatcher(None, key, block_key).ratio(), block_i)
                for block_i, block_key in window
            ]
            scored = [pair for pair in scored if pair[0] >= 0.88]
            if scored:
                match = max(scored)[1]
        if match is not None:
            section.anchor = match
            claimed.add(match)


def attach_bodies(blocks: list[Block], roots: list[Section]) -> None:
    """Fill each section's body with the prose between it and the next section."""
    sections = _flatten(roots)
    # Ordered by physical position, not outline order: a section's body is the
    # prose printed after its heading and before the next section's heading.
    anchored = sorted(
        (s for s in sections if s.anchor is not None), key=lambda s: s.anchor
    )

    for position, section in enumerate(anchored):
        start = section.anchor + 1
        end = anchored[position + 1].anchor if position + 1 < len(anchored) else len(blocks)
        section.block_start = start
        section.block_end = end
        parts: list[str] = []
        pages: list[int] = [blocks[section.anchor].page]
        for block in blocks[start:end]:
            pages.append(block.page)
            if block.style == "SIDEBAR_TITLE":
                parts.append(f"### {block.text}")
            elif block.style == "SIDEBAR":
                # Boxed commentary. Quoting it keeps the aside distinguishable
                # from the rules around it once the prose is flattened.
                parts.append(
                    "\n".join(f"> {line}" for line in block.text.split("\n"))
                )
            elif block.style == "LETTER":
                parts.append(
                    "\n".join(f"> *{line}*" if line else ">"
                              for line in block.text.split("\n"))
                )
            elif block.style == "STATHEAD":
                parts.append(f"**{block.text}**")
            elif block.is_heading:
                parts.append(f"#### {block.text}")
            else:
                parts.append(block.text)
        section.body_md = "\n\n".join(parts).strip()
        section.page_start = min(pages)
        section.page_end = max(pages)

    # Sections the outline lists but which have no printed heading (maps, for
    # instance) still get a page range so the viewer can jump to them.
    for section in sections:
        if section.anchor is None:
            section.page_start = section.page
            section.page_end = section.page

    # A container's own body stops at its first child heading, so its span must
    # be rolled up from its descendants — otherwise a chapter reports one page.
    for section in sorted(sections, key=lambda s: -s.level):
        if not section.children:
            continue
        starts = [section.page_start or section.page]
        ends = [section.page_end or section.page]
        for child in section.children:
            starts.append(child.page_start or child.page)
            ends.append(child.page_end or child.page)
        section.page_start = min(starts)
        section.page_end = max(ends)


def extract_sections(
    doc: ModuleDocument, classifier=classify_module_sections
) -> tuple[list[Section], list[Block]]:
    """Build the section tree and populate it with body text."""
    roots = build_tree(doc, classifier)
    blocks = anchor_sections(doc, roots)
    attach_bodies(blocks, roots)
    return roots, blocks
