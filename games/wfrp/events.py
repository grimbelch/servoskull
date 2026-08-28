"""The campaign chronicle: game sessions and an append-only event log.

Everything that happens at the table is a row in ``game_events`` — scenes
opened, blows landed, treasure looted, NPCs met, quests turned. Events are
never updated or deleted; the campaign's history is exactly the order they
were written in. ``game_sessions`` groups events into sittings and carries
the recap and XP award produced when a session closes, which is what lets
Omega-7 open the next session with "when last we left our heroes...".

The tables live in the same campaign database as everything else
(``db.get_connection``); the schema is created from ``db.init_db``.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Optional

from . import db
from .module_schema import has_fts5

# The vocabulary of things that happen in a game. Unknown kinds are stored
# as given rather than rejected — the log must never lose an event over a
# label — but tools advertise this list so the model stays consistent.
EVENT_KINDS = (
    "scene",       # a new scene or location is framed
    "narration",   # notable GM narration worth remembering
    "roll",        # a dramatic test result
    "combat",      # combat started, ended, or turned
    "damage",      # wounds dealt or healed
    "condition",   # a condition gained or removed
    "death",       # a character or notable NPC dies
    "loot",        # treasure, trappings or money change hands
    "xp",          # experience awarded
    "quest",       # a quest is taken, advanced or resolved
    "npc",         # an NPC is met or a relationship shifts
    "location",    # the party travels somewhere
    "corruption",  # corruption or mutation
    "fate",        # fate or fortune spent or burnt
    "milestone",   # a major plot beat
    "note",        # anything else
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS game_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL,
    number INTEGER NOT NULL,
    title TEXT DEFAULT '',
    in_game_date TEXT DEFAULT '',
    started_at TEXT NOT NULL,
    ended_at TEXT,
    recap TEXT DEFAULT '',
    xp_awarded INTEGER DEFAULT 0,
    UNIQUE (campaign_id, number),
    FOREIGN KEY (campaign_id) REFERENCES campaigns (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS game_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL,
    session_id INTEGER,
    at TEXT NOT NULL,
    in_game_date TEXT DEFAULT '',
    kind TEXT NOT NULL,
    summary TEXT NOT NULL,
    detail TEXT DEFAULT '',
    actor TEXT DEFAULT '',
    data_json TEXT DEFAULT '{}',
    FOREIGN KEY (campaign_id) REFERENCES campaigns (id) ON DELETE CASCADE,
    FOREIGN KEY (session_id) REFERENCES game_sessions (id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_game_events_campaign
    ON game_events (campaign_id, id);
CREATE INDEX IF NOT EXISTS idx_game_events_session
    ON game_events (session_id);
CREATE INDEX IF NOT EXISTS idx_game_events_kind
    ON game_events (campaign_id, kind);
"""

_FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS game_events_fts USING fts5 (
    summary, detail, actor,
    content='game_events', content_rowid='id'
);
CREATE TRIGGER IF NOT EXISTS game_events_ai AFTER INSERT ON game_events BEGIN
    INSERT INTO game_events_fts (rowid, summary, detail, actor)
    VALUES (new.id, new.summary, new.detail, new.actor);
END;
CREATE TRIGGER IF NOT EXISTS game_events_ad AFTER DELETE ON game_events BEGIN
    INSERT INTO game_events_fts (game_events_fts, rowid, summary, detail, actor)
    VALUES ('delete', old.id, old.summary, old.detail, old.actor);
END;
"""


def init_events_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    if has_fts5(conn):
        conn.executescript(_FTS_SCHEMA)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    conn = db.get_connection()
    init_events_schema(conn)
    return conn


def _campaign_id(conn: sqlite3.Connection, campaign: Any = None) -> Optional[int]:
    """Resolve a campaign reference — id, slug, or None for the active one."""
    if isinstance(campaign, int):
        return campaign
    if isinstance(campaign, str) and campaign:
        row = conn.execute(
            "SELECT id FROM campaigns WHERE slug = ? OR name = ?",
            (campaign, campaign)).fetchone()
        return row["id"] if row else None
    from . import campaign as _campaign
    active = _campaign.get_active_campaign()
    if not active:
        return None
    row = conn.execute("SELECT id FROM campaigns WHERE slug = ?",
                       (active.get("slug"),)).fetchone()
    return row["id"] if row else None


def _session_dict(row: sqlite3.Row) -> dict:
    return {k: row[k] for k in row.keys()}


def current_session(campaign: Any = None) -> Optional[dict]:
    """The open (started, not yet ended) session, if any."""
    conn = _connect()
    try:
        cid = _campaign_id(conn, campaign)
        if cid is None:
            return None
        row = conn.execute(
            "SELECT * FROM game_sessions WHERE campaign_id = ? AND ended_at IS NULL "
            "ORDER BY number DESC LIMIT 1", (cid,)).fetchone()
        return _session_dict(row) if row else None
    finally:
        conn.close()


def log_event(kind: str, summary: str, detail: str = "", actor: str = "",
              data: Optional[dict] = None, in_game_date: str = "",
              campaign: Any = None) -> Optional[int]:
    """Append one event to the chronicle. Returns the event id.

    Attaches to the open session when there is one; between sessions the
    event is still recorded, just unattached (downtime, bookkeeping).
    """
    conn = _connect()
    try:
        cid = _campaign_id(conn, campaign)
        if cid is None:
            return None
        sess = conn.execute(
            "SELECT id, in_game_date FROM game_sessions "
            "WHERE campaign_id = ? AND ended_at IS NULL "
            "ORDER BY number DESC LIMIT 1", (cid,)).fetchone()
        cur = conn.execute(
            "INSERT INTO game_events (campaign_id, session_id, at, in_game_date,"
            " kind, summary, detail, actor, data_json)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (cid, sess["id"] if sess else None, _now(),
             in_game_date or (sess["in_game_date"] if sess else ""),
             (kind or "note").strip().lower(), summary.strip(), detail.strip(),
             actor.strip(), json.dumps(data or {})))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def start_session(campaign: Any = None, title: str = "",
                  in_game_date: str = "") -> dict:
    """Open a new session, or resume the one already open.

    Returns the session plus a recap: the previous session's stored recap
    (or one distilled from its events) and anything logged since it ended.
    """
    conn = _connect()
    try:
        cid = _campaign_id(conn, campaign)
        if cid is None:
            return {"error": "No active campaign. Call start_campaign first."}
        open_row = conn.execute(
            "SELECT * FROM game_sessions WHERE campaign_id = ? AND ended_at IS NULL "
            "ORDER BY number DESC LIMIT 1", (cid,)).fetchone()
        if open_row:
            return {"session": _session_dict(open_row), "resumed": True,
                    "recap": _recap_text(conn, cid)}
        recap = _recap_text(conn, cid)
        number = (conn.execute(
            "SELECT COALESCE(MAX(number), 0) FROM game_sessions WHERE campaign_id = ?",
            (cid,)).fetchone()[0]) + 1
        if not in_game_date:
            prev = conn.execute(
                "SELECT in_game_date FROM game_sessions WHERE campaign_id = ? "
                "ORDER BY number DESC LIMIT 1", (cid,)).fetchone()
            in_game_date = prev["in_game_date"] if prev else ""
        cur = conn.execute(
            "INSERT INTO game_sessions (campaign_id, number, title, in_game_date,"
            " started_at) VALUES (?, ?, ?, ?, ?)",
            (cid, number, title.strip(), in_game_date, _now()))
        conn.commit()
        row = conn.execute("SELECT * FROM game_sessions WHERE id = ?",
                           (cur.lastrowid,)).fetchone()
        return {"session": _session_dict(row), "resumed": False, "recap": recap}
    finally:
        conn.close()


def end_session(campaign: Any = None, recap: str = "", xp: int = 0) -> dict:
    """Close the open session, store its recap, and award XP to the party.

    An empty recap is distilled from the session's own events, so a session
    always leaves something behind for the next "previously, on...".
    """
    conn = _connect()
    try:
        cid = _campaign_id(conn, campaign)
        if cid is None:
            return {"error": "No active campaign."}
        row = conn.execute(
            "SELECT * FROM game_sessions WHERE campaign_id = ? AND ended_at IS NULL "
            "ORDER BY number DESC LIMIT 1", (cid,)).fetchone()
        if not row:
            return {"error": "No session is open."}
        recap = recap.strip() or _distill_recap(conn, row["id"])
        xp = max(0, int(xp or 0))
        conn.execute(
            "UPDATE game_sessions SET ended_at = ?, recap = ?, xp_awarded = ? "
            "WHERE id = ?", (_now(), recap, xp, row["id"]))
        awarded_to = []
        if xp:
            chars = conn.execute(
                "SELECT id, name FROM characters WHERE campaign_id = ?",
                (cid,)).fetchall()
            for ch in chars:
                conn.execute(
                    "UPDATE characters SET xp_curr = xp_curr + ?, xp_tot = xp_tot + ? "
                    "WHERE id = ?", (xp, xp, ch["id"]))
                awarded_to.append(ch["name"])
            conn.execute(
                "INSERT INTO game_events (campaign_id, session_id, at, in_game_date,"
                " kind, summary, detail, actor, data_json)"
                " VALUES (?, ?, ?, ?, 'xp', ?, '', '', ?)",
                (cid, row["id"], _now(), row["in_game_date"],
                 f"{xp} XP awarded to {', '.join(awarded_to)}",
                 json.dumps({"xp": xp, "characters": awarded_to})))
        conn.commit()
        done = conn.execute("SELECT * FROM game_sessions WHERE id = ?",
                            (row["id"],)).fetchone()
        out = _session_dict(done)
        out["xp_awarded_to"] = awarded_to
        return out
    finally:
        conn.close()


def _distill_recap(conn: sqlite3.Connection, session_id: int) -> str:
    """A recap built from the session's own log when the GM didn't write one."""
    memorable = ("scene", "milestone", "quest", "death", "combat", "loot",
                 "npc", "location", "corruption", "fate")
    rows = conn.execute(
        "SELECT kind, summary FROM game_events WHERE session_id = ? ORDER BY id",
        (session_id,)).fetchall()
    beats = [r["summary"] for r in rows if r["kind"] in memorable]
    if not beats:
        beats = [r["summary"] for r in rows][:8]
    return "\n".join(f"- {b}" for b in beats[:12])


def _recap_text(conn: sqlite3.Connection, cid: int) -> str:
    """What to read out when a session opens: last recap + interim events."""
    last = conn.execute(
        "SELECT * FROM game_sessions WHERE campaign_id = ? AND ended_at IS NOT NULL "
        "ORDER BY number DESC LIMIT 1", (cid,)).fetchone()
    if not last:
        return ""
    parts = []
    recap = last["recap"] or _distill_recap(conn, last["id"])
    if recap:
        title = f" — {last['title']}" if last["title"] else ""
        parts.append(f"Session {last['number']}{title}:\n{recap}")
    interim = conn.execute(
        "SELECT kind, summary FROM game_events WHERE campaign_id = ? "
        "AND session_id IS NULL AND at > ? ORDER BY id", (cid, last["ended_at"])
    ).fetchall()
    if interim:
        parts.append("Since then:\n" + "\n".join(
            f"- {r['summary']}" for r in interim[:8]))
    return "\n\n".join(parts)


def last_recap(campaign: Any = None) -> str:
    conn = _connect()
    try:
        cid = _campaign_id(conn, campaign)
        return _recap_text(conn, cid) if cid is not None else ""
    finally:
        conn.close()


def chronicle(campaign: Any = None, session_number: Optional[int] = None,
              kinds: Optional[list] = None, limit: int = 50) -> list:
    """Read the log, newest first (a specific session reads oldest first)."""
    conn = _connect()
    try:
        cid = _campaign_id(conn, campaign)
        if cid is None:
            return []
        sql = ("SELECT e.*, s.number AS session_number FROM game_events e "
               "LEFT JOIN game_sessions s ON s.id = e.session_id "
               "WHERE e.campaign_id = ?")
        args: list = [cid]
        if session_number is not None:
            sql += " AND s.number = ?"
            args.append(int(session_number))
        if kinds:
            sql += " AND e.kind IN (%s)" % ",".join("?" * len(kinds))
            args.extend(k.lower() for k in kinds)
        sql += " ORDER BY e.id %s LIMIT ?" % (
            "ASC" if session_number is not None else "DESC")
        args.append(max(1, int(limit)))
        return [dict(r) for r in conn.execute(sql, args).fetchall()]
    finally:
        conn.close()


def search_events(query: str, campaign: Any = None, limit: int = 20) -> list:
    """Full-text search the chronicle ("when did we meet Gravin Roteisen?")."""
    conn = _connect()
    try:
        cid = _campaign_id(conn, campaign)
        if cid is None:
            return []
        if has_fts5(conn):
            fts = " ".join(f'"{t}"' for t in query.split())
            rows = conn.execute(
                "SELECT e.*, s.number AS session_number FROM game_events_fts f "
                "JOIN game_events e ON e.id = f.rowid "
                "LEFT JOIN game_sessions s ON s.id = e.session_id "
                "WHERE game_events_fts MATCH ? AND e.campaign_id = ? "
                "ORDER BY rank LIMIT ?", (fts, cid, max(1, int(limit)))).fetchall()
        else:
            like = f"%{query}%"
            rows = conn.execute(
                "SELECT e.*, s.number AS session_number FROM game_events e "
                "LEFT JOIN game_sessions s ON s.id = e.session_id "
                "WHERE e.campaign_id = ? AND (e.summary LIKE ? OR e.detail LIKE ?"
                " OR e.actor LIKE ?) ORDER BY e.id DESC LIMIT ?",
                (cid, like, like, like, max(1, int(limit)))).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def list_sessions(campaign: Any = None, limit: int = 20) -> list:
    conn = _connect()
    try:
        cid = _campaign_id(conn, campaign)
        if cid is None:
            return []
        rows = conn.execute(
            "SELECT s.*, COUNT(e.id) AS event_count FROM game_sessions s "
            "LEFT JOIN game_events e ON e.session_id = s.id "
            "WHERE s.campaign_id = ? GROUP BY s.id "
            "ORDER BY s.number DESC LIMIT ?", (cid, max(1, int(limit)))).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def try_log(kind: str, summary: str, **kwargs: Any) -> None:
    """Best-effort logging for hooks inside other systems (combat, campaign).

    The game must never crash because the chronicle could not be written.
    """
    try:
        log_event(kind, summary, **kwargs)
    except Exception:
        pass
