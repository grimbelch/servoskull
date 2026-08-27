"""Extract NPC stat blocks and their trait lists from the module PDF.

Each NPC in the book is presented the same way: a bold heading giving the name,
career and status ("MARIA-ULRIKE VON LIEBWITZ - NOBLE LORD (GOLD 7)"), a ruled
characteristic table, and then run-in lists of Skills, Talents, Traits and
Trappings. The characteristic table is a real PDF table, so it is read with
PyMuPDF's table finder rather than by pattern-matching text.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from .layout import Block, ModuleDocument, table_bboxes
from .sections import Section, slugify

# The characteristic columns, in printed order. The book uses both "Ag" and
# "Agi" for Agility across different pages.
PROFILE_COLUMNS = ["m", "ws", "bs", "s", "t", "i", "ag", "dex", "intl", "wp", "fel", "w"]
_HEADER_ALIASES = {
    "m": "m", "ws": "ws", "bs": "bs", "s": "s", "t": "t", "i": "i",
    "ag": "ag", "agi": "ag", "dex": "dex", "int": "intl", "wp": "wp",
    "fel": "fel", "w": "w",
}

_RUNIN_LABELS = ("Skills", "Talents", "Traits", "Trappings", "Spells", "Psychology")
_RUNIN_RE = re.compile(rf"\b({'|'.join(_RUNIN_LABELS)}):\s*")
# "NAME - CAREER (STATUS TIER)", with either a hyphen or an en/em dash.
_STATHEAD_RE = re.compile(
    r"^(?P<name>.+?)\s*[-\u2013\u2014]\s*(?P<career>.+?)"
    r"(?:\s*\((?P<status>[^)]*)\))?\s*$"
)
_TRAIT_SPLIT_RE = re.compile(r",(?![^(]*\))")
_TRAIT_VALUE_RE = re.compile(r"^(?P<name>.*?)(?:\s+(?P<value>[+-]?\d+))?$")


@dataclass
class NpcProfile:
    """One characteristic row belonging to an NPC."""

    label: str = "main"
    characteristics: dict[str, Optional[int]] = field(default_factory=dict)
    skills: list[dict] = field(default_factory=list)
    talents: list[dict] = field(default_factory=list)
    traits: list[dict] = field(default_factory=list)
    trappings: list[dict] = field(default_factory=list)
    spells: list[dict] = field(default_factory=list)
    psychology: list[dict] = field(default_factory=list)


@dataclass
class Npc:
    """An NPC as printed in the module."""

    name: str
    slug: str
    career: str = ""
    status: str = ""
    page: int = 0
    description: str = ""
    faction: str = ""
    chapter_slug: str = ""
    section_slug: str = ""
    profiles: list[NpcProfile] = field(default_factory=list)


def _to_int(text: str) -> Optional[int]:
    match = re.search(r"-?\d+", text or "")
    return int(match.group(0)) if match else None


def _normalise_header(cells: list[Optional[str]]) -> Optional[list[str]]:
    """Map a detected table header onto the canonical characteristic columns."""
    keys = []
    for cell in cells:
        token = re.sub(r"[^a-z]", "", (cell or "").lower())
        if token not in _HEADER_ALIASES:
            return None
        keys.append(_HEADER_ALIASES[token])
    return keys if len(set(keys)) >= 10 else None


def parse_trait_list(text: str) -> list[dict]:
    """Split "Bribery 76, Melee (Basic) 73" into name/value pairs.

    Commas inside parentheses are not separators, so "Melee (Basic, Fencing)"
    survives intact.
    """
    entries = []
    for chunk in _TRAIT_SPLIT_RE.split(text or ""):
        chunk = chunk.strip(" .;")
        if not chunk:
            continue
        match = _TRAIT_VALUE_RE.match(chunk)
        name = (match.group("name") or chunk).strip()
        raw_value = match.group("value")
        if not name:
            continue
        entries.append({"name": name, "value": int(raw_value) if raw_value else None})
    return entries


def parse_runin_lists(text: str) -> dict[str, list[dict]]:
    """Pull the Skills/Talents/Traits/Trappings lists out of a prose run."""
    result: dict[str, list[dict]] = {}
    matches = list(_RUNIN_RE.finditer(text or ""))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        label = match.group(1).lower()
        result[label] = parse_trait_list(text[match.end() : end])
    return result


def _profile_tables(doc: ModuleDocument, page_number: int) -> list[tuple[tuple, list[str], list[list]]]:
    """Return (bbox, column keys, data rows) for each characteristic table."""
    page = doc.doc[page_number - 1]
    found = []
    for table in page.find_tables().tables:
        rows = table.extract()
        if len(rows) < 2:
            continue
        keys = _normalise_header(rows[0])
        if keys is None:
            continue
        found.append((tuple(table.bbox), keys, rows[1:]))
    return found




def _overlaps(a: tuple, b: tuple, minimum: float = 0.4) -> bool:
    """True when two bboxes share most of their horizontal extent."""
    span = min(a[2], b[2]) - max(a[0], b[0])
    width = min(a[2] - a[0], b[2] - b[0])
    return width > 0 and span / width >= minimum


def _anchor_for_table(page_blocks: list[tuple[int, Block]], table_bbox: tuple):
    """Find the heading a characteristic table belongs to.

    Every stat block is typeset as a heading immediately above its table in the
    same column, so the anchor is the nearest block whose bottom edge sits above
    the table and whose horizontal extent overlaps it.
    """
    best = None
    best_bottom = -1.0
    for index, block in page_blocks:
        bbox = block.bbox
        if bbox[3] > table_bbox[1] + 2:
            continue
        if not _overlaps(bbox, table_bbox):
            continue
        if bbox[3] > best_bottom:
            best_bottom = bbox[3]
            best = (index, block)
    return best


def _split_stathead(text: str) -> tuple[str, str, str]:
    """Split "NAME - CAREER (STATUS)" into its parts.

    The separator must be a spaced dash, which keeps hyphenated names such as
    "Maria-Ulrike" and careers such as "Witch-Hunter" intact.
    """
    status = ""
    match = re.search(r"\(([^)]*)\)\s*$", text)
    if match:
        status = match.group(1).strip()
        text = text[: match.start()].strip()
    parts = re.split(r"\s+[-\u2013\u2014]\s+", text)
    if len(parts) >= 2:
        return " - ".join(parts[:-1]).strip(), parts[-1].strip(), status
    return text.strip(), "", status


def _titlecase(text: str) -> str:
    """Restore mixed case from the all-caps stat headings."""
    if not text or text != text.upper():
        return text
    out = re.sub(r"[A-Za-z']+", lambda m: m.group(0).capitalize(), text.lower())
    return re.sub(
        r"\b(Of|The|And|Von|Van|De|Der|Zu)\b", lambda m: m.group(0).lower(), out
    ).strip()


def _runin_tail(blocks: list[Block], start: int) -> str:
    """Collect the run-in lists printed after a stat heading.

    Stops at the next heading or sidebar so an adjacent boxed-out section cannot
    bleed into the NPC's trappings.
    """
    parts = []
    for block in blocks[start:]:
        if block.style not in {"BODY", "EM", "RUNIN"}:
            break
        parts.append(block.text)
    return " ".join(parts)


def extract_npcs(
    doc: ModuleDocument, blocks: list[Block], roots: list[Section]
) -> list[Npc]:
    """Build the NPC list, one per characteristic table found in the book.

    The tables are authoritative: an NPC exists precisely when the book prints a
    profile for them. Each table is then matched back to its heading, its
    descriptive prose, and the section of the adventure it appears in.
    """
    sections = sorted(
        (node for root in roots for node in root.walk() if node.anchor is not None),
        key=lambda node: node.anchor,
    )

    def section_at(block_index: int) -> Optional[Section]:
        found = None
        for section in sections:
            if section.anchor <= block_index:
                found = section
            else:
                break
        return found

    by_page: dict[int, list[tuple[int, Block]]] = {}
    for index, block in enumerate(blocks):
        by_page.setdefault(block.page, []).append((index, block))

    npcs: list[Npc] = []
    for page_number in range(1, doc.page_count + 1):
        page_blocks = by_page.get(page_number, [])
        for table_bbox, keys, rows in _profile_tables(doc, page_number):
            anchor = _anchor_for_table(page_blocks, table_bbox)
            if anchor is None or not rows:
                continue
            index, block = anchor

            if block.style == "STATHEAD":
                raw_name, career, status = _split_stathead(block.text.strip())
            else:
                raw_name, career, status = block.text.strip(), "", ""
            name = _titlecase(raw_name)
            career = _titlecase(career)

            # The heading above the stat heading usually carries the full,
            # properly cased name, e.g. "Gravin Maria-Ulrike von Liebwitz".
            display = name
            description_start = index
            for back in range(index - 1, max(index - 8, -1), -1):
                candidate = blocks[back]
                if candidate.style == "STATHEAD":
                    break
                if candidate.is_heading:
                    if _match_name(candidate.text, name):
                        display = candidate.text.strip()
                    description_start = back + 1
                    break

            description = "\n\n".join(
                b.text
                for b in blocks[description_start:index]
                if b.style in {"BODY", "EM"} and not _RUNIN_RE.search(b.text)
            ).strip()

            # Group stat blocks print the status tier in the heading itself
            # ("Palace Guards (Gold 2)"); it is already captured separately.
            if status:
                display = re.sub(
                    rf"\s*\(\s*{re.escape(status)}\s*\)\s*$", "", display, flags=re.I
                ).strip()

            section = section_at(index)
            chapter = section.ancestor_of_kind("chapter") if section else None
            group = section if section and section.kind == "npc_group" else None
            if section and group is None:
                group = section.ancestor_of_kind("npc_group")

            npc = Npc(
                name=display,
                slug=slugify(f"{display}-p{page_number}"),
                career=career,
                status=status,
                page=page_number,
                description=description,
                faction=group.title if group else "",
                chapter_slug=chapter.slug if chapter else "",
                section_slug=section.slug if section else "",
            )

            row = rows[0]
            profile = NpcProfile(
                characteristics={
                    key: _to_int(row[position] if position < len(row) else "")
                    for position, key in enumerate(keys)
                }
            )
            for label, entries in parse_runin_lists(_runin_tail(blocks, index + 1)).items():
                setattr(profile, label, entries)
            npc.profiles.append(profile)
            npcs.append(npc)

    return npcs


def _match_name(heading: str, name: str) -> bool:
    """True when a heading plausibly names the same NPC as a stat heading."""
    heading_key = re.sub(r"[^a-z]", "", heading.lower())
    name_key = re.sub(r"[^a-z]", "", name.lower())
    if not heading_key or not name_key:
        return False
    if heading_key in name_key or name_key in heading_key:
        return True
    surname = re.sub(r"[^a-z]", "", name.lower().split()[-1]) if name.split() else ""
    return bool(surname) and surname in heading_key
