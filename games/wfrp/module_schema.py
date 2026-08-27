"""Schema for published WFRP adventure modules and the per-campaign state laid over them.

The tables here are split into two halves that must not be confused:

``module_*``
    Immutable *content*, mechanically extracted from a source PDF. Every row can
    be reproduced by re-running the extractor, so the whole set is safe to drop
    and rebuild at any time. Nothing here is campaign specific.

``campaign_module_*``
    Mutable *state* for one campaign playing that content — what the party has
    discovered, which NPCs they have met, which events have fired. These rows
    reference module content by id but are never rewritten by the extractor, so
    re-extracting a module does not destroy a campaign in progress.

The section tree is the backbone. ``module_sections`` mirrors the PDF's bookmark
hierarchy one-for-one, which means every paragraph of the book has somewhere to
live — including front matter and appendices that do not fit a
chapter/plot/event shape.
"""
from __future__ import annotations

import sqlite3


SCHEMA_SQL = """
-- ── module content ───────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS modules (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    slug              TEXT UNIQUE NOT NULL,
    title             TEXT NOT NULL,
    subtitle          TEXT DEFAULT '',
    description       TEXT DEFAULT '',
    system            TEXT DEFAULT 'WFRP 4E',
    source_file       TEXT DEFAULT '',
    source_sha256     TEXT DEFAULT '',
    page_count        INTEGER DEFAULT 0,
    cover_asset_id    INTEGER,
    extracted_at      TEXT DEFAULT '',
    extractor_version TEXT DEFAULT '',
    theme_json        TEXT DEFAULT ''   -- page textures and rules lifted from the PDF
);

-- Self-referencing tree mirroring the PDF bookmark outline. `kind` is inferred
-- from the heading text and its position so the web app and the GM can ask for
-- "the plots of chapter 3" without re-parsing prose.
CREATE TABLE IF NOT EXISTS module_sections (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    module_id     INTEGER NOT NULL,
    parent_id     INTEGER,
    chapter_id    INTEGER,           -- nearest ancestor of kind 'chapter'
    level         INTEGER NOT NULL,  -- 1-5, from the bookmark outline
    ordinal       INTEGER NOT NULL,  -- document order among siblings
    doc_order     INTEGER NOT NULL,  -- absolute document order
    kind          TEXT NOT NULL DEFAULT 'section',
    slug          TEXT NOT NULL DEFAULT '',
    title         TEXT NOT NULL,
    body_md       TEXT DEFAULT '',
    summary       TEXT DEFAULT '',
    page_start    INTEGER DEFAULT 0,
    page_end      INTEGER DEFAULT 0,
    word_count    INTEGER DEFAULT 0,
    accent        TEXT DEFAULT '',   -- chapter tab colour, sampled from the book
    FOREIGN KEY (module_id)  REFERENCES modules (id)         ON DELETE CASCADE,
    FOREIGN KEY (parent_id)  REFERENCES module_sections (id) ON DELETE CASCADE,
    FOREIGN KEY (chapter_id) REFERENCES module_sections (id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_sections_module  ON module_sections (module_id, doc_order);
CREATE INDEX IF NOT EXISTS idx_sections_parent  ON module_sections (parent_id);
CREATE INDEX IF NOT EXISTS idx_sections_chapter ON module_sections (chapter_id, kind);
CREATE INDEX IF NOT EXISTS idx_sections_kind    ON module_sections (module_id, kind);

CREATE TABLE IF NOT EXISTS module_plots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    module_id   INTEGER NOT NULL,
    chapter_id  INTEGER,
    section_id  INTEGER,
    plot_number INTEGER DEFAULT 0,
    title       TEXT NOT NULL,
    description TEXT DEFAULT '',
    page        INTEGER DEFAULT 0,
    FOREIGN KEY (module_id)  REFERENCES modules (id)         ON DELETE CASCADE,
    FOREIGN KEY (chapter_id) REFERENCES module_sections (id) ON DELETE CASCADE,
    FOREIGN KEY (section_id) REFERENCES module_sections (id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_plots_chapter ON module_plots (chapter_id, plot_number);

-- `time_minutes` normalises labels like "9:30 p.m." / "12:15 a.m." / "Midnight"
-- onto a single monotonic in-fiction timeline so events sort correctly across
-- the midnight rollover, which the previous string sort could not do.
CREATE TABLE IF NOT EXISTS module_events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    module_id    INTEGER NOT NULL,
    chapter_id   INTEGER,
    section_id   INTEGER,
    plot_id      INTEGER,
    ordinal      INTEGER DEFAULT 0,
    time_label   TEXT NOT NULL DEFAULT '',
    time_minutes INTEGER,
    description  TEXT DEFAULT '',
    page         INTEGER DEFAULT 0,
    FOREIGN KEY (module_id)  REFERENCES modules (id)         ON DELETE CASCADE,
    FOREIGN KEY (chapter_id) REFERENCES module_sections (id) ON DELETE CASCADE,
    FOREIGN KEY (section_id) REFERENCES module_sections (id) ON DELETE SET NULL,
    FOREIGN KEY (plot_id)    REFERENCES module_plots (id)    ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_events_chapter ON module_events (chapter_id, ordinal);

CREATE TABLE IF NOT EXISTS module_npcs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    module_id     INTEGER NOT NULL,
    section_id    INTEGER,
    slug          TEXT NOT NULL DEFAULT '',
    name          TEXT NOT NULL,
    title         TEXT DEFAULT '',   -- e.g. "Noble Lord (Gold 7)" from the stat header
    faction       TEXT DEFAULT '',   -- owning npc_group section, e.g. "The Gravin's Party"
    description   TEXT DEFAULT '',
    is_group      INTEGER DEFAULT 0, -- "Coachmen and Boatmen" style collective entries
    portrait_id   INTEGER,
    page          INTEGER DEFAULT 0,
    FOREIGN KEY (module_id)   REFERENCES modules (id)         ON DELETE CASCADE,
    FOREIGN KEY (section_id)  REFERENCES module_sections (id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_npcs_module ON module_npcs (module_id, name);

-- One row per printed characteristic profile. Kept as real columns rather than a
-- JSON blob so combat tooling can read them directly and so the data is
-- queryable ("who in this chapter has WS above 60?").
CREATE TABLE IF NOT EXISTS module_npc_profiles (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    npc_id         INTEGER NOT NULL,
    label          TEXT DEFAULT '',
    m              INTEGER, ws INTEGER, bs  INTEGER, s   INTEGER,
    t              INTEGER, i  INTEGER, ag  INTEGER, dex INTEGER,
    intl           INTEGER, wp INTEGER, fel INTEGER, w   INTEGER,
    skills_json    TEXT DEFAULT '[]',  -- [{"name": "Bribery", "value": 76}, ...]
    talents_json   TEXT DEFAULT '[]',
    traits_json    TEXT DEFAULT '[]',
    trappings_json TEXT DEFAULT '[]',
    spells_json    TEXT DEFAULT '[]',
    raw_extras     TEXT DEFAULT '',
    page           INTEGER DEFAULT 0,
    FOREIGN KEY (npc_id) REFERENCES module_npcs (id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_profiles_npc ON module_npc_profiles (npc_id);

-- NPCs recur across chapters with different roles (Glimbrin Oddsocks appears in
-- three of the five adventures), so the relationship is many-to-many.
CREATE TABLE IF NOT EXISTS module_npc_appearances (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    npc_id     INTEGER NOT NULL,
    section_id INTEGER NOT NULL,
    chapter_id INTEGER,
    role       TEXT DEFAULT '',
    notes      TEXT DEFAULT '',
    UNIQUE (npc_id, section_id),
    FOREIGN KEY (npc_id)     REFERENCES module_npcs (id)     ON DELETE CASCADE,
    FOREIGN KEY (section_id) REFERENCES module_sections (id) ON DELETE CASCADE,
    FOREIGN KEY (chapter_id) REFERENCES module_sections (id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_appearances_chapter ON module_npc_appearances (chapter_id);

-- `kind` lets the renderer ask for just the maps, or just the portraits, and
-- lets the extractor discard page backgrounds and border furniture rather than
-- dumping every embedded xref to disk.
CREATE TABLE IF NOT EXISTS module_assets (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    module_id  INTEGER NOT NULL,
    section_id INTEGER,
    chapter_id INTEGER,
    npc_id     INTEGER,
    kind       TEXT NOT NULL DEFAULT 'art',  -- map|art|portrait|diagram|cover
    path       TEXT NOT NULL,
    caption    TEXT DEFAULT '',
    page       INTEGER DEFAULT 0,
    bbox_json  TEXT DEFAULT '',
    width      INTEGER DEFAULT 0,
    height     INTEGER DEFAULT 0,
    sha256     TEXT DEFAULT '',
    FOREIGN KEY (module_id)  REFERENCES modules (id)         ON DELETE CASCADE,
    FOREIGN KEY (section_id) REFERENCES module_sections (id) ON DELETE SET NULL,
    FOREIGN KEY (chapter_id) REFERENCES module_sections (id) ON DELETE SET NULL,
    FOREIGN KEY (npc_id)     REFERENCES module_npcs (id)     ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_assets_module ON module_assets (module_id, kind);
CREATE INDEX IF NOT EXISTS idx_assets_page   ON module_assets (module_id, page);

-- Numbered callouts printed on the maps ("21 Hall", "24 Dormitory"), so the web
-- app can overlay clickable hotspots and the GM can answer "what is room 24?".
CREATE TABLE IF NOT EXISTS module_map_keys (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id   INTEGER NOT NULL,
    key_label  TEXT NOT NULL,
    label      TEXT NOT NULL,
    detail     TEXT DEFAULT '',
    section_id INTEGER,
    FOREIGN KEY (asset_id)   REFERENCES module_assets (id)   ON DELETE CASCADE,
    FOREIGN KEY (section_id) REFERENCES module_sections (id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_mapkeys_asset ON module_map_keys (asset_id);

CREATE TABLE IF NOT EXISTS module_tables (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    module_id  INTEGER NOT NULL,
    section_id INTEGER,
    chapter_id INTEGER,
    title      TEXT DEFAULT '',
    kind       TEXT DEFAULT 'rules',
    columns_json TEXT DEFAULT '[]',
    rows_json    TEXT DEFAULT '[]',
    page       INTEGER DEFAULT 0,
    FOREIGN KEY (module_id)  REFERENCES modules (id)         ON DELETE CASCADE,
    FOREIGN KEY (section_id) REFERENCES module_sections (id) ON DELETE SET NULL,
    FOREIGN KEY (chapter_id) REFERENCES module_sections (id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_tables_module ON module_tables (module_id);

"""

# Installed only when a campaigns table exists: module content is useful on its
# own (the web app reads it without a campaign, and extraction can target a
# scratch database), but these tables key off campaigns and cannot exist alone.
CAMPAIGN_SCHEMA_SQL = """
-- ── per-campaign state laid over module content ──────────────────────────────

CREATE TABLE IF NOT EXISTS campaign_modules (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id  INTEGER NOT NULL,
    module_id    INTEGER NOT NULL,
    current_section_id INTEGER,
    started_at   TEXT DEFAULT '',
    UNIQUE (campaign_id, module_id),
    FOREIGN KEY (campaign_id) REFERENCES campaigns (id) ON DELETE CASCADE,
    FOREIGN KEY (module_id)   REFERENCES modules (id)   ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS campaign_section_state (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL,
    section_id  INTEGER NOT NULL,
    status      TEXT DEFAULT 'unvisited',  -- unvisited|active|complete|skipped
    revealed    INTEGER DEFAULT 0,
    gm_notes    TEXT DEFAULT '',
    updated_at  TEXT DEFAULT '',
    UNIQUE (campaign_id, section_id),
    FOREIGN KEY (campaign_id) REFERENCES campaigns (id)        ON DELETE CASCADE,
    FOREIGN KEY (section_id)  REFERENCES module_sections (id)  ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS campaign_npc_state (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id      INTEGER NOT NULL,
    module_npc_id    INTEGER NOT NULL,
    met              INTEGER DEFAULT 0,
    alive            INTEGER DEFAULT 1,
    wounds_current   INTEGER,
    disposition      TEXT DEFAULT '',
    party_disposition TEXT DEFAULT '',
    gm_notes         TEXT DEFAULT '',
    updated_at       TEXT DEFAULT '',
    UNIQUE (campaign_id, module_npc_id),
    FOREIGN KEY (campaign_id)   REFERENCES campaigns (id)   ON DELETE CASCADE,
    FOREIGN KEY (module_npc_id) REFERENCES module_npcs (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS campaign_event_state (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id      INTEGER NOT NULL,
    module_event_id  INTEGER NOT NULL,
    fired            INTEGER DEFAULT 0,
    fired_at         TEXT DEFAULT '',
    gm_notes         TEXT DEFAULT '',
    UNIQUE (campaign_id, module_event_id),
    FOREIGN KEY (campaign_id)     REFERENCES campaigns (id)     ON DELETE CASCADE,
    FOREIGN KEY (module_event_id) REFERENCES module_events (id) ON DELETE CASCADE
);
"""

# Retrieval index. Kept separate because FTS5 may be unavailable on a stripped
# SQLite build, in which case the rest of the schema must still install.
FTS_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS module_search USING fts5 (
    title,
    body,
    kind UNINDEXED,
    module_id UNINDEXED,
    section_id UNINDEXED,
    npc_id UNINDEXED,
    page UNINDEXED,
    tokenize = 'unicode61'
);
"""

# Tables holding extracted content, ordered so children drop before parents.
CONTENT_TABLES = [
    "module_map_keys",
    "module_assets",
    "module_tables",
    "module_npc_appearances",
    "module_npc_profiles",
    "module_events",
    "module_plots",
    "module_npcs",
    "module_sections",
    "modules",
]

# Superseded by module_sections / campaign_section_state.
LEGACY_TABLES = [
    "adventure_nodes",
    "adventure_state",
    "campaign_module_state",
    "module_images",
    "module_chapters",
    "module_catalog",
]


def has_fts5(conn: sqlite3.Connection) -> bool:
    try:
        conn.execute("CREATE VIRTUAL TABLE temp._fts5_probe USING fts5(x);")
        conn.execute("DROP TABLE temp._fts5_probe;")
        return True
    except sqlite3.Error:
        return False


# A column that only exists in the current shape of each content table. If an
# older database already has the table under a previous shape, it is dropped and
# rebuilt rather than migrated — the rows are extracted content and are always
# reproducible from the source PDF.
_SHAPE_SENTINELS = {
    "modules": "theme_json",
    "module_sections": "accent",
    "module_plots": "plot_number",
    "module_events": "time_minutes",
    "module_npcs": "faction",
    "module_npc_profiles": "intl",
    "module_npc_appearances": "role",
    "module_assets": "kind",
    "module_map_keys": "key_label",
    "module_tables": "rows_json",
}


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def drop_stale_content_tables(conn: sqlite3.Connection) -> list[str]:
    """Drop content tables left over from an incompatible earlier schema."""
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


def init_module_schema(conn: sqlite3.Connection) -> None:
    """Create module content and campaign state tables if absent."""
    # Dropping a stale table fires its foreign-key actions, and those cascades
    # walk into sibling tables whose own references may already be gone -- a
    # half-migrated database raises "no such table" from a table we never
    # touched. Enforcement is off for the teardown and restored afterwards.
    # The pragma is a no-op inside a transaction, so any open one is closed
    # first.
    previous = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    conn.commit()
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        drop_legacy_tables(conn)
        drop_stale_content_tables(conn)
        conn.commit()
    finally:
        conn.execute(f"PRAGMA foreign_keys = {'ON' if previous else 'OFF'}")
    conn.executescript(SCHEMA_SQL)
    if _table_exists(conn, "campaigns"):
        conn.executescript(CAMPAIGN_SCHEMA_SQL)
    if has_fts5(conn):
        conn.executescript(FTS_SQL)


def drop_legacy_tables(conn: sqlite3.Connection) -> list[str]:
    """Drop the superseded module/adventure tables. Returns what was removed."""
    dropped = []
    for table in LEGACY_TABLES:
        if _table_exists(conn, table):
            conn.execute(f"DROP TABLE {table}")
            dropped.append(table)
    return dropped


def reset_module_content(conn: sqlite3.Connection, module_slug: str | None = None) -> None:
    """Clear extracted content so a module can be re-ingested from source.

    Campaign state tables are deliberately untouched; their rows cascade only if
    the module content they reference is deleted.
    """
    if module_slug is None:
        for table in CONTENT_TABLES:
            conn.execute(f"DELETE FROM {table}")
        if has_fts5(conn):
            conn.execute("DELETE FROM module_search")
        return

    row = conn.execute("SELECT id FROM modules WHERE slug = ?", (module_slug,)).fetchone()
    if not row:
        return
    module_id = row[0]
    # Every content table cascades from modules, so one delete is enough.
    conn.execute("DELETE FROM modules WHERE id = ?", (module_id,))
    if has_fts5(conn):
        conn.execute("DELETE FROM module_search WHERE module_id = ?", (module_id,))
