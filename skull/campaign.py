"""Campaign memory manager for Omega-7's RPG Gamemaster mode.

Each named campaign (e.g. "The Enemy Within") is persisted as a JSON file:
    <data_dir>/campaigns/<slug>.json

The "active" campaign is tracked in memory for the current process; it resets
on restart (intentional — the GM asks at session start which campaign to resume).

Public API
----------
list_campaigns()          -> list[dict]
new_campaign(name)        -> dict           (creates and sets active)
load_campaign(name)       -> dict | None    (sets active)
get_active_campaign()     -> dict | None
set_active_campaign(name) -> dict | None
save_campaign(data)       -> None           (write active campaign to disk)
update_field(key, value)  -> None           (update + autosave)
add_session_note(note)    -> None           (append + autosave)
"""
from __future__ import annotations

import json
import os
import pathlib
import re
from datetime import datetime
from typing import Any, Optional


# ── storage ─────────────────────────────────────────────────────────────────

def _campaigns_dir() -> pathlib.Path:
    data_dir = pathlib.Path(
        os.getenv("OMEGA7_DATA_DIR", "~/.config/omega7")
    ).expanduser()
    d = data_dir / "campaigns"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _slug(name: str) -> str:
    """URL-safe slug from a campaign name."""
    s = name.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:60] or "unnamed"


def _campaign_path(name: str) -> pathlib.Path:
    return _campaigns_dir() / f"{_slug(name)}.json"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ── in-process active campaign ───────────────────────────────────────────────

_active_campaign: Optional[dict] = None


def get_active_campaign() -> Optional[dict]:
    """Return the in-memory active campaign dict, or None if none is set."""
    return _active_campaign


def set_active_campaign(name: str) -> Optional[dict]:
    """Load a campaign by name and make it the active campaign."""
    global _active_campaign
    data = load_campaign(name, set_active=False)
    _active_campaign = data
    return data


# ── CRUD ─────────────────────────────────────────────────────────────────────

def list_campaigns() -> list:
    """Return a list of all saved campaigns (summary dicts, not full data)."""
    results = []
    for f in sorted(_campaigns_dir().glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            results.append({
                "name": data.get("name", f.stem),
                "slug": f.stem,
                "adventure": data.get("adventure", ""),
                "last_modified": data.get("last_modified", ""),
                "characters": [c.get("name", "?") for c in data.get("characters", [])],
            })
        except Exception:
            continue
    return results


def load_campaign(name: str, set_active: bool = True) -> Optional[dict]:
    """Load a campaign from disk by name. Returns None if not found."""
    global _active_campaign
    p = _campaign_path(name)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if set_active:
            _active_campaign = data
        return data
    except Exception as e:
        print(f"[campaign] Failed to load {p}: {e}")
        return None


def new_campaign(name: str, adventure: str = "", characters: Optional[list] = None) -> dict:
    """Create a new campaign (or overwrite an existing one) and set it as active."""
    global _active_campaign
    slug = _slug(name)
    now = _now()
    data: dict[str, Any] = {
        "name": name,
        "slug": slug,
        "created": now,
        "last_modified": now,
        "adventure": adventure or name,
        "characters": characters or [],
        "current_location": "",
        "current_scene": "",
        "active_npcs": [],
        "session_notes": [],
    }
    _save_to_disk(data)
    _active_campaign = data
    return data


def save_campaign(data: Optional[dict] = None) -> None:
    """Persist the given campaign dict (or the active campaign) to disk."""
    if data is None:
        data = _active_campaign
    if data is None:
        return
    data["last_modified"] = _now()
    _save_to_disk(data)


def _save_to_disk(data: dict) -> None:
    p = _campaign_path(data["name"])
    try:
        p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[campaign] Saved campaign '{data['name']}' → {p}")
    except Exception as e:
        print(f"[campaign] Save error: {e}")


def update_field(key: str, value: Any) -> None:
    """Update a top-level field in the active campaign and autosave."""
    global _active_campaign
    if _active_campaign is None:
        print("[campaign] No active campaign — cannot update field.")
        return
    _active_campaign[key] = value
    save_campaign()


def add_session_note(note: str) -> None:
    """Append a timestamped session note to the active campaign and autosave."""
    global _active_campaign
    if _active_campaign is None:
        print("[campaign] No active campaign — cannot add note.")
        return
    entry = {"timestamp": _now(), "note": note.strip()}
    _active_campaign.setdefault("session_notes", []).append(entry)
    save_campaign()


# ── helpers for brain.py tools ───────────────────────────────────────────────

def campaign_summary(data: dict) -> str:
    """Return a concise text summary of a campaign suitable for Omega-7 to read aloud."""
    lines = [f"Campaign: {data.get('name', '?')}"]
    if data.get("adventure"):
        lines.append(f"Adventure: {data['adventure']}")
    chars = data.get("characters", [])
    if chars:
        for c in chars:
            name = c.get("name", "Unknown")
            career = c.get("career", "")
            race = c.get("race", "")
            wounds = c.get("wounds", {})
            fate = c.get("fate", {})
            w_str = f"Wounds {wounds.get('current', '?')}/{wounds.get('max', '?')}" if wounds else ""
            f_str = f"Fate {fate.get('current', '?')}/{fate.get('total', '?')}" if fate else ""
            parts = [p for p in [race, career, w_str, f_str] if p]
            lines.append(f"  Character: {name}" + (f" ({', '.join(parts)})" if parts else ""))
    if data.get("current_location"):
        lines.append(f"Location: {data['current_location']}")
    if data.get("current_scene"):
        lines.append(f"Scene: {data['current_scene']}")
    notes = data.get("session_notes", [])
    if notes:
        last = notes[-1]
        lines.append(f"Last note ({last.get('timestamp', '')[:10]}): {last.get('note', '')}")
    return "\n".join(lines)
