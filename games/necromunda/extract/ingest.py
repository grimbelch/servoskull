"""Build the Necromunda rules database from the source PDF.

Run this once, on a real computer rather than the Pi -- it needs PyMuPDF, which
is a dev-time dependency only:

    python -m games.necromunda.extract.ingest \\
        "games/necromunda/rules/manuals/necromunda-skirmish-core-rulebook-2026.pdf"

Everything written here is reproducible from the source, so the database is
dropped and rebuilt rather than migrated. The source file's SHA-256 is recorded
so a rebuild can be told apart from a different printing.

The rules text is copyrighted. The PDF and this database stay on the device.
"""
from __future__ import annotations

import argparse
import collections
import datetime
import hashlib
import json
import pathlib
import re

# PyMuPDF is a dev-time dependency: the database is built on a real computer
# and copied to the unit, which does not carry it. Importing this module must
# therefore not be fatal -- it is imported for its parsing helpers as well as
# for running the extraction, and a module that calls sys.exit() on import
# would take the whole service down with it. The absence is reported by the
# one function that actually needs the library.
try:
    import pymupdf
except ImportError:  # pragma: no cover - older wheels only expose fitz
    try:
        import fitz as pymupdf
    except ImportError:
        pymupdf = None

_NO_PYMUPDF = "PyMuPDF is required to build the rules database: pip install pymupdf"

from .. import db as necro_db
from .. import rules_schema
from . import actions as actions_mod
from . import conditions as conditions_mod
from . import equipment as equipment_mod
from . import randtables as randtables_mod
from . import sections as sections_mod
from . import skills as skills_mod
from . import tables
from . import subtypes as subtypes_mod
from . import territories as territories_mod
from . import traits as traits_mod

EXTRACTOR_VERSION = "1.0"
DEFAULT_SLUG = "necromunda-skirmish-core-rulebook"
DEFAULT_TITLE = "Necromunda Skirmish: Core Rulebook"

# Front and back matter carry no rules: the contents list and the index are just
# page pointers, and indexing them would put a bare letter heading ("A", "B")
# into search results ahead of real rules.
_SKIP_CHAPTERS = {"contents", "index", "", "model-showcase",
                  "necromunda-battlefield-showcase"}
# A heading with almost nothing under it is a label on a photograph or a blank
# form, not a rule. Indexed, they answer questions with a bare caption.
_MIN_SECTION_WORDS = 5

_INT_OK = str.maketrans({'"': "", "*": "", "+": "", "’": ""})


_CONTENTS_PAGES = 6
_NORM = re.compile(r"[^a-z0-9]+")


def _normalise(text: str) -> str:
    return _NORM.sub(" ", (text or "").lower()).strip()


def _contents_entries(doc) -> list[tuple[str, int]]:
    """(title, printed page) pairs read off the book's contents list.

    The list prints a heading and its page number on consecutive lines, which is
    the only place in this scan that a printed page number appears as text at
    all -- the folios on the pages themselves did not survive the OCR.
    """
    entries: list[tuple[str, int]] = []
    for page_no in range(min(_CONTENTS_PAGES, doc.page_count)):
        lines = [l.strip() for l in doc.load_page(page_no).get_text("text").splitlines()
                 if l.strip()]
        if not any(_normalise(l) == "contents" for l in lines):
            continue
        for first, second in zip(lines, lines[1:]):
            if not re.fullmatch(r"\d{1,3}", second) or re.fullmatch(r"\d{1,3}", first):
                continue
            title = re.sub(r"^[-\u2022\u00b7\s]+", "", first)
            title = re.sub(r"[.\u00b7\s]+$", "", title)
            if len(title) > 2:
                entries.append((title, int(second)))
    return entries


def _derive_page_offset(doc, tree: list[dict]) -> tuple[int, int]:
    """Measure how far the PDF index runs ahead of the printed page number.

    Each contents entry names a heading and the page it is printed on. Finding
    where that heading actually falls in the scan gives one measurement of the
    offset; the modal value across every entry that can be matched is the
    answer, and a stray mismatch cannot move it. Returns (offset, support).
    """
    first_seen: dict[str, int] = {}
    for item in tree:
        for key in (item["title"], item["section"], item["chapter"]):
            name = _normalise(key)
            if name and name not in first_seen:
                first_seen[name] = item["page"]

    votes: collections.Counter = collections.Counter()
    for title, printed in _contents_entries(doc):
        found = first_seen.get(_normalise(title))
        if found is not None and 0 <= found - printed <= 30:
            votes[found - printed] += 1
    if not votes:
        return 0, 0
    offset, support = votes.most_common(1)[0]
    return offset, support


def _table_kind(title: str) -> str:
    """Group the tables the engine resolves for itself."""
    upper = (title or "").upper()
    if "LASTING INJURY" in upper or "LASTING DAMAGE" in upper:
        return "lasting_injury"
    if "ADVANCEMENT" in upper:
        return "advancement"
    if "SCENARIO" in upper or "OBJECTIVE" in upper:
        return "scenario"
    return "reference"


def _sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _as_int(text: str) -> int | None:
    """The numeric value of a printed cell, or None when it is not a number.

    A blank or dashed cell must come back as None rather than 0: "no AP printed"
    and "AP 0" are different claims, and only one of them is in the book.
    """
    cleaned = (text or "").strip().translate(_INT_OK)
    if not cleaned or cleaned in {"-", "—"}:
        return None
    try:
        return int(cleaned)
    except ValueError:
        return None


def _traits_list(traits: str) -> list[str]:
    """Split a printed trait list on commas, keeping bracketed values intact."""
    out: list[str] = []
    depth = 0
    current = ""
    for char in traits:
        if char in "([":
            depth += 1
        elif char in ")]":
            depth = max(0, depth - 1)
        if char == "," and depth == 0:
            if current.strip():
                out.append(current.strip())
            current = ""
            continue
        current += char
    if current.strip():
        out.append(current.strip())
    return out


def _weapon_class(category: str, cells: list[str]) -> str:
    cat = (category or "").upper()
    if "GRENADE" in cat:
        return "grenade"
    # An Engaged-range weapon ("E") with no long range is a close combat arm.
    if (cells[0] or "").strip().upper() == "E":
        return "close_combat"
    if any(key in cat for key in ("CHAIN", "POWER", "SHOCK", "CLOSE COMBAT")):
        return "close_combat"
    return "ranged"


def ingest(pdf_path: pathlib.Path, slug: str = DEFAULT_SLUG,
           title: str = DEFAULT_TITLE, edition: str = "2026") -> dict:
    """Extract the rulebook into the rules database, replacing any earlier copy."""
    if pymupdf is None:
        raise RuntimeError(_NO_PYMUPDF)
    doc = pymupdf.open(pdf_path)
    # Before anything reads prose: what a hyphen at the end of a line meant is
    # decided against the words this book uses.
    sections_mod.load_vocabulary(doc)
    tree = sections_mod.build_tree(doc)
    offset, support = _derive_page_offset(doc, tree)
    print(f"[necromunda] Printed-page offset: {offset} (agreed by {support} contents entries)")
    conn = necro_db.connect()
    try:
        rules_schema.reset_rulebook(conn, slug)
        with conn:
            cur = conn.execute(
                "INSERT INTO rulebooks (slug, title, system, edition, source_file,"
                " source_sha256, page_count, page_offset, extracted_at,"
                " extractor_version) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (slug, title, "Necromunda Skirmish", edition, pdf_path.name,
                 _sha256(pdf_path), doc.page_count, offset,
                 datetime.datetime.now().isoformat(timespec="seconds"),
                 EXTRACTOR_VERSION),
            )
            book_id = cur.lastrowid

            counts = {"sections": 0, "weapons": 0, "traits": 0, "skills": 0,
                      "conditions": 0, "equipment": 0, "actions": 0,
                      "territories": 0, "subtypes": 0,
                      "tables": 0, "table_rows": 0}
            section_ids: dict[tuple[str, str, str], int] = {}

            # --- prose layer -------------------------------------------------
            chapters: dict[str, int] = {}
            doc_order = 0
            for item in tree:
                chapter = item["chapter"].strip()
                if sections_mod.slugify(chapter) in _SKIP_CHAPTERS:
                    continue
                chapter_id = chapters.get(chapter)
                if chapter_id is None:
                    doc_order += 1
                    chapter_id = conn.execute(
                        "INSERT INTO rule_sections (rulebook_id, parent_id, chapter_id,"
                        " level, ordinal, doc_order, kind, slug, path, title,"
                        " body_md, page_start, page_end, word_count)"
                        " VALUES (?,NULL,NULL,1,?,?,?,?,?,?,'',?,?,0)",
                        (book_id, len(chapters), doc_order, "chapter",
                         sections_mod.slugify(chapter), sections_mod.slugify(chapter),
                         chapter, item["page"], item["page"]),
                    ).lastrowid
                    conn.execute("UPDATE rule_sections SET chapter_id = ? WHERE id = ?",
                                 (chapter_id, chapter_id))
                    chapters[chapter] = chapter_id
                    counts["sections"] += 1

                doc_order += 1
                path = "/".join(p for p in (
                    sections_mod.slugify(chapter),
                    sections_mod.slugify(item["section"]),
                    sections_mod.slugify(item["title"]),
                ) if p)
                body = item["body"]
                if len(body.split()) < _MIN_SECTION_WORDS:
                    continue
                sec_id = conn.execute(
                    "INSERT INTO rule_sections (rulebook_id, parent_id, chapter_id,"
                    " level, ordinal, doc_order, kind, slug, path, title, body_md,"
                    " page_start, page_end, word_count) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (book_id, chapter_id, chapter_id, 3, doc_order, doc_order,
                     sections_mod.slugify(chapter) or "section",
                     sections_mod.slugify(item["title"]), path, item["title"],
                     body, item["page"], item.get("page_end", item["page"]),
                     len(body.split())),
                ).lastrowid
                section_ids[(chapter, item["section"], item["title"])] = sec_id
                counts["sections"] += 1

            # --- weapon profiles --------------------------------------------
            anchors = tables.header_anchors(doc, tables.WEAPON_COLUMNS, ["SR", "LR"])
            for row in tables.weapon_rows(doc, anchors):
                cells = row["cells"]
                traits = cells[5].strip()
                conn.execute(
                    "INSERT INTO rule_weapons (rulebook_id, section_id, slug, name,"
                    " weapon_class, category, parent_slug, is_variant, sr_text, lr_text,"
                    " str_text, ap_text, lethality_text, creds_text, tp_text, strength,"
                    " ap, lethality, creds, trading_post, traits, traits_json,"
                    " cells_json, needs_review, page)"
                    " VALUES (?,NULL,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (book_id, sections_mod.slugify(row["name"]), row["name"],
                     _weapon_class(row["category"], cells), row["category"], "",
                     int(row["is_variant"]), cells[0], cells[1], cells[2], cells[3],
                     cells[4], cells[6], cells[7], _as_int(cells[2]), _as_int(cells[3]),
                     _as_int(cells[4]), _as_int(cells[6]), _as_int(cells[7]),
                     traits, json.dumps(_traits_list(traits)),
                     json.dumps(cells), int(row["needs_review"]), row["page"]),
                )
                counts["weapons"] += 1

            # --- named rules -------------------------------------------------
            # Traits, skills and conditions are each a short name in display
            # type with the rule beneath, which the section extractor cannot
            # see: it looks for chapter headings at 12pt and these are set at
            # body size. They are collected separately so that "what does Blaze
            # do" is a row lookup rather than a search of prose.
            for trait in traits_mod.extract(doc):
                conn.execute(
                    "INSERT INTO rule_traits (rulebook_id, slug, name,"
                    " takes_value, description, page) VALUES (?,?,?,?,?,?)",
                    (book_id, sections_mod.slugify(trait["name"]), trait["name"],
                     int(trait["takes_value"]), trait["description"], trait["page"]))
                counts["traits"] += 1

            for skill in skills_mod.extract(doc):
                conn.execute(
                    "INSERT INTO rule_skills (rulebook_id, slug, name, skill_set,"
                    " usable_by, description, page) VALUES (?,?,?,?,?,?,?)",
                    (book_id, sections_mod.slugify(skill["name"]), skill["name"],
                     skill["skill_set"], skill.get("usable_by", ""),
                     skill["description"], skill["page"]))
                counts["skills"] += 1

            for condition in conditions_mod.extract(doc):
                conn.execute(
                    "INSERT INTO rule_conditions (rulebook_id, slug, name, kind,"
                    " description, page) VALUES (?,?,?,?,?,?)",
                    (book_id, sections_mod.slugify(condition["name"]),
                     condition["name"], condition["kind"],
                     condition["description"], condition["page"]))
                counts["conditions"] += 1

            # --- equipment ---------------------------------------------------
            for item in equipment_mod.extract(doc, tree):
                conn.execute(
                    "INSERT INTO rule_equipment (rulebook_id, slug, name, category,"
                    " parent_slug, variant, usable_by, creds_text, tp_text, creds,"
                    " trading_post, description, page)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (book_id, sections_mod.slugify(item["name"]), item["name"],
                     item["category"],
                     sections_mod.slugify(item.get("base_name", item["name"]))
                     if item.get("variant") else "",
                     item.get("variant", ""), item.get("usable_by", ""),
                     item["creds_text"], item["tp_text"], item["creds"],
                     item["trading_post"], item["description"], item["page"]))
                counts["equipment"] += 1

            # --- actions -----------------------------------------------------
            for action in actions_mod.extract(doc):
                conn.execute(
                    "INSERT INTO rule_actions (rulebook_id, slug, name, cost,"
                    " usable_by, status, description, page)"
                    " VALUES (?,?,?,?,?,?,?,?)",
                    (book_id, sections_mod.slugify(
                        f"{action['name']}-{action['status']}"),
                     action["name"], action["cost"], action["usable_by"],
                     action["status"], action["description"], action["page"]))
                counts["actions"] += 1

            # --- model subtypes ----------------------------------------------
            for subtype in subtypes_mod.extract(doc):
                conn.execute(
                    "INSERT INTO rule_subtypes (rulebook_id, slug, name,"
                    " applies_to, takes_value, description, page)"
                    " VALUES (?,?,?,?,?,?,?)",
                    (book_id,
                     # Fighter and Vehicle each have a Loner, so the list has
                     # to be part of the key.
                     sections_mod.slugify(
                         f"{subtype['name']}-{subtype['applies_to']}"),
                     subtype["name"].title(), subtype["applies_to"],
                     int(subtype["takes_value"]), subtype["description"],
                     subtype["page"]))
                counts["subtypes"] += 1

            # --- territories -------------------------------------------------
            for territory in territories_mod.extract(doc):
                conn.execute(
                    "INSERT INTO rule_territories (rulebook_id, slug, name,"
                    " flavour, boons_json, battlefield_effect, page)"
                    " VALUES (?,?,?,?,?,?,?)",
                    (book_id, sections_mod.slugify(territory["name"]),
                     territory["name"], territory["flavour"],
                     json.dumps(territory["boons"]),
                     territory["battlefield_effect"], territory["page"]))
                counts["territories"] += 1

            # --- random tables -----------------------------------------------
            # Rows keep their parsed span, so resolving a roll is an index
            # lookup rather than a parse of "21-26" at the table.
            # The Panicked Pets table is a Status-to-Action lookup printed
            # inside the Pet subtype, not a dice table, so it comes from the
            # subtype extractor; its rows carry no roll span.
            found_tables = randtables_mod.extract(doc)
            # Two tables the row reader cannot see: the Panicked Pets table is
            # a Status lookup inside the Pet subtype, and the Pitch Black table
            # centres its roll between the two lines of its own result.
            for extra in (subtypes_mod.panicked_table(doc),
                          randtables_mod.pitch_black_table(doc)):
                if extra is not None:
                    found_tables.append(extra)
            for table in found_tables:
                table_id = conn.execute(
                    "INSERT INTO rule_tables (rulebook_id, slug, title, kind,"
                    " dice, columns_json, notes, page) VALUES (?,?,?,?,?,?,?,?)",
                    (book_id, sections_mod.slugify(table["title"]), table["title"],
                     table.get("kind") or _table_kind(table["title"]),
                     table["dice"],
                     json.dumps(table["columns"]),
                     ("No row was recovered for: "
                      + ", ".join(str(m) for m in table["missing"]))
                     if table.get("missing") else "",
                     table["page"])).lastrowid
                counts["tables"] += 1
                for ordinal, row in enumerate(table["rows"]):
                    conn.execute(
                        "INSERT INTO rule_table_rows (table_id, ordinal, roll_min,"
                        " roll_max, roll_label, result, detail, cells_json)"
                        " VALUES (?,?,?,?,?,?,'',?)",
                        (table_id, ordinal, row["roll_min"], row["roll_max"],
                         row["roll_label"], row["result"],
                         json.dumps([row["roll_label"], row["result"]])))
                    counts["table_rows"] += 1

            _build_search_index(conn, book_id)
        return counts
    finally:
        conn.close()
        doc.close()


def _build_search_index(conn, book_id: int) -> None:
    """Populate the FTS index over prose and weapon rows.

    Weapons go in alongside the prose so one query can surface both the boltgun's
    profile and the paragraph explaining the trait it carries.
    """
    if not rules_schema.has_fts5(conn):
        print("[necromunda] SQLite has no FTS5; search will fall back to LIKE.")
        return
    conn.execute("DELETE FROM rule_search WHERE rulebook_id = ?", (book_id,))
    for row in conn.execute(
            "SELECT id, title, body_md, kind, page_start, path FROM rule_sections"
            " WHERE rulebook_id = ? AND body_md != ''", (book_id,)):
        conn.execute(
            "INSERT INTO rule_search (title, body, kind, rulebook_id, section_id,"
            " ref_table, ref_id, page) VALUES (?,?,?,?,?,?,?,?)",
            (f"{row['title']} {row['path']}", row["body_md"], row["kind"], book_id,
             row["id"], "rule_sections", row["id"], row["page_start"]),
        )
    # The named rules go in too, so a search for a trait finds the trait and
    # not merely a weapon that happens to carry it.
    # Each table names its own body column: a Territory has no "description",
    # it has a battlefield effect and its Boons.
    for table, kind, extra, body in (
            ("rule_traits", "trait", "takes_value", "description"),
            ("rule_skills", "skill", "skill_set", "description"),
            ("rule_conditions", "condition", "kind", "description"),
            ("rule_actions", "action", "cost", "description"),
            ("rule_equipment", "equipment", "category", "description"),
            ("rule_subtypes", "subtype", "applies_to", "description"),
            ("rule_territories", "territory", "boons_json", "battlefield_effect")):
        for row in conn.execute(
                f"SELECT id, name, {body} AS description, page, {extra} AS extra"
                f" FROM {table} WHERE rulebook_id = ?", (book_id,)):
            conn.execute(
                "INSERT INTO rule_search (title, body, kind, rulebook_id,"
                " section_id, ref_table, ref_id, page) VALUES (?,?,?,?,NULL,?,?,?)",
                (row["name"], f"{row['name']} {row['extra']} {row['description']}",
                 kind, book_id, table, row["id"], row["page"]))

    for row in conn.execute(
            "SELECT id, name, category, traits, sr_text, lr_text, str_text, ap_text,"
            " lethality_text, creds_text, page FROM rule_weapons WHERE rulebook_id = ?",
            (book_id,)):
        body = (f"{row['name']} {row['category']} SR {row['sr_text']} LR {row['lr_text']}"
                f" Str {row['str_text']} AP {row['ap_text']} Lethality"
                f" {row['lethality_text']} {row['traits']} {row['creds_text']} credits")
        conn.execute(
            "INSERT INTO rule_search (title, body, kind, rulebook_id, section_id,"
            " ref_table, ref_id, page) VALUES (?,?,?,?,NULL,?,?,?)",
            (row["name"], body, "weapon", book_id, "rule_weapons", row["id"], row["page"]),
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pdf", type=pathlib.Path, help="source rulebook PDF")
    parser.add_argument("--slug", default=DEFAULT_SLUG)
    parser.add_argument("--title", default=DEFAULT_TITLE)
    parser.add_argument("--edition", default="2026")
    args = parser.parse_args(argv)

    if pymupdf is None:
        print(f"[necromunda] {_NO_PYMUPDF}")
        return 1
    if not args.pdf.exists():
        print(f"[necromunda] No such PDF: {args.pdf}")
        return 1
    counts = ingest(args.pdf, args.slug, args.title, args.edition)
    print(f"[necromunda] Ingested {args.pdf.name} -> {necro_db.db_path()}")
    for key, value in counts.items():
        print(f"[necromunda]   {key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
