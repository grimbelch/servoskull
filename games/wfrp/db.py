"""SQLite Campaign Database Engine for Omega-7's WFRP 4E System.

Provides relational storage, auto-migration from JSON campaign files, deterministic entity lookups,
and prompt-context helpers for:
- Campaigns & Meta
- Player Characters
- Locations & Old World Sites
- Dramatis Personae (NPCs)
- Quests & Encounters
- Timeline Logs & History
- Party Inventory & Treasury
"""

from __future__ import annotations
import sqlite3
import json
import os
import pathlib
import datetime
import re
from typing import Any, Optional, Dict, List

from . import module_schema as _module_schema

_DB_PATH: Optional[pathlib.Path] = None


def get_db_path() -> pathlib.Path:
    global _DB_PATH
    if _DB_PATH is not None:
        return _DB_PATH

    data_dir = pathlib.Path(
        os.getenv("OMEGA7_DATA_DIR", "~/.config/omega7")
    ).expanduser()
    campaigns_dir = data_dir / "campaigns"
    campaigns_dir.mkdir(parents=True, exist_ok=True)
    _DB_PATH = campaigns_dir / "skull_campaigns.db"
    return _DB_PATH


def get_connection() -> sqlite3.Connection:
    db_path = get_db_path()
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db() -> None:
    """Initialize SQLite database tables if they do not exist."""
    conn = get_connection()
    with conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS hirelings_catalog (
                name TEXT PRIMARY KEY,
                quick_job_cost TEXT,
                daily_cost TEXT,
                weekly_cost TEXT,
                notes TEXT
            );
        ''')
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS campaigns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                slug TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                adventure TEXT DEFAULT '',
                current_location TEXT DEFAULT 'The Reikland',
                current_scene TEXT DEFAULT '',
                party_ambition_short TEXT DEFAULT '',
                party_ambition_long TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS characters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                species TEXT DEFAULT 'Human',
                class_name TEXT DEFAULT 'Academics',
                career TEXT DEFAULT 'Scholar',
                career_level TEXT DEFAULT '1',
                career_path TEXT DEFAULT '',
                status TEXT DEFAULT 'Brass 3',
                age INTEGER,
                height TEXT DEFAULT '',
                hair_color TEXT DEFAULT '',
                eye_color TEXT DEFAULT '',
                doomed TEXT DEFAULT '',
                star_sign TEXT DEFAULT '',
                motivation TEXT DEFAULT '',
                wounds_curr INTEGER DEFAULT 10,
                wounds_max INTEGER DEFAULT 10,
                hardy_advances INTEGER DEFAULT 0,
                fate_curr INTEGER DEFAULT 3,
                fate_tot INTEGER DEFAULT 3,
                fortune_curr INTEGER DEFAULT 3,
                resilience_tot INTEGER DEFAULT 0,
                resolve_curr INTEGER DEFAULT 0,
                move_base INTEGER DEFAULT 4,
                move_walk INTEGER DEFAULT 8,
                move_run INTEGER DEFAULT 16,
                xp_curr INTEGER DEFAULT 0,
                xp_spent INTEGER DEFAULT 0,
                xp_tot INTEGER DEFAULT 0,
                sin INTEGER DEFAULT 0,
                corruption_curr INTEGER DEFAULT 0,
                corruption_max INTEGER DEFAULT 6,
                characteristics_json TEXT DEFAULT '{}',
                basic_skill_advances_json TEXT DEFAULT '{}',
                skills_json TEXT DEFAULT '[]',
                talents_json TEXT DEFAULT '[]',
                trappings_json TEXT DEFAULT '[]',
                weapons_json TEXT DEFAULT '[]',
                armour_json TEXT DEFAULT '{}',
                encumbrance_json TEXT DEFAULT '{}',
                money_json TEXT DEFAULT '{}',
                psychology_json TEXT DEFAULT '{}',
                spells_json TEXT DEFAULT '[]',
                ambitions_json TEXT DEFAULT '{}',
                ten_questions_json TEXT DEFAULT '{}',
                FOREIGN KEY (campaign_id) REFERENCES campaigns (id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS locations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                type TEXT DEFAULT 'City',
                region TEXT DEFAULT 'Reikland',
                description TEXT DEFAULT '',
                controlling_faction TEXT DEFAULT '',
                danger_level TEXT DEFAULT 'Low',
                visited INTEGER DEFAULT 1,
                history TEXT DEFAULT '',
                FOREIGN KEY (campaign_id) REFERENCES campaigns (id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS npcs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id INTEGER NOT NULL,
                location_id INTEGER,
                name TEXT NOT NULL,
                role_career TEXT DEFAULT '',
                species TEXT DEFAULT 'Human',
                disposition TEXT DEFAULT 'Neutral',
                status TEXT DEFAULT 'Alive',
                secrets_lore TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                motivations_goals TEXT DEFAULT '',
                party_disposition TEXT DEFAULT 'Neutral',
                FOREIGN KEY (campaign_id) REFERENCES campaigns (id) ON DELETE CASCADE,
                FOREIGN KEY (location_id) REFERENCES locations (id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS npc_character_relations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                npc_id INTEGER NOT NULL,
                character_id INTEGER NOT NULL,
                disposition_score INTEGER DEFAULT 0,
                notes TEXT DEFAULT '',
                FOREIGN KEY (npc_id) REFERENCES npcs (id) ON DELETE CASCADE,
                FOREIGN KEY (character_id) REFERENCES characters (id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS quests_encounters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                type TEXT DEFAULT 'Main Quest',
                status TEXT DEFAULT 'Active',
                objective TEXT DEFAULT '',
                reward TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                FOREIGN KEY (campaign_id) REFERENCES campaigns (id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS timeline_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id INTEGER NOT NULL,
                session_num INTEGER DEFAULT 1,
                in_game_date TEXT DEFAULT '',
                event_summary TEXT NOT NULL,
                related_npcs_json TEXT DEFAULT '[]',
                related_locations_json TEXT DEFAULT '[]',
                created_at TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES campaigns (id) ON DELETE CASCADE
            );

            
            CREATE TABLE IF NOT EXISTS armour_catalog (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                category TEXT NOT NULL,
                price TEXT DEFAULT '',
                encumbrance REAL NOT NULL,
                availability TEXT DEFAULT 'Common',
                penalty TEXT DEFAULT '-',
                locations TEXT NOT NULL,
                ap INTEGER NOT NULL,
                qualities TEXT DEFAULT '-'
            );

            CREATE TABLE IF NOT EXISTS weapons_catalog (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                group_name TEXT NOT NULL,
                is_ranged INTEGER DEFAULT 0,
                price TEXT DEFAULT '',
                encumbrance REAL NOT NULL,
                availability TEXT DEFAULT 'Common',
                reach_range TEXT DEFAULT '',
                damage TEXT NOT NULL,
                qualities TEXT DEFAULT '-'
            );

            CREATE TABLE IF NOT EXISTS bestiary_catalog (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                description TEXT DEFAULT '',
                m TEXT DEFAULT '-',
                ws TEXT DEFAULT '-',
                bs TEXT DEFAULT '-',
                s TEXT DEFAULT '-',
                t TEXT DEFAULT '-',
                i TEXT DEFAULT '-',
                ag TEXT DEFAULT '-',
                dex TEXT DEFAULT '-',
                int TEXT DEFAULT '-',
                wp TEXT DEFAULT '-',
                fel TEXT DEFAULT '-',
                w TEXT DEFAULT '-',
                traits TEXT DEFAULT '',
                optional_traits TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS trappings_catalog (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                category TEXT NOT NULL,
                price TEXT DEFAULT '',
                encumbrance REAL NOT NULL DEFAULT 0.0,
                availability TEXT DEFAULT 'Common',
                carries TEXT DEFAULT '',
                description TEXT DEFAULT '',
                is_worn INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS party_inventory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id INTEGER NOT NULL,
                item_name TEXT NOT NULL,
                quantity INTEGER DEFAULT 1,
                encumbrance REAL DEFAULT 1.0,
                held_by TEXT DEFAULT 'Party Chest',
                notes TEXT DEFAULT '',
                FOREIGN KEY (campaign_id) REFERENCES campaigns (id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS combat_encounters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id INTEGER NOT NULL,
                name TEXT DEFAULT 'Combat',
                round INTEGER DEFAULT 1,
                current_turn_index INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                FOREIGN KEY (campaign_id) REFERENCES campaigns (id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS combatants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                encounter_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                initiative INTEGER DEFAULT 0,
                wounds_current INTEGER DEFAULT 0,
                wounds_max INTEGER DEFAULT 0,
                advantage INTEGER DEFAULT 0,
                conditions TEXT DEFAULT '',
                is_npc INTEGER DEFAULT 1,
                FOREIGN KEY (encounter_id) REFERENCES combat_encounters (id) ON DELETE CASCADE
            );
        """)
        # Published module content and the per-campaign state laid over it live
        # in games/wfrp/module_schema.py — see that module for the split between
        # re-extractable content and campaign state.
        _module_schema.init_module_schema(conn)
        # The session/event chronicle lives in games/wfrp/events.py.
        from . import events as _events
        _events.init_events_schema(conn)
        for col, default in [("price", "''"), ("availability", "'Common'"), ("penalty", "'-'")]:
            try:
                conn.execute(f"ALTER TABLE armour_catalog ADD COLUMN {col} TEXT DEFAULT {default};")
            except Exception:
                pass
        try:
            conn.execute("ALTER TABLE trappings_catalog ADD COLUMN is_worn INTEGER DEFAULT 0;")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE npcs ADD COLUMN module_npc_id INTEGER REFERENCES module_npcs (id) ON DELETE SET NULL;")
        except Exception:
            pass
        for col, default in [("foundry_actor_id", "''"), ("foundry_synced_at", "''")]:
            try:
                conn.execute(f"ALTER TABLE characters ADD COLUMN {col} TEXT DEFAULT {default};")
            except Exception:
                pass
    conn.close()

    try:
        seed_armour_catalog()
        seed_weapons_catalog()
        seed_trappings_catalog()
        seed_hirelings_catalog()
    except Exception as e:
        print(f"[db] Failed to seed catalogs: {e}")


def _slug(text: str) -> str:
    s = text.strip().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def migrate_json_files() -> None:
    """Scan existing JSON campaign files and import them into SQLite if missing."""
    init_db()
    
    # Search paths for JSON campaign files
    search_dirs = [
        pathlib.Path(__file__).resolve().parent.parent / "campaigns",
        pathlib.Path(__file__).resolve().parent.parent.parent.parent / "campaigns",
        pathlib.Path(os.getenv("OMEGA7_DATA_DIR", "~/.config/omega7")).expanduser() / "campaigns"
    ]

    found_json = {}
    for d in search_dirs:
        if d.exists() and d.is_dir():
            for f in sorted(d.glob("*.json")):
                if f.name not in found_json:
                    found_json[f.name] = f

    if not found_json:
        return

    conn = get_connection()
    for f_name, f_path in found_json.items():
        try:
            data = json.loads(f_path.read_text(encoding="utf-8"))
            name = data.get("name", f_path.stem.replace("-", " ").title())
            slug = data.get("slug", _slug(name))

            with conn:
                cur = conn.execute("SELECT id FROM campaigns WHERE slug = ?", (slug,))
                row = cur.fetchone()
                if row:
                    continue  # Already migrated

                now = _now()
                cur = conn.execute("""
                    INSERT INTO campaigns (slug, name, adventure, current_location, current_scene, party_ambition_short, party_ambition_long, notes, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    slug,
                    name,
                    data.get("adventure", name),
                    data.get("current_location", "The Reikland"),
                    data.get("current_scene", ""),
                    data.get("party_ambition_short", ""),
                    data.get("party_ambition_long", ""),
                    json.dumps(data.get("session_notes", [])),
                    data.get("created", now),
                    data.get("last_modified", now)
                ))
                cid = cur.lastrowid

                # Migrate Characters
                for char in data.get("characters", []):
                    c_name = char.get("name", "Unnamed Hero")
                    w = char.get("wounds", {})
                    w_curr = w.get("current", 10) if isinstance(w, dict) else (w if isinstance(w, int) else 10)
                    w_max = w.get("max", 10) if isinstance(w, dict) else 10

                    ft = char.get("fate", {})
                    f_curr = ft.get("current", 3) if isinstance(ft, dict) else (ft if isinstance(ft, int) else 3)
                    f_tot = ft.get("total", 3) if isinstance(ft, dict) else 3

                    fr = char.get("fortune", {})
                    fort_curr = fr.get("current", f_curr) if isinstance(fr, dict) else (fr if isinstance(fr, int) else f_curr)

                    mv = char.get("move", {})
                    m_base = mv.get("base", 4) if isinstance(mv, dict) else (mv if isinstance(mv, int) else 4)
                    m_walk = mv.get("walk", m_base * 2) if isinstance(mv, dict) else m_base * 2
                    m_run = mv.get("run", m_base * 4) if isinstance(mv, dict) else m_base * 4

                    xp = char.get("xp", {})
                    xp_tot = xp.get("total", 0) if isinstance(xp, dict) else (xp if isinstance(xp, int) else 0)
                    xp_spent = xp.get("spent", 0) if isinstance(xp, dict) else 0
                    xp_curr = xp.get("current", xp_tot - xp_spent) if isinstance(xp, dict) else (xp_tot - xp_spent)

                    conn.execute("""
                        INSERT INTO characters (
                            campaign_id, name, species, class_name, career, career_level, career_path, status,
                            age, height, hair_color, eye_color, doomed, star_sign, motivation,
                            wounds_curr, wounds_max, hardy_advances, fate_curr, fate_tot, fortune_curr,
                            resilience_tot, resolve_curr, move_base, move_walk, move_run,
                            xp_curr, xp_spent, xp_tot, sin, corruption_curr, corruption_max,
                            characteristics_json, basic_skill_advances_json, skills_json, talents_json,
                            trappings_json, weapons_json, armour_json, encumbrance_json, money_json,
                            psychology_json, spells_json, ambitions_json, ten_questions_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        cid, c_name,
                        char.get("race", "Human"),
                        char.get("class", char.get("class_name", "Academics")),
                        char.get("career", "Scholar"),
                        char.get("career_level", "1"),
                        char.get("career_path", ""),
                        char.get("status", "Brass 3"),
                        char.get("age"),
                        char.get("height", ""),
                        char.get("hair_color", ""),
                        char.get("eye_color", ""),
                        char.get("doomed", ""),
                        char.get("star_sign", ""),
                        char.get("motivation", ""),
                        w_curr, w_max, char.get("hardy_advances", 0),
                        f_curr, f_tot, fort_curr,
                        char.get("resilience", 0) if isinstance(char.get("resilience"), int) else char.get("resilience", {}).get("total", 0),
                        char.get("resolve", 0) if isinstance(char.get("resolve"), int) else char.get("resolve", {}).get("current", 0),
                        m_base, m_walk, m_run,
                        xp_curr, xp_spent, xp_tot,
                        char.get("sin", 0),
                        char.get("corruption", {}).get("current", 0) if isinstance(char.get("corruption"), dict) else (char.get("corruption", 0)),
                        char.get("corruption", {}).get("max", 6) if isinstance(char.get("corruption"), dict) else 6,
                        json.dumps(char.get("characteristics", {})),
                        json.dumps(char.get("basic_skill_advances", {})),
                        json.dumps(char.get("skills", [])),
                        json.dumps(char.get("talents", [])),
                        json.dumps(char.get("trappings", [])),
                        json.dumps(char.get("weapons", [])),
                        json.dumps(char.get("armour", {})),
                        json.dumps(char.get("encumbrance", {})),
                        json.dumps(char.get("money", {})),
                        json.dumps(char.get("psychology", {})),
                        json.dumps(char.get("spells", [])),
                        json.dumps(char.get("ambitions", {})),
                        json.dumps(char.get("ten_questions", {}))
                    ))

                # Create default location & starter NPC
                cur_loc = conn.execute("""
                    INSERT INTO locations (campaign_id, name, type, region, description, visited)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (cid, "The Reikland", "Region", "Reikland", "The heartland of the Empire.", 1))
                loc_id = cur_loc.lastrowid

                # Migrate NPCs if present
                for npc in data.get("active_npcs", []):
                    npc_name = npc.get("name") if isinstance(npc, dict) else str(npc)
                    conn.execute("""
                        INSERT INTO npcs (campaign_id, location_id, name, role_career, disposition, notes)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (cid, loc_id, npc_name, "NPC", "Neutral", "Migrated from campaign file."))

                # Create initial timeline log
                conn.execute("""
                    INSERT INTO timeline_logs (campaign_id, session_num, in_game_date, event_summary, created_at)
                    VALUES (?, 1, '2502 IC', 'Campaign initialized and party assembled in Reikland.', ?)
                """, (cid, now))

            print(f"[db] Migrated {f_path} into SQLite successfully.")
        except Exception as e:
            print(f"[db] Migration failed for {f_path}: {e}")

    conn.close()





# ── REPOSITORY METHODS ────────────────────────────────────────────────────────

def get_campaign_dict(slug_or_name: str) -> Optional[dict]:
    """Retrieve full campaign dict matching JSON structure from SQLite."""
    conn = get_connection()
    slug = _slug(slug_or_name)
    cur = conn.execute("SELECT * FROM campaigns WHERE slug = ? OR name = ?", (slug, slug_or_name))
    row = cur.fetchone()
    if not row:
        conn.close()
        return None

    cid = row["id"]
    camp_dict = dict(row)

    # Fetch Characters
    cur_chars = conn.execute("SELECT * FROM characters WHERE campaign_id = ?", (cid,))
    chars_list = []
    for c_row in cur_chars.fetchall():
        c_dict = dict(c_row)
        race_val = c_dict.pop("species", None) or c_dict.get("race") or "Human"
        c_dict["race"] = race_val
        c_dict["species"] = race_val
        c_dict["hair"] = c_dict.get("hair_color") or c_dict.get("hair", "")
        c_dict["hair_color"] = c_dict["hair"]
        c_dict["eyes"] = c_dict.get("eye_color") or c_dict.get("eyes", "")
        c_dict["eye_color"] = c_dict["eyes"]
        c_dict["starsign"] = c_dict.get("star_sign") or c_dict.get("starsign", "")
        c_dict["star_sign"] = c_dict["starsign"]
        c_dict["class"] = c_dict.pop("class_name", "Academics")
        c_dict["characteristics"] = json.loads(c_dict.pop("characteristics_json") or "{}")
        c_dict["basic_skill_advances"] = json.loads(c_dict.pop("basic_skill_advances_json") or "{}")
        c_dict["skills"] = json.loads(c_dict.pop("skills_json") or "[]")
        c_dict["talents"] = json.loads(c_dict.pop("talents_json") or "[]")
        c_dict["trappings"] = json.loads(c_dict.pop("trappings_json") or "[]")
        c_dict["weapons"] = json.loads(c_dict.pop("weapons_json") or "[]")
        c_dict["armour"] = json.loads(c_dict.pop("armour_json") or "{}")
        c_dict["encumbrance"] = json.loads(c_dict.pop("encumbrance_json") or "{}")
        c_dict["money"] = json.loads(c_dict.pop("money_json") or "{}")
        c_dict["psychology"] = json.loads(c_dict.pop("psychology_json") or "{}")
        c_dict["spells"] = json.loads(c_dict.pop("spells_json") or "[]")
        c_dict["ambitions"] = json.loads(c_dict.pop("ambitions_json") or "{}")
        c_dict["ten_questions"] = json.loads(c_dict.pop("ten_questions_json") or "{}")

        c_dict["wounds"] = {"current": c_dict.pop("wounds_curr"), "max": c_dict.pop("wounds_max")}
        c_dict["fate"] = {"current": c_dict.pop("fate_curr"), "total": c_dict.pop("fate_tot")}
        c_dict["fortune"] = {"current": c_dict.pop("fortune_curr"), "total": c_dict["fate"]["total"]}
        c_dict["move"] = {"base": c_dict.pop("move_base"), "walk": c_dict.pop("move_walk"), "run": c_dict.pop("move_run")}
        c_dict["xp"] = {"current": c_dict.pop("xp_curr"), "spent": c_dict.pop("xp_spent"), "total": c_dict.pop("xp_tot")}
        c_dict["corruption"] = {"current": c_dict.pop("corruption_curr"), "max": c_dict.pop("corruption_max")}

        chars_list.append(c_dict)

    camp_dict["characters"] = chars_list

    # Fetch Locations, NPCs, Quests, Timeline, Inventory
    cur_locs = conn.execute("SELECT * FROM locations WHERE campaign_id = ?", (cid,))
    camp_dict["locations"] = [dict(r) for r in cur_locs.fetchall()]

    cur_npcs = conn.execute("SELECT * FROM npcs WHERE campaign_id = ?", (cid,))
    npcs = []
    for r in cur_npcs.fetchall():
        n = dict(r)
        # Fetch relations
        rel_cur = conn.execute("SELECT * FROM npc_character_relations WHERE npc_id = ?", (n["id"],))
        n["character_relations"] = [dict(rel) for rel in rel_cur.fetchall()]
        npcs.append(n)
        
    camp_dict["npcs"] = npcs
    camp_dict["active_npcs"] = [n["name"] for n in camp_dict["npcs"] if n["status"] == "Alive"]

    cur_quests = conn.execute("SELECT * FROM quests_encounters WHERE campaign_id = ?", (cid,))
    camp_dict["quests"] = [dict(r) for r in cur_quests.fetchall()]

    cur_time = conn.execute("SELECT * FROM timeline_logs WHERE campaign_id = ? ORDER BY id ASC", (cid,))
    timeline = []
    for r in cur_time.fetchall():
        t = dict(r)
        t["related_npcs"] = json.loads(t.pop("related_npcs_json", "[]"))
        t["related_locations"] = json.loads(t.pop("related_locations_json", "[]"))
        timeline.append(t)
    camp_dict["timeline"] = timeline

    cur_inv = conn.execute("SELECT * FROM party_inventory WHERE campaign_id = ?", (cid,))
    camp_dict["inventory"] = [dict(r) for r in cur_inv.fetchall()]

    try:
        camp_dict["session_notes"] = json.loads(camp_dict.get("notes") or "[]")
    except Exception:
        camp_dict["session_notes"] = [camp_dict.get("notes", "")]

    conn.close()
    return camp_dict


def list_all_campaigns() -> List[dict]:
    conn = get_connection()
    cur = conn.execute("SELECT slug, name, adventure, current_location, updated_at FROM campaigns ORDER BY updated_at DESC")
    results = []
    for row in cur.fetchall():
        r = dict(row)
        # count chars
        c_cur = conn.execute("SELECT COUNT(*) as count FROM characters WHERE campaign_id = (SELECT id FROM campaigns WHERE slug = ?)", (r["slug"],))
        r["character_count"] = c_cur.fetchone()["count"]
        results.append(r)
    conn.close()
    return results


def save_or_upsert_campaign(camp_dict: dict) -> dict:
    name = camp_dict.get("name", "New Campaign")
    slug = camp_dict.get("slug", _slug(name))
    now = _now()

    conn = get_connection()
    with conn:
        cur = conn.execute("SELECT id FROM campaigns WHERE slug = ?", (slug,))
        row = cur.fetchone()
        if row:
            cid = row["id"]
            conn.execute("""
                UPDATE campaigns SET
                    name = ?, adventure = ?, current_location = ?, current_scene = ?,
                    party_ambition_short = ?, party_ambition_long = ?, notes = ?, updated_at = ?
                WHERE id = ?
            """, (
                name,
                camp_dict.get("adventure", name),
                camp_dict.get("current_location", "The Reikland"),
                camp_dict.get("current_scene", ""),
                camp_dict.get("party_ambition_short", ""),
                camp_dict.get("party_ambition_long", ""),
                camp_dict.get("notes", ""),
                now,
                cid
            ))
        else:
            cur = conn.execute("""
                INSERT INTO campaigns (slug, name, adventure, current_location, current_scene, party_ambition_short, party_ambition_long, notes, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                slug, name, camp_dict.get("adventure", name),
                camp_dict.get("current_location", "The Reikland"),
                camp_dict.get("current_scene", ""),
                camp_dict.get("party_ambition_short", ""),
                camp_dict.get("party_ambition_long", ""),
                camp_dict.get("notes", ""),
                now, now
            ))
            cid = cur.lastrowid

    conn.close()
    return get_campaign_dict(slug)


def upsert_character_record(slug: str, char_dict: dict) -> None:
    conn = get_connection()
    cur = conn.execute("SELECT id FROM campaigns WHERE slug = ?", (slug,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return
    cid = row["id"]

    c_name = char_dict.get("name", "Unnamed Agent")

    w = char_dict.get("wounds", {})
    w_curr = w.get("current", 10) if isinstance(w, dict) else (w if isinstance(w, int) else 10)
    w_max = w.get("max", 10) if isinstance(w, dict) else 10

    ft = char_dict.get("fate", {})
    f_curr = ft.get("current", 3) if isinstance(ft, dict) else (ft if isinstance(ft, int) else 3)
    f_tot = ft.get("total", 3) if isinstance(ft, dict) else 3

    fr = char_dict.get("fortune", {})
    fort_curr = fr.get("current", f_curr) if isinstance(fr, dict) else (fr if isinstance(fr, int) else f_curr)

    mv = char_dict.get("move", {})
    m_base = mv.get("base", 4) if isinstance(mv, dict) else (mv if isinstance(mv, int) else 4)
    m_walk = mv.get("walk", m_base * 2) if isinstance(mv, dict) else m_base * 2
    m_run = mv.get("run", m_base * 4) if isinstance(mv, dict) else m_base * 4

    xp = char_dict.get("xp", {})
    xp_tot = xp.get("total", 0) if isinstance(xp, dict) else (xp if isinstance(xp, int) else 0)
    xp_spent = xp.get("spent", 0) if isinstance(xp, dict) else 0
    xp_curr = xp.get("current", xp_tot - xp_spent) if isinstance(xp, dict) else (xp_tot - xp_spent)

    char_id = char_dict.get("id")
    orig_name = char_dict.get("original_name") or c_name

    with conn:
        ch_row = None
        if char_id:
            try:
                ch_cur = conn.execute("SELECT id FROM characters WHERE campaign_id = ? AND id = ?", (cid, int(char_id)))
                ch_row = ch_cur.fetchone()
            except (ValueError, TypeError):
                pass
        if not ch_row:
            ch_cur = conn.execute("SELECT id FROM characters WHERE campaign_id = ? AND (LOWER(name) = LOWER(?) OR LOWER(name) = LOWER(?))", (cid, orig_name, c_name))
            ch_row = ch_cur.fetchone()
        if ch_row:
            conn.execute("""
                UPDATE characters SET
                    name = ?, species = ?, class_name = ?, career = ?, career_level = ?, career_path = ?, status = ?,
                    age = ?, height = ?, hair_color = ?, eye_color = ?, doomed = ?, star_sign = ?, motivation = ?,
                    wounds_curr = ?, wounds_max = ?, hardy_advances = ?, fate_curr = ?, fate_tot = ?, fortune_curr = ?,
                    resilience_tot = ?, resolve_curr = ?, move_base = ?, move_walk = ?, move_run = ?,
                    xp_curr = ?, xp_spent = ?, xp_tot = ?, sin = ?, corruption_curr = ?, corruption_max = ?,
                    characteristics_json = ?, basic_skill_advances_json = ?, skills_json = ?, talents_json = ?,
                    trappings_json = ?, weapons_json = ?, armour_json = ?, encumbrance_json = ?, money_json = ?,
                    psychology_json = ?, spells_json = ?, ambitions_json = ?, ten_questions_json = ?
                WHERE id = ?
            """, (
                c_name,
                char_dict.get("race") or char_dict.get("species", "Human"),
                char_dict.get("class", "Academics"),
                char_dict.get("career", "Scholar"),
                char_dict.get("career_level", "1"),
                char_dict.get("career_path", ""),
                char_dict.get("status", "Brass 3"),
                char_dict.get("age"),
                char_dict.get("height", ""),
                char_dict.get("hair_color") or char_dict.get("hair", ""),
                char_dict.get("eye_color") or char_dict.get("eyes", ""),
                char_dict.get("doomed", ""),
                char_dict.get("star_sign") or char_dict.get("starsign", ""),
                char_dict.get("motivation", ""),
                w_curr, w_max, char_dict.get("hardy_advances", 0),
                f_curr, f_tot, fort_curr,
                char_dict.get("resilience", 0) if isinstance(char_dict.get("resilience"), int) else char_dict.get("resilience", {}).get("total", 0),
                char_dict.get("resolve", 0) if isinstance(char_dict.get("resolve"), int) else char_dict.get("resolve", {}).get("current", 0),
                m_base, m_walk, m_run,
                xp_curr, xp_spent, xp_tot,
                char_dict.get("sin", 0),
                char_dict.get("corruption", {}).get("current", 0) if isinstance(char_dict.get("corruption"), dict) else (char_dict.get("corruption", 0)),
                char_dict.get("corruption", {}).get("max", 6) if isinstance(char_dict.get("corruption"), dict) else 6,
                json.dumps(char_dict.get("characteristics", {})),
                json.dumps(char_dict.get("basic_skill_advances", {})),
                json.dumps(char_dict.get("skills", [])),
                json.dumps(char_dict.get("talents", [])),
                json.dumps(char_dict.get("trappings", [])),
                json.dumps(char_dict.get("weapons", [])),
                json.dumps(char_dict.get("armour", {})),
                json.dumps(char_dict.get("encumbrance", {})),
                json.dumps(char_dict.get("money", {})),
                json.dumps(char_dict.get("psychology", {})),
                json.dumps(char_dict.get("spells", [])),
                json.dumps(char_dict.get("ambitions", {})),
                json.dumps(char_dict.get("ten_questions", {})),
                ch_row["id"]
            ))
        else:
            conn.execute("""
                INSERT INTO characters (
                    campaign_id, name, species, class_name, career, career_level, career_path, status,
                    age, height, hair_color, eye_color, doomed, star_sign, motivation,
                    wounds_curr, wounds_max, hardy_advances, fate_curr, fate_tot, fortune_curr,
                    resilience_tot, resolve_curr, move_base, move_walk, move_run,
                    xp_curr, xp_spent, xp_tot, sin, corruption_curr, corruption_max,
                    characteristics_json, basic_skill_advances_json, skills_json, talents_json,
                    trappings_json, weapons_json, armour_json, encumbrance_json, money_json,
                    psychology_json, spells_json, ambitions_json, ten_questions_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                cid, c_name,
                char_dict.get("race") or char_dict.get("species", "Human"),
                char_dict.get("class", "Academics"),
                char_dict.get("career", "Scholar"),
                char_dict.get("career_level", "1"),
                char_dict.get("career_path", ""),
                char_dict.get("status", "Brass 3"),
                char_dict.get("age"),
                char_dict.get("height", ""),
                char_dict.get("hair_color") or char_dict.get("hair", ""),
                char_dict.get("eye_color") or char_dict.get("eyes", ""),
                char_dict.get("doomed", ""),
                char_dict.get("star_sign") or char_dict.get("starsign", ""),
                char_dict.get("motivation", ""),
                w_curr, w_max, char_dict.get("hardy_advances", 0),
                f_curr, f_tot, fort_curr,
                char_dict.get("resilience", 0) if isinstance(char_dict.get("resilience"), int) else char_dict.get("resilience", {}).get("total", 0),
                char_dict.get("resolve", 0) if isinstance(char_dict.get("resolve"), int) else char_dict.get("resolve", {}).get("current", 0),
                m_base, m_walk, m_run,
                xp_curr, xp_spent, xp_tot,
                char_dict.get("sin", 0),
                char_dict.get("corruption", {}).get("current", 0) if isinstance(char_dict.get("corruption"), dict) else (char_dict.get("corruption", 0)),
                char_dict.get("corruption", {}).get("max", 6) if isinstance(char_dict.get("corruption"), dict) else 6,
                json.dumps(char_dict.get("characteristics", {})),
                json.dumps(char_dict.get("basic_skill_advances", {})),
                json.dumps(char_dict.get("skills", [])),
                json.dumps(char_dict.get("talents", [])),
                json.dumps(char_dict.get("trappings", [])),
                json.dumps(char_dict.get("weapons", [])),
                json.dumps(char_dict.get("armour", {})),
                json.dumps(char_dict.get("encumbrance", {})),
                json.dumps(char_dict.get("money", {})),
                json.dumps(char_dict.get("psychology", {})),
                json.dumps(char_dict.get("spells", [])),
                json.dumps(char_dict.get("ambitions", {})),
                json.dumps(char_dict.get("ten_questions", {}))
            ))
    conn.close()


def get_character_row(slug: str, char_id: int) -> Optional[dict]:
    """Raw row lookup by campaign slug + character id, for Foundry-sync bookkeeping."""
    conn = get_connection()
    cur = conn.execute("SELECT id FROM campaigns WHERE slug = ?", (slug,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return None
    cid = row["id"]
    cur = conn.execute("SELECT * FROM characters WHERE campaign_id = ? AND id = ?", (cid, char_id))
    c_row = cur.fetchone()
    conn.close()
    return dict(c_row) if c_row else None


def set_foundry_link(slug: str, char_id: int, actor_id: str) -> None:
    """Record the Foundry actor id a local character is linked to, and stamp the sync time."""
    conn = get_connection()
    cur = conn.execute("SELECT id FROM campaigns WHERE slug = ?", (slug,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return
    cid = row["id"]
    with conn:
        conn.execute(
            "UPDATE characters SET foundry_actor_id = ?, foundry_synced_at = ? WHERE campaign_id = ? AND id = ?",
            (actor_id, _now(), cid, char_id),
        )
    conn.close()


def touch_foundry_sync(slug: str, char_id: int) -> None:
    """Stamp the last-synced time without changing the linked actor id."""
    conn = get_connection()
    cur = conn.execute("SELECT id FROM campaigns WHERE slug = ?", (slug,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return
    cid = row["id"]
    with conn:
        conn.execute(
            "UPDATE characters SET foundry_synced_at = ? WHERE campaign_id = ? AND id = ?",
            (_now(), cid, char_id),
        )
    conn.close()


# ── ENTITY LOOKUP & QUERY METHODS (For LLM Prompt Context) ───────────────────

def lookup_npc(slug: str, npc_query: str) -> Optional[dict]:
    conn = get_connection()
    cur = conn.execute("""
        SELECT n.*, l.name as location_name FROM npcs n
        LEFT JOIN locations l ON n.location_id = l.id
        WHERE n.campaign_id = (SELECT id FROM campaigns WHERE slug = ?)
        AND (n.name LIKE ? OR n.role_career LIKE ?)
    """, (slug, f"%{npc_query}%", f"%{npc_query}%"))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def lookup_location(slug: str, loc_query: str) -> Optional[dict]:
    conn = get_connection()
    cur = conn.execute("""
        SELECT * FROM locations
        WHERE campaign_id = (SELECT id FROM campaigns WHERE slug = ?)
        AND (name LIKE ? OR region LIKE ?)
    """, (slug, f"%{loc_query}%", f"%{loc_query}%"))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def add_timeline_event(slug: str, event_summary: str, in_game_date: str = "") -> None:
    conn = get_connection()
    with conn:
        cur = conn.execute("SELECT id FROM campaigns WHERE slug = ?", (slug,))
        row = cur.fetchone()
        if row:
            conn.execute("""
                INSERT INTO timeline_logs (campaign_id, event_summary, in_game_date, related_npcs_json, related_locations_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (row["id"], event_summary, in_game_date or "2502 IC", "[]", "[]", _now()))
    conn.close()


def add_npc(slug: str, name: str, role_career: str = "", disposition: str = "Neutral", secrets_lore: str = "", notes: str = "", motivations_goals: str = "", party_disposition: str = "Neutral") -> dict:
    conn = get_connection()
    with conn:
        cur = conn.execute("SELECT id FROM campaigns WHERE slug = ?", (slug,))
        row = cur.fetchone()
        if row:
            n_cur = conn.execute("""
                INSERT INTO npcs (campaign_id, name, role_career, disposition, secrets_lore, notes, motivations_goals, party_disposition)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (row["id"], name, role_career, disposition, secrets_lore, notes, motivations_goals, party_disposition))
            nid = n_cur.lastrowid
            conn.close()
            return {"id": nid, "name": name, "role_career": role_career, "disposition": disposition, "party_disposition": party_disposition}
    conn.close()
    return {}

def delete_character_record(slug: str, char_identifier: Any) -> None:
    conn = get_connection()
    target_str = str(char_identifier).strip()
    with conn:
        if target_str.isdigit():
            conn.execute("""
                DELETE FROM characters
                WHERE campaign_id = (SELECT id FROM campaigns WHERE slug = ?)
                AND (id = ? OR LOWER(name) = LOWER(?))
            """, (slug, int(target_str), target_str))
        else:
            conn.execute("""
                DELETE FROM characters
                WHERE campaign_id = (SELECT id FROM campaigns WHERE slug = ?)
                AND LOWER(name) = LOWER(?)
            """, (slug, target_str))
    conn.close()


def upsert_location(slug: str, loc_dict: dict) -> dict:
    conn = get_connection()
    cur = conn.execute("SELECT id FROM campaigns WHERE slug = ?", (slug,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return {}
    cid = row["id"]

    loc_id = loc_dict.get("id")
    name = loc_dict.get("name", "Unnamed Site")
    loc_type = loc_dict.get("type", "City")
    region = loc_dict.get("region", "Reikland")
    description = loc_dict.get("description", "")
    faction = loc_dict.get("controlling_faction", "")
    danger = loc_dict.get("danger_level", "Low")
    visited = 1 if loc_dict.get("visited", True) else 0
    history = loc_dict.get("history", "")

    with conn:
        if loc_id:
            conn.execute("""
                UPDATE locations SET
                    name = ?, type = ?, region = ?, description = ?,
                    controlling_faction = ?, danger_level = ?, visited = ?, history = ?
                WHERE id = ? AND campaign_id = ?
            """, (name, loc_type, region, description, faction, danger, visited, history, loc_id, cid))
        else:
            conn.execute("""
                INSERT INTO locations (campaign_id, name, type, region, description, controlling_faction, danger_level, visited, history)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (cid, name, loc_type, region, description, faction, danger, visited, history))
    conn.close()
    return get_campaign_dict(slug) or {}


def delete_location(slug: str, loc_id: int) -> None:
    conn = get_connection()
    with conn:
        conn.execute("""
            DELETE FROM locations
            WHERE campaign_id = (SELECT id FROM campaigns WHERE slug = ?)
            AND id = ?
        """, (slug, loc_id))
    conn.close()


def upsert_npc(slug: str, npc_dict: dict) -> dict:
    conn = get_connection()
    cur = conn.execute("SELECT id FROM campaigns WHERE slug = ?", (slug,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return {}
    cid = row["id"]

    npc_id = npc_dict.get("id")
    name = npc_dict.get("name", "Unnamed NPC")
    role_career = npc_dict.get("role_career", "")
    species = npc_dict.get("species", "Human")
    disposition = npc_dict.get("disposition", "Neutral")
    status = npc_dict.get("status", "Alive")
    secrets_lore = npc_dict.get("secrets_lore", "")
    notes = npc_dict.get("notes", "")
    motivations_goals = npc_dict.get("motivations_goals", "")
    party_disposition = npc_dict.get("party_disposition", "Neutral")
    loc_id = npc_dict.get("location_id")

    with conn:
        if npc_id:
            conn.execute("""
                UPDATE npcs SET
                    name = ?, role_career = ?, species = ?, disposition = ?,
                    status = ?, secrets_lore = ?, notes = ?, motivations_goals = ?, party_disposition = ?, location_id = ?
                WHERE id = ? AND campaign_id = ?
            """, (name, role_career, species, disposition, status, secrets_lore, notes, motivations_goals, party_disposition, loc_id, npc_id, cid))
        else:
            conn.execute("""
                INSERT INTO npcs (campaign_id, location_id, name, role_career, species, disposition, status, secrets_lore, notes, motivations_goals, party_disposition)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (cid, loc_id, name, role_career, species, disposition, status, secrets_lore, notes, motivations_goals, party_disposition))
    conn.close()
    return get_campaign_dict(slug) or {}


def delete_npc(slug: str, npc_id: int) -> None:
    conn = get_connection()
    with conn:
        conn.execute("""
            DELETE FROM npcs
            WHERE campaign_id = (SELECT id FROM campaigns WHERE slug = ?)
            AND id = ?
        """, (slug, npc_id))
    conn.close()


def upsert_quest(slug: str, quest_dict: dict) -> dict:
    conn = get_connection()
    cur = conn.execute("SELECT id FROM campaigns WHERE slug = ?", (slug,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return {}
    cid = row["id"]

    qid = quest_dict.get("id")
    title = quest_dict.get("title", "Unnamed Quest")
    qtype = quest_dict.get("type", "Main Quest")
    qstatus = quest_dict.get("status", "Active")
    objective = quest_dict.get("objective", "")
    reward = quest_dict.get("reward", "")
    notes = quest_dict.get("notes", "")

    with conn:
        if qid:
            conn.execute("""
                UPDATE quests_encounters SET
                    title = ?, type = ?, status = ?, objective = ?, reward = ?, notes = ?
                WHERE id = ? AND campaign_id = ?
            """, (title, qtype, qstatus, objective, reward, notes, qid, cid))
        else:
            conn.execute("""
                INSERT INTO quests_encounters (campaign_id, title, type, status, objective, reward, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (cid, title, qtype, qstatus, objective, reward, notes))
    conn.close()
    return get_campaign_dict(slug) or {}


def delete_quest(slug: str, quest_id: int) -> None:
    conn = get_connection()
    with conn:
        conn.execute("""
            DELETE FROM quests_encounters
            WHERE campaign_id = (SELECT id FROM campaigns WHERE slug = ?)
            AND id = ?
        """, (slug, quest_id))
    conn.close()


def seed_armour_catalog() -> None:
    conn = get_connection()
    # Official WFRP 4E Core Rulebook Armour Table
    armour_items = [
        # Soft Leather
        ("Leather Jack", "Soft Leather", "12/-", 1, "Common", "-", "Arms, Body", 1, "-"),
        ("Leather Jerkin", "Soft Leather", "10/-", 1, "Common", "-", "Body", 1, "-"),
        ("Leather Leggings", "Soft Leather", "14/-", 1, "Common", "-", "Legs", 1, "-"),
        ("Leather Skullcap", "Soft Leather", "8/-", 0, "Common", "-", "Head", 1, "-"),
        # Boiled Leather
        ("Breastplate (Boiled)", "Boiled Leather", "18/-", 2, "Scarce", "-", "Body", 2, "Weakpoints"),
        # Mail
        ("Mail Chausses", "Mail", "2GC", 3, "Scarce", "-", "Legs", 2, "Flexible"),
        ("Mail Coat", "Mail", "3GC", 3, "Common", "-", "Arms, Body", 2, "Flexible"),
        ("Mail Coif", "Mail", "1GC", 2, "Scarce", "-10% Perception", "Head", 2, "Flexible, Partial"),
        ("Mail Shirt", "Mail", "2GC", 2, "Scarce", "-", "Body", 2, "Flexible"),
        # Plate
        ("Breastplate (Plate)", "Plate", "10GC", 3, "Scarce", "-", "Body", 2, "Impenetrable, Weakpoints"),
        ("Open Helm", "Plate", "2GC", 1, "Common", "-10% Perception", "Head", 2, "Partial"),
        ("Bracers", "Plate", "8GC", 3, "Rare", "-", "Arms", 2, "Impenetrable, Weakpoints"),
        ("Plate Leggings", "Plate", "10GC", 3, "Rare", "-10 Stealth", "Legs", 2, "Impenetrable, Weakpoints"),
        ("Helm", "Plate", "3GC", 2, "Rare", "-20% Perception", "Head", 2, "Impenetrable, Weakpoints"),
    ]
    with conn:
        for name, cat, price, enc, avail, pen, locs, ap, qual in armour_items:
            conn.execute(
                "INSERT OR REPLACE INTO armour_catalog (name, category, price, encumbrance, availability, penalty, locations, ap, qualities) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
                (name, cat, price, enc, avail, pen, locs, ap, qual)
            )
    conn.close()



def get_hirelings_catalog() -> list[dict]:
    conn = get_connection()
    cur = conn.execute("SELECT name, quick_job_cost, daily_cost, weekly_cost, notes FROM hirelings_catalog ORDER BY name ASC")
    res = []
    for row in cur:
        res.append({
            "name": row[0],
            "quick_job_cost": row[1],
            "daily_cost": row[2],
            "weekly_cost": row[3],
            "notes": row[4]
        })
    return res

def seed_trappings_catalog() -> None:
    conn = get_connection()
    items = [
        ("Backpack", "Packs and Containers", "4/10", "2", "Common", "4", "Counts as ‘worn’ when strapped to your back."),
        ("Barrel", "Packs and Containers", "8/–", "6", "Common", "12", "Capacity: 32 gallons of liquid."),
        ("Cask", "Packs and Containers", "3/–", "2", "Common", "4", "Capacity: 10 gallons of liquid."),
        ("Flask", "Packs and Containers", "5/–", "0", "Common", "0", "Capacity: 1 pint of liquid."),
        ("Jug", "Packs and Containers", "3/2", "1", "Common", "1", "Capacity: 1 gallon of liquid."),
        ("Pewter Stein", "Packs and Containers", "4/–", "0", "Common", "0", ""),
        ("Pouch", "Packs and Containers", "4d", "0", "Common", "1", ""),
        ("Sack", "Packs and Containers", "1/–", "2", "Common", "4", "Requires 1 hand to carry."),
        ("Sack, Large", "Packs and Containers", "1/6", "3", "Common", "6", "Requires 1 hand to carry (or 2 hands if full)."),
        ("Saddlebags", "Packs and Containers", "18/–", "4", "Common", "8", ""),
        ("Sling Bag", "Packs and Containers", "1/–", "1", "Common", "2", "Counts as ‘worn’ when slung over your shoulder."),
        ("Scroll Case", "Packs and Containers", "16/–", "0", "Scarce", "0", ""),
        ("Waterskin", "Packs and Containers", "1/8", "1", "Common", "1", "Capacity: 1 gallon of liquid."),
        ("Amulet", "Clothing and Accessories", "2d", "0", "Common", "", ""),
        ("Boots", "Clothing and Accessories", "5/–", "1", "Common", "", ""),
        ("Cloak", "Clothing and Accessories", "10/–", "1", "Common", "", "Protects wearer against the elements."),
        ("Clothing", "Clothing and Accessories", "6/–", "1", "Common", "", ""),
        ("Coat", "Clothing and Accessories", "18/–", "1", "Common", "", "Protects wearer against the elements and extreme cold;"),
        ("Costume", "Clothing and Accessories", "1GC", "1", "Scarce", "", ""),
        ("Courtly Garb", "Clothing and Accessories", "12GC", "1", "Scarce", "", "Nobles’ garb features embellishments such as lace"),
        ("Face Powder", "Clothing and Accessories", "10/–", "0", "Common", "", ""),
        ("Gloves", "Clothing and Accessories", "4/–", "0", "Common", "", ""),
        ("Hood or Mask", "Clothing and Accessories", "5/–", "0", "Common", "", ""),
        ("Jewellery", "Clothing and Accessories", "Varies", "0", "Common", "", "Prices vary by craftsmanship, metal type, and gem"),
        ("Perfume", "Clothing and Accessories", "10/–", "0", "Common", "", ""),
        ("Pins (6)", "Clothing and Accessories", "10 s", "0", "Scarce", "", ""),
        ("Religious Symbol", "Clothing and Accessories", "6/8", "0", "Common", "", ""),
        ("Robes", "Clothing and Accessories", "2GC", "1", "Common", "", ""),
        ("Sceptre", "Clothing and Accessories", "8GC", "1", "Rare", "", "The highest-ranking legal officials carry sceptres to"),
        ("Shoes", "Clothing and Accessories", "5/–", "0", "Common", "", ""),
        ("Signet Ring", "Clothing and Accessories", "5GC", "0", "Rare", "", "Gold rings with engraved stamps are worn by"),
        ("Tattoo", "Clothing and Accessories", "4/– +", "0", "Scarce", "", ""),
        ("Uniform", "Clothing and Accessories", "1GC 2/–", "1", "Scarce", "", ""),
        ("Walking Cane", "Clothing and Accessories", "3GC", "1", "Common", "", "Polished wooden canes with metal caps are status"),
        ("Ale, pint", "Food, Drink, and Lodging", "3d", "0", "Common", "", ""),
        ("Ale, keg", "Food, Drink, and Lodging", "3 s", "2", "Common", "", "Capacity 3 gallons. Empty kegs can be refilled for 18d."),
        ("Bugman’s XXXXXX Ale, pint", "Food, Drink, and Lodging", "9d", "0", "Exotic", "", ""),
        ("Food, groceries/day", "Food, Drink, and Lodging", "10d", "1", "Common", "", ""),
        ("Meal, inn", "Food, Drink, and Lodging", "1/–", "0", "Common", "", ""),
        ("Rations, 1 day", "Food, Drink, and Lodging", "2/–", "0", "Common", "", ""),
        ("Room, common/night", "Food, Drink, and Lodging", "10d", "–", "Common", "", ""),
        ("Room, private/night", "Food, Drink, and Lodging", "10/–", "–", "Common", "", ""),
        ("Spirits, pint", "Food, Drink, and Lodging", "2/–", "0", "Common", "", ""),
        ("Stables/night", "Food, Drink, and Lodging", "10d", "–", "Common", "", ""),
        ("Wine, bottle", "Food, Drink, and Lodging", "10d", "0", "Common", "", ""),
        ("Wine & Spirits, drink", "Food, Drink, and Lodging", "1/–", "0", "Common", "", ""),
        ("Abacus", "Tools and Kits", "3/4", "0", "Scarce", "", ""),
        ("Animal Trap", "Tools and Kits", "2/6", "1", "Common", "", "Used to catch game (see **Gathering Food andHerbs** on page 127)."),
        ("Antitoxin Kit", "Tools and Kits", "3GC", "0", "Scarce", "", "Contains a small knife, herbs, and a jar of leeches."),
        ("Boat Hook", "Tools and Kits", "5/–", "1", "Common", "", ""),
        ("Broom", "Tools and Kits", "10d", "2", "Common", "", ""),
        ("Bucket", "Tools and Kits", "2/6", "1", "Common", "", ""),
        ("Chisel", "Tools and Kits", "4/2", "0", "Common", "", ""),
        ("Comb", "Tools and Kits", "10d", "0", "Common", "", ""),
        ("Crowbar", "Tools and Kits", "2/6", "1", "Common", "", ""),
        ("Crutch", "Tools and Kits", "3/–", "2", "Common", "", ""),
        ("Disguise Kit", "Tools and Kits", "6/6", "0", "Scarce", "", "Contains enough props for four disguises (e.g. wigs"),
        ("Ear Pick", "Tools and Kits", "2/–", "0", "Scarce", "", ""),
        ("Fish Hooks (12)", "Tools and Kits", "1/–", "0", "Common", "", ""),
        ("Floor Brush", "Tools and Kits", "1/6", "0", "Common", "", ""),
        ("Gavel", "Tools and Kits", "1GC", "0", "Scarce", "", ""),
        ("Hammer", "Tools and Kits", "3/–", "0", "Common", "", ""),
        ("Hand Mirror", "Tools and Kits", "1GC 1/6", "0", "Exotic", "", ""),
        ("Hoe", "Tools and Kits", "4/–", "2", "Common", "", ""),
        ("Key", "Tools and Kits", "1/–", "0", "Common", "", ""),
        ("Knife", "Tools and Kits", "8/–", "0", "Common", "", ""),
        ("Lock Picks", "Tools and Kits", "15/–", "0", "Scarce", "", "An assortment of small, variously-shaped tools"),
        ("Manacles", "Tools and Kits", "18/–", "0", "Scarce", "", "Prisoners trying to break out of manacles suffer 1"),
        ("Mop", "Tools and Kits", "1/–", "2", "Common", "", ""),
        ("Nails (12)", "Tools and Kits", "2d", "0", "Common", "", ""),
        ("Paint Brush", "Tools and Kits", "4/–", "0", "Common", "", ""),
        ("Pestle & Mortar", "Tools and Kits", "14/–", "0", "Common", "", ""),
        ("Pick", "Tools and Kits", "18/–", "1", "Scarce", "", ""),
        ("Pole (3 yards)", "Tools and Kits", "8/–", "3", "Common", "", ""),
        ("Quill Pen", "Tools and Kits", "3/–", "0", "Common", "", ""),
        ("Rake", "Tools and Kits", "4/6", "2", "Common", "", ""),
        ("Reading Lens", "Tools and Kits", "3GC", "0", "Rare", "", "Glass lenses with handles provide a +20 bonus to"),
        ("Saw", "Tools and Kits", "6/–", "1", "Common", "", ""),
        ("Sickle", "Tools and Kits", "1GC", "1", "Common", "", ""),
        ("Spade", "Tools and Kits", "8/–", "2", "Common", "", ""),
        ("Spike", "Tools and Kits", "1/–", "0", "Common", "", ""),
        ("Stamp, engraved", "Tools and Kits", "5GC", "0", "Scarce", "", ""),
        ("Tongs, steel", "Tools and Kits", "16/–", "0", "Common", "", ""),
        ("Telescope", "Tools and Kits", "5GC", "0", "Rare", "", ""),
        ("Tweezers", "Tools and Kits", "1/–", "0", "Scarce", "", ""),
        ("Writing Kit", "Tools and Kits", "2GC", "0", "Scarce", "", "Contains a quill pen, inkpot, and ink blotter."),
        ("Book, Apothecary", "Books and Documents", "8GC", "1", "Scarce", "", "Apothecary books are usually hand-written."),
        ("Book, Art", "Books and Documents", "5GC", "1", "Scarce", "", "Plays, poems, and ballads or perhaps musical"),
        ("Book, Cryptography", "Books and Documents", "8GC", "1", "Exotic", "", "Where individual ciphers and encryption"),
        ("Book, Engineer", "Books and Documents", "3GC", "1", "Scarce", "", "The majority of engineering books are pressprinted. Engineering is an advanced science in the Empire,"),
        ("Book, Law", "Books and Documents", "15GC", "1", "Rare", "", "Laws vary considerably from one region to the next."),
        ("Book, Magic", "Books and Documents", "20GC", "1", "Exotic", "", "Spell grimoires are usually scribed by wizards, and"),
        ("Book, Medicine", "Books and Documents", "15GC", "1", "Rare", "", "Medical texts can either be scribed or pressprinted, depending on the authoring physician’s prestige."),
        ("Book, Religion", "Books and Documents", "1GC", "1", "Common", "", "Religions books come in all forms in the"),
        ("Guild License", "Books and Documents", "N/A", "0", "N/A", "", "Guild licenses are usually printed on single sheets"),
        ("Leafet", "Books and Documents", "1/–", "0", "Common", "", ""),
        ("Legal Document", "Books and Documents", "3/–", "0", "Common", "", "Asimple legal document such as a will, IOU"),
        ("Map", "Books and Documents", "3GC", "0", "Scarce", "", ""),
        ("Parchment/sheet", "Books and Documents", "1/–", "0", "Common", "", ""),
        ("Trade Tools", "Trade Tools and Workshops", "3GC", "1", "Rare", "", ""),
        ("Workshop", "Trade Tools and Workshops", "80GC", "N/A", "Exotic", "", ""),
        ("Cart", "Animals and Vehicles", "20GC", "–", "Common", "25", "One driver and one draft animal required."),
        ("Chicken", "Animals and Vehicles", "5d", "1", "Common", "0", ""),
        ("Coach", "Animals and Vehicles", "150GC", "–", "Rare", "80", "Two drivers and four horses are standard."),
        ("Coracle", "Animals and Vehicles", "2GC", "6", "Scarce", "10", "Coracles are small, lightweight boats that accommodate"),
        ("Destrier", "Animals and Vehicles", "230GC", "–", "Scarce", "20", "Horse trained for war."),
        ("Dog collar and lead", "Animals and Vehicles", "1/7", "0", "Common", "–", ""),
        ("Draught Horse", "Animals and Vehicles", "4GC", "–", "Common", "20", ""),
        ("Homing Pigeons", "Animals and Vehicles", "3/–", "1", "Scarce", "0", ""),
        ("Hunting Dog", "Animals and Vehicles", "2GC", "–", "Rare", "0", ""),
        ("Light Warhorse", "Animals and Vehicles", "70GC", "–", "Common", "18", ""),
        ("Monkey", "Animals and Vehicles", "10GC", "2", "Rare", "1", ""),
        ("Mule", "Animals and Vehicles", "5GC", "–", "Common", "14", ""),
        ("Pony", "Animals and Vehicles", "10GC", "–", "Common", "14", ""),
        ("Riding Horse", "Animals and Vehicles", "15GC", "–", "Common", "16", ""),
        ("River Barge", "Animals and Vehicles", "225GC", "–", "Rare", "300", "Three crew are standard."),
        ("Row Boat", "Animals and Vehicles", "6GC", "–", "Scarce", "60", "One rower is standard."),
        ("Saddle and Harness", "Animals and Vehicles", "6GC", "4", "Common", "–", ""),
        ("Wagon", "Animals and Vehicles", "75GC", "–", "Common", "30", "One driver and two horses are standard."),
        ("Worms (6)", "Animals and Vehicles", "1d", "0", "Common", "–", ""),
        ("Black Lotus", "Drugs and Poisons", "20GC", "0", "Exotic", "", "This deadly plant grows in Southland jungles and is"),
        ("Heartkill", "Drugs and Poisons", "40GC", "0", "Exotic", "", "Combining the venoms from an Amphisbaena (a rare,"),
        ("Mad Cap Mushrooms", "Drugs and Poisons", "5GC", "0", "Exotic", "", "These hallucinogenic mushrooms are"),
        ("Mandrake Root", "Drugs and Poisons", "1GC", "0", "Rare", "", "This highly-addictive deliriant grows under"),
        ("Moonfower", "Drugs and Poisons", "5GC", "0", "Scarce", "", ""),
        ("Ranald’s Delight", "Drugs and Poisons", "18/–", "0", "Scarce", "", "This highly-addictive stimulant is a synthetic"),
        ("Spit", "Drugs and Poisons", "1GC 5/–", "0", "Rare", "", "Extracted from Chameleoleeches found in the marshes of"),
        ("Weirdroot", "Drugs and Poisons", "4/–", "0", "Rare", "", "One of the most common street-drugs in the"),
        ("Digestive Tonic", "Herbs and Draughts", "3/–", "0", "Common", "", "Provides +20 to recovery Tests from stomach"),
        ("Earth Root", "Herbs and Draughts", "5GC", "0", "Scarce", "", "This herb is ingested to negate the effects of Buboes"),
        ("Faxtoryll", "Herbs and Draughts", "15/–", "0", "Exotic", "", "When smeared on a wound, poultices made from this"),
        ("Healing Draught", "Herbs and Draughts", "10/–", "0", "Scarce", "", "If you have more than 0 Wounds, recover"),
        ("Healing Poultice", "Herbs and Draughts", "12/–", "0", "Common", "", "This foul-smelling medicinal wrap is made"),
        ("Nightshade", "Herbs and Draughts", "3GC", "0", "Rare", "", "Consuming this herb causes the victim to fall into"),
        ("Salwort", "Herbs and Draughts", "12/–", "0", "Common", "", "When held under someone’s nose, the aroma from a"),
        ("Vitality Draught", "Herbs and Draughts", "18/–", "0", "Scarce", "", "Drinking this draught instantly removes all"),
        ("Eye Patch", "Prosthetics", "6d", "0", "Common", "", "Often decorated, an eye patch is used to cover scarred"),
        ("False Eye", "Prosthetics", "1GC", "0", "Rare", "", "Particularly popular amongst the rich who prefer not"),
        ("False Leg", "Prosthetics", "16/–", "2", "Scarce", "", "A False Leg (or just a False Foot, for half price),"),
        ("Gilded Nose", "Prosthetics", "18/–", "0", "Scarce", "", "Though most are made of wood or ceramic, the"),
        ("Hook", "Prosthetics", "3/4", "1", "Common", "", "You have a hook strapped where you used to have a hand."),
        ("Engineering Marvel", "Prosthetics", "20GC", "1", "Exotic", "", "Only for the exceedingly rich, you"),
        ("Wooden teeth", "Prosthetics", "10/–", "0", "Rare", "", "False Teeth are often beautifully carved and"),
        ("Ball", "Miscellaneous Trappings", "5d", "0", "Common", "", ""),
        ("Bandage", "Miscellaneous Trappings", "4d", "0", "Common", "", "Asuccessful Heal Test removes +1 extra Bleeding"),
        ("Baton", "Miscellaneous Trappings", "1/–", "0", "Common", "", ""),
        ("Bedroll", "Miscellaneous Trappings", "6/–", "1", "Common", "", "Endurance Tests rolled to resist cold exposure (see page"),
        ("Blanket", "Miscellaneous Trappings", "8d", "0", "Common", "", ""),
        ("Candle (dozen)", "Miscellaneous Trappings", "1/–", "0", "Common", "", ""),
        ("Canvas Tarp", "Miscellaneous Trappings", "8/–", "1", "Common", "", ""),
        ("Chalk", "Miscellaneous Trappings", "10d", "0", "Common", "", ""),
        ("Charcoal stick", "Miscellaneous Trappings", "10d", "0", "Common", "", ""),
        ("Cutlery", "Miscellaneous Trappings", "3/6", "0", "Common", "", ""),
        ("Davrich Lamp", "Miscellaneous Trappings", "2GC", "1", "Rare", "", "Asafety lamp emitting the light of a candle,"),
        ("Deck of Cards", "Miscellaneous Trappings", "1/–", "0", "Common", "", ""),
        ("Cooking Pot", "Miscellaneous Trappings", "8/–", "1", "Common", "", ""),
        ("Cup", "Miscellaneous Trappings", "8d", "0", "Common", "", ""),
        ("Dice", "Miscellaneous Trappings", "10d", "0", "Common", "", ""),
        ("Doll", "Miscellaneous Trappings", "2/–", "0", "Common", "", ""),
        ("Grappling Hook", "Miscellaneous Trappings", "1GC 0/10", "1", "Scarce", "", "Coupled with a rope, allows unscalable"),
        ("Instrument", "Miscellaneous Trappings", "2GC", "1", "Rare", "", "Various instruments are included in this category."),
        ("Lamp Oil", "Miscellaneous Trappings", "2/–", "0", "Common", "", "Contains enough fuel for 4 hours of standard use, or"),
        ("Lantern", "Miscellaneous Trappings", "12/–", "1", "Common", "", "Provides illumination for 20 yards."),
        ("Storm Lantern", "Miscellaneous Trappings", "1GC", "1", "Scarce", "", "Shutters protect the flame from wind, and also"),
        ("Match", "Miscellaneous Trappings", "1d", "0", "Common", "", ""),
        ("Pan", "Miscellaneous Trappings", "7/6", "1", "Common", "", ""),
        ("Pipe and Tobacco", "Miscellaneous Trappings", "3/4", "0", "Scarce", "", ""),
        ("Placard", "Miscellaneous Trappings", "1/–", "2", "Common", "", ""),
        ("Plate", "Miscellaneous Trappings", "1/–", "0", "Common", "", ""),
        ("Bowl", "Miscellaneous Trappings", "1/–", "0", "Common", "", ""),
        ("Rags", "Miscellaneous Trappings", "1d", "0", "Common", "", ""),
        ("Rope, 10 yards", "Miscellaneous Trappings", "8/4", "1", "Common", "", ""),
        ("Tent", "Miscellaneous Trappings", "12/–", "2", "Scarce", "", "Amedium-sized tent accommodating four people sleeping"),
        ("Tinderbox", "Miscellaneous Trappings", "4/2", "0", "Common", "", ""),
    ]
    with conn:
        for name, cat, price, enc, avail, carries, desc in items:
            conn.execute(
                "INSERT OR REPLACE INTO trappings_catalog (name, category, price, encumbrance, availability, carries, description) VALUES (?, ?, ?, ?, ?, ?, ?);",
                (name, cat, price, enc, avail, carries, desc)
            )

def seed_trappings_catalog() -> None:
    conn = get_connection()
    items = [
        ("Backpack", "Packs and Containers", "4/10", "2", "Common", "4", "Counts as ‘worn’ when strapped to your back."),
        ("Barrel", "Packs and Containers", "8/–", "6", "Common", "12", "Capacity: 32 gallons of liquid."),
        ("Cask", "Packs and Containers", "3/–", "2", "Common", "4", "Capacity: 10 gallons of liquid."),
        ("Flask", "Packs and Containers", "5/–", "0", "Common", "0", "Capacity: 1 pint of liquid."),
        ("Jug", "Packs and Containers", "3/2", "1", "Common", "1", "Capacity: 1 gallon of liquid."),
        ("Pewter Stein", "Packs and Containers", "4/–", "0", "Common", "0", ""),
        ("Pouch", "Packs and Containers", "4d", "0", "Common", "1", ""),
        ("Sack", "Packs and Containers", "1/–", "2", "Common", "4", "Requires 1 hand to carry."),
        ("Sack, Large", "Packs and Containers", "1/6", "3", "Common", "6", "Requires 1 hand to carry (or 2 hands if full)."),
        ("Saddlebags", "Packs and Containers", "18/–", "4", "Common", "8", ""),
        ("Sling Bag", "Packs and Containers", "1/–", "1", "Common", "2", "Counts as ‘worn’ when slung over your shoulder."),
        ("Scroll Case", "Packs and Containers", "16/–", "0", "Scarce", "0", ""),
        ("Waterskin", "Packs and Containers", "1/8", "1", "Common", "1", "Capacity: 1 gallon of liquid."),
        ("Amulet", "Clothing and Accessories", "2d", "0", "Common", "", ""),
        ("Boots", "Clothing and Accessories", "5/–", "1", "Common", "", ""),
        ("Cloak", "Clothing and Accessories", "10/–", "1", "Common", "", "Protects wearer against the elements."),
        ("Clothing", "Clothing and Accessories", "6/–", "1", "Common", "", ""),
        ("Coat", "Clothing and Accessories", "18/–", "1", "Common", "", "Protects wearer against the elements and extreme cold;"),
        ("Costume", "Clothing and Accessories", "1GC", "1", "Scarce", "", ""),
        ("Courtly Garb", "Clothing and Accessories", "12GC", "1", "Scarce", "", "Nobles’ garb features embellishments such as lace"),
        ("Face Powder", "Clothing and Accessories", "10/–", "0", "Common", "", ""),
        ("Gloves", "Clothing and Accessories", "4/–", "0", "Common", "", ""),
        ("Hood or Mask", "Clothing and Accessories", "5/–", "0", "Common", "", ""),
        ("Jewellery", "Clothing and Accessories", "Varies", "0", "Common", "", "Prices vary by craftsmanship, metal type, and gem"),
        ("Perfume", "Clothing and Accessories", "10/–", "0", "Common", "", ""),
        ("Pins (6)", "Clothing and Accessories", "10 s", "0", "Scarce", "", ""),
        ("Religious Symbol", "Clothing and Accessories", "6/8", "0", "Common", "", ""),
        ("Robes", "Clothing and Accessories", "2GC", "1", "Common", "", ""),
        ("Sceptre", "Clothing and Accessories", "8GC", "1", "Rare", "", "The highest-ranking legal officials carry sceptres to"),
        ("Shoes", "Clothing and Accessories", "5/–", "0", "Common", "", ""),
        ("Signet Ring", "Clothing and Accessories", "5GC", "0", "Rare", "", "Gold rings with engraved stamps are worn by"),
        ("Tattoo", "Clothing and Accessories", "4/– +", "0", "Scarce", "", ""),
        ("Uniform", "Clothing and Accessories", "1GC 2/–", "1", "Scarce", "", ""),
        ("Walking Cane", "Clothing and Accessories", "3GC", "1", "Common", "", "Polished wooden canes with metal caps are status"),
        ("Ale, pint", "Food, Drink, and Lodging", "3d", "0", "Common", "", ""),
        ("Ale, keg", "Food, Drink, and Lodging", "3 s", "2", "Common", "", "Capacity 3 gallons. Empty kegs can be refilled for 18d."),
        ("Bugman’s XXXXXX Ale, pint", "Food, Drink, and Lodging", "9d", "0", "Exotic", "", ""),
        ("Food, groceries/day", "Food, Drink, and Lodging", "10d", "1", "Common", "", ""),
        ("Meal, inn", "Food, Drink, and Lodging", "1/–", "0", "Common", "", ""),
        ("Rations, 1 day", "Food, Drink, and Lodging", "2/–", "0", "Common", "", ""),
        ("Room, common/night", "Food, Drink, and Lodging", "10d", "–", "Common", "", ""),
        ("Room, private/night", "Food, Drink, and Lodging", "10/–", "–", "Common", "", ""),
        ("Spirits, pint", "Food, Drink, and Lodging", "2/–", "0", "Common", "", ""),
        ("Stables/night", "Food, Drink, and Lodging", "10d", "–", "Common", "", ""),
        ("Wine, bottle", "Food, Drink, and Lodging", "10d", "0", "Common", "", ""),
        ("Wine & Spirits, drink", "Food, Drink, and Lodging", "1/–", "0", "Common", "", ""),
        ("Abacus", "Tools and Kits", "3/4", "0", "Scarce", "", ""),
        ("Animal Trap", "Tools and Kits", "2/6", "1", "Common", "", "Used to catch game (see **Gathering Food andHerbs** on page 127)."),
        ("Antitoxin Kit", "Tools and Kits", "3GC", "0", "Scarce", "", "Contains a small knife, herbs, and a jar of leeches."),
        ("Boat Hook", "Tools and Kits", "5/–", "1", "Common", "", ""),
        ("Broom", "Tools and Kits", "10d", "2", "Common", "", ""),
        ("Bucket", "Tools and Kits", "2/6", "1", "Common", "", ""),
        ("Chisel", "Tools and Kits", "4/2", "0", "Common", "", ""),
        ("Comb", "Tools and Kits", "10d", "0", "Common", "", ""),
        ("Crowbar", "Tools and Kits", "2/6", "1", "Common", "", ""),
        ("Crutch", "Tools and Kits", "3/–", "2", "Common", "", ""),
        ("Disguise Kit", "Tools and Kits", "6/6", "0", "Scarce", "", "Contains enough props for four disguises (e.g. wigs"),
        ("Ear Pick", "Tools and Kits", "2/–", "0", "Scarce", "", ""),
        ("Fish Hooks (12)", "Tools and Kits", "1/–", "0", "Common", "", ""),
        ("Floor Brush", "Tools and Kits", "1/6", "0", "Common", "", ""),
        ("Gavel", "Tools and Kits", "1GC", "0", "Scarce", "", ""),
        ("Hammer", "Tools and Kits", "3/–", "0", "Common", "", ""),
        ("Hand Mirror", "Tools and Kits", "1GC 1/6", "0", "Exotic", "", ""),
        ("Hoe", "Tools and Kits", "4/–", "2", "Common", "", ""),
        ("Key", "Tools and Kits", "1/–", "0", "Common", "", ""),
        ("Knife", "Tools and Kits", "8/–", "0", "Common", "", ""),
        ("Lock Picks", "Tools and Kits", "15/–", "0", "Scarce", "", "An assortment of small, variously-shaped tools"),
        ("Manacles", "Tools and Kits", "18/–", "0", "Scarce", "", "Prisoners trying to break out of manacles suffer 1"),
        ("Mop", "Tools and Kits", "1/–", "2", "Common", "", ""),
        ("Nails (12)", "Tools and Kits", "2d", "0", "Common", "", ""),
        ("Paint Brush", "Tools and Kits", "4/–", "0", "Common", "", ""),
        ("Pestle & Mortar", "Tools and Kits", "14/–", "0", "Common", "", ""),
        ("Pick", "Tools and Kits", "18/–", "1", "Scarce", "", ""),
        ("Pole (3 yards)", "Tools and Kits", "8/–", "3", "Common", "", ""),
        ("Quill Pen", "Tools and Kits", "3/–", "0", "Common", "", ""),
        ("Rake", "Tools and Kits", "4/6", "2", "Common", "", ""),
        ("Reading Lens", "Tools and Kits", "3GC", "0", "Rare", "", "Glass lenses with handles provide a +20 bonus to"),
        ("Saw", "Tools and Kits", "6/–", "1", "Common", "", ""),
        ("Sickle", "Tools and Kits", "1GC", "1", "Common", "", ""),
        ("Spade", "Tools and Kits", "8/–", "2", "Common", "", ""),
        ("Spike", "Tools and Kits", "1/–", "0", "Common", "", ""),
        ("Stamp, engraved", "Tools and Kits", "5GC", "0", "Scarce", "", ""),
        ("Tongs, steel", "Tools and Kits", "16/–", "0", "Common", "", ""),
        ("Telescope", "Tools and Kits", "5GC", "0", "Rare", "", ""),
        ("Tweezers", "Tools and Kits", "1/–", "0", "Scarce", "", ""),
        ("Writing Kit", "Tools and Kits", "2GC", "0", "Scarce", "", "Contains a quill pen, inkpot, and ink blotter."),
        ("Book, Apothecary", "Books and Documents", "8GC", "1", "Scarce", "", "Apothecary books are usually hand-written."),
        ("Book, Art", "Books and Documents", "5GC", "1", "Scarce", "", "Plays, poems, and ballads or perhaps musical"),
        ("Book, Cryptography", "Books and Documents", "8GC", "1", "Exotic", "", "Where individual ciphers and encryption"),
        ("Book, Engineer", "Books and Documents", "3GC", "1", "Scarce", "", "The majority of engineering books are pressprinted. Engineering is an advanced science in the Empire,"),
        ("Book, Law", "Books and Documents", "15GC", "1", "Rare", "", "Laws vary considerably from one region to the next."),
        ("Book, Magic", "Books and Documents", "20GC", "1", "Exotic", "", "Spell grimoires are usually scribed by wizards, and"),
        ("Book, Medicine", "Books and Documents", "15GC", "1", "Rare", "", "Medical texts can either be scribed or pressprinted, depending on the authoring physician’s prestige."),
        ("Book, Religion", "Books and Documents", "1GC", "1", "Common", "", "Religions books come in all forms in the"),
        ("Guild License", "Books and Documents", "N/A", "0", "N/A", "", "Guild licenses are usually printed on single sheets"),
        ("Leafet", "Books and Documents", "1/–", "0", "Common", "", ""),
        ("Legal Document", "Books and Documents", "3/–", "0", "Common", "", "Asimple legal document such as a will, IOU"),
        ("Map", "Books and Documents", "3GC", "0", "Scarce", "", ""),
        ("Parchment/sheet", "Books and Documents", "1/–", "0", "Common", "", ""),
        ("Trade Tools", "Trade Tools and Workshops", "3GC", "1", "Rare", "", ""),
        ("Workshop", "Trade Tools and Workshops", "80GC", "N/A", "Exotic", "", ""),
        ("Cart", "Animals and Vehicles", "20GC", "–", "Common", "25", "One driver and one draft animal required."),
        ("Chicken", "Animals and Vehicles", "5d", "1", "Common", "0", ""),
        ("Coach", "Animals and Vehicles", "150GC", "–", "Rare", "80", "Two drivers and four horses are standard."),
        ("Coracle", "Animals and Vehicles", "2GC", "6", "Scarce", "10", "Coracles are small, lightweight boats that accommodate"),
        ("Destrier", "Animals and Vehicles", "230GC", "–", "Scarce", "20", "Horse trained for war."),
        ("Dog collar and lead", "Animals and Vehicles", "1/7", "0", "Common", "–", ""),
        ("Draught Horse", "Animals and Vehicles", "4GC", "–", "Common", "20", ""),
        ("Homing Pigeons", "Animals and Vehicles", "3/–", "1", "Scarce", "0", ""),
        ("Hunting Dog", "Animals and Vehicles", "2GC", "–", "Rare", "0", ""),
        ("Light Warhorse", "Animals and Vehicles", "70GC", "–", "Common", "18", ""),
        ("Monkey", "Animals and Vehicles", "10GC", "2", "Rare", "1", ""),
        ("Mule", "Animals and Vehicles", "5GC", "–", "Common", "14", ""),
        ("Pony", "Animals and Vehicles", "10GC", "–", "Common", "14", ""),
        ("Riding Horse", "Animals and Vehicles", "15GC", "–", "Common", "16", ""),
        ("River Barge", "Animals and Vehicles", "225GC", "–", "Rare", "300", "Three crew are standard."),
        ("Row Boat", "Animals and Vehicles", "6GC", "–", "Scarce", "60", "One rower is standard."),
        ("Saddle and Harness", "Animals and Vehicles", "6GC", "4", "Common", "–", ""),
        ("Wagon", "Animals and Vehicles", "75GC", "–", "Common", "30", "One driver and two horses are standard."),
        ("Worms (6)", "Animals and Vehicles", "1d", "0", "Common", "–", ""),
        ("Black Lotus", "Drugs and Poisons", "20GC", "0", "Exotic", "", "This deadly plant grows in Southland jungles and is"),
        ("Heartkill", "Drugs and Poisons", "40GC", "0", "Exotic", "", "Combining the venoms from an Amphisbaena (a rare,"),
        ("Mad Cap Mushrooms", "Drugs and Poisons", "5GC", "0", "Exotic", "", "These hallucinogenic mushrooms are"),
        ("Mandrake Root", "Drugs and Poisons", "1GC", "0", "Rare", "", "This highly-addictive deliriant grows under"),
        ("Moonfower", "Drugs and Poisons", "5GC", "0", "Scarce", "", ""),
        ("Ranald’s Delight", "Drugs and Poisons", "18/–", "0", "Scarce", "", "This highly-addictive stimulant is a synthetic"),
        ("Spit", "Drugs and Poisons", "1GC 5/–", "0", "Rare", "", "Extracted from Chameleoleeches found in the marshes of"),
        ("Weirdroot", "Drugs and Poisons", "4/–", "0", "Rare", "", "One of the most common street-drugs in the"),
        ("Digestive Tonic", "Herbs and Draughts", "3/–", "0", "Common", "", "Provides +20 to recovery Tests from stomach"),
        ("Earth Root", "Herbs and Draughts", "5GC", "0", "Scarce", "", "This herb is ingested to negate the effects of Buboes"),
        ("Faxtoryll", "Herbs and Draughts", "15/–", "0", "Exotic", "", "When smeared on a wound, poultices made from this"),
        ("Healing Draught", "Herbs and Draughts", "10/–", "0", "Scarce", "", "If you have more than 0 Wounds, recover"),
        ("Healing Poultice", "Herbs and Draughts", "12/–", "0", "Common", "", "This foul-smelling medicinal wrap is made"),
        ("Nightshade", "Herbs and Draughts", "3GC", "0", "Rare", "", "Consuming this herb causes the victim to fall into"),
        ("Salwort", "Herbs and Draughts", "12/–", "0", "Common", "", "When held under someone’s nose, the aroma from a"),
        ("Vitality Draught", "Herbs and Draughts", "18/–", "0", "Scarce", "", "Drinking this draught instantly removes all"),
        ("Eye Patch", "Prosthetics", "6d", "0", "Common", "", "Often decorated, an eye patch is used to cover scarred"),
        ("False Eye", "Prosthetics", "1GC", "0", "Rare", "", "Particularly popular amongst the rich who prefer not"),
        ("False Leg", "Prosthetics", "16/–", "2", "Scarce", "", "A False Leg (or just a False Foot, for half price),"),
        ("Gilded Nose", "Prosthetics", "18/–", "0", "Scarce", "", "Though most are made of wood or ceramic, the"),
        ("Hook", "Prosthetics", "3/4", "1", "Common", "", "You have a hook strapped where you used to have a hand."),
        ("Engineering Marvel", "Prosthetics", "20GC", "1", "Exotic", "", "Only for the exceedingly rich, you"),
        ("Wooden teeth", "Prosthetics", "10/–", "0", "Rare", "", "False Teeth are often beautifully carved and"),
        ("Ball", "Miscellaneous Trappings", "5d", "0", "Common", "", ""),
        ("Bandage", "Miscellaneous Trappings", "4d", "0", "Common", "", "Asuccessful Heal Test removes +1 extra Bleeding"),
        ("Baton", "Miscellaneous Trappings", "1/–", "0", "Common", "", ""),
        ("Bedroll", "Miscellaneous Trappings", "6/–", "1", "Common", "", "Endurance Tests rolled to resist cold exposure (see page"),
        ("Blanket", "Miscellaneous Trappings", "8d", "0", "Common", "", ""),
        ("Candle (dozen)", "Miscellaneous Trappings", "1/–", "0", "Common", "", ""),
        ("Canvas Tarp", "Miscellaneous Trappings", "8/–", "1", "Common", "", ""),
        ("Chalk", "Miscellaneous Trappings", "10d", "0", "Common", "", ""),
        ("Charcoal stick", "Miscellaneous Trappings", "10d", "0", "Common", "", ""),
        ("Cutlery", "Miscellaneous Trappings", "3/6", "0", "Common", "", ""),
        ("Davrich Lamp", "Miscellaneous Trappings", "2GC", "1", "Rare", "", "Asafety lamp emitting the light of a candle,"),
        ("Deck of Cards", "Miscellaneous Trappings", "1/–", "0", "Common", "", ""),
        ("Cooking Pot", "Miscellaneous Trappings", "8/–", "1", "Common", "", ""),
        ("Cup", "Miscellaneous Trappings", "8d", "0", "Common", "", ""),
        ("Dice", "Miscellaneous Trappings", "10d", "0", "Common", "", ""),
        ("Doll", "Miscellaneous Trappings", "2/–", "0", "Common", "", ""),
        ("Grappling Hook", "Miscellaneous Trappings", "1GC 0/10", "1", "Scarce", "", "Coupled with a rope, allows unscalable"),
        ("Instrument", "Miscellaneous Trappings", "2GC", "1", "Rare", "", "Various instruments are included in this category."),
        ("Lamp Oil", "Miscellaneous Trappings", "2/–", "0", "Common", "", "Contains enough fuel for 4 hours of standard use, or"),
        ("Lantern", "Miscellaneous Trappings", "12/–", "1", "Common", "", "Provides illumination for 20 yards."),
        ("Storm Lantern", "Miscellaneous Trappings", "1GC", "1", "Scarce", "", "Shutters protect the flame from wind, and also"),
        ("Match", "Miscellaneous Trappings", "1d", "0", "Common", "", ""),
        ("Pan", "Miscellaneous Trappings", "7/6", "1", "Common", "", ""),
        ("Pipe and Tobacco", "Miscellaneous Trappings", "3/4", "0", "Scarce", "", ""),
        ("Placard", "Miscellaneous Trappings", "1/–", "2", "Common", "", ""),
        ("Plate", "Miscellaneous Trappings", "1/–", "0", "Common", "", ""),
        ("Bowl", "Miscellaneous Trappings", "1/–", "0", "Common", "", ""),
        ("Rags", "Miscellaneous Trappings", "1d", "0", "Common", "", ""),
        ("Rope, 10 yards", "Miscellaneous Trappings", "8/4", "1", "Common", "", ""),
        ("Tent", "Miscellaneous Trappings", "12/–", "2", "Scarce", "", "Amedium-sized tent accommodating four people sleeping"),
        ("Tinderbox", "Miscellaneous Trappings", "4/2", "0", "Common", "", ""),
    ]
    with conn:
        for name, cat, price, enc, avail, carries, desc in items:
            conn.execute(
                "INSERT OR REPLACE INTO trappings_catalog (name, category, price, encumbrance, availability, carries, description) VALUES (?, ?, ?, ?, ?, ?, ?);",
                (name, cat, price, enc, avail, carries, desc)
            )

def seed_trappings_catalog() -> None:
    conn = get_connection()
    items = [
        ("Backpack", "Packs and Containers", "4/10", "2", "Common", "4", "Counts as ‘worn’ when strapped to your back."),
        ("Barrel", "Packs and Containers", "8/–", "6", "Common", "12", "Capacity: 32 gallons of liquid."),
        ("Cask", "Packs and Containers", "3/–", "2", "Common", "4", "Capacity: 10 gallons of liquid."),
        ("Flask", "Packs and Containers", "5/–", "0", "Common", "0", "Capacity: 1 pint of liquid."),
        ("Jug", "Packs and Containers", "3/2", "1", "Common", "1", "Capacity: 1 gallon of liquid."),
        ("Pewter Stein", "Packs and Containers", "4/–", "0", "Common", "0", ""),
        ("Pouch", "Packs and Containers", "4d", "0", "Common", "1", ""),
        ("Sack", "Packs and Containers", "1/–", "2", "Common", "4", "Requires 1 hand to carry."),
        ("Sack, Large", "Packs and Containers", "1/6", "3", "Common", "6", "Requires 1 hand to carry (or 2 hands if full)."),
        ("Saddlebags", "Packs and Containers", "18/–", "4", "Common", "8", ""),
        ("Sling Bag", "Packs and Containers", "1/–", "1", "Common", "2", "Counts as ‘worn’ when slung over your shoulder."),
        ("Scroll Case", "Packs and Containers", "16/–", "0", "Scarce", "0", ""),
        ("Waterskin", "Packs and Containers", "1/8", "1", "Common", "1", "Capacity: 1 gallon of liquid."),
        ("Amulet", "Clothing and Accessories", "2d", "0", "Common", "", ""),
        ("Boots", "Clothing and Accessories", "5/–", "1", "Common", "", ""),
        ("Cloak", "Clothing and Accessories", "10/–", "1", "Common", "", "Protects wearer against the elements."),
        ("Clothing", "Clothing and Accessories", "6/–", "1", "Common", "", ""),
        ("Coat", "Clothing and Accessories", "18/–", "1", "Common", "", "Protects wearer against the elements and extreme cold;"),
        ("Costume", "Clothing and Accessories", "1GC", "1", "Scarce", "", ""),
        ("Courtly Garb", "Clothing and Accessories", "12GC", "1", "Scarce", "", "Nobles’ garb features embellishments such as lace"),
        ("Face Powder", "Clothing and Accessories", "10/–", "0", "Common", "", ""),
        ("Gloves", "Clothing and Accessories", "4/–", "0", "Common", "", ""),
        ("Hood or Mask", "Clothing and Accessories", "5/–", "0", "Common", "", ""),
        ("Jewellery", "Clothing and Accessories", "Varies", "0", "Common", "", "Prices vary by craftsmanship, metal type, and gem"),
        ("Perfume", "Clothing and Accessories", "10/–", "0", "Common", "", ""),
        ("Pins (6)", "Clothing and Accessories", "10 s", "0", "Scarce", "", ""),
        ("Religious Symbol", "Clothing and Accessories", "6/8", "0", "Common", "", ""),
        ("Robes", "Clothing and Accessories", "2GC", "1", "Common", "", ""),
        ("Sceptre", "Clothing and Accessories", "8GC", "1", "Rare", "", "The highest-ranking legal officials carry sceptres to"),
        ("Shoes", "Clothing and Accessories", "5/–", "0", "Common", "", ""),
        ("Signet Ring", "Clothing and Accessories", "5GC", "0", "Rare", "", "Gold rings with engraved stamps are worn by"),
        ("Tattoo", "Clothing and Accessories", "4/– +", "0", "Scarce", "", ""),
        ("Uniform", "Clothing and Accessories", "1GC 2/–", "1", "Scarce", "", ""),
        ("Walking Cane", "Clothing and Accessories", "3GC", "1", "Common", "", "Polished wooden canes with metal caps are status"),
        ("Ale, pint", "Food, Drink, and Lodging", "3d", "0", "Common", "", ""),
        ("Ale, keg", "Food, Drink, and Lodging", "3 s", "2", "Common", "", "Capacity 3 gallons. Empty kegs can be refilled for 18d."),
        ("Bugman’s XXXXXX Ale, pint", "Food, Drink, and Lodging", "9d", "0", "Exotic", "", ""),
        ("Food, groceries/day", "Food, Drink, and Lodging", "10d", "1", "Common", "", ""),
        ("Meal, inn", "Food, Drink, and Lodging", "1/–", "0", "Common", "", ""),
        ("Rations, 1 day", "Food, Drink, and Lodging", "2/–", "0", "Common", "", ""),
        ("Room, common/night", "Food, Drink, and Lodging", "10d", "–", "Common", "", ""),
        ("Room, private/night", "Food, Drink, and Lodging", "10/–", "–", "Common", "", ""),
        ("Spirits, pint", "Food, Drink, and Lodging", "2/–", "0", "Common", "", ""),
        ("Stables/night", "Food, Drink, and Lodging", "10d", "–", "Common", "", ""),
        ("Wine, bottle", "Food, Drink, and Lodging", "10d", "0", "Common", "", ""),
        ("Wine & Spirits, drink", "Food, Drink, and Lodging", "1/–", "0", "Common", "", ""),
        ("Abacus", "Tools and Kits", "3/4", "0", "Scarce", "", ""),
        ("Animal Trap", "Tools and Kits", "2/6", "1", "Common", "", "Used to catch game (see **Gathering Food andHerbs** on page 127)."),
        ("Antitoxin Kit", "Tools and Kits", "3GC", "0", "Scarce", "", "Contains a small knife, herbs, and a jar of leeches."),
        ("Boat Hook", "Tools and Kits", "5/–", "1", "Common", "", ""),
        ("Broom", "Tools and Kits", "10d", "2", "Common", "", ""),
        ("Bucket", "Tools and Kits", "2/6", "1", "Common", "", ""),
        ("Chisel", "Tools and Kits", "4/2", "0", "Common", "", ""),
        ("Comb", "Tools and Kits", "10d", "0", "Common", "", ""),
        ("Crowbar", "Tools and Kits", "2/6", "1", "Common", "", ""),
        ("Crutch", "Tools and Kits", "3/–", "2", "Common", "", ""),
        ("Disguise Kit", "Tools and Kits", "6/6", "0", "Scarce", "", "Contains enough props for four disguises (e.g. wigs"),
        ("Ear Pick", "Tools and Kits", "2/–", "0", "Scarce", "", ""),
        ("Fish Hooks (12)", "Tools and Kits", "1/–", "0", "Common", "", ""),
        ("Floor Brush", "Tools and Kits", "1/6", "0", "Common", "", ""),
        ("Gavel", "Tools and Kits", "1GC", "0", "Scarce", "", ""),
        ("Hammer", "Tools and Kits", "3/–", "0", "Common", "", ""),
        ("Hand Mirror", "Tools and Kits", "1GC 1/6", "0", "Exotic", "", ""),
        ("Hoe", "Tools and Kits", "4/–", "2", "Common", "", ""),
        ("Key", "Tools and Kits", "1/–", "0", "Common", "", ""),
        ("Knife", "Tools and Kits", "8/–", "0", "Common", "", ""),
        ("Lock Picks", "Tools and Kits", "15/–", "0", "Scarce", "", "An assortment of small, variously-shaped tools"),
        ("Manacles", "Tools and Kits", "18/–", "0", "Scarce", "", "Prisoners trying to break out of manacles suffer 1"),
        ("Mop", "Tools and Kits", "1/–", "2", "Common", "", ""),
        ("Nails (12)", "Tools and Kits", "2d", "0", "Common", "", ""),
        ("Paint Brush", "Tools and Kits", "4/–", "0", "Common", "", ""),
        ("Pestle & Mortar", "Tools and Kits", "14/–", "0", "Common", "", ""),
        ("Pick", "Tools and Kits", "18/–", "1", "Scarce", "", ""),
        ("Pole (3 yards)", "Tools and Kits", "8/–", "3", "Common", "", ""),
        ("Quill Pen", "Tools and Kits", "3/–", "0", "Common", "", ""),
        ("Rake", "Tools and Kits", "4/6", "2", "Common", "", ""),
        ("Reading Lens", "Tools and Kits", "3GC", "0", "Rare", "", "Glass lenses with handles provide a +20 bonus to"),
        ("Saw", "Tools and Kits", "6/–", "1", "Common", "", ""),
        ("Sickle", "Tools and Kits", "1GC", "1", "Common", "", ""),
        ("Spade", "Tools and Kits", "8/–", "2", "Common", "", ""),
        ("Spike", "Tools and Kits", "1/–", "0", "Common", "", ""),
        ("Stamp, engraved", "Tools and Kits", "5GC", "0", "Scarce", "", ""),
        ("Tongs, steel", "Tools and Kits", "16/–", "0", "Common", "", ""),
        ("Telescope", "Tools and Kits", "5GC", "0", "Rare", "", ""),
        ("Tweezers", "Tools and Kits", "1/–", "0", "Scarce", "", ""),
        ("Writing Kit", "Tools and Kits", "2GC", "0", "Scarce", "", "Contains a quill pen, inkpot, and ink blotter."),
        ("Book, Apothecary", "Books and Documents", "8GC", "1", "Scarce", "", "Apothecary books are usually hand-written."),
        ("Book, Art", "Books and Documents", "5GC", "1", "Scarce", "", "Plays, poems, and ballads or perhaps musical"),
        ("Book, Cryptography", "Books and Documents", "8GC", "1", "Exotic", "", "Where individual ciphers and encryption"),
        ("Book, Engineer", "Books and Documents", "3GC", "1", "Scarce", "", "The majority of engineering books are pressprinted. Engineering is an advanced science in the Empire,"),
        ("Book, Law", "Books and Documents", "15GC", "1", "Rare", "", "Laws vary considerably from one region to the next."),
        ("Book, Magic", "Books and Documents", "20GC", "1", "Exotic", "", "Spell grimoires are usually scribed by wizards, and"),
        ("Book, Medicine", "Books and Documents", "15GC", "1", "Rare", "", "Medical texts can either be scribed or pressprinted, depending on the authoring physician’s prestige."),
        ("Book, Religion", "Books and Documents", "1GC", "1", "Common", "", "Religions books come in all forms in the"),
        ("Guild License", "Books and Documents", "N/A", "0", "N/A", "", "Guild licenses are usually printed on single sheets"),
        ("Leafet", "Books and Documents", "1/–", "0", "Common", "", ""),
        ("Legal Document", "Books and Documents", "3/–", "0", "Common", "", "Asimple legal document such as a will, IOU"),
        ("Map", "Books and Documents", "3GC", "0", "Scarce", "", ""),
        ("Parchment/sheet", "Books and Documents", "1/–", "0", "Common", "", ""),
        ("Trade Tools", "Trade Tools and Workshops", "3GC", "1", "Rare", "", ""),
        ("Workshop", "Trade Tools and Workshops", "80GC", "N/A", "Exotic", "", ""),
        ("Cart", "Animals and Vehicles", "20GC", "–", "Common", "25", "One driver and one draft animal required."),
        ("Chicken", "Animals and Vehicles", "5d", "1", "Common", "0", ""),
        ("Coach", "Animals and Vehicles", "150GC", "–", "Rare", "80", "Two drivers and four horses are standard."),
        ("Coracle", "Animals and Vehicles", "2GC", "6", "Scarce", "10", "Coracles are small, lightweight boats that accommodate"),
        ("Destrier", "Animals and Vehicles", "230GC", "–", "Scarce", "20", "Horse trained for war."),
        ("Dog collar and lead", "Animals and Vehicles", "1/7", "0", "Common", "–", ""),
        ("Draught Horse", "Animals and Vehicles", "4GC", "–", "Common", "20", ""),
        ("Homing Pigeons", "Animals and Vehicles", "3/–", "1", "Scarce", "0", ""),
        ("Hunting Dog", "Animals and Vehicles", "2GC", "–", "Rare", "0", ""),
        ("Light Warhorse", "Animals and Vehicles", "70GC", "–", "Common", "18", ""),
        ("Monkey", "Animals and Vehicles", "10GC", "2", "Rare", "1", ""),
        ("Mule", "Animals and Vehicles", "5GC", "–", "Common", "14", ""),
        ("Pony", "Animals and Vehicles", "10GC", "–", "Common", "14", ""),
        ("Riding Horse", "Animals and Vehicles", "15GC", "–", "Common", "16", ""),
        ("River Barge", "Animals and Vehicles", "225GC", "–", "Rare", "300", "Three crew are standard."),
        ("Row Boat", "Animals and Vehicles", "6GC", "–", "Scarce", "60", "One rower is standard."),
        ("Saddle and Harness", "Animals and Vehicles", "6GC", "4", "Common", "–", ""),
        ("Wagon", "Animals and Vehicles", "75GC", "–", "Common", "30", "One driver and two horses are standard."),
        ("Worms (6)", "Animals and Vehicles", "1d", "0", "Common", "–", ""),
        ("Black Lotus", "Drugs and Poisons", "20GC", "0", "Exotic", "", "This deadly plant grows in Southland jungles and is"),
        ("Heartkill", "Drugs and Poisons", "40GC", "0", "Exotic", "", "Combining the venoms from an Amphisbaena (a rare,"),
        ("Mad Cap Mushrooms", "Drugs and Poisons", "5GC", "0", "Exotic", "", "These hallucinogenic mushrooms are"),
        ("Mandrake Root", "Drugs and Poisons", "1GC", "0", "Rare", "", "This highly-addictive deliriant grows under"),
        ("Moonfower", "Drugs and Poisons", "5GC", "0", "Scarce", "", ""),
        ("Ranald’s Delight", "Drugs and Poisons", "18/–", "0", "Scarce", "", "This highly-addictive stimulant is a synthetic"),
        ("Spit", "Drugs and Poisons", "1GC 5/–", "0", "Rare", "", "Extracted from Chameleoleeches found in the marshes of"),
        ("Weirdroot", "Drugs and Poisons", "4/–", "0", "Rare", "", "One of the most common street-drugs in the"),
        ("Digestive Tonic", "Herbs and Draughts", "3/–", "0", "Common", "", "Provides +20 to recovery Tests from stomach"),
        ("Earth Root", "Herbs and Draughts", "5GC", "0", "Scarce", "", "This herb is ingested to negate the effects of Buboes"),
        ("Faxtoryll", "Herbs and Draughts", "15/–", "0", "Exotic", "", "When smeared on a wound, poultices made from this"),
        ("Healing Draught", "Herbs and Draughts", "10/–", "0", "Scarce", "", "If you have more than 0 Wounds, recover"),
        ("Healing Poultice", "Herbs and Draughts", "12/–", "0", "Common", "", "This foul-smelling medicinal wrap is made"),
        ("Nightshade", "Herbs and Draughts", "3GC", "0", "Rare", "", "Consuming this herb causes the victim to fall into"),
        ("Salwort", "Herbs and Draughts", "12/–", "0", "Common", "", "When held under someone’s nose, the aroma from a"),
        ("Vitality Draught", "Herbs and Draughts", "18/–", "0", "Scarce", "", "Drinking this draught instantly removes all"),
        ("Eye Patch", "Prosthetics", "6d", "0", "Common", "", "Often decorated, an eye patch is used to cover scarred"),
        ("False Eye", "Prosthetics", "1GC", "0", "Rare", "", "Particularly popular amongst the rich who prefer not"),
        ("False Leg", "Prosthetics", "16/–", "2", "Scarce", "", "A False Leg (or just a False Foot, for half price),"),
        ("Gilded Nose", "Prosthetics", "18/–", "0", "Scarce", "", "Though most are made of wood or ceramic, the"),
        ("Hook", "Prosthetics", "3/4", "1", "Common", "", "You have a hook strapped where you used to have a hand."),
        ("Engineering Marvel", "Prosthetics", "20GC", "1", "Exotic", "", "Only for the exceedingly rich, you"),
        ("Wooden teeth", "Prosthetics", "10/–", "0", "Rare", "", "False Teeth are often beautifully carved and"),
        ("Ball", "Miscellaneous Trappings", "5d", "0", "Common", "", ""),
        ("Bandage", "Miscellaneous Trappings", "4d", "0", "Common", "", "Asuccessful Heal Test removes +1 extra Bleeding"),
        ("Baton", "Miscellaneous Trappings", "1/–", "0", "Common", "", ""),
        ("Bedroll", "Miscellaneous Trappings", "6/–", "1", "Common", "", "Endurance Tests rolled to resist cold exposure (see page"),
        ("Blanket", "Miscellaneous Trappings", "8d", "0", "Common", "", ""),
        ("Candle (dozen)", "Miscellaneous Trappings", "1/–", "0", "Common", "", ""),
        ("Canvas Tarp", "Miscellaneous Trappings", "8/–", "1", "Common", "", ""),
        ("Chalk", "Miscellaneous Trappings", "10d", "0", "Common", "", ""),
        ("Charcoal stick", "Miscellaneous Trappings", "10d", "0", "Common", "", ""),
        ("Cutlery", "Miscellaneous Trappings", "3/6", "0", "Common", "", ""),
        ("Davrich Lamp", "Miscellaneous Trappings", "2GC", "1", "Rare", "", "Asafety lamp emitting the light of a candle,"),
        ("Deck of Cards", "Miscellaneous Trappings", "1/–", "0", "Common", "", ""),
        ("Cooking Pot", "Miscellaneous Trappings", "8/–", "1", "Common", "", ""),
        ("Cup", "Miscellaneous Trappings", "8d", "0", "Common", "", ""),
        ("Dice", "Miscellaneous Trappings", "10d", "0", "Common", "", ""),
        ("Doll", "Miscellaneous Trappings", "2/–", "0", "Common", "", ""),
        ("Grappling Hook", "Miscellaneous Trappings", "1GC 0/10", "1", "Scarce", "", "Coupled with a rope, allows unscalable"),
        ("Instrument", "Miscellaneous Trappings", "2GC", "1", "Rare", "", "Various instruments are included in this category."),
        ("Lamp Oil", "Miscellaneous Trappings", "2/–", "0", "Common", "", "Contains enough fuel for 4 hours of standard use, or"),
        ("Lantern", "Miscellaneous Trappings", "12/–", "1", "Common", "", "Provides illumination for 20 yards."),
        ("Storm Lantern", "Miscellaneous Trappings", "1GC", "1", "Scarce", "", "Shutters protect the flame from wind, and also"),
        ("Match", "Miscellaneous Trappings", "1d", "0", "Common", "", ""),
        ("Pan", "Miscellaneous Trappings", "7/6", "1", "Common", "", ""),
        ("Pipe and Tobacco", "Miscellaneous Trappings", "3/4", "0", "Scarce", "", ""),
        ("Placard", "Miscellaneous Trappings", "1/–", "2", "Common", "", ""),
        ("Plate", "Miscellaneous Trappings", "1/–", "0", "Common", "", ""),
        ("Bowl", "Miscellaneous Trappings", "1/–", "0", "Common", "", ""),
        ("Rags", "Miscellaneous Trappings", "1d", "0", "Common", "", ""),
        ("Rope, 10 yards", "Miscellaneous Trappings", "8/4", "1", "Common", "", ""),
        ("Tent", "Miscellaneous Trappings", "12/–", "2", "Scarce", "", "Amedium-sized tent accommodating four people sleeping"),
        ("Tinderbox", "Miscellaneous Trappings", "4/2", "0", "Common", "", ""),
    ]
    with conn:
        for name, cat, price, enc, avail, carries, desc in items:
            conn.execute(
                "INSERT OR REPLACE INTO trappings_catalog (name, category, price, encumbrance, availability, carries, description) VALUES (?, ?, ?, ?, ?, ?, ?);",
                (name, cat, price, enc, avail, carries, desc)
            )


def get_trappings_catalog() -> list[dict]:
    conn = get_connection()
    try:
        cur = conn.execute("SELECT name, category, price, encumbrance, availability, carries, description, is_worn FROM trappings_catalog ORDER BY name ASC")
        res = []
        for row in cur:
            cat = row[1]
            is_worn = row[7] if row[7] is not None else (1 if cat in ("Clothing and Accessories", "Armour") else 0)
            res.append({
                "name": row[0],
                "category": cat,
                "price": row[2],
                "encumbrance": row[3],
                "availability": row[4],
                "carries": row[5],
                "description": row[6],
                "is_worn": is_worn
            })
        return res
    except Exception:
        cur = conn.execute("SELECT name, category, price, encumbrance, availability, carries, description FROM trappings_catalog ORDER BY name ASC")
        res = []
        for row in cur:
            cat = row[1]
            res.append({
                "name": row[0],
                "category": cat,
                "price": row[2],
                "encumbrance": row[3],
                "availability": row[4],
                "carries": row[5],
                "description": row[6],
                "is_worn": 1 if cat in ("Clothing and Accessories", "Armour") else 0
            })
        return res

def get_weapons_catalog() -> list[dict]:
    conn = get_connection()
    cur = conn.execute("SELECT name, group_name, price, encumbrance, availability, reach_range, damage, qualities FROM weapons_catalog ORDER BY name ASC")
    res = []
    for row in cur:
        res.append({
            "name": row[0],
            "group_name": row[1],
            "price": row[2],
            "encumbrance": row[3],
            "availability": row[4],
            "reach_range": row[5],
            "damage": row[6],
            "qualities": row[7],
            "is_worn": 0
        })
    return res

def get_armour_catalog() -> list[dict]:
    conn = get_connection()
    cur = conn.execute("SELECT name, category, price, encumbrance, availability, penalty, locations, ap, qualities FROM armour_catalog ORDER BY name ASC")
    res = []
    for row in cur:
        res.append({
            "name": row[0],
            "category": row[1],
            "price": row[2],
            "encumbrance": row[3],
            "availability": row[4],
            "penalty": row[5],
            "locations": row[6],
            "ap": row[7],
            "qualities": row[8],
            "is_worn": 1
        })
    return res

def seed_weapons_catalog() -> None:
    conn = get_connection()
    items = [
        ("Hand Weapon", "Basic", "1GC", "1", "Common", "Average", "+SB+4", "–"),
        ("Improvised Weapon", "Basic", "N/A", "Varies", "N/A", "Varies", "+SB+1", "Undamaging"),
        ("Dagger", "Basic", "16/–", "0", "Common", "Very Short", "+SB+2", "–"),
        ("Knife", "Basic", "8/–", "0", "Common", "Very Short", "+SB+1", "Undamaging"),
        ("Shield (Buckler)", "Basic", "18/2", "0", "Common", "Personal", "+SB+1", "Shield 1, Defensive, Undamaging"),
        ("Shield", "Basic", "2GC", "1", "Common", "Very Short", "+SB+2", "Shield 2, Defensive, Undamaging"),
        ("Shield (Large)", "Basic", "3GC", "3", "Common", "Very Short", "+SB+3", "Shield 3, Defensive, Undamaging"),
        ("(2H)Cavalry Hammer", "Cavalry", "3GC", "3", "Scarce", "Long", "+SB+5", "Pummel"),
        ("Lance", "Cavalry", "1GC", "3", "Rare", "Very Long", "+SB+6*", "Impact, Impale"),
        ("Foil", "Fencing", "5GC", "1", "Scarce", "Medium", "+SB+3", "Fast, Impale, Precise, Undamaging"),
        ("Rapier", "Fencing", "5GC", "1", "Scarce", "Long", "+SB+4", "Fast, Impale"),
        ("Unarmed", "Brawling", "N/A", "0", "–", "Personal", "+SB+0", "Undamaging"),
        ("Knuckledusters", "Brawling", "2/6", "0", "Common", "Personal", "+SB+2", "–"),
        ("Grain Flail", "Flail", "10/–", "1", "Common", "Average", "+SB+3", "Distract, Imprecise, Wrap"),
        ("Flail", "Flail", "2GC", "1", "Scarce", "Average", "+SB+5", "Distract, Wrap"),
        ("(2H)Military Flail", "Flail", "3GC", "2", "Rare", "Long", "+SB+6", "Distract, Impact, Tiring, Wrap"),
        ("Main Gauche", "Parry", "1GC", "0", "Rare", "Very Short", "+SB+2", "Defensive"),
        ("Swordbreaker", "Parry", "1GC 2/6", "1", "Scarce", "Short", "+SB+3", "Defensive, Trap-blade"),
        ("(2H)Halberd", "Polearm", "2GC", "3", "Common", "Long", "+SB+4", "Defensive, Hack, Impale"),
        ("(2H)Spear", "Polearm", "15/–", "2", "Common", "Very Long", "+SB+4", "Impale"),
        ("(2H)Pike", "Polearm", "18/–", "4", "Rare", "Massive", "+SB+4", "Impale"),
        ("(2H)Quarter Staf", "Polearm", "3/–", "2", "Common", "Long", "+SB+4", "Defensive, Pummel"),
        ("(2H)Bastard Sword", "Two-Handed", "8GC", "3", "Scarce", "Long", "+SB+5", "Damaging, Defensive"),
        ("(2H)Great Axe", "Two-Handed", "4GC", "3", "Scarce", "Long", "+SB+6", "Hack, Impact, Tiring"),
        ("(2H)Pick", "Two-Handed", "9/–", "3", "Common", "Average", "+SB+5", "Damaging, Impale"),
        ("(2H)Warhammer", "Two-Handed", "3GC", "3", "Common", "Average", "+SB+6", "Damaging, Pummel"),
        ("(2H)Zweihänder", "Two-Handed", "10GC", "3", "Scarce", "Long", "+SB+5", "Damaging, Hack"),
        ("(2H)Blunderbuss*", "Blackpowder*", "2GC", "1", "Scarce", "20", "+8", "Blast 3, Dangerous, Reload 2"),
        ("(2H)Hochland Long Rife*", "Blackpowder*", "100GC", "3", "Exotic", "100", "+9", "Accurate, Precise, Reload 4"),
        ("(2H)Handgun*", "Blackpowder*", "4GC", "2", "Scarce", "50", "+9", "Dangerous, Reload 3"),
        ("Pistol*", "Blackpowder*", "8GC", "0", "Rare", "20", "+8", "Pistol, Reload 1"),
        ("(2H)Elf Bow", "Bow", "10GC", "2", "Exotic", "150", "+SB+4", "Damaging, Precise"),
        ("(2H)Longbow", "Bow", "5GC", "3", "Scarce", "100", "+SB+4", "Damaging"),
        ("(2H)Bow", "Bow", "4GC", "2", "Common", "50", "+SB+3", "–"),
        ("(2H)Shortbow", "Bow", "3GC", "1", "Common", "20", "+SB+2", "–"),
        ("Crossbow Pistol", "Crossbow", "6GC", "0", "Scarce", "10", "+7", "Pistol"),
        ("(2H)Heavy Crossbow", "Crossbow", "7GC", "3", "Rare", "100", "+9", "Damaging, Reload 2"),
        ("(2H)Crossbow", "Crossbow", "5GC", "2", "Common", "60", "+9", "Reload 1"),
        ("(2H)Repeater Handgun*", "Engineering*", "10GC", "3", "Rare", "30", "+9", "Dangerous, Reload 5, Repeater 4"),
        ("Repeater Pistol*", "Engineering*", "15GC", "1", "Rare", "10", "+8", "Dangerous, Repeater, Reload 4, Repeater 4"),
        ("Lasso", "Entangling**", "6/–", "0", "Common", "SBx2", "–", "Entangle"),
        ("Whip", "Entangling**", "5/–", "0", "Common", "6", "+SB+2", "Entangle"),
        ("Bomb", "Explosives", "3GC", "0", "Rare", "SB", "+12", "Blast 5, Dangerous, Impact"),
        ("Incendiary", "Explosives", "1GC", "0", "Scarce", "SB", "Special***", "Blast 4, Dangerous"),
        ("Sling", "Sling", "1/–", "0", "Common", "60", "+6", "–"),
        ("(2H)Staf Sling", "Sling", "4/–", "2", "Scarce", "100", "+7", "–"),
        ("Bolas", "Throwing", "10/–", "0", "Rare", "SB×3", "+SB", "Entangle"),
        ("Dart", "Throwing", "2/–", "0", "Scarce", "SB×2", "+SB+1", "Impale"),
        ("Javelin", "Throwing", "10/6", "1", "Scarce", "SB×3", "+SB+3", "Impale"),
        ("Rock", "Throwing", "–", "0", "Common", "SB×3", "+SB+0", "–"),
        ("Trowing Axe", "Throwing", "1GC", "1", "Average", "SB×2", "+SB+3", "Hack"),
        ("Trowing Knife", "Throwing", "18/–", "0", "Common", "SB×2", "+SB+2", "–"),
        ("Bullet and Powder (12)", "Blackpowder And Engineering", "3/3", "0", "Common", "As weapon", "+1", "Impale, Penetrating"),
        ("Improvised Shot and Powder", "Blackpowder And Engineering", "3d", "0", "Common", "Half weapon", "–", "–"),
        ("Small Shot and Powder (12)", "Blackpowder And Engineering", "3/3", "0", "Common", "As weapon", "–", "Blast +1"),
        ("Arrow (12)", "Bow", "5/–", "0", "Common", "As weapon", "–", "Impale"),
        ("Elf Arrow", "Bow", "6/–", "0", "Exotic", "+50", "+1", "Accurate, Impale, Penetrating"),
        ("Bolt (12)", "Crossbow", "5/–", "0", "Common", "As weapon", "–", "Impale"),
        ("Lead Bullet (12)", "Sling", "4d", "0", "Common", "–10", "+1", "Pummel"),
        ("Stone Bullet (12)", "Sling", "2d", "0", "Common", "As weapon", "–", "Pummel"),
    ]
    with conn:
        for name, group_name, price, enc, avail, reach_range, damage, qualities in items:
            conn.execute(
                "INSERT OR REPLACE INTO weapons_catalog (name, group_name, price, encumbrance, availability, reach_range, damage, qualities) VALUES (?, ?, ?, ?, ?, ?, ?, ?);",
                (name, group_name, price, enc, avail, reach_range, damage, qualities)
            )
def seed_armour_catalog() -> None:
    conn = get_connection()
    items = [
        ("Leather Jack", "Soft Leather*", "12/–", 1, "Common", "–", "Arms, Body", 1, "–"),
        ("Leather Jerkin", "Soft Leather*", "10/–", 1, "Common", "–", "Body", 1, "–"),
        ("Leather Leggings", "Soft Leather*", "14/–", 1, "Common", "–", "Legs", 1, "–"),
        ("Leather Skullcap", "Soft Leather*", "8/–", 0, "Common", "–", "Head", 1, "–"),
        ("Breastplate", "Boiled Leather", "18/–", 2, "Scarce", "–", "Body", 2, "Weakpoints"),
        ("Mail Chausses", "Mail**", "2GC", 3, "Scarce", "–", "Legs", 2, "Flexible"),
        ("Mail Coat", "Mail**", "3GC", 3, "Common", "–", "Arms, Body", 2, "Flexible"),
        ("Mail Coif", "Mail**", "1GC", 2, "Scarce", "–10% Perception", "Head", 2, "Flexible, Partial"),
        ("Mail Shirt", "Mail**", "2GC", 2, "Scarce", "–", "Body", 2, "Flexible"),
        ("Breastplate", "Plate**", "10GC", 3, "Scarce", "–", "Body", 2, "Impenetrable, Weakpoints"),
        ("Open Helm", "Plate**", "2GC", 1, "Common", "–10% Perception", "Head", 2, "Partial"),
        ("Bracers", "Plate**", "8GC", 3, "Rare", "–", "Arms", 2, "Impenetrable, Weakpoints"),
        ("Plate Leggings", "Plate**", "10GC", 3, "Rare", "–10 Stealth", "Legs", 2, "Impenetrable, Weakpoints"),
        ("Helm", "Plate**", "3GC", 2, "Rare", "–20% Perception", "Head", 2, "Impenetrable, Weakpoints"),
        ("Light Armour", "Leather", "2GC", 1, "Common", "–", "All", 1, "Flexible"),
        ("Medium Armour", "Leather", "5GC", 5, "Scarce", "–10% Perception –10 Stealth", "All", 2, "Flexible"),
        ("Heavy Armour", "Leather", "30GC", 6, "Rare", "–20% Perception –20 Stealth", "All", 3, "Impenetrable, Weakpoints"),
    ]
    with conn:
        for name, category, price, enc, avail, penalty, locs, ap, qual in items:
            conn.execute(
                "INSERT OR REPLACE INTO armour_catalog (name, category, price, encumbrance, availability, penalty, locations, ap, qualities) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
                (name, category, price, enc, avail, penalty, locs, ap, qual)
            )
def seed_hirelings_catalog() -> None:
    conn = get_connection()
    items = [
        ("Local Scout", "5d", "15d", "10/–", "Works independently without Leadership Tests"),
        ("Seasoned Mercenary", "3/–", "9/–", "3GC 12/–", "Demands a share of loot in lieu of danger pay"),
        ("Lawyer", "3/–", "9/–", "3GC 12/–", "Drafting a simple legal document costs 2–4 shillings"),
        ("Porter", "1/–", "3/–", "1GC 4/–", "Carries 10 Encumbrance points"),
        ("Scribe", "2/–", "6/–", "2GC 8/–", "Also translates 1-2 other common languages"),
        ("Doktor", "5/–", "15/–", "5GC", "A single visit costs 4–6 shillings for medical attention"),
    ]
    with conn:
        for name, quick, daily, weekly, notes in items:
            conn.execute(
                "INSERT OR REPLACE INTO hirelings_catalog (name, quick_job_cost, daily_cost, weekly_cost, notes) VALUES (?, ?, ?, ?, ?);",
                (name, quick, daily, weekly, notes)
            )


# Initialize and run migration on module import
init_db()
migrate_json_files()
