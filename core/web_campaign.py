"""Campaign Web Management Module for Omega-7.

Handles all Campaign Dashboard routes, character sheet edits, NPC/Timeline updates,
and WFRP 4E Core Rulebook Page Spread HTML rendering.
"""

from __future__ import annotations
import json
from typing import Any
from games.wfrp import campaign, db, modules_db


def dispatch_request(server_handler: Any, path: str, method: str) -> bool:
    """Dispatch incoming HTTP requests for campaign features.
    
    Returns True if handled, False otherwise.
    """
    path_clean = path.split("?")[0].rstrip("/")
    
    if method == "GET":
        if path_clean == "/api/campaign":
            _handle_campaign_get(server_handler)
            return True
        elif path_clean == "/api/campaign/armour_catalog":
            server_handler._send_json({"ok": True, "armour_catalog": db.get_armour_catalog()})
            return True
        elif path_clean == "/api/campaign/weapons_catalog":
            server_handler._send_json({"ok": True, "weapons_catalog": db.get_weapons_catalog()})
            return True
        elif path_clean == "/api/campaign/hirelings_catalog":
            server_handler._send_json({"ok": True, "hirelings_catalog": db.get_hirelings_catalog()})
            return True
        elif path_clean == "/api/campaign/trappings_catalog":
            server_handler._send_json({"ok": True, "trappings_catalog": db.get_trappings_catalog()})
            return True
        elif path_clean == "/api/modules":
            server_handler._send_json({"ok": True, "modules": modules_db.list_modules()})
            return True
        elif path_clean.startswith("/api/modules/"):
            slug = path_clean.split("/")[-1]
            mod = modules_db.get_module(slug)
            if mod:
                server_handler._send_json({"ok": True, "module": mod})
            else:
                server_handler._send_json({"ok": False, "error": "Module not found"}, 404)
            return True
        elif path_clean.startswith("/api/campaign/module/"):
            slug = path_clean.split("/")[-1]
            active = campaign.get_active_campaign()
            if not active:
                server_handler._send_json({"ok": False, "error": "No active campaign"}, 400)
                return True
            mod = modules_db.get_module_with_campaign_state(slug, active["id"])
            if mod:
                server_handler._send_json({"ok": True, "module": mod})
            else:
                server_handler._send_json({"ok": False, "error": "Module not found"}, 404)
            return True

    elif method == "POST":
        routes = {
            "/api/campaign/load": _handle_campaign_load,
            "/api/campaign/new": _handle_campaign_new,
            "/api/campaign/update": _handle_campaign_update,
            "/api/campaign/character/upsert": _handle_campaign_character_upsert,
            "/api/campaign/character/delete": _handle_campaign_character_delete,
            "/api/campaign/roll_char": _handle_campaign_roll_char,
            "/api/campaign/npc/add": _handle_campaign_npc_add,
            "/api/campaign/npc/upsert": _handle_campaign_npc_upsert,
            "/api/campaign/npc/delete": _handle_campaign_npc_delete,
            "/api/campaign/location/upsert": _handle_campaign_location_upsert,
            "/api/campaign/location/delete": _handle_campaign_location_delete,
            "/api/campaign/quest/upsert": _handle_campaign_quest_upsert,
            "/api/campaign/quest/delete": _handle_campaign_quest_delete,
            "/api/campaign/timeline/add": _handle_campaign_timeline_add,
            "/api/campaign/module/state": _handle_campaign_module_state_update,
        }
        fn = routes.get(path_clean)
        if fn:
            fn(server_handler)
            return True

    return False


def _handle_campaign_get(server_handler: Any) -> None:
    try:
        c_list = campaign.list_campaigns()
        # Re-read rather than trust the cache: the skull's voice loop and the
        # web UI both write to the same database from different code paths.
        active = campaign.reload_active() or campaign.get_active_campaign()
        if not active and c_list:
            first_name = c_list[0].get("name") or c_list[0].get("slug")
            if first_name:
                active = campaign.load_campaign(first_name, set_active=True)
        server_handler._send_json({"ok": True, "active_campaign": active, "campaigns": c_list})
    except Exception as e:
        server_handler._send_json({"ok": False, "error": str(e)}, 500)


def _handle_campaign_load(server_handler: Any) -> None:
    try:
        data = _read_json(server_handler)
        name = data.get("name", "").strip()
        c = campaign.load_campaign(name, set_active=True)
        if not c:
            server_handler._send_json({"ok": False, "error": f"Campaign '{name}' not found"}, 404)
            return
        server_handler._send_json({"ok": True, "active_campaign": c, "campaigns": campaign.list_campaigns()})
    except Exception as e:
        server_handler._send_json({"ok": False, "error": str(e)}, 500)


def _handle_campaign_new(server_handler: Any) -> None:
    try:
        data = _read_json(server_handler)
        name = data.get("name", "").strip()
        adv = data.get("adventure", "").strip()
        if not name:
            server_handler._send_json({"ok": False, "error": "Campaign name required"}, 400)
            return
        c = campaign.new_campaign(name, adventure=adv)
        server_handler._send_json({"ok": True, "active_campaign": c, "campaigns": campaign.list_campaigns()})
    except Exception as e:
        server_handler._send_json({"ok": False, "error": str(e)}, 500)


def _handle_campaign_update(server_handler: Any) -> None:
    try:
        data = _read_json(server_handler)
        active = campaign.get_active_campaign()
        if not active:
            server_handler._send_json({"ok": False, "error": "No active campaign"}, 400)
            return
        for k in ("name", "adventure", "current_location", "current_scene", "party_ambition_short", "party_ambition_long", "notes"):
            if k in data:
                campaign.update_field(k, data[k])
        _send_active(server_handler)
    except Exception as e:
        server_handler._send_json({"ok": False, "error": str(e)}, 500)


def _handle_campaign_character_upsert(server_handler: Any) -> None:
    try:
        char_dict = _read_json(server_handler)
        active = campaign.get_active_campaign()
        if not active:
            server_handler._send_json({"ok": False, "error": "No active campaign"}, 400)
            return
        campaign.upsert_character(char_dict)
        _send_active(server_handler)
    except Exception as e:
        server_handler._send_json({"ok": False, "error": str(e)}, 500)


def _handle_campaign_character_delete(server_handler: Any) -> None:
    try:
        data = _read_json(server_handler)
        char_identifier = data.get("id") or data.get("name", "").strip()
        active = campaign.get_active_campaign()
        if not active:
            server_handler._send_json({"ok": False, "error": "No active campaign"}, 400)
            return
        if char_identifier:
            campaign.delete_character(char_identifier)
        _send_active(server_handler)
    except Exception as e:
        server_handler._send_json({"ok": False, "error": str(e)}, 500)


def _handle_campaign_roll_char(server_handler: Any) -> None:
    try:
        data = _read_json(server_handler)
        race = data.get("race", "Human")
        c_block = campaign.roll_characteristics(race)
        server_handler._send_json({"ok": True, "race": race, "characteristics": c_block, "character_block": c_block})
    except Exception as e:
        server_handler._send_json({"ok": False, "error": str(e)}, 500)


def _handle_campaign_npc_add(server_handler: Any) -> None:
    try:
        data = _read_json(server_handler)
        active = campaign.get_active_campaign()
        if not active:
            server_handler._send_json({"ok": False, "error": "No active campaign"}, 400)
            return
        slug = active.get("slug", "shadows-over-reikland")
        res = db.add_npc(slug, data.get("name", "NPC"), data.get("role_career", ""), data.get("disposition", "Neutral"), data.get("secrets_lore", ""), data.get("notes", ""))
        _send_active(server_handler, npc=res)
    except Exception as e:
        server_handler._send_json({"ok": False, "error": str(e)}, 500)


def _handle_campaign_timeline_add(server_handler: Any) -> None:
    try:
        data = _read_json(server_handler)
        active = campaign.get_active_campaign()
        if not active:
            server_handler._send_json({"ok": False, "error": "No active campaign"}, 400)
            return
        slug = active.get("slug", "shadows-over-reikland")
        db.add_timeline_event(slug, data.get("event_summary", ""), data.get("in_game_date", ""))
        _send_active(server_handler)
    except Exception as e:
        server_handler._send_json({"ok": False, "error": str(e)}, 500)


def _send_active(server_handler: Any, **extra: Any) -> None:
    """Reply with the campaign as it now stands on disk.

    Writes go straight to SQLite while `campaign` keeps the active campaign
    cached in memory, so the cache has to be re-read after every mutation or
    the caller is handed a snapshot that predates its own change.
    """
    payload = {"ok": True, "active_campaign": campaign.reload_active()}
    payload.update(extra)
    server_handler._send_json(payload)


def _read_json(server_handler: Any) -> dict:
    content_length = int(server_handler.headers.get("Content-Length", 0))
    raw = server_handler.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
    return json.loads(raw)


def _handle_campaign_npc_upsert(server_handler: Any) -> None:
    try:
        data = _read_json(server_handler)
        active = campaign.get_active_campaign()
        if not active:
            server_handler._send_json({"ok": False, "error": "No active campaign"}, 400)
            return
        slug = active.get("slug", "shadows-over-reikland")
        res = db.upsert_npc(slug, data)
        _send_active(server_handler)
    except Exception as e:
        server_handler._send_json({"ok": False, "error": str(e)}, 500)


def _handle_campaign_npc_delete(server_handler: Any) -> None:
    try:
        data = _read_json(server_handler)
        nid = data.get("id")
        active = campaign.get_active_campaign()
        if not active:
            server_handler._send_json({"ok": False, "error": "No active campaign"}, 400)
            return
        slug = active.get("slug", "shadows-over-reikland")
        if nid:
            db.delete_npc(slug, int(nid))
        _send_active(server_handler)
    except Exception as e:
        server_handler._send_json({"ok": False, "error": str(e)}, 500)


def _handle_campaign_location_upsert(server_handler: Any) -> None:
    try:
        data = _read_json(server_handler)
        active = campaign.get_active_campaign()
        if not active:
            server_handler._send_json({"ok": False, "error": "No active campaign"}, 400)
            return
        slug = active.get("slug", "shadows-over-reikland")
        res = db.upsert_location(slug, data)
        _send_active(server_handler)
    except Exception as e:
        server_handler._send_json({"ok": False, "error": str(e)}, 500)


def _handle_campaign_location_delete(server_handler: Any) -> None:
    try:
        data = _read_json(server_handler)
        lid = data.get("id")
        active = campaign.get_active_campaign()
        if not active:
            server_handler._send_json({"ok": False, "error": "No active campaign"}, 400)
            return
        slug = active.get("slug", "shadows-over-reikland")
        if lid:
            db.delete_location(slug, int(lid))
        _send_active(server_handler)
    except Exception as e:
        server_handler._send_json({"ok": False, "error": str(e)}, 500)


def _handle_campaign_quest_upsert(server_handler: Any) -> None:
    try:
        data = _read_json(server_handler)
        active = campaign.get_active_campaign()
        if not active:
            server_handler._send_json({"ok": False, "error": "No active campaign"}, 400)
            return
        slug = active.get("slug", "shadows-over-reikland")
        res = db.upsert_quest(slug, data)
        _send_active(server_handler)
    except Exception as e:
        server_handler._send_json({"ok": False, "error": str(e)}, 500)


def _handle_campaign_quest_delete(server_handler: Any) -> None:
    try:
        data = _read_json(server_handler)
        qid = data.get("id")
        active = campaign.get_active_campaign()
        if not active:
            server_handler._send_json({"ok": False, "error": "No active campaign"}, 400)
            return
        slug = active.get("slug", "shadows-over-reikland")
        if qid:
            db.delete_quest(slug, int(qid))
        _send_active(server_handler)
    except Exception as e:
        server_handler._send_json({"ok": False, "error": str(e)}, 500)

def _handle_campaign_module_state_update(server_handler: Any) -> None:
    try:
        data = _read_json(server_handler)
        active = campaign.get_active_campaign()
        if not active:
            server_handler._send_json({"ok": False, "error": "No active campaign"}, 400)
            return

        entity_type = data.get("entity_type")
        entity_id = data.get("entity_id")
        status = data.get("status")
        gm_notes = data.get("gm_notes")

        if not entity_type or not entity_id:
            server_handler._send_json({"ok": False, "error": "entity_type and entity_id required"}, 400)
            return

        # Chapters, rooms and plots are all sections in the module tree, so they
        # share one state table; events are tracked separately as fired or not.
        if entity_type == "event":
            modules_db.set_event_fired(
                active["id"], int(entity_id),
                fired=str(status).lower() in {"complete", "fired", "done", "true"},
                gm_notes=gm_notes or "",
            )
        elif entity_type == "npc":
            modules_db.set_npc_state(active["id"], int(entity_id), gm_notes=gm_notes or "")
        else:
            modules_db.set_section_state(
                active["id"], int(entity_id), status=status, gm_notes=gm_notes
            )
        server_handler._send_json({"ok": True})
    except Exception as e:
        server_handler._send_json({"ok": False, "error": str(e)}, 500)
