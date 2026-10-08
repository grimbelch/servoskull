"""Schema for the Necromunda Skirmish core rulebook: prose plus machine-usable data.

Everything here is ``rule_*`` content extracted from a source PDF, so the whole
set is reproducible by re-running the extractor and safe to drop and rebuild.
Nothing is campaign specific.

The tables fall into three layers, and the split is the same one the WFRP
rulebook uses (see ``games/wfrp/rules_schema.py``) for the same reason:

``rule_sections``
    The reference layer -- the book's heading tree with the prose under each
    heading. This is what full-text search reads and what Omega-7 quotes when
    someone asks "how does an Engage action work?".

``rule_weapons`` / ``rule_traits`` / ``rule_skills`` / ``rule_equipment`` / ``rule_conditions``
    The data layer. The same content parsed into columns so it can be queried
    rather than grepped: "what is a boltgun's AP?", "which Cunning skills are
    there?". These exist because the printed tables do NOT survive linear text
    extraction: an empty cell leaves no token, so reading a row as a sequence
    shifts every later value left by one. On the Trading Post weapon tables that
    turns an autopistol's Lethality into its AP. The extractor recovers the true
    columns from word geometry; these tables record the result so the answer is a
    column lookup and never a re-parse of prose.

``rule_tables`` / ``rule_table_rows``
    The random-table layer. Lasting Injuries, scenario generation and the like.
    Rows carry a parsed ``roll_min``/``roll_max`` span so a D66 or 2D6 resolves
    by index lookup instead of parsing "11-16" at runtime.
"""
from __future__ import annotations

import sqlite3

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS rulebooks (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    slug              TEXT UNIQUE NOT NULL,
    title             TEXT NOT NULL,
    system            TEXT DEFAULT 'Necromunda Skirmish',
    edition           TEXT DEFAULT '',
    source_file       TEXT DEFAULT '',
    source_sha256     TEXT DEFAULT '',
    page_count        INTEGER DEFAULT 0,
    -- How far the PDF's page index runs ahead of the page number printed on the
    -- page. The scan carries front matter the folios do not count, and the
    -- folios themselves are not in the OCR text layer, so this is measured at
    -- ingest from the contents list. Citations subtract it; a reader who turns
    -- to the page a lookup names has to find the rule there.
    page_offset       INTEGER DEFAULT 0,
    extracted_at      TEXT DEFAULT '',
    extractor_version TEXT DEFAULT ''
);

-- The heading tree recovered from type size and the running header, so every
-- paragraph has a home. `kind` is inferred from position in the tree and lets a
-- caller ask for just the core rules or just the Trading Post.
CREATE TABLE IF NOT EXISTS rule_sections (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    rulebook_id  INTEGER NOT NULL,
    parent_id    INTEGER,
    chapter_id   INTEGER,          -- nearest level-1 ancestor
    level        INTEGER NOT NULL,
    ordinal      INTEGER NOT NULL, -- order among siblings
    doc_order    INTEGER NOT NULL, -- absolute document order
    kind         TEXT NOT NULL DEFAULT 'section',
    slug         TEXT NOT NULL DEFAULT '',
    path         TEXT NOT NULL DEFAULT '',  -- "core-rules/movement/terrain"
    title        TEXT NOT NULL,
    body_md      TEXT DEFAULT '',
    page_start   INTEGER DEFAULT 0,
    page_end     INTEGER DEFAULT 0,
    word_count   INTEGER DEFAULT 0,
    FOREIGN KEY (rulebook_id) REFERENCES rulebooks (id)     ON DELETE CASCADE,
    FOREIGN KEY (parent_id)   REFERENCES rule_sections (id) ON DELETE CASCADE,
    FOREIGN KEY (chapter_id)  REFERENCES rule_sections (id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_necro_sections_book   ON rule_sections (rulebook_id, doc_order);
CREATE INDEX IF NOT EXISTS idx_necro_sections_parent ON rule_sections (parent_id);
CREATE INDEX IF NOT EXISTS idx_necro_sections_kind   ON rule_sections (rulebook_id, kind);
CREATE INDEX IF NOT EXISTS idx_necro_sections_slug   ON rule_sections (rulebook_id, slug);

-- One row per printed weapon profile line.
--
-- `lethality` is the book's L column: the number of Injury dice rolled when a
-- wound takes the target to zero Wounds, so it must be numeric for the injury
-- resolver and must not be confused with AP. A blank printed cell is NULL, not
-- 0, so "not printed" stays distinguishable from "printed as zero".
--
-- Ammo and special-round lines are printed beneath their weapon as "- warp
-- round" and modify it rather than standing alone; they keep `parent_slug` and
-- `is_variant` so a lookup of the parent can offer them, and `creds` holds the
-- printed delta ("+10") in `creds_text`.
CREATE TABLE IF NOT EXISTS rule_weapons (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    rulebook_id  INTEGER NOT NULL,
    section_id   INTEGER,
    slug         TEXT NOT NULL,
    name         TEXT NOT NULL,
    weapon_class TEXT DEFAULT 'ranged',   -- ranged|close_combat|grenade|special
    category     TEXT DEFAULT '',         -- printed table heading, "AUTO/STUB WEAPONS"
    parent_slug  TEXT DEFAULT '',
    is_variant   INTEGER DEFAULT 0,
    sr_text      TEXT DEFAULT '',         -- short range, as printed ('8"')
    lr_text      TEXT DEFAULT '',         -- long range, as printed
    str_text     TEXT DEFAULT '',
    ap_text      TEXT DEFAULT '',
    lethality_text TEXT DEFAULT '',
    creds_text   TEXT DEFAULT '',
    tp_text      TEXT DEFAULT '',
    strength     INTEGER,
    ap           INTEGER,
    lethality    INTEGER,
    creds        INTEGER,
    trading_post INTEGER,                 -- the TP rarity column
    traits       TEXT DEFAULT '',
    traits_json  TEXT DEFAULT '[]',
    cells_json   TEXT DEFAULT '[]',       -- raw recovered cells, for auditing
    -- Set when the recovered row looks contaminated by surrounding prose: a few
    -- profiles are printed inline in body text rather than in a table, and
    -- their widest cell then absorbs neighbouring sentences. The profile
    -- numbers are still sound; only the trait list is suspect, and a reader can
    -- say so instead of quoting it as printed.
    needs_review INTEGER DEFAULT 0,
    page         INTEGER DEFAULT 0,
    FOREIGN KEY (rulebook_id) REFERENCES rulebooks (id)     ON DELETE CASCADE,
    FOREIGN KEY (section_id)  REFERENCES rule_sections (id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_necro_weapons_book ON rule_weapons (rulebook_id, slug);
CREATE INDEX IF NOT EXISTS idx_necro_weapons_name ON rule_weapons (rulebook_id, name);

-- Weapon traits are referenced by name from every weapon profile, so they are a
-- table rather than prose: resolving "Rapid Fire (1)" must not depend on search.
CREATE TABLE IF NOT EXISTS rule_traits (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    rulebook_id INTEGER NOT NULL,
    section_id  INTEGER,
    slug        TEXT NOT NULL,
    name        TEXT NOT NULL,
    takes_value INTEGER DEFAULT 0,   -- printed with a bracketed value, "Blast (3\")"
    description TEXT DEFAULT '',
    page        INTEGER DEFAULT 0,
    FOREIGN KEY (rulebook_id) REFERENCES rulebooks (id)     ON DELETE CASCADE,
    FOREIGN KEY (section_id)  REFERENCES rule_sections (id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_necro_traits_book ON rule_traits (rulebook_id, slug);

CREATE TABLE IF NOT EXISTS rule_skills (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    rulebook_id INTEGER NOT NULL,
    section_id  INTEGER,
    slug        TEXT NOT NULL,
    name        TEXT NOT NULL,
    skill_set   TEXT DEFAULT '',   -- agility|brawn|combat|cunning|savant|shooting|inherent
    description TEXT DEFAULT '',
    page        INTEGER DEFAULT 0,
    FOREIGN KEY (rulebook_id) REFERENCES rulebooks (id)     ON DELETE CASCADE,
    FOREIGN KEY (section_id)  REFERENCES rule_sections (id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_necro_skills_book ON rule_skills (rulebook_id, skill_set, slug);

CREATE TABLE IF NOT EXISTS rule_equipment (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    rulebook_id INTEGER NOT NULL,
    section_id  INTEGER,
    slug        TEXT NOT NULL,
    name        TEXT NOT NULL,
    category    TEXT DEFAULT '',   -- armour|field_armour|personal|gang|accessory
    creds_text  TEXT DEFAULT '',
    tp_text     TEXT DEFAULT '',
    creds       INTEGER,
    trading_post INTEGER,
    description TEXT DEFAULT '',
    cells_json  TEXT DEFAULT '[]',
    page        INTEGER DEFAULT 0,
    FOREIGN KEY (rulebook_id) REFERENCES rulebooks (id)     ON DELETE CASCADE,
    FOREIGN KEY (section_id)  REFERENCES rule_sections (id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_necro_equipment_book ON rule_equipment (rulebook_id, category, slug);

-- Conditions and model statuses both gate what a model may do, so they share a
-- table and are told apart by `kind`. Status is a new-edition concept (Active,
-- Injured, Seriously Injured, Out of Action) and drives the injury resolver.
CREATE TABLE IF NOT EXISTS rule_conditions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    rulebook_id INTEGER NOT NULL,
    section_id  INTEGER,
    slug        TEXT NOT NULL,
    name        TEXT NOT NULL,
    kind        TEXT DEFAULT 'condition',  -- condition|status
    description TEXT DEFAULT '',
    page        INTEGER DEFAULT 0,
    FOREIGN KEY (rulebook_id) REFERENCES rulebooks (id)     ON DELETE CASCADE,
    FOREIGN KEY (section_id)  REFERENCES rule_sections (id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_necro_conditions_book ON rule_conditions (rulebook_id, kind, slug);

-- `dice` records what the table is rolled on ("D6", "D66", "2D6"); `kind`
-- groups the tables the engine resolves for itself.
CREATE TABLE IF NOT EXISTS rule_tables (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    rulebook_id  INTEGER NOT NULL,
    section_id   INTEGER,
    slug         TEXT NOT NULL,
    title        TEXT NOT NULL,
    kind         TEXT DEFAULT 'reference',  -- lasting_injury|scenario|territory|reference
    dice         TEXT DEFAULT '',
    columns_json TEXT DEFAULT '[]',
    notes        TEXT DEFAULT '',
    page         INTEGER DEFAULT 0,
    FOREIGN KEY (rulebook_id) REFERENCES rulebooks (id)     ON DELETE CASCADE,
    FOREIGN KEY (section_id)  REFERENCES rule_sections (id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_necro_tables_book ON rule_tables (rulebook_id, kind, slug);

CREATE TABLE IF NOT EXISTS rule_table_rows (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    table_id   INTEGER NOT NULL,
    ordinal    INTEGER NOT NULL,
    roll_min   INTEGER,           -- NULL when the row is not roll-indexed
    roll_max   INTEGER,
    roll_label TEXT DEFAULT '',   -- as printed, e.g. "11-16", "6+"
    result     TEXT DEFAULT '',   -- the primary result cell
    detail     TEXT DEFAULT '',   -- remaining cells, joined
    cells_json TEXT DEFAULT '[]',
    FOREIGN KEY (table_id) REFERENCES rule_tables (id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_necro_table_rows ON rule_table_rows (table_id, ordinal);
CREATE INDEX IF NOT EXISTS idx_necro_table_roll ON rule_table_rows (table_id, roll_min, roll_max);
"""

# Retrieval index over both prose and data rows, so one query can surface the
# Rapid Fire trait and the paragraph that explains how its extra hits are taken.
FTS_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS rule_search USING fts5 (
    title,
    body,
    kind UNINDEXED,
    rulebook_id UNINDEXED,
    section_id UNINDEXED,
    ref_table UNINDEXED,
    ref_id UNINDEXED,
    page UNINDEXED,
    tokenize = 'unicode61'
);
"""

# Ordered so children drop before parents.
CONTENT_TABLES = [
    "rule_table_rows",
    "rule_tables",
    "rule_conditions",
    "rule_equipment",
    "rule_skills",
    "rule_traits",
    "rule_weapons",
    "rule_sections",
    "rulebooks",
]

# A column that only exists in the current shape of each table. An older
# database is rebuilt rather than migrated: every row is reproducible from the
# source PDF, so there is nothing to preserve.
_SHAPE_SENTINELS = {
    "rulebooks": "page_offset",
    "rule_sections": "path",
    "rule_weapons": "lethality",
    "rule_traits": "takes_value",
    "rule_skills": "skill_set",
    "rule_equipment": "category",
    "rule_conditions": "kind",
    "rule_tables": "dice",
    "rule_table_rows": "roll_min",
}


def has_fts5(conn: sqlite3.Connection) -> bool:
    try:
        conn.execute("CREATE VIRTUAL TABLE temp._fts5_probe USING fts5(x);")
        conn.execute("DROP TABLE temp._fts5_probe;")
        return True
    except sqlite3.Error:
        return False


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def drop_stale_content_tables(conn: sqlite3.Connection) -> list[str]:
    """Drop rule tables left over from an incompatible earlier schema."""
    dropped = []
    for table in CONTENT_TABLES:
        sentinel = _SHAPE_SENTINELS.get(table)
        if not sentinel or not _table_exists(conn, table):
            continue
        columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if sentinel not in columns:
            conn.execute(f"DROP TABLE {table}")
            dropped.append(table)
    return dropped


def init_rules_schema(conn: sqlite3.Connection) -> None:
    """Create the rulebook content tables if absent, rebuilding stale ones."""
    # Dropping a stale table fires its foreign-key actions, and those cascades
    # walk into sibling tables that may already be gone. Enforcement is off for
    # the teardown and restored afterwards; the pragma is a no-op inside a
    # transaction, so any open one is closed first.
    previous = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    conn.commit()
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        drop_stale_content_tables(conn)
        conn.commit()
    finally:
        conn.execute(f"PRAGMA foreign_keys = {'ON' if previous else 'OFF'}")
    conn.executescript(SCHEMA_SQL)
    if has_fts5(conn):
        conn.executescript(FTS_SQL)


def reset_rulebook(conn: sqlite3.Connection, slug: str | None = None) -> None:
    """Clear extracted rules so a book can be re-ingested from source."""
    if slug is None:
        for table in CONTENT_TABLES:
            if _table_exists(conn, table):
                conn.execute(f"DELETE FROM {table}")
        if _table_exists(conn, "rule_search"):
            conn.execute("DELETE FROM rule_search")
        return

    row = conn.execute("SELECT id FROM rulebooks WHERE slug = ?", (slug,)).fetchone()
    if not row:
        return
    # Every content table cascades from rulebooks, so one delete is enough.
    conn.execute("DELETE FROM rulebooks WHERE id = ?", (row[0],))
    if _table_exists(conn, "rule_search"):
        conn.execute("DELETE FROM rule_search WHERE rulebook_id = ?", (row[0],))
