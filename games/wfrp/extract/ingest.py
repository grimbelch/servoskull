"""Command-line ingestion of a WFRP adventure module into the campaign database.

Run as::

    python -m games.wfrp.extract.ingest "path/to/module.pdf" --slug rough-nights-and-hard-days

Everything under ``module_*`` is rebuilt from scratch on each run. Per-campaign
state in ``campaign_module_*`` is keyed by module id and is left untouched, so a
re-extraction does not disturb a campaign in progress.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from typing import Optional

from .. import module_schema
from .assets import Asset, extract_assets
from .layout import ModuleDocument
from .map_keys import apply_map_keys
from .sections import Section, extract_sections, slugify
from .statblocks import Npc, extract_npcs
from .tables import RulesTable, extract_tables

EXTRACTOR_VERSION = "2.0"

_PLOT_NUMBER_RE = re.compile(r"^plot\s*(\d+)", re.IGNORECASE)
_CLOCK_RE = re.compile(
    r"^(?P<hour>\d{1,2})(?:[:.](?P<minute>\d{2}))?\s*(?P<meridiem>a\.?m\.?|p\.?m\.?)",
    re.IGNORECASE,
)


def time_to_minutes(label: str) -> Optional[int]:
    """Map an in-fiction time label onto minutes since the adventure's noon start.

    The adventures run from an afternoon through to the following morning, so a
    plain clock sort puts "4:30am" before "9:30pm". Anchoring at noon and rolling
    past midnight keeps the timeline monotonic.
    """
    text = (label or "").strip().lower()
    if not text:
        return None
    if text.startswith("midnight"):
        return 12 * 60
    if text.startswith("noon") or text.startswith("midday"):
        return 0

    match = _CLOCK_RE.match(text)
    if not match:
        return None
    hour = int(match.group("hour")) % 12
    minute = int(match.group("minute") or 0)
    if match.group("meridiem").startswith("p"):
        hour += 12
    minutes = hour * 60 + minute
    # Anchor at noon; anything earlier in clock terms is the following morning.
    return minutes - 12 * 60 if minutes >= 12 * 60 else minutes + 12 * 60


def file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _plain_text(markdown: str) -> str:
    return re.sub(r"[#*_`]", "", markdown or "")


class Ingestor:
    """Writes one extracted module into the database."""

    def __init__(self, conn: sqlite3.Connection, module_id: int):
        self.conn = conn
        self.module_id = module_id
        self.section_ids: dict[int, int] = {}   # doc_order -> module_sections.id
        self.section_by_slug: dict[str, int] = {}
        self.chapter_by_slug: dict[str, int] = {}
        self.npc_ids: dict[str, int] = {}

    # ── sections ─────────────────────────────────────────────────────────────

    def write_sections(self, roots: list[Section]) -> None:
        ordered = sorted(
            (node for root in roots for node in root.walk()), key=lambda n: n.doc_order
        )
        for section in ordered:
            parent_id = (
                self.section_ids.get(section.parent.doc_order) if section.parent else None
            )
            chapter = section.ancestor_of_kind("chapter")
            if section.kind == "chapter":
                chapter = section
            chapter_id = self.section_ids.get(chapter.doc_order) if chapter else None

            cursor = self.conn.execute(
                """
                INSERT INTO module_sections
                    (module_id, parent_id, chapter_id, level, ordinal, doc_order,
                     kind, slug, title, body_md, page_start, page_end, word_count)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    self.module_id, parent_id, chapter_id, section.level,
                    section.ordinal, section.doc_order, section.kind, section.slug,
                    section.title, section.body_md, section.page_start,
                    section.page_end, section.word_count,
                ),
            )
            row_id = cursor.lastrowid
            self.section_ids[section.doc_order] = row_id
            self.section_by_slug.setdefault(section.slug, row_id)
            if section.kind == "chapter":
                self.chapter_by_slug[section.slug] = row_id

    # ── plots and events ─────────────────────────────────────────────────────

    def write_plots_and_events(self, roots: list[Section]) -> None:
        ordered = sorted(
            (node for root in roots for node in root.walk()), key=lambda n: n.doc_order
        )
        plot_ids: dict[tuple[Optional[int], int], int] = {}

        for section in ordered:
            section_id = self.section_ids.get(section.doc_order)
            chapter = section.ancestor_of_kind("chapter")
            chapter_id = self.section_ids.get(chapter.doc_order) if chapter else None

            if section.kind == "plot":
                match = _PLOT_NUMBER_RE.match(section.title)
                number = int(match.group(1)) if match else section.ordinal + 1
                cursor = self.conn.execute(
                    """
                    INSERT INTO module_plots
                        (module_id, chapter_id, section_id, plot_number, title,
                         description, page)
                    VALUES (?,?,?,?,?,?,?)
                    """,
                    (
                        self.module_id, chapter_id, section_id, number,
                        section.title, section.body_md, section.page_start,
                    ),
                )
                plot_ids[(chapter_id, number)] = cursor.lastrowid

            elif section.kind in {"event", "event_note"}:
                # Events reference the plot they advance when the text names one.
                plot_id = None
                reference = _PLOT_NUMBER_RE.search(section.body_md[:400] or "")
                if reference:
                    plot_id = plot_ids.get((chapter_id, int(reference.group(1))))
                self.conn.execute(
                    """
                    INSERT INTO module_events
                        (module_id, chapter_id, section_id, plot_id, ordinal,
                         time_label, time_minutes, description, page)
                    VALUES (?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        self.module_id, chapter_id, section_id, plot_id,
                        section.doc_order, section.title,
                        time_to_minutes(section.title), section.body_md,
                        section.page_start,
                    ),
                )

    # ── NPCs ─────────────────────────────────────────────────────────────────

    def write_npcs(self, npcs: list[Npc]) -> None:
        for npc in npcs:
            section_id = self.section_by_slug.get(npc.section_slug)
            chapter_id = self.chapter_by_slug.get(npc.chapter_slug)
            title = " ".join(
                part for part in (npc.career, f"({npc.status})" if npc.status else "") if part
            ).strip()
            is_group = 1 if re.search(r"s$|\band\b", npc.name, re.IGNORECASE) and not npc.career else 0

            cursor = self.conn.execute(
                """
                INSERT INTO module_npcs
                    (module_id, section_id, slug, name, title, faction,
                     description, is_group, page)
                VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (
                    self.module_id, section_id, npc.slug, npc.name, title,
                    npc.faction, npc.description, is_group, npc.page,
                ),
            )
            npc_id = cursor.lastrowid
            self.npc_ids[npc.slug] = npc_id

            for profile in npc.profiles:
                stats = profile.characteristics
                self.conn.execute(
                    """
                    INSERT INTO module_npc_profiles
                        (npc_id, label, m, ws, bs, s, t, i, ag, dex, intl, wp, fel, w,
                         skills_json, talents_json, traits_json, trappings_json,
                         spells_json, page)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        npc_id, profile.label,
                        stats.get("m"), stats.get("ws"), stats.get("bs"), stats.get("s"),
                        stats.get("t"), stats.get("i"), stats.get("ag"), stats.get("dex"),
                        stats.get("intl"), stats.get("wp"), stats.get("fel"), stats.get("w"),
                        json.dumps(profile.skills), json.dumps(profile.talents),
                        json.dumps(profile.traits), json.dumps(profile.trappings),
                        json.dumps(profile.spells), npc.page,
                    ),
                )

            if section_id:
                self.conn.execute(
                    """
                    INSERT OR IGNORE INTO module_npc_appearances
                        (npc_id, section_id, chapter_id, role)
                    VALUES (?,?,?,?)
                    """,
                    (npc_id, section_id, chapter_id, npc.faction),
                )

    # ── assets and tables ────────────────────────────────────────────────────

    def write_assets(self, assets: list[Asset]) -> Optional[int]:
        cover_id = None
        for asset in assets:
            cursor = self.conn.execute(
                """
                INSERT INTO module_assets
                    (module_id, section_id, chapter_id, kind, path, caption, page,
                     bbox_json, width, height, sha256)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    self.module_id,
                    self.section_by_slug.get(asset.section_slug),
                    self.chapter_by_slug.get(asset.chapter_slug),
                    asset.kind, asset.path, asset.caption, asset.page,
                    json.dumps([round(v, 2) for v in asset.bbox]),
                    asset.width, asset.height, asset.sha256,
                ),
            )
            if asset.kind == "cover" and cover_id is None:
                cover_id = cursor.lastrowid
        return cover_id

    def write_tables(self, tables: list[RulesTable]) -> None:
        for table in tables:
            self.conn.execute(
                """
                INSERT INTO module_tables
                    (module_id, section_id, chapter_id, title, kind,
                     columns_json, rows_json, page)
                VALUES (?,?,?,?,?,?,?,?)
                """,
                (
                    self.module_id,
                    self.section_by_slug.get(table.section_slug),
                    self.chapter_by_slug.get(table.chapter_slug),
                    table.title, "rules",
                    json.dumps(table.headers), json.dumps(table.rows), table.page,
                ),
            )

    # ── search index ─────────────────────────────────────────────────────────

    def build_search_index(self, roots: list[Section], npcs: list[Npc]) -> None:
        if not module_schema.has_fts5(self.conn):
            return
        self.conn.execute(
            "DELETE FROM module_search WHERE module_id = ?", (self.module_id,)
        )
        for section in (node for root in roots for node in root.walk()):
            if not section.body_md:
                continue
            self.conn.execute(
                """
                INSERT INTO module_search
                    (title, body, kind, module_id, section_id, npc_id, page)
                VALUES (?,?,?,?,?,?,?)
                """,
                (
                    section.title, _plain_text(section.body_md), section.kind,
                    self.module_id, self.section_ids.get(section.doc_order), None,
                    section.page_start,
                ),
            )
        for npc in npcs:
            profile = npc.profiles[0] if npc.profiles else None
            body = [npc.description]
            if profile:
                for label in ("skills", "talents", "traits", "trappings"):
                    entries = getattr(profile, label)
                    if entries:
                        body.append(
                            f"{label.title()}: "
                            + ", ".join(e["name"] for e in entries)
                        )
            self.conn.execute(
                """
                INSERT INTO module_search
                    (title, body, kind, module_id, section_id, npc_id, page)
                VALUES (?,?,?,?,?,?,?)
                """,
                (
                    npc.name, "\n".join(p for p in body if p), "npc", self.module_id,
                    self.section_by_slug.get(npc.section_slug),
                    self.npc_ids.get(npc.slug), npc.page,
                ),
            )


def ingest(pdf_path: str, db_path: str, slug: str, title: str, image_dir: str) -> dict:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    module_schema.init_module_schema(conn)

    with ModuleDocument(pdf_path) as doc:
        roots, blocks = extract_sections(doc)
        npcs = extract_npcs(doc, blocks, roots)
        tables = extract_tables(doc, blocks, roots)
        assets = extract_assets(doc, roots, image_dir)
        page_count = doc.page_count

    # Image paths are stored relative to the repository root so the database can
    # be built on one machine and served from another.
    # games/wfrp/extract/ingest.py -> repository root
    repo_root = os.path.abspath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
    )
    for asset in assets:
        asset.path = os.path.relpath(os.path.abspath(asset.path), repo_root)

    # Replacing a module cascades away its old content but leaves campaign state,
    # which references module id and is re-linked on the next run.
    conn.execute("DELETE FROM modules WHERE slug = ?", (slug,))
    cursor = conn.execute(
        """
        INSERT INTO modules
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
    module_id = cursor.lastrowid

    writer = Ingestor(conn, module_id)
    writer.write_sections(roots)
    writer.write_plots_and_events(roots)
    writer.write_npcs(npcs)
    cover_id = writer.write_assets(assets)
    writer.write_tables(tables)
    map_keys = apply_map_keys(conn, module_id, slug)
    writer.build_search_index(roots, npcs)
    if cover_id:
        conn.execute("UPDATE modules SET cover_asset_id = ? WHERE id = ?", (cover_id, module_id))

    conn.commit()
    counts = {
        table: conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE module_id = ?", (module_id,)
        ).fetchone()[0]
        for table in ("module_sections", "module_plots", "module_events",
                      "module_npcs", "module_assets", "module_tables")
    }
    counts["module_npc_profiles"] = conn.execute(
        "SELECT COUNT(*) FROM module_npc_profiles p JOIN module_npcs n ON n.id = p.npc_id"
        " WHERE n.module_id = ?", (module_id,)
    ).fetchone()[0]
    counts["module_map_keys"] = map_keys
    conn.close()
    return counts


def main(argv: Optional[list[str]] = None) -> int:
    from .. import db as wfrp_db

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", help="Path to the module PDF")
    parser.add_argument("--slug", required=True, help="Stable module identifier")
    parser.add_argument("--title", default="", help="Display title")
    parser.add_argument("--db", default="", help="Campaign database (defaults to the live one)")
    parser.add_argument("--images", default="", help="Directory for rendered images")
    args = parser.parse_args(argv)

    db_path = args.db or wfrp_db.get_db_path()
    image_dir = args.images or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "rules", "modules", args.slug, "images",
    )
    title = args.title or args.slug.replace("-", " ").title()

    counts = ingest(args.pdf, db_path, args.slug, title, image_dir)
    width = max(len(name) for name in counts)
    print(f"Ingested {title!r} into {db_path}")
    for name, value in counts.items():
        print(f"  {name:<{width}}  {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
