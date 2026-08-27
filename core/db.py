import sqlite3
import json
import threading
from core import config

_DB_PATH = config.USER_DATA_DIR / "state.db"
# Use a thread-local storage for connections since sqlite connections can't be shared across threads by default.
_local = threading.local()

def _get_conn():
    if not hasattr(_local, "conn"):
        # check_same_thread=False is okay here because we enforce thread-locality or it's just simpler
        # but since we use threading.local, it's inherently thread-safe per thread.
        # However, to avoid issues, we can just let each thread have its own connection.
        _local.conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
        # WAL mode is better for concurrency
        _local.conn.execute("PRAGMA journal_mode=WAL")
    return _local.conn

def init_db():
    conn = _get_conn()
    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT NOT NULL,
                content TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS memory_facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fact TEXT UNIQUE NOT NULL,
                is_longterm BOOLEAN NOT NULL DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                id TEXT PRIMARY KEY,
                message TEXT NOT NULL,
                fire_at TEXT NOT NULL,
                repeating BOOLEAN NOT NULL DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS kv_store (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
    _run_migrations()

def _run_migrations():
    """Migrate data from legacy JSON files into SQLite on first boot."""
    conn = _get_conn()
    
    # Check if we already migrated
    cursor = conn.execute("SELECT value FROM kv_store WHERE key = 'migrated_json'")
    row = cursor.fetchone()
    if row and row['value'] == 'true':
        return

    print("[db] Running initial JSON to SQLite migrations...")

    # Migrate history
    history_path = config.USER_DATA_DIR / config.HISTORY_FILE
    if history_path.exists():
        try:
            with history_path.open() as f:
                history = json.load(f)
            with conn:
                for item in history:
                    conn.execute("INSERT INTO history (role, content) VALUES (?, ?)", 
                                 (item["role"], json.dumps(item["content"]) if isinstance(item["content"], (list, dict)) else item["content"]))
            print(f"[db] Migrated {len(history)} history turns.")
            history_path.rename(history_path.with_suffix(".json.bak"))
        except Exception as e:
            print(f"[db] Error migrating history: {e}")

    # Migrate short-term memory
    mem_path = config.data_path("memory.json")
    if mem_path.exists():
        try:
            with mem_path.open() as f:
                facts = json.load(f)
            with conn:
                for f in facts:
                    conn.execute("INSERT OR IGNORE INTO memory_facts (fact, is_longterm) VALUES (?, 0)", (str(f),))
            print(f"[db] Migrated {len(facts)} memory facts.")
            mem_path.rename(mem_path.with_suffix(".json.bak"))
        except Exception as e:
            print(f"[db] Error migrating memory: {e}")

    # Migrate long-term memory
    lt_mem_path = config.data_path("longterm_memory.json")
    if lt_mem_path.exists():
        try:
            with lt_mem_path.open() as f:
                lt_facts = json.load(f)
            with conn:
                for f in lt_facts:
                    conn.execute("INSERT OR IGNORE INTO memory_facts (fact, is_longterm) VALUES (?, 1)", (str(f),))
            print(f"[db] Migrated {len(lt_facts)} long-term memory facts.")
            lt_mem_path.rename(lt_mem_path.with_suffix(".json.bak"))
        except Exception as e:
            print(f"[db] Error migrating longterm memory: {e}")

    # Migrate reminders
    rem_path = config.data_path("reminders.json")
    if rem_path.exists():
        try:
            with rem_path.open() as f:
                rems = json.load(f)
            with conn:
                for r in rems:
                    conn.execute("INSERT OR REPLACE INTO reminders (id, message, fire_at, repeating) VALUES (?, ?, ?, ?)",
                                 (r["id"], r["message"], r["fire_at"], r.get("repeating", False)))
            print(f"[db] Migrated {len(rems)} reminders.")
            rem_path.rename(rem_path.with_suffix(".json.bak"))
        except Exception as e:
            print(f"[db] Error migrating reminders: {e}")

    # Mark as migrated
    with conn:
        conn.execute("INSERT OR REPLACE INTO kv_store (key, value) VALUES ('migrated_json', 'true')")
    print("[db] Migrations complete.")

# ── History API ─────────────────────────────────────────────────────────────

def append_history(role: str, content):
    conn = _get_conn()
    if isinstance(content, (list, dict)):
        content = json.dumps(content)
    with conn:
        conn.execute("INSERT INTO history (role, content) VALUES (?, ?)", (role, content))
        
        # Enforce history limit
        # Delete rows where id is not in the last HISTORY_LIMIT ids
        limit = config.HISTORY_LIMIT
        conn.execute(f"DELETE FROM history WHERE id NOT IN (SELECT id FROM history ORDER BY id DESC LIMIT {limit})")

def get_history() -> list[dict]:
    conn = _get_conn()
    cursor = conn.execute("SELECT role, content FROM history ORDER BY id ASC")
    res = []
    for row in cursor.fetchall():
        content_str = row['content']
        try:
            if content_str.startswith('[') or content_str.startswith('{'):
                content = json.loads(content_str)
            else:
                content = content_str
        except json.JSONDecodeError:
            content = content_str
        res.append({"role": row['role'], "content": content})
    return res

def clear_history():
    conn = _get_conn()
    with conn:
        conn.execute("DELETE FROM history")

# ── Memory API ──────────────────────────────────────────────────────────────

def get_memory_facts(longterm: bool) -> list[str]:
    conn = _get_conn()
    cursor = conn.execute("SELECT fact FROM memory_facts WHERE is_longterm = ? ORDER BY id ASC", (1 if longterm else 0,))
    return [row['fact'] for row in cursor.fetchall()]

def add_memory_fact(fact: str, longterm: bool = False):
    conn = _get_conn()
    with conn:
        conn.execute("INSERT OR IGNORE INTO memory_facts (fact, is_longterm) VALUES (?, ?)", (fact, 1 if longterm else 0))

def remove_memory_fact(fact: str, longterm: bool = False):
    conn = _get_conn()
    with conn:
        conn.execute("DELETE FROM memory_facts WHERE fact = ? AND is_longterm = ?", (fact, 1 if longterm else 0))
        
def enforce_memory_limit(limit: int):
    conn = _get_conn()
    with conn:
        conn.execute(f"DELETE FROM memory_facts WHERE is_longterm = 0 AND id NOT IN (SELECT id FROM memory_facts WHERE is_longterm = 0 ORDER BY id DESC LIMIT {limit})")

def update_memory_fact(old_fact: str, new_fact: str, longterm: bool = False):
    conn = _get_conn()
    with conn:
        conn.execute("UPDATE memory_facts SET fact = ? WHERE fact = ? AND is_longterm = ?", (new_fact, old_fact, 1 if longterm else 0))

def remove_facts_by_name(name: str) -> int:
    conn = _get_conn()
    name_like = f"%{name}%"
    with conn:
        cursor = conn.execute("DELETE FROM memory_facts WHERE fact LIKE ?", (name_like,))
        return cursor.rowcount

# ── Reminders API ───────────────────────────────────────────────────────────

def add_reminder(rid: str, message: str, fire_at: str, repeating: bool = False):
    conn = _get_conn()
    with conn:
        conn.execute("INSERT INTO reminders (id, message, fire_at, repeating) VALUES (?, ?, ?, ?)",
                     (rid, message, fire_at, 1 if repeating else 0))

def get_all_reminders() -> list[dict]:
    conn = _get_conn()
    cursor = conn.execute("SELECT id, message, fire_at, repeating FROM reminders")
    return [{"id": r['id'], "message": r['message'], "fire_at": r['fire_at'], "repeating": bool(r['repeating'])} for r in cursor.fetchall()]

def get_due_reminders(now_iso: str) -> list[dict]:
    conn = _get_conn()
    with conn:
        cursor = conn.execute("DELETE FROM reminders WHERE fire_at <= ? RETURNING id, message, fire_at, repeating", (now_iso,))
        return [{"id": r['id'], "message": r['message'], "fire_at": r['fire_at'], "repeating": bool(r['repeating'])} for r in cursor.fetchall()]

def remove_reminder(rid: str) -> bool:
    conn = _get_conn()
    with conn:
        cursor = conn.execute("DELETE FROM reminders WHERE id = ?", (rid,))
        return cursor.rowcount > 0

def remove_repeating_reminders() -> int:
    conn = _get_conn()
    with conn:
        cursor = conn.execute("DELETE FROM reminders WHERE repeating = 1")
        return cursor.rowcount

# ── KV Store API ────────────────────────────────────────────────────────────

def kv_get(key: str, default=None):
    conn = _get_conn()
    cursor = conn.execute("SELECT value FROM kv_store WHERE key = ?", (key,))
    row = cursor.fetchone()
    if row:
        try:
            return json.loads(row['value'])
        except json.JSONDecodeError:
            return row['value']
    return default

def kv_set(key: str, value):
    conn = _get_conn()
    with conn:
        conn.execute("INSERT OR REPLACE INTO kv_store (key, value) VALUES (?, ?)", (key, json.dumps(value)))
