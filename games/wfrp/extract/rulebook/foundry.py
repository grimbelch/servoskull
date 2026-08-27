"""Ingest the WFRP core rulebook from a Foundry VTT compendium export.

Run as::

    python -m games.wfrp.extract.rulebook.foundry wfrp4e-core.foundry-export.json \\
        --slug wfrp-4e-core

The export is produced by ``games/wfrp/extract/foundry_export.cjs`` pointed at
the ``wfrp4e-core`` module — see ``games/wfrp/extract/README.md``. It carries
the same book the PDF extractor reads, but as structured documents: careers
with parsed skill lists, creatures with real characteristic numbers, and roll
tables with machine-readable ranges. Where the PDF path recovers structure
from glyph geometry, this path just reads it, so it is preferred whenever the
book exists in Foundry.

The output is identical in shape to the PDF path: the ``rule_*`` tables of
:mod:`games.wfrp.rules_schema`, rebuilt for the named slug on every run. The
rules engine cannot tell which extractor filled them.

What each table is sourced from:

===================  ========================================================
rule_sections        journal entries (chapters) and their pages
rule_skills          ``skill`` items, specialisations folded into one row
rule_talents         ``talent`` items
rule_spells          ``spell`` and ``prayer`` items
rule_careers/_tiers  ``career`` items grouped by career group, one row a tier
rule_creatures       actors, with categories from the Bestiary journal links
rule_conditions      the module's language file (``WFRP4E.Conditions.*``)
rule_tables/_rows    roll tables, kinds derived from wfrp4e system keys
===================  ========================================================
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from ... import rules_schema
from ..foundry_module import file_sha256, html_to_markdown, slugify, _strip_tags

EXTRACTOR_VERSION = "foundry-1.0"

_CHAR_NAMES = {
    "ws": "Weapon Skill", "bs": "Ballistic Skill", "s": "Strength",
    "t": "Toughness", "i": "Initiative", "ag": "Agility", "dex": "Dexterity",
    "int": "Intelligence", "wp": "Willpower", "fel": "Fellowship",
}

# wfrp4e species column codes as used by the career/hair/eye tables.
_SPECIES_NAMES = {
    "human": "Human", "dwarf": "Dwarf", "halfling": "Halfling",
    "helf": "High Elf", "welf": "Wood Elf", "gnome": "Gnome",
}

# Bestiary journal page -> rule_creatures.category, same values the PDF
# extractor derives from the chapter's section headings.
_BESTIARY_PAGES = (
    "Peoples of the Reikland", "Beasts of the Reikland",
    "Monstrous Beasts of the Reikland", "The Greenskin Hordes",
    "The Restless Dead", "Slaves to Darkness",
)

# The wfrp4e `key` flag names what a table is for; the engine selects critical,
# miscast, fumble and hit-location tables by `kind`. Tables titled "(Moo)" are
# the system author's homebrew alternates and must not shadow the printed ones,
# so they stay plain references.
_TABLE_KINDS = {
    "crithead": "critical", "critarm": "critical",
    "critbody": "critical", "critleg": "critical",
    "minormis": "miscast", "majormis": "miscast",
    "hitloc": "hit_location", "snake": "hit_location", "spider": "hit_location",
    "oops": "fumble",
}

# `page` breaks ties when the engine asks for a kind without a title — give the
# humanoid hit-location table precedence over the snake and spider variants.
_TABLE_PRIORITY_PAGE = {"hitloc": 1}
_VARIANT_PAGE = 999

_ROLL_INLINE_RE = re.compile(r"\[\[/r\s*([^\]]+?)\]\](?:\{[^}]*\})?")
_CONDITION_REF_RE = re.compile(r"@Condition\[([^\]]+)\](?:\{([^}]*)\})?")
_TABLE_REF_RE = re.compile(r"@Table\[([^\]]+)\](?:\{([^}]*)\})?")


def _clean(html: str) -> str:
    """Foundry rich text -> markdown, with roll/condition enrichers inlined."""
    text = html_to_markdown(html or "")
    text = _ROLL_INLINE_RE.sub(lambda m: m.group(1).strip(), text)
    text = _CONDITION_REF_RE.sub(lambda m: m.group(2) or m.group(1), text)
    text = _TABLE_REF_RE.sub(lambda m: m.group(2) or m.group(1), text)
    return text.strip()


def _value(field, default=""):
    """Unwrap the {'type','label','value'} envelopes wfrp4e wraps fields in."""
    if isinstance(field, dict):
        return field.get("value", default)
    if field is None:
        return default
    return field


def _split_name(name: str) -> tuple[str, str]:
    """'Trade (Apothecary)' -> ('Trade', 'Apothecary'); no group -> ('Dodge', '')."""
    match = re.match(r"^(.*?)\s*\((.*?)\)\s*$", name.strip())
    if not match:
        return name.strip(), ""
    return match.group(1).strip(), match.group(2).strip()


class FoundryRulebook:
    """One parsed export, ready to write."""

    def __init__(self, data: dict):
        self.data = data
        self.items = data.get("items", [])
        self.actors = data.get("actors", [])
        self.journals = data.get("journals", [])
        self.tables = data.get("tables", [])
        self.lang = data.get("lang", {})

    def items_of(self, *types: str) -> list:
        wanted = set(types)
        return [item for item in self.items if item.get("type") in wanted]

    def items_by_id(self) -> dict:
        return {item.get("_id"): item for item in self.items if item.get("_id")}

    # Actor id -> bestiary category, from the @UUID links on the Bestiary pages.
    def creature_categories(self) -> dict:
        categories: dict = {}
        uuid_re = re.compile(r"@UUID\[Compendium\.[^.]+\.actors\.([A-Za-z0-9]+)\]")
        for journal in self.journals:
            if journal.get("name") != "Bestiary":
                continue
            for page in journal.get("pages", []):
                if page.get("name") not in _BESTIARY_PAGES:
                    continue
                for actor_id in uuid_re.findall(page.get("html", "")):
                    categories.setdefault(actor_id, page["name"])
        return categories


class Writer:
    """Writes one parsed export into the ``rule_*`` tables."""

    def __init__(self, conn: sqlite3.Connection, rulebook_id: int):
        self.conn = conn
        self.rulebook_id = rulebook_id
        self.section_ids: dict = {}          # slug -> rule_sections.id
        self.search_rows: list = []

    def _index(self, title, body, kind, section_id, ref_table, ref_id) -> None:
        self.search_rows.append(
            (title or "", body or "", kind or "", self.rulebook_id,
             section_id, ref_table, ref_id, 0)
        )

    # ── prose ────────────────────────────────────────────────────────────────

    def write_sections(self, journals: list) -> None:
        doc_order = 0
        ordered = sorted(journals, key=lambda j: j.get("sort", 0))
        for chapter_ordinal, journal in enumerate(ordered):
            doc_order += 1
            chapter_slug = slugify(journal.get("name", ""))
            cursor = self.conn.execute(
                """
                INSERT INTO rule_sections
                    (rulebook_id, parent_id, chapter_id, level, ordinal,
                     doc_order, kind, slug, path, title, body_md,
                     page_start, page_end, word_count)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (self.rulebook_id, None, None, 1, chapter_ordinal, doc_order,
                 "chapter", chapter_slug, chapter_slug,
                 journal.get("name", ""), "", 0, 0, 0),
            )
            chapter_id = cursor.lastrowid
            self.section_ids[chapter_slug] = chapter_id

            pages = sorted(journal.get("pages", []), key=lambda p: p.get("sort", 0))
            for ordinal, page in enumerate(pages):
                doc_order += 1
                body = _clean(page.get("html", ""))
                slug = slugify(page.get("name", ""))
                cursor = self.conn.execute(
                    """
                    INSERT INTO rule_sections
                        (rulebook_id, parent_id, chapter_id, level, ordinal,
                         doc_order, kind, slug, path, title, body_md,
                         page_start, page_end, word_count)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (self.rulebook_id, chapter_id, chapter_id, 2, ordinal,
                     doc_order, "section", slug, f"{chapter_slug}/{slug}",
                     page.get("name", ""), body, 0, 0, len(body.split())),
                )
                section_id = cursor.lastrowid
                self.section_ids.setdefault(slug, section_id)
                if body:
                    self._index(page.get("name", ""), body, "section",
                                section_id, "rule_sections", section_id)

    # ── skills ───────────────────────────────────────────────────────────────

    def write_skills(self, skills: list) -> None:
        # Foundry ships one item per printed specialisation ("Trade (Cook)",
        # "Trade (Smith)"); the book — and rule_skills — has one grouped entry.
        grouped: dict = {}
        for item in skills:
            system = item.get("system", {})
            base, spec = _split_name(item.get("name", ""))
            entry = grouped.setdefault(base, {
                "name": base,
                "characteristic": _value(system.get("characteristic")),
                "advanced": _value(system.get("advanced")) == "adv",
                "grouped": False,
                "specs": set(),
                "description": "",
            })
            if _value(system.get("grouped")) == "isSpec":
                entry["grouped"] = True
            if spec and spec not in ("Any",):
                entry["specs"].add(spec)
            description = _clean(_value(system.get("description")))
            if description and len(description) > len(entry["description"]):
                entry["description"] = description

        for name in sorted(grouped):
            entry = grouped[name]
            cursor = self.conn.execute(
                """
                INSERT INTO rule_skills
                    (rulebook_id, section_id, slug, name, characteristic,
                     is_advanced, is_grouped, specialisations_json,
                     description, page)
                VALUES (?,?,?,?,?,?,?,?,?,0)
                """,
                (self.rulebook_id, self.section_ids.get("skills-and-talents"),
                 slugify(name), name, entry["characteristic"],
                 int(entry["advanced"]), int(entry["grouped"]),
                 json.dumps(sorted(entry["specs"])), entry["description"]),
            )
            self._index(name, entry["description"], "skill",
                        self.section_ids.get("skills-and-talents"),
                        "rule_skills", cursor.lastrowid)

    # ── talents ──────────────────────────────────────────────────────────────

    def write_talents(self, talents: list) -> None:
        for item in talents:
            system = item.get("system", {})
            raw_max = str(_value(system.get("max"))).strip().lower()
            if raw_max in _CHAR_NAMES:
                max_formula = f"{_CHAR_NAMES[raw_max]} Bonus"
            elif raw_max in ("none", ""):
                max_formula = "None"
            else:
                max_formula = raw_max
            description = _clean(_value(system.get("description")))
            cursor = self.conn.execute(
                """
                INSERT INTO rule_talents
                    (rulebook_id, section_id, slug, name, max_formula, tests,
                     description, page)
                VALUES (?,?,?,?,?,?,?,0)
                """,
                (self.rulebook_id, self.section_ids.get("skills-and-talents"),
                 slugify(item.get("name", "")), item.get("name", ""),
                 max_formula, _value(system.get("tests")), description),
            )
            self._index(item.get("name", ""), description, "talent",
                        self.section_ids.get("skills-and-talents"),
                        "rule_talents", cursor.lastrowid)

    # ── spells and prayers ───────────────────────────────────────────────────

    def write_spells(self, spells: list, prayers: list) -> None:
        rows = []
        for item in spells:
            system = item.get("system", {})
            lore = str(_value(system.get("lore"))).strip().lower()
            if lore == "petty":
                kind = "petty"
            elif lore:
                kind = "lore"
            else:
                lore, kind = "arcane", "arcane"
            cn = _value(system.get("cn"), None)
            rows.append((item, lore, kind,
                         int(cn) if isinstance(cn, (int, float)) else None))
        for item in prayers:
            system = item.get("system", {})
            kind = str(_value(system.get("type"))).strip().lower() or "miracle"
            if kind == "blessing":
                lore = "blessing"
            else:
                lore = str(_value(system.get("god"))).strip().lower()
            rows.append((item, lore, kind, None))

        for item, lore, kind, cn in rows:
            system = item.get("system", {})
            description = _clean(_value(system.get("description")))
            cursor = self.conn.execute(
                """
                INSERT INTO rule_spells
                    (rulebook_id, section_id, slug, name, lore, kind, cn,
                     range_text, target, duration, description, page)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,0)
                """,
                (self.rulebook_id,
                 self.section_ids.get("magic" if kind in ("petty", "arcane", "lore")
                                      else "religion-and-belief"),
                 slugify(item.get("name", "")), item.get("name", ""),
                 lore, kind, cn,
                 str(_value(system.get("range"))),
                 str(_value(system.get("target"))),
                 str(_value(system.get("duration"))), description),
            )
            self._index(item.get("name", ""), description, kind,
                        None, "rule_spells", cursor.lastrowid)

    # ── conditions ───────────────────────────────────────────────────────────

    def write_conditions_from_lang(self, lang: dict) -> None:
        section_id = self.section_ids.get("conditions")
        for key, text in sorted(lang.items()):
            match = re.match(r"^WFRP4E\.Conditions\.(\w+)$", key)
            if not match or not str(text).strip():
                continue
            name = match.group(1)
            description = _clean(str(text))
            cursor = self.conn.execute(
                """
                INSERT INTO rule_conditions
                    (rulebook_id, section_id, slug, name, is_stacking,
                     description, page)
                VALUES (?,?,?,?,?,?,0)
                """,
                # Prone, Surprised and Unconscious do not stack; everything
                # else accumulates. (WFRP 4E, Conditions, p.167.)
                (self.rulebook_id, section_id, slugify(name), name,
                 int(name.lower() not in ("prone", "surprised", "unconscious")),
                 description),
            )
            self._index(name, description, "condition", section_id,
                        "rule_conditions", cursor.lastrowid)

    # ── careers ──────────────────────────────────────────────────────────────

    def write_careers(self, careers: list, species_by_group: dict) -> None:
        groups: dict = defaultdict(list)
        for item in careers:
            groups[str(_value(item.get("system", {}).get("careergroup")))].append(item)

        for group_name in sorted(groups):
            tiers = sorted(groups[group_name],
                           key=lambda i: int(_value(i["system"].get("level"), 0)))
            first = tiers[0]["system"]
            description = _clean(_value(first.get("description")))
            cursor = self.conn.execute(
                """
                INSERT INTO rule_careers
                    (rulebook_id, section_id, slug, name, class, species_json,
                     description, page)
                VALUES (?,?,?,?,?,?,?,0)
                """,
                (self.rulebook_id, self.section_ids.get("class-and-careers"),
                 slugify(group_name), group_name,
                 str(_value(first.get("class"))),
                 json.dumps(species_by_group.get(group_name, [])), description),
            )
            career_id = cursor.lastrowid

            # Foundry lists are cumulative per tier; the book prints only what
            # each tier adds, so store the delta against the previous tier.
            seen_skills: set = set()
            seen_talents: set = set()
            seen_trappings: set = set()
            for item in tiers:
                system = item["system"]
                tier = int(_value(system.get("level"), 0))
                status = system.get("status", {}) or {}
                tier_names = {"b": "Brass", "s": "Silver", "g": "Gold"}
                skills = [s for s in system.get("skills", []) if s not in seen_skills]
                talents = [t for t in system.get("talents", []) if t not in seen_talents]
                trappings = [t for t in system.get("trappings", []) if t not in seen_trappings]
                seen_skills.update(skills)
                seen_talents.update(talents)
                seen_trappings.update(trappings)
                self.conn.execute(
                    """
                    INSERT INTO rule_career_tiers
                        (career_id, tier, name, status_tier, status_standing,
                         advances_json, skills_json, talents_json,
                         trappings_json, page)
                    VALUES (?,?,?,?,?,?,?,?,?,0)
                    """,
                    (career_id, tier, item.get("name", ""),
                     tier_names.get(status.get("tier", ""), ""),
                     int(status.get("standing", 0) or 0),
                     json.dumps(sorted(system.get("characteristics", []))),
                     json.dumps(skills), json.dumps(talents),
                     json.dumps(trappings)),
                )
            body = "%s %s" % (description,
                              " ".join(item.get("name", "") for item in tiers))
            self._index(group_name, body, "career",
                        self.section_ids.get("class-and-careers"),
                        "rule_careers", career_id)

    # ── bestiary ─────────────────────────────────────────────────────────────

    def write_creatures(self, actors: list, categories: dict) -> None:
        for actor in actors:
            if actor.get("type") not in ("creature", "npc"):
                continue
            system = actor.get("system", {})
            chars = system.get("characteristics", {})

            def stat(code: str):
                value = (chars.get(code) or {}).get("value")
                return int(value) if isinstance(value, (int, float)) else None

            details = system.get("details", {}) or {}
            status = system.get("status", {}) or {}
            wounds = ((status.get("wounds") or {}).get("max"))
            excluded = set(system.get("excludedTraits") or [])

            traits, optional_traits, skills, talents = [], [], [], []
            for item in actor.get("items", []):
                item_type = item.get("type")
                if item_type == "trait":
                    spec = str(_value(item.get("system", {}).get("specification")))
                    entry = {"name": item.get("name", "")}
                    if spec:
                        entry["value"] = spec
                    if item.get("_id") in excluded:
                        optional_traits.append(entry)
                    else:
                        traits.append(entry)
                elif item_type == "skill":
                    skills.append(item.get("name", ""))
                elif item_type == "talent":
                    talents.append(item.get("name", ""))

            description = _clean(_value(details.get("biography"), "") or "")
            cursor = self.conn.execute(
                """
                INSERT INTO rule_creatures
                    (rulebook_id, section_id, slug, name, category,
                     m, ws, bs, s, t, i, ag, dex, intl, wp, fel, w,
                     traits_json, optional_traits_json, skills_json,
                     talents_json, description, page)
                VALUES (?,?,?,?,?, ?,?,?,?,?,?,?,?,?,?,?,?, ?,?,?,?, ?,0)
                """,
                (self.rulebook_id, self.section_ids.get("bestiary"),
                 slugify(actor.get("name", "")), actor.get("name", ""),
                 categories.get(actor.get("_id"), ""),
                 _value(details.get("move"), None) or None,
                 stat("ws"), stat("bs"), stat("s"), stat("t"), stat("i"),
                 stat("ag"), stat("dex"), stat("int"), stat("wp"), stat("fel"),
                 int(wounds) if isinstance(wounds, (int, float)) else None,
                 json.dumps(traits), json.dumps(optional_traits),
                 json.dumps(skills), json.dumps(talents), description),
            )
            trait_names = ", ".join(entry["name"] for entry in traits)
            self._index(actor.get("name", ""),
                        "%s %s" % (description, trait_names), "creature",
                        self.section_ids.get("bestiary"),
                        "rule_creatures", cursor.lastrowid)

    # ── roll tables ──────────────────────────────────────────────────────────

    def write_tables(self, tables: list, items_by_id: Optional[dict] = None) -> None:
        items_by_id = items_by_id or {}
        for table in tables:
            flags = table.get("flags", {}) or {}
            key = flags.get("key", "")
            column = flags.get("column", "")
            name = table.get("name", "")
            if "(moo)" in name.lower():
                kind = "reference"
            else:
                kind = _TABLE_KINDS.get(key, "reference")
            page = _TABLE_PRIORITY_PAGE.get(key, 0)
            if kind == "hit_location" and key != "hitloc":
                page = _VARIANT_PAGE

            cursor = self.conn.execute(
                """
                INSERT INTO rule_tables
                    (rulebook_id, section_id, slug, title, kind, dice,
                     columns_json, notes, page)
                VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (self.rulebook_id, None, slugify(name), name, kind,
                 table.get("formula", ""),
                 json.dumps([c for c in ("Roll", column or "Result") if c]),
                 _clean(table.get("description", "")), page),
            )
            table_id = cursor.lastrowid

            results = sorted(table.get("results", []),
                             key=lambda r: (r.get("range") or [0])[0])
            body_parts = []
            for ordinal, result in enumerate(results):
                lo, hi = (result.get("range") or [None, None])[:2]
                text = result.get("text", "") or ""
                detail = _clean(result.get("description", ""))
                # Document results carry only a name; the rules text lives on
                # the referenced compendium item (criticals, injuries, ...).
                # The reference is either a documentUuid or an inline @UUID.
                uuid = result.get("documentUuid", "")
                if not uuid:
                    match = re.search(r"@UUID\[([^\]]+)\]", result.get("description", ""))
                    uuid = match.group(1) if match else ""
                if uuid and (not detail or detail == text):
                    item = items_by_id.get(uuid.rsplit(".", 1)[-1])
                    if item is not None:
                        system = item.get("system", {}) or {}
                        parts = []
                        wounds = str(_value(system.get("wounds"))).strip()
                        if wounds:
                            parts.append("Wounds: %s." % wounds)
                        modifier = str(_value(system.get("modifier"))).strip()
                        if modifier:
                            parts.append("%s." % modifier.rstrip("."))
                        parts.append(_clean(_value(system.get("description"))))
                        detail = " ".join(p for p in parts if p)
                        text = text or item.get("name", "")
                if not text:
                    text, detail = detail, ""
                if text == detail:
                    detail = ""
                label = ("%02d" % lo if lo == hi else "%02d-%02d" % (lo, hi)) \
                    if isinstance(lo, int) and isinstance(hi, int) else ""
                self.conn.execute(
                    """
                    INSERT INTO rule_table_rows
                        (table_id, ordinal, roll_min, roll_max, roll_label,
                         result, detail, cells_json)
                    VALUES (?,?,?,?,?,?,?,?)
                    """,
                    (table_id, ordinal, lo, hi, label, text, detail,
                     json.dumps([label, text, detail])),
                )
                body_parts.append(" ".join(p for p in (label, text, detail) if p))
            self._index(name, " ".join(body_parts), "table", None,
                        "rule_tables", table_id)

    # ── search ───────────────────────────────────────────────────────────────

    def build_search_index(self) -> int:
        if not rules_schema.has_fts5(self.conn):
            return 0
        self.conn.executemany(
            """
            INSERT INTO rule_search
                (title, body, kind, rulebook_id, section_id, ref_table,
                 ref_id, page)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            self.search_rows,
        )
        return len(self.search_rows)


def _species_by_career_group(book: FoundryRulebook) -> dict:
    """Which species may enter each career, from the species career tables."""
    result: dict = defaultdict(list)
    for table in book.tables:
        flags = table.get("flags", {}) or {}
        if flags.get("key") != "career":
            continue
        species = _SPECIES_NAMES.get(flags.get("column", ""))
        if not species:
            continue
        for row in table.get("results", []):
            name = row.get("text") or _strip_tags(row.get("description", "")).strip()
            if name and species not in result[name]:
                result[name].append(species)
    return dict(result)


def ingest(export_path: str, db_path: str, slug: str, title: str) -> dict:
    with open(export_path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    book = FoundryRulebook(data)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    rules_schema.init_rules_schema(conn)
    rules_schema.reset_rulebook(conn, slug)

    module = data.get("module", {})
    cursor = conn.execute(
        """
        INSERT INTO rulebooks
            (slug, title, system, source_file, source_sha256, page_count,
             extracted_at, extractor_version)
        VALUES (?,?,?,?,?,?,?,?)
        """,
        (slug, title or module.get("title", slug), "WFRP 4E",
         os.path.basename(export_path), file_sha256(export_path), 0,
         datetime.now(timezone.utc).isoformat(timespec="seconds"),
         "%s (%s %s)" % (EXTRACTOR_VERSION, module.get("id", "?"),
                         module.get("version", "?"))),
    )
    rulebook_id = cursor.lastrowid

    writer = Writer(conn, rulebook_id)
    writer.write_sections(book.journals)
    writer.write_skills(book.items_of("skill"))
    writer.write_talents(book.items_of("talent"))
    writer.write_spells(book.items_of("spell"), book.items_of("prayer"))
    writer.write_conditions_from_lang(book.lang)
    writer.write_careers(book.items_of("career"), _species_by_career_group(book))
    writer.write_creatures(book.actors, book.creature_categories())
    writer.write_tables(book.tables, book.items_by_id())
    indexed = writer.build_search_index()
    conn.commit()

    counts = {
        table: conn.execute(
            "SELECT COUNT(*) FROM %s WHERE rulebook_id = ?" % table,
            (rulebook_id,),
        ).fetchone()[0]
        for table in ("rule_sections", "rule_skills", "rule_talents",
                      "rule_spells", "rule_careers", "rule_creatures",
                      "rule_conditions", "rule_tables")
    }
    counts["rule_career_tiers"] = conn.execute(
        "SELECT COUNT(*) FROM rule_career_tiers t"
        " JOIN rule_careers c ON c.id = t.career_id WHERE c.rulebook_id = ?",
        (rulebook_id,),
    ).fetchone()[0]
    counts["rule_table_rows"] = conn.execute(
        "SELECT COUNT(*) FROM rule_table_rows r"
        " JOIN rule_tables t ON t.id = r.table_id WHERE t.rulebook_id = ?",
        (rulebook_id,),
    ).fetchone()[0]
    counts["rule_search"] = indexed
    conn.close()
    return counts


def main(argv: Optional[list] = None) -> int:
    from ... import db as wfrp_db

    parser = argparse.ArgumentParser(
        description="Ingest a WFRP rulebook from a Foundry compendium export")
    parser.add_argument("export", help="JSON produced by foundry_export.cjs")
    parser.add_argument("--slug", default="wfrp-4e-core")
    parser.add_argument("--title", default="Warhammer Fantasy Roleplay 4E Core Rulebook")
    parser.add_argument("--db", default=str(wfrp_db.get_db_path()))
    args = parser.parse_args(argv)

    counts = ingest(args.export, args.db, args.slug, args.title)
    width = max(len(k) for k in counts)
    for key in sorted(counts):
        print("%-*s %6d" % (width, key, counts[key]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
