"""Classify the core rulebook's outline into the kinds the rest of the pipeline needs.

The book's bookmark outline is complete and well-nested, so what a section *is*
can be read from where it sits rather than guessed from its prose. Three shapes
recur and account for nearly all the mechanical content:

* a "Master X List" container whose children are the individual entries
  (skills, talents, conditions);
* a chapter of same-shaped level-2 sections (the 64 careers);
* a list container whose grandchildren are entries (spells under Spell Lists,
  miracles under Miracles).

Anything not recognised stays ``section`` and lives in the reference layer only,
which is the safe default: it is still searchable prose, it simply gets no
structured row.
"""
from __future__ import annotations

import re
from typing import Optional

from ..sections import Section

# Level-1 entries that are navigation or front matter rather than rules.
_NON_CHAPTERS = {"contents", "index", "character sheet", "credits"}

# Level-2 sections of "Class and Careers" that introduce the chapter rather
# than describe a career.
_CAREER_CHAPTER_PROSE = {"clases", "classes", "careers", "status"}

# Sidebars are titled like entries but are commentary. "Options:" is the book's
# own marker for optional rules; the rest are boxed asides sitting in an
# entry list.
_SIDEBAR_PREFIXES = ("options:", "option:")
_SIDEBAR_TITLES = {
    "how much rest?", "complete condition list", "critical tables",
}

# The level-2 sections of the Magic chapter that hold spell lists. The lores are
# deliberately split across five containers in the book, so keying off "Spell
# Lists" alone finds only the petty and arcane spells.
_SPELL_CONTAINERS = {
    "spell lists", "colour magic", "witch magic", "dark magic", "chaos magic",
}

_SPELL_LIST_RE = re.compile(r"^(?:the\s+)?lore\s+of\s+\w|^petty\s+spells$|^arcane\s+spells$")


def _is_spell_list(title_key: str) -> bool:
    return bool(_SPELL_LIST_RE.match(title_key))


def _ancestors(section: Section):
    node = section.parent
    while node is not None:
        yield node
        node = node.parent


def _key(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _ancestor_titled(section: Section, title: str) -> Optional[Section]:
    node = section.parent
    wanted = _key(title)
    while node is not None:
        if _key(node.title) == wanted:
            return node
        node = node.parent
    return None


def _chapter_of(section: Section) -> str:
    node = section
    while node.parent is not None:
        node = node.parent
    return _key(node.title)


def is_sidebar(section: Section) -> bool:
    key = _key(section.title)
    return key.startswith(_SIDEBAR_PREFIXES) or key in _SIDEBAR_TITLES


def classify_rule_sections(roots: list[Section]) -> None:
    """Assign a ``kind`` to every node of the rulebook outline."""
    for root in roots:
        for section in root.walk():
            section.kind = _kind_of(section)


def _kind_of(section: Section) -> str:
    key = _key(section.title)
    chapter = _chapter_of(section)
    parent_key = _key(section.parent.title) if section.parent else ""

    if section.level == 1:
        return "front_matter" if key in _NON_CHAPTERS else "chapter"

    if is_sidebar(section):
        return "sidebar"

    # Careers: every level-2 section of the careers chapter bar its preamble.
    if chapter == "class and careers":
        if section.level == 2 and key not in _CAREER_CHAPTER_PROSE:
            return "career"
        return "section"

    # Skills, talents and conditions each hang off a "Master ... List".
    if parent_key == "master skill list":
        return "skill"
    if parent_key == "master talent list":
        return "talent"
    if parent_key == "master condition list":
        return "condition"

    # Spells: each lore is a level-3 list whose children are the spells. The
    # lists are spread across five level-2 containers rather than gathered
    # under "Spell Lists" alone.
    if chapter == "magic":
        container = next(
            (
                node
                for node in _ancestors(section)
                if node.level == 2 and _key(node.title) in _SPELL_CONTAINERS
            ),
            None,
        )
        if container is not None:
            if section.level == 3:
                return "spell_list" if _is_spell_list(key) else "section"
            if section.level == 4 and _is_spell_list(parent_key):
                return "spell"
        return "section"

    # Blessings are level-3 siblings; miracles are grouped by cult one level
    # deeper. Both are cast like spells and share the spell parser.
    if _ancestor_titled(section, "Blessings") is not None and key.startswith("blessing of"):
        return "blessing"
    if _ancestor_titled(section, "Miracles") is not None and section.level == 4:
        return "miracle"

    # Bestiary: creature entries are the leaf sections beneath each category,
    # and traits are listed under their own level-2 section. The Chaos and
    # Skaven categories sit a level deeper in the outline than the others, so
    # depth alone cannot tell an entry from the group that contains it.
    if chapter == "bestiary":
        if _ancestor_titled(section, "Creature Traits") is not None:
            return "creature_trait"
        if section.level >= 3 and not section.children:
            if parent_key in {"creature hit locations"}:
                return "section"
            return "creature"
        return "section"

    return "section"
