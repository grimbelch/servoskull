"""Extract the bestiary's creature profiles and trait lists.

Bestiary entries are laid out like the module's NPCs -- a heading, a ruled
characteristic table, then run-in lists -- so the profile is read with the same
table finder rather than by pattern-matching text. A creature's profile is
identified by position: it is the first characteristic table below the
creature's heading and above the next one.

Creature traits carry a rating in the name as printed, "Weapon+7" or
"Ranged+8 (50)", and the optional traits that distinguish a variant are
introduced by a second run-in label inside the same paragraph.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from ..layout import ModuleDocument
from ..sections import Section, slugify
from ..statblocks import PROFILE_COLUMNS, _profile_tables, _to_int, parse_trait_list

_TRAITS_RE = re.compile(r"\bTraits:\s*", re.IGNORECASE)
_OPTIONAL_RE = re.compile(r"\bOptional:\s*", re.IGNORECASE)
_SKILLS_RE = re.compile(r"\bSkills:\s*", re.IGNORECASE)
_TALENTS_RE = re.compile(r"\bTalents:\s*", re.IGNORECASE)

# Bestiary columns are ~270pt wide and start at x=51 or x=280.
_COLUMN_TOLERANCE = 120.0


@dataclass
class Creature:
    name: str
    slug: str
    category: str = ""
    page: int = 0
    characteristics: dict = field(default_factory=dict)
    traits: list = field(default_factory=list)
    optional_traits: list = field(default_factory=list)
    skills: list = field(default_factory=list)
    talents: list = field(default_factory=list)
    description: str = ""
    section_slug: str = ""


def _heading_position(doc: ModuleDocument, section: Section):
    """Where the creature's heading sits, so its profile can be found below it.

    Only an H3 counts: the bestiary's category headings and sidebar titles also
    appear in the outline, and an entry is exactly what an H3 introduces.
    """
    wanted = re.sub(r"\s+", "", section.title).lower()
    page_number = section.page_start or section.page
    for candidate in (page_number, page_number + 1):
        for line in doc.lines(candidate):
            if line.style != "H3":
                continue
            if re.sub(r"\s+", "", line.text).lower() == wanted:
                return candidate, line.bbox[1], line.bbox[0]
    return None


def _entry_text(doc: ModuleDocument, page_number: int, top: float, left: float) -> str:
    """The prose belonging to one creature, read straight from its column.

    Bestiary pages that carry a full-width illustration defeat block merging --
    the two columns end up interleaved in a single block -- so an entry is
    delimited geometrically instead: everything in the heading's column, from
    the heading down to the next heading in that same column.
    """
    column = [
        line
        for line in doc.lines(page_number)
        if abs(line.bbox[0] - left) <= _COLUMN_TOLERANCE and line.bbox[1] > top
    ]
    column.sort(key=lambda line: line.bbox[1])

    kept = []
    for line in column:
        if line.style.startswith("H") or line.style.startswith("SIDEBAR"):
            break
        kept.append(line.text)
    return " ".join(kept)


def _profile_for(doc: ModuleDocument, page_number: int, top: float, left: float) -> dict:
    """The characteristic table belonging to a heading at ``top``.

    Bestiary pages carry several creatures in two columns, so the profile is
    the nearest table below the heading that starts in the same column.
    """
    best = None
    for bbox, keys, rows in _profile_tables(doc, page_number):
        if not rows or bbox[1] < top:
            continue
        if abs(bbox[0] - left) > _COLUMN_TOLERANCE:
            continue
        distance = bbox[1] - top
        if best is None or distance < best[0]:
            best = (distance, keys, rows[0])
    if best is None:
        return {}
    _, keys, row = best
    values = {}
    for index, key in enumerate(keys):
        if index < len(row):
            values[key] = _to_int(row[index])
    return {key: values.get(key) for key in PROFILE_COLUMNS}


_RATED_TRAIT_RE = re.compile(r"^(?P<name>.+?)\s*\+\s*(?P<value>\d+)\s*(?P<qualifier>\(.*\))?$")


def _normalise_traits(entries: list) -> list:
    """Give rated traits a separate rating.

    The bestiary prints a trait's rating inside its name -- "Weapon+7",
    "Breath+15 (various)" -- which hides the trait from the glossary. Splitting
    the two lets a profile be matched against the Creature Traits section.
    """
    out = []
    for entry in entries:
        name = entry.get("name", "")
        value = entry.get("value")
        match = _RATED_TRAIT_RE.match(name)
        if match is not None:
            name = match.group("name").strip()
            value = int(match.group("value"))
            qualifier = match.group("qualifier")
            if qualifier:
                name = "%s %s" % (name, qualifier)
        out.append({"name": name, "value": value})
    return out


def _split_runin(text: str) -> dict:
    """Peel the Traits/Optional/Skills/Talents lists out of a creature's paragraph.

    The labels run into one another inside a single paragraph, so each list
    ends where the next label begins.
    """
    marks = []
    for label, pattern in (
        ("traits", _TRAITS_RE),
        ("optional", _OPTIONAL_RE),
        ("skills", _SKILLS_RE),
        ("talents", _TALENTS_RE),
    ):
        for match in pattern.finditer(text or ""):
            marks.append((match.start(), match.end(), label))
    marks.sort()

    found: dict = {}
    for index, (_, end, label) in enumerate(marks):
        stop = marks[index + 1][0] if index + 1 < len(marks) else len(text)
        found[label] = _normalise_traits(parse_trait_list(text[end:stop]))
    return found


def _category_of(section: Section) -> str:
    node = section.parent
    return node.title.strip() if node is not None else ""


def extract_creatures(
    doc: ModuleDocument, sections: list, blocks: list
) -> list:
    """Build a `Creature` for every bestiary entry in the outline."""
    out: list = []
    for section in sections:
        if section.kind != "creature":
            continue
        position = _heading_position(doc, section)
        if position is None:
            continue
        page_number, top, left = position
        text = _entry_text(doc, page_number, top, left)
        lists = _split_runin(text)
        description = text
        first = min(
            (match.start() for match in (_TRAITS_RE.search(text),) if match),
            default=len(text),
        )
        creature = Creature(
            name=section.title.strip(),
            slug=slugify(section.title),
            category=_category_of(section),
            page=page_number,
            section_slug=section.slug,
            characteristics=_profile_for(doc, page_number, top, left),
            description=description[:first].strip(),
            traits=lists.get("traits", []),
            optional_traits=lists.get("optional", []),
            skills=lists.get("skills", []),
            talents=lists.get("talents", []),
        )
        out.append(creature)
    return out


@dataclass
class CreatureTrait:
    name: str
    slug: str
    rated: bool
    description: str
    page: int = 0


_RATED_RE = re.compile(r"[+(]")


def extract_creature_traits(sections: list) -> list:
    """The generic traits the bestiary's profiles refer to."""
    out: list = []
    for section in sections:
        if section.kind != "creature_trait":
            continue
        title = section.title.strip()
        out.append(
            CreatureTrait(
                name=title,
                slug=slugify(title),
                rated=bool(_RATED_RE.search(title)),
                description=section.body_md,
                page=section.page_start or section.page,
            )
        )
    return out
