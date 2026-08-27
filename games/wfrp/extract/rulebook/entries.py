"""Parse the rulebook's entry lists: skills, talents, spells, prayers, conditions.

Skills, talents and spells are typeset identically -- a bold name, then a run of
bold run-in labels, then the description -- so one parser serves all three and
only the label set differs.

The labels cannot be recovered from the merged paragraph text. "CN: 0" is set
with a bold label and a regular value, so the line resolves to body style and is
joined into the surrounding prose: the result reads "CN: 0 Range: Touch Target: 1
Duration: Instant You sense the influx..." with no way to tell where the last
value ends. The original visual lines survive on ``Block.lines`` though, and in
the PDF each label is a line of its own, so the split is read from there.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional, Sequence

from ..layout import Block, join_wrapped
from ..sections import Section, slugify

# Characteristic abbreviations as printed in skill headings.
CHARACTERISTICS = {
    "ws": "ws", "bs": "bs", "s": "s", "t": "t", "i": "i", "ag": "ag",
    "dex": "dex", "int": "int", "wp": "wp", "fel": "fel",
}

_SKILL_HEAD_RE = re.compile(
    r"^(?P<name>.+?)\s*\((?P<char>WS|BS|S|T|I|Ag|Dex|Int|WP|Fel)\)\s*"
    r"(?P<flags>.*)$",
    re.IGNORECASE,
)

_SPELL_LABELS = ("CN", "Range", "Target", "Duration")
# The book prints "Test:" on most talents and "Tests:" on a few; one uses
# "Maximum:" where the rest use "Max:".
_TALENT_LABELS = ("Maximum", "Max", "Tests", "Test")


def _label_pattern(labels: Sequence[str]) -> "re.Pattern":
    joined = "|".join(re.escape(label) for label in labels)
    return re.compile(rf"^\s*(?P<label>{joined})\s*:\s*(?P<value>.*)$", re.IGNORECASE)


def section_lines(blocks: list[Block], section: Section) -> list[str]:
    """The section's own prose as printed visual lines, in reading order."""
    out: list[str] = []
    for block in blocks[section.block_start:section.block_end]:
        out.extend(line.text for line in block.lines)
    return out


def split_labels(
    lines: Sequence[str], labels: Sequence[str], compounds: Optional[set] = None
) -> tuple[dict, str]:
    """Peel leading ``Label: value`` lines off an entry, returning the rest.

    A value that wraps onto the next line is folded back into the label it
    belongs to: continuation lines are recognised because the labels are
    printed in a fixed order, so any line before the next expected label -- and
    before the description proper -- is still part of the current value.
    """
    pattern = _label_pattern(labels)
    found: dict[str, str] = {}
    current: Optional[str] = None
    index = 0

    for index, line in enumerate(lines):
        match = pattern.match(line)
        if match:
            current = match.group("label").lower()
            found[current] = match.group("value").strip()
            continue
        if current is not None and _is_continuation(line, found[current]):
            found[current] = f"{found[current]} {line.strip()}".strip()
            continue
        break
    else:
        index = len(lines)

    description = join_wrapped(list(lines[index:]), compounds)
    return found, description


def _is_continuation(line: str, value_so_far: str) -> bool:
    """Whether a line continues the previous label's value rather than starting prose.

    A wrapped value is short and unpunctuated where a description is a
    sentence, so the test is that the value so far reads as incomplete: it ends
    on a word that cannot end a phrase, or the line itself is a bracketed
    fragment.
    """
    text = line.strip()
    if not text or len(text) > 44:
        return False
    if text.startswith((")", "(")) or text.endswith(("(", ",")):
        return True
    return bool(re.search(r"\b(?:or|and|of|per|plus|to|the|a|AoE)$", value_so_far))


# ── skills ───────────────────────────────────────────────────────────────────


@dataclass
class SkillEntry:
    slug: str
    name: str
    characteristic: str = ""
    is_advanced: bool = False
    is_grouped: bool = False
    specialisations: list = field(default_factory=list)
    description: str = ""
    page: int = 0
    section: Optional[Section] = None


def parse_skill_heading(heading: str) -> Optional[tuple]:
    """Split "Art (Dex) basic, grouped" into its parts."""
    match = _SKILL_HEAD_RE.match(heading.strip())
    if not match:
        return None
    flags = match.group("flags").lower()
    return (
        match.group("name").strip(),
        CHARACTERISTICS[match.group("char").lower()],
        "advanced" in flags,
        "grouped" in flags,
    )


def extract_skills(blocks: list[Block], sections: list[Section], compounds=None) -> list[SkillEntry]:
    entries: list[SkillEntry] = []
    for section in sections:
        if section.kind != "skill" or section.anchor is None:
            continue
        parsed = parse_skill_heading(blocks[section.anchor].text)
        if not parsed:
            continue
        name, characteristic, advanced, grouped = parsed
        entries.append(
            SkillEntry(
                slug=slugify(name),
                name=name,
                characteristic=characteristic,
                is_advanced=advanced,
                is_grouped=grouped,
                specialisations=_specialisations(section, blocks, compounds),
                description=join_wrapped(section_lines(blocks, section), compounds),
                page=section.page_start or section.page,
                section=section,
            )
        )
    return entries


_SPEC_RE = re.compile(
    r"(?:examples?|specialisations?|include|such as)\s*:?\s*(?P<list>[^.]{4,300})\.",
    re.IGNORECASE,
)


def _specialisations(section: Section, blocks: list[Block], compounds) -> list:
    """Named specialisations for a grouped skill, when the text lists them."""
    text = join_wrapped(section_lines(blocks, section), compounds)
    match = _SPEC_RE.search(text)
    if not match:
        return []
    raw = re.split(r",| and ", match.group("list"))
    out = []
    for item in raw:
        item = item.strip(" .;:")
        # Specialisations are proper nouns; a lower-case fragment is prose that
        # happened to follow the cue word.
        if 2 <= len(item) <= 40 and item[:1].isupper():
            out.append(item)
    return out


# ── talents ──────────────────────────────────────────────────────────────────


@dataclass
class TalentEntry:
    slug: str
    name: str
    max_formula: str = ""
    tests: str = ""
    description: str = ""
    page: int = 0
    section: Optional[Section] = None


def extract_talents(blocks: list[Block], sections: list[Section], compounds=None) -> list[TalentEntry]:
    entries: list[TalentEntry] = []
    for section in sections:
        if section.kind != "talent" or section.anchor is None:
            continue
        labels, description = split_labels(
            section_lines(blocks, section), _TALENT_LABELS, compounds
        )
        name = blocks[section.anchor].text.strip()
        entries.append(
            TalentEntry(
                slug=slugify(name),
                name=name,
                max_formula=labels.get("max", "") or labels.get("maximum", ""),
                tests=labels.get("tests", "") or labels.get("test", ""),
                description=description,
                page=section.page_start or section.page,
                section=section,
            )
        )
    return entries


# ── spells, blessings and miracles ───────────────────────────────────────────


@dataclass
class SpellEntry:
    slug: str
    name: str
    lore: str = ""
    kind: str = "arcane"
    cn: Optional[int] = None
    range_text: str = ""
    target: str = ""
    duration: str = ""
    description: str = ""
    page: int = 0
    section: Optional[Section] = None


_LORE_RE = re.compile(r"^(?:the\s+)?lore\s+of\s+(?P<lore>.+)$", re.IGNORECASE)


def _lore_of(section: Section) -> tuple[str, str]:
    """The lore name and spell kind for an entry, from its parent list."""
    parent = section.parent.title.strip() if section.parent else ""
    match = _LORE_RE.match(parent)
    if match:
        return match.group("lore").strip().lower(), "lore"
    key = parent.lower()
    if key.startswith("petty"):
        return "petty", "petty"
    if key.startswith("arcane"):
        return "arcane", "arcane"
    return key, "arcane"


def extract_spells(blocks: list[Block], sections: list[Section], compounds=None) -> list[SpellEntry]:
    entries: list[SpellEntry] = []
    for section in sections:
        if section.kind not in {"spell", "blessing", "miracle"} or section.anchor is None:
            continue
        labels, description = split_labels(
            section_lines(blocks, section), _SPELL_LABELS, compounds
        )
        name = blocks[section.anchor].text.strip()

        # A few list entries are explanatory notes set like spells -- "Seers"
        # in the Lore of Heavens explains which spells a career may take. They
        # carry none of the casting labels, so they stay prose-only.
        if not labels:
            continue

        if section.kind == "spell":
            lore, kind = _lore_of(section)
        elif section.kind == "blessing":
            lore, kind = "blessing", "blessing"
        else:
            # Miracles are grouped by cult: "Miracles of Manann".
            cult = (section.parent.title if section.parent else "").strip()
            lore = re.sub(r"^miracles\s+of\s+", "", cult, flags=re.IGNORECASE).lower()
            kind = "miracle"

        cn = labels.get("cn", "")
        entries.append(
            SpellEntry(
                slug=slugify(name),
                name=name,
                lore=lore,
                kind=kind,
                cn=int(cn) if cn.isdigit() else None,
                range_text=labels.get("range", ""),
                target=labels.get("target", ""),
                duration=labels.get("duration", ""),
                description=description,
                page=section.page_start or section.page,
                section=section,
            )
        )
    return entries


# ── conditions ───────────────────────────────────────────────────────────────


@dataclass
class ConditionEntry:
    slug: str
    name: str
    is_stacking: bool = True
    description: str = ""
    page: int = 0
    section: Optional[Section] = None


# Conditions that a character either has or does not; the rest accumulate.
_NON_STACKING = {"blinded", "deafened", "entangled", "prone", "unconscious", "surprised"}


def extract_conditions(
    blocks: list[Block], sections: list[Section], compounds=None
) -> list[ConditionEntry]:
    entries: list[ConditionEntry] = []
    for section in sections:
        if section.kind != "condition" or section.anchor is None:
            continue
        name = blocks[section.anchor].text.strip()
        entries.append(
            ConditionEntry(
                slug=slugify(name),
                name=name,
                is_stacking=slugify(name) not in _NON_STACKING,
                description=join_wrapped(section_lines(blocks, section), compounds),
                page=section.page_start or section.page,
                section=section,
            )
        )
    return entries
