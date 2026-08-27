"""Read access to extracted module content, optionally overlaid with campaign state.

This is the query layer the web app and the GM tools sit on. It reads the
``module_*`` content tables produced by :mod:`games.wfrp.extract.foundry_module`
and, when given a campaign, merges in that campaign's progress from
``campaign_*_state``.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from . import db


def _rows(conn, sql: str, *params) -> list[dict]:
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def _loads(value: Optional[str], default: Any) -> Any:
    try:
        return json.loads(value) if value else default
    except (TypeError, ValueError):
        return default


def _decode_profiles(profiles: list[dict]) -> list[dict]:
    for profile in profiles:
        for field in ("skills", "talents", "traits", "trappings", "spells"):
            profile[field] = _loads(profile.pop(f"{field}_json", None), [])
    return profiles


def list_modules() -> list[dict]:
    conn = db.get_connection()
    try:
        return _rows(
            conn,
            """
            SELECT m.*,
                   (SELECT COUNT(*) FROM module_sections s
                     WHERE s.module_id = m.id AND s.kind = 'chapter') AS chapter_count,
                   (SELECT COUNT(*) FROM module_npcs n
                     WHERE n.module_id = m.id) AS npc_count
              FROM modules m
             ORDER BY m.title
            """,
        )
    finally:
        conn.close()


def get_section_tree(module_id: int, conn=None) -> list[dict]:
    """The module's full outline as nested dicts, in document order."""
    owned = conn is None
    conn = conn or db.get_connection()
    try:
        flat = _rows(
            conn,
            "SELECT * FROM module_sections WHERE module_id = ? ORDER BY doc_order",
            module_id,
        )
        by_id = {section["id"]: section for section in flat}
        roots = []
        for section in flat:
            section["children"] = []
        for section in flat:
            parent = by_id.get(section["parent_id"])
            (parent["children"] if parent else roots).append(section)
        return roots
    finally:
        if owned:
            conn.close()


def get_npc(npc_id: int) -> Optional[dict]:
    """One NPC with their characteristic profiles decoded."""
    conn = db.get_connection()
    try:
        rows = _rows(conn, "SELECT * FROM module_npcs WHERE id = ?", npc_id)
        if not rows:
            return None
        npc = rows[0]
        npc["profiles"] = _decode_profiles(
            _rows(conn, "SELECT * FROM module_npc_profiles WHERE npc_id = ?", npc_id)
        )
        npc["appearances"] = _rows(
            conn,
            """
            SELECT a.*, s.title AS section_title, c.title AS chapter_title
              FROM module_npc_appearances a
              LEFT JOIN module_sections s ON s.id = a.section_id
              LEFT JOIN module_sections c ON c.id = a.chapter_id
             WHERE a.npc_id = ?
            """,
            npc_id,
        )
        return npc
    finally:
        conn.close()


def get_module(slug: str) -> Optional[dict]:
    """A module and all of its extracted content."""
    conn = db.get_connection()
    try:
        rows = _rows(conn, "SELECT * FROM modules WHERE slug = ?", slug)
        if not rows:
            return None
        module = rows[0]
        module_id = module["id"]
        module["theme"] = _loads(module.pop("theme_json", None), {})

        module["sections"] = get_section_tree(module_id, conn)
        module["chapters"] = _rows(
            conn,
            "SELECT * FROM module_sections WHERE module_id = ? AND kind = 'chapter'"
            " ORDER BY doc_order",
            module_id,
        )

        plots = _rows(
            conn,
            "SELECT * FROM module_plots WHERE module_id = ? ORDER BY chapter_id, plot_number",
            module_id,
        )
        events = _rows(
            conn,
            "SELECT * FROM module_events WHERE module_id = ?"
            " ORDER BY chapter_id, time_minutes IS NULL, time_minutes, ordinal",
            module_id,
        )
        npcs = _rows(
            conn, "SELECT * FROM module_npcs WHERE module_id = ? ORDER BY name", module_id
        )
        profiles = _decode_profiles(
            _rows(
                conn,
                "SELECT p.* FROM module_npc_profiles p JOIN module_npcs n ON n.id = p.npc_id"
                " WHERE n.module_id = ?",
                module_id,
            )
        )
        by_npc: dict[int, list[dict]] = {}
        for profile in profiles:
            by_npc.setdefault(profile["npc_id"], []).append(profile)
        for npc in npcs:
            npc["profiles"] = by_npc.get(npc["id"], [])

        chapter_of_section = {
            row["id"]: row["chapter_id"]
            for row in _rows(
                conn,
                "SELECT id, chapter_id FROM module_sections WHERE module_id = ?",
                module_id,
            )
        }
        for chapter in module["chapters"]:
            chapter["plots"] = [p for p in plots if p["chapter_id"] == chapter["id"]]
            chapter["events"] = [e for e in events if e["chapter_id"] == chapter["id"]]
            chapter["npcs"] = [
                n
                for n in npcs
                if chapter_of_section.get(n["section_id"]) == chapter["id"]
            ]

        module["plots"] = plots
        module["events"] = events
        module["npcs"] = npcs
        module["assets"] = _rows(
            conn,
            "SELECT * FROM module_assets WHERE module_id = ? ORDER BY page, id",
            module_id,
        )
        keys_by_asset: dict[int, list[dict]] = {}
        for key in _rows(
            conn,
            "SELECT k.* FROM module_map_keys k"
            "  JOIN module_assets a ON a.id = k.asset_id"
            " WHERE a.module_id = ?"
            " ORDER BY k.asset_id, CAST(k.key_label AS INTEGER), k.key_label",
            module_id,
        ):
            keys_by_asset.setdefault(key["asset_id"], []).append(key)
        for asset in module["assets"]:
            asset["keys"] = keys_by_asset.get(asset["id"], [])
        module["maps"] = [a for a in module["assets"] if a["kind"] == "map"]
        module["tables"] = [
            dict(
                table,
                columns=_loads(table.pop("columns_json", None), []),
                rows=_loads(table.pop("rows_json", None), []),
            )
            for table in _rows(
                conn,
                "SELECT * FROM module_tables WHERE module_id = ? ORDER BY page, id",
                module_id,
            )
        ]
        return module
    finally:
        conn.close()


def search_module(query: str, module_id: Optional[int] = None, limit: int = 20) -> list[dict]:
    """Full-text search across section prose and NPC entries."""
    conn = db.get_connection()
    try:
        sql = (
            "SELECT title, kind, page, section_id, npc_id,"
            "       snippet(module_search, 1, '[', ']', '...', 18) AS excerpt"
            "  FROM module_search WHERE module_search MATCH ?"
        )
        params: list[Any] = [query]
        if module_id is not None:
            sql += " AND module_id = ?"
            params.append(module_id)
        sql += " LIMIT ?"
        params.append(limit)
        return _rows(conn, sql, *params)
    except Exception:
        # FTS5 is unavailable on some SQLite builds; the caller can fall back.
        return []
    finally:
        conn.close()


def get_module_with_campaign_state(slug: str, campaign_id: int) -> Optional[dict]:
    """A module with one campaign's progress merged into it."""
    module = get_module(slug)
    if not module:
        return None

    conn = db.get_connection()
    try:
        section_state = {
            row["section_id"]: row
            for row in _rows(
                conn,
                "SELECT * FROM campaign_section_state WHERE campaign_id = ?",
                campaign_id,
            )
        }
        npc_state = {
            row["module_npc_id"]: row
            for row in _rows(
                conn, "SELECT * FROM campaign_npc_state WHERE campaign_id = ?", campaign_id
            )
        }
        event_state = {
            row["module_event_id"]: row
            for row in _rows(
                conn, "SELECT * FROM campaign_event_state WHERE campaign_id = ?", campaign_id
            )
        }
        overrides = {
            row["module_npc_id"]: row
            for row in _rows(
                conn,
                "SELECT id AS campaign_npc_id, module_npc_id, name, role_career"
                "  FROM npcs WHERE campaign_id = ? AND module_npc_id IS NOT NULL",
                campaign_id,
            )
        }
    finally:
        conn.close()

    default_section = {"status": "unvisited", "revealed": 0, "gm_notes": ""}

    def apply_sections(nodes: list[dict]) -> None:
        for node in nodes:
            node["campaign_state"] = section_state.get(node["id"], default_section)
            apply_sections(node.get("children", []))

    apply_sections(module["sections"])
    for chapter in module["chapters"]:
        chapter["campaign_state"] = section_state.get(chapter["id"], default_section)
    for event in module["events"]:
        event["campaign_state"] = event_state.get(event["id"], {"fired": 0, "gm_notes": ""})
    for npc in module["npcs"]:
        npc["campaign_state"] = npc_state.get(
            npc["id"], {"met": 0, "alive": 1, "gm_notes": ""}
        )
        if npc["id"] in overrides:
            npc["campaign_override"] = overrides[npc["id"]]

    return module


def set_section_state(
    campaign_id: int,
    section_id: int,
    status: Optional[str] = None,
    revealed: Optional[bool] = None,
    gm_notes: Optional[str] = None,
) -> None:
    """Record the party's progress through one section."""
    revealed_value = None if revealed is None else int(revealed)
    conn = db.get_connection()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO campaign_section_state (campaign_id, section_id)"
            " VALUES (?, ?)",
            (campaign_id, section_id),
        )
        conn.execute(
            """
            UPDATE campaign_section_state
               SET status     = COALESCE(?, status),
                   revealed   = COALESCE(?, revealed),
                   gm_notes   = COALESCE(?, gm_notes),
                   updated_at = datetime('now')
             WHERE campaign_id = ? AND section_id = ?
            """,
            (status, revealed_value, gm_notes, campaign_id, section_id),
        )
        conn.commit()
    finally:
        conn.close()


def set_event_fired(
    campaign_id: int, event_id: int, fired: bool = True, gm_notes: str = ""
) -> None:
    conn = db.get_connection()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO campaign_event_state (campaign_id, module_event_id)"
            " VALUES (?, ?)",
            (campaign_id, event_id),
        )
        conn.execute(
            """
            UPDATE campaign_event_state
               SET fired    = ?,
                   fired_at = datetime('now'),
                   gm_notes = CASE WHEN ? = '' THEN gm_notes ELSE ? END
             WHERE campaign_id = ? AND module_event_id = ?
            """,
            (int(fired), gm_notes, gm_notes, campaign_id, event_id),
        )
        conn.commit()
    finally:
        conn.close()


def set_npc_state(campaign_id: int, module_npc_id: int, **fields) -> None:
    """Update what a campaign knows about a module NPC."""
    allowed = {
        "met", "alive", "wounds_current", "disposition", "party_disposition", "gm_notes",
    }
    updates = {key: value for key, value in fields.items() if key in allowed}
    if not updates:
        return
    conn = db.get_connection()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO campaign_npc_state (campaign_id, module_npc_id)"
            " VALUES (?, ?)",
            (campaign_id, module_npc_id),
        )
        assignments = ", ".join(f"{key} = ?" for key in updates)
        conn.execute(
            f"UPDATE campaign_npc_state SET {assignments}, updated_at = datetime('now')"
            " WHERE campaign_id = ? AND module_npc_id = ?",
            (*updates.values(), campaign_id, module_npc_id),
        )
        conn.commit()
    finally:
        conn.close()
