"""Two-way character sync between Omega-7's web campaign app and Foundry VTT.

Design (confirmed with the user):
    * Direction: both ways.
    * Trigger: manual "Sync with Foundry" button per character (no polling).
    * Conflict resolution: Foundry always wins on any field present on both
      sides. Local values are only ever *pushed* to fill gaps (things the
      wizard added locally that the Foundry actor doesn't have yet), or to
      seed a brand-new actor the first time a character is linked.
    * Linking: match an existing Foundry actor by name; if none exists, create
      one and push the full local character onto it.

Field mapping was reverse-engineered against a live WFRP4e (system) actor via
``get-character`` / ``manage-actors`` (see FOUNDRY_VTT_BRIDGE.md history):

    characteristics.<KEY> = {initial, advances, modifier, value, bonus}
    wounds                = {value, max}
    status.fate           = {value: fate points}      (get-character: fate.fate)
    status.fortune        = {value: fortune points}    (get-character: fate.fortune)
    status.resilience     = {value}                    (get-character: resilience.resilience)
    status.resolve        = {value}                    (get-character: resilience.resolve)
    details.experience     = {total, spent}  <- NOTE: writing "total" pops a
        blocking "Enter Reason for XP Change" dialog in a GM's browser, so we
        only ever *push* XP once, at actor creation, and otherwise only *pull*
        it (read-only) on every subsequent sync.
    money                  = embedded items of type "money" (Gold Crown /
        Silver Shilling / Brass Penny), quantity.value each.
    skills/talents/trappings/career = embedded items; new ones are added via
        wfrp4e-add-items (never removed — that's a gap-fill, not an override).
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from . import db, foundry

log = logging.getLogger(__name__)

_CHAR_KEYS = ["WS", "BS", "S", "T", "I", "Ag", "Dex", "Int", "WP", "Fel"]
_MCP_CHAR_KEYS = {
    "WS": "ws", "BS": "bs", "S": "s", "T": "t", "I": "i",
    "Ag": "ag", "Dex": "dex", "Int": "int", "WP": "wp", "Fel": "fel",
}
_MONEY_ITEM_NAMES = {"gc": "Gold Crown", "ss": "Silver Shilling", "bp": "Brass Penny"}


class SyncError(RuntimeError):
    pass


def _call(mcp_name: str, payload: Optional[dict] = None) -> Any:
    result = foundry.call_raw(mcp_name, payload or {})
    if isinstance(result, dict) and "error" in result:
        raise SyncError(result["error"])
    return result


def find_actor_id_by_name(name: str) -> Optional[str]:
    listing = foundry.call_raw("list-characters", {})
    if isinstance(listing, dict) and "error" in listing:
        raise SyncError(listing["error"])
    for entry in (listing or {}).get("characters", []):
        if str(entry.get("name", "")).strip().lower() == name.strip().lower():
            return entry.get("id")
    return None


def _get_actor(actor_id: str) -> dict:
    return _call("get-character", {"identifier": actor_id})


def create_actor(name: str) -> str:
    result = _call("manage-actors", {"action": "create", "actors": [{"name": name, "type": "character"}]})
    created = result.get("created") or []
    if not created:
        raise SyncError(f"Foundry did not report a created actor for {name!r}")
    return created[0]["id"]


def _pull_into_local(char_dict: dict, actor: dict) -> dict:
    """Return a copy of char_dict overwritten with Foundry's authoritative fields."""
    c = dict(char_dict)
    stats = actor.get("stats", {})

    chars = stats.get("characteristics", {})
    if chars:
        local_chars = dict(c.get("characteristics", {}))
        for key in _CHAR_KEYS:
            fchar = chars.get(key)
            if not fchar:
                continue
            local_chars[key] = {
                "initial": fchar.get("initial", 0),
                "advances": fchar.get("advances", 0),
                "total": fchar.get("value", fchar.get("initial", 0)),
            }
        c["characteristics"] = local_chars

    wounds = stats.get("wounds")
    if wounds:
        c["wounds"] = {"current": wounds.get("value", 0), "max": wounds.get("max", 0)}

    fate = stats.get("fate")
    if fate:
        c["fate"] = {"current": fate.get("fate", 0), "total": fate.get("fate", 0)}
        c["fortune"] = {"current": fate.get("fortune", 0), "total": fate.get("fortune", 0)}

    resilience = stats.get("resilience")
    if resilience:
        c["resilience"] = resilience.get("resilience", 0)
        c["resolve"] = resilience.get("resolve", 0)

    move = stats.get("movement")
    if move:
        c["move"] = {"base": move.get("value", 4), "walk": move.get("walk", 8), "run": move.get("run", 16)}

    xp = stats.get("experience")
    if xp:
        c["xp"] = {"total": xp.get("total", 0), "spent": xp.get("spent", 0), "current": xp.get("current", 0)}

    # Money lives as embedded items of type "money" on the actor, not in `stats`.
    money = dict(c.get("money", {}))
    for item in actor.get("items", []):
        if item.get("type") == "money":
            name = item.get("name", "")
            qty = (item.get("quantity") or {}).get("value", 0)
            for code, item_name in _MONEY_ITEM_NAMES.items():
                if name == item_name:
                    money[code] = qty
    c["money"] = money

    # Skills: Foundry's per-skill advances are authoritative for any skill
    # both sides already know about; skills only known locally are untouched
    # (they get gap-filled onto the actor separately, not overwritten here).
    foundry_skill_advances = {s["name"]: s.get("advances", 0) for s in stats.get("skills", [])}
    if foundry_skill_advances:
        local_skills = list(c.get("skills", []))
        seen = set()
        for sk in local_skills:
            nm = sk.get("name") if isinstance(sk, dict) else sk
            if nm in foundry_skill_advances:
                if isinstance(sk, dict):
                    sk["advances"] = foundry_skill_advances[nm]
                seen.add(nm)
        for nm, adv in foundry_skill_advances.items():
            if nm not in seen:
                local_skills.append({"name": nm, "advances": adv})
        c["skills"] = local_skills

    # Talents/trappings/career: take Foundry's embedded items as the
    # authoritative list where present, since "Foundry wins".
    talents = [i["name"] for i in actor.get("items", []) if i.get("type") == "talent"]
    if talents:
        c["talents"] = talents
    trappings = [i["name"] for i in actor.get("items", []) if i.get("type") == "trapping"]
    if trappings:
        c["trappings"] = trappings
    careers = [i for i in actor.get("items", []) if i.get("type") == "career"]
    current_career = next((i for i in careers if i.get("system", {}).get("current")), None)
    if current_career:
        c["career"] = current_career.get("name", c.get("career"))

    basic_info = actor.get("basicInfo", {})
    klass = basic_info.get("class", {}).get("value")
    if klass:
        c["class"] = klass

    return c


def _push_characteristics_wounds(actor_id: str, char: dict) -> None:
    chars_payload = {}
    for key in _CHAR_KEYS:
        block = char.get("characteristics", {}).get(key)
        if not isinstance(block, dict):
            continue
        chars_payload[_MCP_CHAR_KEYS[key]] = {
            "initial": block.get("initial", 0),
            "advances": block.get("advances", 0),
        }
    wounds = char.get("wounds", {})
    move = char.get("move", {})
    payload = {"actor": actor_id}
    if chars_payload:
        payload["characteristics"] = chars_payload
    if wounds:
        payload["wounds"] = {"value": wounds.get("current", 0), "max": wounds.get("max", 0)}
    if move:
        payload["movement"] = move.get("base", 4)
    if len(payload) > 1:
        _call("wfrp4e-update-actor", payload)


def _push_status(actor_id: str, char: dict, include_xp: bool = False) -> None:
    """Push fate/fortune/resilience/resolve (and, only on creation, XP) to Foundry.

    XP is deliberately excluded by default: writing system.details.experience
    on an existing actor pops a blocking "Enter Reason for XP Change" dialog
    in whichever GM browser session is open, which the bridge has no way to
    answer. Only pass include_xp=True right after creating a brand-new actor.
    """
    fate = char.get("fate", {})
    fortune = char.get("fortune", {})
    resilience = char.get("resilience")
    resolve = char.get("resolve")
    status: dict = {}
    if isinstance(fate, dict) and "total" in fate:
        status["fate"] = {"value": fate.get("total", 0)}
    if isinstance(fortune, dict) and "total" in fortune:
        status["fortune"] = {"value": fortune.get("total", 0)}
    if resilience is not None:
        val = resilience.get("total", 0) if isinstance(resilience, dict) else resilience
        status["resilience"] = {"value": val}
    if resolve is not None:
        val = resolve.get("current", 0) if isinstance(resolve, dict) else resolve
        status["resolve"] = {"value": val}

    system: dict = {}
    if status:
        system["status"] = status
    if include_xp:
        xp = char.get("xp", {})
        if isinstance(xp, dict):
            system["details"] = {"experience": {"total": xp.get("total", 0), "spent": xp.get("spent", 0)}}
    if system:
        _call("manage-actors", {"action": "update", "updates": [{"id": actor_id, "system": system}]})


def _push_money(actor_id: str, char: dict) -> None:
    money = char.get("money", {})
    if not isinstance(money, dict) or not money:
        return
    items = []
    for code, item_name in _MONEY_ITEM_NAMES.items():
        if code in money:
            items.append({"name": item_name, "type": "money", "quantity": money.get(code, 0)})
    if items:
        _call("wfrp4e-add-items", {"actor": actor_id, "items": items})


def _gap_fill_items(actor_id: str, char: dict, actor: dict) -> list[str]:
    """Add local skills/talents/trappings/career the actor doesn't have yet.

    This never removes or overwrites anything already on the actor — it only
    fills gaps, so it's consistent with "Foundry wins" on genuine overlaps.
    """
    existing_names = {i.get("name") for i in actor.get("items", [])}
    to_add = []
    added_labels = []

    for sk in char.get("skills", []):
        name = sk.get("name") if isinstance(sk, dict) else sk
        if name and name not in existing_names:
            advances = sk.get("advances", 0) if isinstance(sk, dict) else 0
            to_add.append({"name": name, "type": "skill", "advances": advances})
            added_labels.append(f"skill: {name}")

    for name in char.get("talents", []):
        nm = name.get("name") if isinstance(name, dict) else name
        if nm and nm not in existing_names:
            to_add.append({"name": nm, "type": "talent"})
            added_labels.append(f"talent: {nm}")

    for name in char.get("trappings", []):
        nm = name.get("name") if isinstance(name, dict) else name
        if nm and nm not in existing_names:
            to_add.append({"name": nm, "type": "trapping"})
            added_labels.append(f"trapping: {nm}")

    career = char.get("career")
    if career and career not in existing_names:
        to_add.append({"name": career, "type": "career", "setCurrent": True})
        added_labels.append(f"career: {career}")

    if to_add:
        _call("wfrp4e-add-items", {"actor": actor_id, "items": to_add})
    return added_labels


def sync_character(slug: str, char_dict: dict) -> dict:
    """Run a full two-way sync for one character. Returns a summary dict.

    ``char_dict`` should be the already-normalized local character (see
    ``games.wfrp.campaign.normalize_character``); ``char_dict["id"]`` must be
    the local characters.id row so we can persist the link and updated data.
    """
    if not foundry.ENABLED:
        raise SyncError("Foundry bridge is not enabled (FOUNDRY_MCP_ENABLED is not set).")

    char_id = char_dict.get("id")
    if not char_id:
        raise SyncError("Character has no local id to sync.")

    name = char_dict.get("name") or "Unnamed Adventurer"
    row = db.get_character_row(slug, int(char_id)) or {}
    actor_id = row.get("foundry_actor_id") or None

    created_new = False
    if not actor_id:
        actor_id = find_actor_id_by_name(name)
    if not actor_id:
        actor_id = create_actor(name)
        created_new = True

    if created_new:
        # Nothing exists on the Foundry side yet — push everything, including
        # XP once (accepting the one-time "reason" dialog on the GM's screen).
        _push_characteristics_wounds(actor_id, char_dict)
        _push_status(actor_id, char_dict, include_xp=True)
        _push_money(actor_id, char_dict)
        actor_now = _get_actor(actor_id)
        added = _gap_fill_items(actor_id, char_dict, actor_now)
        merged = char_dict
        summary = {
            "actor_id": actor_id,
            "created_actor": True,
            "pulled_fields": [],
            "pushed_fields": ["characteristics", "wounds", "movement", "fate", "resilience", "xp", "money"],
            "added_items": added,
        }
    else:
        actor_now = _get_actor(actor_id)
        merged = _pull_into_local(char_dict, actor_now)
        added = _gap_fill_items(actor_id, merged, actor_now)
        summary = {
            "actor_id": actor_id,
            "created_actor": False,
            "pulled_fields": [
                "characteristics", "wounds", "fate", "resilience", "movement",
                "xp", "money", "skills", "talents", "trappings", "career",
            ],
            "pushed_fields": [],
            "added_items": added,
        }

    merged["id"] = char_id
    db.upsert_character_record(slug, merged)
    db.set_foundry_link(slug, int(char_id), actor_id)
    summary["character"] = merged
    return summary
