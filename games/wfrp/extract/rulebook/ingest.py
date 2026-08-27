"""Command-line ingestion of a WFRP core rulebook into the campaign database.

Run as::

    python -m games.wfrp.extract.rulebook.ingest "path/to/rulebook.pdf" \\
        --slug wfrp-4e-core

The rulebook is stored in two layers. Every outline section is written verbatim
so any rule can be quoted, and on top of that the mechanical content -- skills,
talents, spells, careers, creatures, conditions and roll tables -- is written as
structured rows the rules engine can resolve without reading prose.

Everything under ``rule_*`` for the named book is rebuilt on each run. No
campaign state references it, so a re-extraction is always safe.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Optional

from ... import rules_schema
from ..ingest import file_sha256
from ..layout import RULEBOOK_STYLESHEET, ModuleDocument
from ..sections import Section, extract_sections
from .careers import extract_careers
from .creatures import extract_creatures
from .entries import (
    extract_conditions,
    extract_skills,
    extract_spells,
    extract_talents,
)
from .outline import classify_rule_sections
from .roll_tables import extract_roll_tables

EXTRACTOR_VERSION = "1.0"

# Section kinds that also get a structured row. Their prose is indexed once,
# from the entry, so a search for "Dodge" returns the Skill and not the same
# text twice.
_STRUCTURED_KINDS = frozenset({
    "skill", "talent", "spell", "blessing", "miracle",
    "career", "creature", "condition",
})


def _walk(roots: list) -> list:
    """Every section in document order."""
    return sorted(
        (node for root in roots for node in root.walk()),
        key=lambda node: node.doc_order,
    )


def _path_of(section: Section) -> str:
    """Slash-joined slugs from the chapter down, so a section can be addressed."""
    parts = []
    node = section
    while node is not None:
        if node.slug:
            parts.append(node.slug)
        node = node.parent
    return "/".join(reversed(parts))


class RulesIngestor:
    """Writes one extracted rulebook into the database."""

    def __init__(self, conn: sqlite3.Connection, rulebook_id: int):
        self.conn = conn
        self.rulebook_id = rulebook_id
        self.section_ids: dict = {}     # doc_order -> rule_sections.id
        self.section_by_slug: dict = {}
        self.search_rows: list = []

    # ── prose layer ──────────────────────────────────────────────────────────

    def write_sections(self, roots: list) -> None:
        for section in _walk(roots):
            parent_id = (
                self.section_ids.get(section.parent.doc_order)
                if section.parent is not None
                else None
            )
            chapter = (
                section if section.kind == "chapter"
                else section.ancestor_of_kind("chapter")
            )
            chapter_id = self.section_ids.get(chapter.doc_order) if chapter else None

            cursor = self.conn.execute(
                """
                INSERT INTO rule_sections
                    (rulebook_id, parent_id, chapter_id, level, ordinal, doc_order,
                     kind, slug, path, title, body_md, page_start, page_end,
                     word_count)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    self.rulebook_id, parent_id, chapter_id, section.level,
                    section.ordinal, section.doc_order, section.kind, section.slug,
                    _path_of(section), section.title, section.body_md,
                    section.page_start, section.page_end, section.word_count,
                ),
            )
            section_id = cursor.lastrowid
            self.section_ids[section.doc_order] = section_id
            self.section_by_slug.setdefault(section.slug, section_id)

            if (section.body_md or "").strip() and section.kind not in _STRUCTURED_KINDS:
                self._index(section.title, section.body_md, section.kind,
                            section_id, "rule_sections", section_id,
                            section.page_start)

    def _section_id_for(self, section: Optional[Section]) -> Optional[int]:
        if section is None:
            return None
        return self.section_ids.get(section.doc_order)

    # ── entry layer ──────────────────────────────────────────────────────────

    def write_skills(self, skills: list) -> None:
        for skill in skills:
            section_id = self._section_id_for(skill.section)
            cursor = self.conn.execute(
                """
                INSERT INTO rule_skills
                    (rulebook_id, section_id, slug, name, characteristic,
                     is_advanced, is_grouped, specialisations_json, description, page)
                VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    self.rulebook_id, section_id, skill.slug, skill.name,
                    skill.characteristic, int(skill.is_advanced),
                    int(skill.is_grouped), json.dumps(skill.specialisations),
                    skill.description, skill.page,
                ),
            )
            self._index(skill.name, skill.description, "skill", section_id,
                        "rule_skills", cursor.lastrowid, skill.page)

    def write_talents(self, talents: list) -> None:
        for talent in talents:
            section_id = self._section_id_for(talent.section)
            cursor = self.conn.execute(
                """
                INSERT INTO rule_talents
                    (rulebook_id, section_id, slug, name, max_formula, tests,
                     description, page)
                VALUES (?,?,?,?,?,?,?,?)
                """,
                (
                    self.rulebook_id, section_id, talent.slug, talent.name,
                    talent.max_formula, talent.tests, talent.description, talent.page,
                ),
            )
            self._index(talent.name, talent.description, "talent", section_id,
                        "rule_talents", cursor.lastrowid, talent.page)

    def write_spells(self, spells: list) -> None:
        for spell in spells:
            section_id = self._section_id_for(spell.section)
            cursor = self.conn.execute(
                """
                INSERT INTO rule_spells
                    (rulebook_id, section_id, slug, name, lore, kind, cn,
                     range_text, target, duration, description, page)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    self.rulebook_id, section_id, spell.slug, spell.name, spell.lore,
                    spell.kind, spell.cn, spell.range_text, spell.target,
                    spell.duration, spell.description, spell.page,
                ),
            )
            self._index(spell.name, spell.description, spell.kind, section_id,
                        "rule_spells", cursor.lastrowid, spell.page)

    def write_conditions(self, conditions: list) -> None:
        for condition in conditions:
            section_id = self._section_id_for(condition.section)
            cursor = self.conn.execute(
                """
                INSERT INTO rule_conditions
                    (rulebook_id, section_id, slug, name, is_stacking,
                     description, page)
                VALUES (?,?,?,?,?,?,?)
                """,
                (
                    self.rulebook_id, section_id, condition.slug, condition.name,
                    int(condition.is_stacking), condition.description, condition.page,
                ),
            )
            self._index(condition.name, condition.description, "condition",
                        section_id, "rule_conditions", cursor.lastrowid,
                        condition.page)

    # ── careers ──────────────────────────────────────────────────────────────

    def write_careers(self, careers: list) -> None:
        for career in careers:
            section_id = self.section_by_slug.get(career.slug)
            cursor = self.conn.execute(
                """
                INSERT INTO rule_careers
                    (rulebook_id, section_id, slug, name, class, species_json,
                     description, page)
                VALUES (?,?,?,?,?,?,?,?)
                """,
                (
                    self.rulebook_id, section_id, career.slug, career.name,
                    career.career_class, json.dumps(career.species),
                    career.summary, career.page,
                ),
            )
            career_id = cursor.lastrowid
            for tier in career.tiers:
                # The advance scheme is printed once for the whole career and a
                # characteristic stays advanceable once unlocked, so each tier
                # stores the cumulative set it may actually advance.
                advances = sorted(
                    name for name, level in career.advances.items()
                    if level <= tier.level
                )
                self.conn.execute(
                    """
                    INSERT INTO rule_career_tiers
                        (career_id, tier, name, status_tier, status_standing,
                         advances_json, skills_json, talents_json, trappings_json,
                         page)
                    VALUES (?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        career_id, tier.level, tier.name, tier.status_tier,
                        tier.status_standing, json.dumps(advances),
                        json.dumps(tier.skills), json.dumps(tier.talents),
                        json.dumps(tier.trappings), career.page,
                    ),
                )
            body = "%s %s" % (
                career.summary,
                " ".join(tier.name for tier in career.tiers),
            )
            self._index(career.name, body, "career", section_id,
                        "rule_careers", career_id, career.page)

    # ── bestiary ─────────────────────────────────────────────────────────────

    def write_creatures(self, creatures: list) -> None:
        for creature in creatures:
            section_id = self.section_by_slug.get(creature.section_slug)
            stats = creature.characteristics
            cursor = self.conn.execute(
                """
                INSERT INTO rule_creatures
                    (rulebook_id, section_id, slug, name, category,
                     m, ws, bs, s, t, i, ag, dex, intl, wp, fel, w,
                     traits_json, optional_traits_json, skills_json, talents_json,
                     description, page)
                VALUES (?,?,?,?,?, ?,?,?,?,?,?,?,?,?,?,?,?, ?,?,?,?, ?,?)
                """,
                (
                    self.rulebook_id, section_id, creature.slug, creature.name,
                    creature.category,
                    stats.get("m"), stats.get("ws"), stats.get("bs"), stats.get("s"),
                    stats.get("t"), stats.get("i"), stats.get("ag"), stats.get("dex"),
                    stats.get("intl"), stats.get("wp"), stats.get("fel"), stats.get("w"),
                    json.dumps(creature.traits),
                    json.dumps(creature.optional_traits),
                    json.dumps(creature.skills), json.dumps(creature.talents),
                    creature.description, creature.page,
                ),
            )
            traits = ", ".join(entry.get("name", "") for entry in creature.traits)
            self._index(creature.name, "%s %s" % (creature.description, traits),
                        "creature", section_id, "rule_creatures",
                        cursor.lastrowid, creature.page)

    # ── tables ───────────────────────────────────────────────────────────────

    def write_tables(self, tables: list) -> None:
        for table in tables:
            section_id = self.section_by_slug.get(table.section_slug)
            cursor = self.conn.execute(
                """
                INSERT INTO rule_tables
                    (rulebook_id, section_id, slug, title, kind, dice,
                     columns_json, notes, page)
                VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (
                    self.rulebook_id, section_id, table.slug, table.title,
                    table.kind, table.dice, json.dumps(table.columns), "", table.page,
                ),
            )
            table_id = cursor.lastrowid
            for row in table.rows:
                self.conn.execute(
                    """
                    INSERT INTO rule_table_rows
                        (table_id, ordinal, roll_min, roll_max, roll_label,
                         result, detail, cells_json)
                    VALUES (?,?,?,?,?,?,?,?)
                    """,
                    (
                        table_id, row.ordinal, row.roll_min, row.roll_max,
                        row.roll_label, row.result, row.detail, json.dumps(row.cells),
                    ),
                )
            # Indexing the results themselves is how a GM finds "Torn Muscle"
            # without already knowing which table it came from.
            body = " ".join(
                " ".join(
                    part for part in (row.roll_label, row.result, row.detail) if part
                )
                for row in table.rows
            )
            self._index(table.title, body, "table", section_id,
                        "rule_tables", table_id, table.page)

    # ── search ───────────────────────────────────────────────────────────────

    def _index(self, title, body, kind, section_id, ref_table, ref_id, page) -> None:
        self.search_rows.append(
            (title or "", body or "", kind or "", self.rulebook_id,
             section_id, ref_table, ref_id, page or 0)
        )

    def build_search_index(self) -> int:
        if not rules_schema.has_fts5(self.conn):
            return 0
        self.conn.executemany(
            """
            INSERT INTO rule_search
                (title, body, kind, rulebook_id, section_id, ref_table, ref_id, page)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            self.search_rows,
        )
        return len(self.search_rows)


def ingest(pdf_path: str, db_path: str, slug: str, title: str) -> dict:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    rules_schema.init_rules_schema(conn)

    with ModuleDocument(pdf_path, RULEBOOK_STYLESHEET) as doc:
        roots, blocks = extract_sections(doc)
        classify_rule_sections(roots)
        flat = _walk(roots)
        compounds = doc.compounds()

        skills = extract_skills(blocks, flat, compounds)
        talents = extract_talents(blocks, flat, compounds)
        spells = extract_spells(blocks, flat, compounds)
        conditions = extract_conditions(blocks, flat, compounds)
        careers = extract_careers(doc, flat, blocks)
        creatures = extract_creatures(doc, flat, blocks)
        tables = extract_roll_tables(doc, blocks, roots)
        page_count = doc.page_count

    rules_schema.reset_rulebook(conn, slug)
    cursor = conn.execute(
        """
        INSERT INTO rulebooks
            (slug, title, system, source_file, source_sha256, page_count,
             extracted_at, extractor_version)
        VALUES (?,?,?,?,?,?,?,?)
        """,
        (
            slug, title, "WFRP 4E", os.path.basename(pdf_path),
            file_sha256(pdf_path), page_count,
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            EXTRACTOR_VERSION,
        ),
    )
    rulebook_id = cursor.lastrowid

    writer = RulesIngestor(conn, rulebook_id)
    writer.write_sections(roots)
    writer.write_skills(skills)
    writer.write_talents(talents)
    writer.write_spells(spells)
    writer.write_conditions(conditions)
    writer.write_careers(careers)
    writer.write_creatures(creatures)
    writer.write_tables(tables)
    indexed = writer.build_search_index()
    conn.commit()

    counts = {
        table: conn.execute(
            "SELECT COUNT(*) FROM %s WHERE rulebook_id = ?" % table, (rulebook_id,)
        ).fetchone()[0]
        for table in ("rule_sections", "rule_skills", "rule_talents", "rule_spells",
                      "rule_careers", "rule_creatures", "rule_conditions",
                      "rule_tables")
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

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", help="Path to the rulebook PDF")
    parser.add_argument("--slug", default="wfrp-4e-core",
                        help="Stable rulebook identifier")
    parser.add_argument("--title", default="", help="Display title")
    parser.add_argument("--db", default="",
                        help="Campaign database (defaults to the live one)")
    args = parser.parse_args(argv)

    db_path = args.db or wfrp_db.get_db_path()
    title = args.title or "Warhammer Fantasy Roleplay 4th Edition Rulebook"

    counts = ingest(args.pdf, db_path, args.slug, title)
    width = max(len(name) for name in counts)
    print("Ingested %r into %s" % (title, db_path))
    for name, value in counts.items():
        print("  %-*s  %s" % (width, name, value))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
