"""Connection handling for the Necromunda rules database.

The rules are reference data rebuilt from a source PDF, not campaign state, so
they live in their own file: dropping it loses nothing that re-running the
extractor does not restore.
"""
from __future__ import annotations

import pathlib
import sqlite3

from core import config
from . import rules_schema

_DB_NAME = "necromunda_rules.db"


def db_path() -> pathlib.Path:
    """Absolute path to the rules database inside USER_DATA_DIR."""
    return config.data_path(_DB_NAME)


def connect(create: bool = True) -> sqlite3.Connection:
    """Open the rules database, creating the schema when asked.

    ``create=False`` is for readers: they must not bring a database into
    existence just by asking a question, so a missing file stays missing and the
    caller reports the library as not installed.
    """
    path = db_path()
    if not create and not path.exists():
        raise FileNotFoundError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    if create:
        rules_schema.init_rules_schema(conn)
        conn.commit()
    return conn


def is_installed() -> bool:
    """True when a rulebook has actually been ingested."""
    try:
        conn = connect(create=False)
    except (FileNotFoundError, sqlite3.Error):
        return False
    try:
        row = conn.execute("SELECT COUNT(*) FROM rulebooks").fetchone()
        return bool(row and row[0])
    except sqlite3.Error:
        return False
    finally:
        conn.close()
