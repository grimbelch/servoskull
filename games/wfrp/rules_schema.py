"""Schema for the WFRP core rulebook: reference prose plus machine-usable mechanics.

Everything here is ``rule_*`` content extracted from a source PDF. Like the
``module_*`` tables it is wholly reproducible by re-running the extractor, so
the entire set is safe to drop and rebuild. Nothing is campaign specific.

The tables fall into three layers, and the split is deliberate:

``rule_sections``
    The reference layer -- the book's bookmark outline with the prose under each
    heading. This is what full-text search reads, and it is what the GM quotes
    when a player asks "how does Dodge work?".

``rule_skills`` / ``rule_talents`` / ``rule_spells`` / ``rule_careers`` / ``rule_creatures``
    The data layer. The same content as the prose, but parsed into columns so it
    can be queried rather than grepped: "which careers advance Willpower?",
    "what is the CN of Shroud of Invisibility?". Attributes that the rules
    engine needs are real columns; everything else stays as description text.

``rule_tables`` / ``rule_table_rows``
    The random-table layer. Critical wounds, miscasts, hit locations and the
    like. Rows carry a parsed ``roll_min``/``roll_max`` span so the engine can
    resolve a d100 with an index lookup instead of parsing "01-10" at runtime;
    this is the difference between the GM computing a critical and inventing
    one.
"""
from __future__ import annotations

import sqlite3

from .module_schema import has_fts5


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS rulebooks (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    slug              TEXT UNIQUE NOT NULL,
    title             TEXT NOT NULL,
    system            TEXT DEFAULT 'WFRP 4E',
    source_file       TEXT DEFAULT '',
    source_sha256     TEXT DEFAULT '',
    page_count        INTEGER DEFAULT 0,
    extracted_at      TEXT DEFAULT '',
    extractor_version TEXT DEFAULT ''
);

-- Mirrors the PDF bookmark outline one-for-one so every paragraph has a home.
-- `kind` is inferred from position in the tree and lets a caller ask for just
-- the combat rules or just the careers without re-parsing prose.
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
    path         TEXT NOT NULL DEFAULT '',  -- "magic/magic-rules/casting"
    title        TEXT NOT NULL,
    body_md      TEXT DEFAULT '',
    page_start   INTEGER DEFAULT 0,
    page_end     INTEGER DEFAULT 0,
    word_count   INTEGER DEFAULT 0,
    FOREIGN KEY (rulebook_id) REFERENCES rulebooks (id)     ON DELETE CASCADE,
    FOREIGN KEY (parent_id)   REFERENCES rule_sections (id) ON DELETE CASCADE,
    FOREIGN KEY (chapter_id)  REFERENCES rule_sections (id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_rule_sections_book   ON rule_sections (rulebook_id, doc_order);
CREATE INDEX IF NOT EXISTS idx_rule_sections_parent ON rule_sections (parent_id);
CREATE INDEX IF NOT EXISTS idx_rule_sections_kind   ON rule_sections (rulebook_id, kind);
CREATE INDEX IF NOT EXISTS idx_rule_sections_slug   ON rule_sections (rulebook_id, slug);

-- `characteristic` is the default stat a test is made against, which is what
-- the engine needs to resolve "test Climb" without being told the attribute.
CREATE TABLE IF NOT EXISTS rule_skills (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    rulebook_id    INTEGER NOT NULL,
    section_id     INTEGER,
    slug           TEXT NOT NULL,
    name           TEXT NOT NULL,
    characteristic TEXT DEFAULT '',   -- ws|bs|s|t|i|ag|dex|int|wp|fel
    is_advanced    INTEGER DEFAULT 0, -- advanced skills cannot be used untrained
    is_grouped     INTEGER DEFAULT 0, -- takes a specialisation, e.g. Lore (Theology)
    specialisations_json TEXT DEFAULT '[]',
    description    TEXT DEFAULT '',
    page           INTEGER DEFAULT 0,
    FOREIGN KEY (rulebook_id) REFERENCES rulebooks (id)     ON DELETE CASCADE,
    FOREIGN KEY (section_id)  REFERENCES rule_sections (id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_rule_skills_book ON rule_skills (rulebook_id, slug);

CREATE TABLE IF NOT EXISTS rule_talents (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    rulebook_id INTEGER NOT NULL,
    section_id  INTEGER,
    slug        TEXT NOT NULL,
    name        TEXT NOT NULL,
    max_formula TEXT DEFAULT '',  -- "Toughness Bonus", "Initiative Bonus", "None"
    tests       TEXT DEFAULT '',  -- printed "Tests:" line, when present
    description TEXT DEFAULT '',
    page        INTEGER DEFAULT 0,
    FOREIGN KEY (rulebook_id) REFERENCES rulebooks (id)     ON DELETE CASCADE,
    FOREIGN KEY (section_id)  REFERENCES rule_sections (id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_rule_talents_book ON rule_talents (rulebook_id, slug);

-- `cn` is the Casting Number the caster must reach with accumulated SL, so it
-- must be numeric for the casting resolver. Petty spells are CN 0.
CREATE TABLE IF NOT EXISTS rule_spells (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    rulebook_id INTEGER NOT NULL,
    section_id  INTEGER,
    slug        TEXT NOT NULL,
    name        TEXT NOT NULL,
    lore        TEXT DEFAULT '',   -- petty|beasts|death|fire|...|necromancy
    kind        TEXT DEFAULT 'arcane',  -- petty|arcane|lore|blessing|miracle
    cn          INTEGER,
    range_text  TEXT DEFAULT '',
    target      TEXT DEFAULT '',
    duration    TEXT DEFAULT '',
    description TEXT DEFAULT '',
    page        INTEGER DEFAULT 0,
    FOREIGN KEY (rulebook_id) REFERENCES rulebooks (id)     ON DELETE CASCADE,
    FOREIGN KEY (section_id)  REFERENCES rule_sections (id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_rule_spells_book ON rule_spells (rulebook_id, lore, slug);

CREATE TABLE IF NOT EXISTS rule_careers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    rulebook_id INTEGER NOT NULL,
    section_id  INTEGER,
    slug        TEXT NOT NULL,
    name        TEXT NOT NULL,
    class       TEXT DEFAULT '',   -- Academic, Burgher, Courtier, ...
    species_json TEXT DEFAULT '[]',
    description TEXT DEFAULT '',
    page        INTEGER DEFAULT 0,
    FOREIGN KEY (rulebook_id) REFERENCES rulebooks (id)     ON DELETE CASCADE,
    FOREIGN KEY (section_id)  REFERENCES rule_sections (id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_rule_careers_book ON rule_careers (rulebook_id, slug);

-- One row per printed tier. `advances_json` is the list of characteristics the
-- tier may advance; in the PDF that is a row of dingbat glyphs aligned under a
-- header row, recovered by column geometry rather than by reading the glyph.
CREATE TABLE IF NOT EXISTS rule_career_tiers (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    career_id      INTEGER NOT NULL,
    tier           INTEGER NOT NULL,  -- 1-4
    name           TEXT NOT NULL,
    status_tier    TEXT DEFAULT '',   -- Brass|Silver|Gold
    status_standing INTEGER DEFAULT 0,
    advances_json  TEXT DEFAULT '[]',
    skills_json    TEXT DEFAULT '[]',
    talents_json   TEXT DEFAULT '[]',
    trappings_json TEXT DEFAULT '[]',
    page           INTEGER DEFAULT 0,
    UNIQUE (career_id, tier),
    FOREIGN KEY (career_id) REFERENCES rule_careers (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS rule_creatures (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    rulebook_id INTEGER NOT NULL,
    section_id  INTEGER,
    slug        TEXT NOT NULL,
    name        TEXT NOT NULL,
    category    TEXT DEFAULT '',   -- peoples|beasts|monstrous|greenskins|undead|chaos
    m INTEGER, ws INTEGER, bs INTEGER, s INTEGER, t INTEGER, i INTEGER,
    ag INTEGER, dex INTEGER, intl INTEGER, wp INTEGER, fel INTEGER, w INTEGER,
    traits_json          TEXT DEFAULT '[]',
    optional_traits_json TEXT DEFAULT '[]',
    skills_json          TEXT DEFAULT '[]',
    talents_json         TEXT DEFAULT '[]',
    description TEXT DEFAULT '',
    page        INTEGER DEFAULT 0,
    FOREIGN KEY (rulebook_id) REFERENCES rulebooks (id)     ON DELETE CASCADE,
    FOREIGN KEY (section_id)  REFERENCES rule_sections (id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_rule_creatures_book ON rule_creatures (rulebook_id, slug);

-- Conditions drive combat state, so they are first-class rather than prose.
CREATE TABLE IF NOT EXISTS rule_conditions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    rulebook_id  INTEGER NOT NULL,
    section_id   INTEGER,
    slug         TEXT NOT NULL,
    name         TEXT NOT NULL,
    is_stacking  INTEGER DEFAULT 1,
    description  TEXT DEFAULT '',
    page         INTEGER DEFAULT 0,
    FOREIGN KEY (rulebook_id) REFERENCES rulebooks (id)     ON DELETE CASCADE,
    FOREIGN KEY (section_id)  REFERENCES rule_sections (id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_rule_conditions_book ON rule_conditions (rulebook_id, slug);

-- `dice` records what the table is rolled on ("1d100", "1d10"), and `kind`
-- groups the tables the engine resolves automatically.
CREATE TABLE IF NOT EXISTS rule_tables (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    rulebook_id  INTEGER NOT NULL,
    section_id   INTEGER,
    slug         TEXT NOT NULL,
    title        TEXT NOT NULL,
    kind         TEXT DEFAULT 'reference',  -- critical|miscast|hit_location|fumble|reference
    dice         TEXT DEFAULT '',
    columns_json TEXT DEFAULT '[]',
    notes        TEXT DEFAULT '',
    page         INTEGER DEFAULT 0,
    FOREIGN KEY (rulebook_id) REFERENCES rulebooks (id)     ON DELETE CASCADE,
    FOREIGN KEY (section_id)  REFERENCES rule_sections (id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_rule_tables_book ON rule_tables (rulebook_id, kind, slug);

CREATE TABLE IF NOT EXISTS rule_table_rows (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    table_id   INTEGER NOT NULL,
    ordinal    INTEGER NOT NULL,
    roll_min   INTEGER,           -- NULL when the row is not roll-indexed
    roll_max   INTEGER,
    roll_label TEXT DEFAULT '',   -- as printed, e.g. "01-10", "96+"
    result     TEXT DEFAULT '',   -- the primary result cell
    detail     TEXT DEFAULT '',   -- remaining cells, joined
    cells_json TEXT DEFAULT '[]',
    FOREIGN KEY (table_id) REFERENCES rule_tables (id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_rule_table_rows ON rule_table_rows (table_id, ordinal);
CREATE INDEX IF NOT EXISTS idx_rule_table_roll ON rule_table_rows (table_id, roll_min, roll_max);
"""

# Retrieval index over both prose and data rows, so a single query can surface
# "Dodge" the skill and the paragraph that explains opposed Dodge tests.
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
    "rule_career_tiers",
    "rule_careers",
    "rule_conditions",
    "rule_creatures",
    "rule_spells",
    "rule_talents",
    "rule_skills",
    "rule_sections",
    "rulebooks",
]

# A column that only exists in the current shape of each table. An older
# database is rebuilt rather than migrated: every row is reproducible from the
# source PDF, so there is nothing to preserve.
_SHAPE_SENTINELS = {
    "rulebooks": "extractor_version",
    "rule_sections": "path",
    "rule_skills": "specialisations_json",
    "rule_talents": "max_formula",
    "rule_spells": "cn",
    "rule_careers": "species_json",
    "rule_career_tiers": "advances_json",
    "rule_creatures": "optional_traits_json",
    "rule_conditions": "is_stacking",
    "rule_tables": "dice",
    "rule_table_rows": "roll_min",
}


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
