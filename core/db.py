import sqlite3
import json
import threading
from typing import Optional
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

def _current_personality(personality: Optional[str] = None) -> str:
    if personality:
        return str(personality).strip().lower()
    return config.get_personality_key()


def init_db():
    conn = _get_conn()
    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                personality TEXT NOT NULL DEFAULT 'omega7',
                role TEXT NOT NULL,
                content TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS memory_facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                personality TEXT NOT NULL DEFAULT 'omega7',
                fact TEXT NOT NULL,
                is_longterm BOOLEAN NOT NULL DEFAULT 0,
                UNIQUE(personality, fact, is_longterm)
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
    _check_schema_upgrades(conn)
    _run_migrations()


def _check_schema_upgrades(conn):
    """Upgrade existing SQLite tables to support per-personality scoping."""
    # 1. Check memory_facts
    cursor = conn.execute("PRAGMA table_info(memory_facts)")
    mem_cols = [row['name'] for row in cursor.fetchall()]
    if mem_cols and "personality" not in mem_cols:
        print("[db] Migrating memory_facts table to support per-personality scoping...")
        with conn:
            conn.execute("""
                CREATE TABLE memory_facts_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    personality TEXT NOT NULL DEFAULT 'omega7',
                    fact TEXT NOT NULL,
                    is_longterm BOOLEAN NOT NULL DEFAULT 0,
                    UNIQUE(personality, fact, is_longterm)
                )
            """)
            old_rows = conn.execute("SELECT id, fact, is_longterm FROM memory_facts").fetchall()
            for r in old_rows:
                fact_str = r['fact']
                is_lt = r['is_longterm']
                p = "jax" if "jax" in fact_str.lower() else "omega7"
                conn.execute(
                    "INSERT OR IGNORE INTO memory_facts_new (id, personality, fact, is_longterm) VALUES (?, ?, ?, ?)",
                    (r['id'], p, fact_str, is_lt)
                )
            conn.execute("DROP TABLE memory_facts")
            conn.execute("ALTER TABLE memory_facts_new RENAME TO memory_facts")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_personality ON memory_facts(personality, is_longterm)")
        print("[db] memory_facts migration complete.")

    # 2. Check history
    cursor = conn.execute("PRAGMA table_info(history)")
    hist_cols = [row['name'] for row in cursor.fetchall()]
    if hist_cols and "personality" not in hist_cols:
        print("[db] Migrating history table to support per-personality scoping...")
        current_p = config.get_personality_key()
        with conn:
            conn.execute("""
                CREATE TABLE history_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    personality TEXT NOT NULL DEFAULT 'omega7',
                    role TEXT NOT NULL,
                    content TEXT NOT NULL
                )
            """)
            old_rows = conn.execute("SELECT id, role, content FROM history").fetchall()
            for r in old_rows:
                conn.execute(
                    "INSERT INTO history_new (id, personality, role, content) VALUES (?, ?, ?, ?)",
                    (r['id'], current_p, r['role'], r['content'])
                )
            conn.execute("DROP TABLE history")
            conn.execute("ALTER TABLE history_new RENAME TO history")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_hist_personality ON history(personality)")
        print("[db] history migration complete.")


def _run_migrations():
    """Migrate data from legacy JSON files into SQLite on first boot."""
    conn = _get_conn()
    
    # Check if we already migrated
    cursor = conn.execute("SELECT value FROM kv_store WHERE key = 'migrated_json'")
    row = cursor.fetchone()
    if row and row['value'] == 'true':
        return

    print("[db] Running initial JSON to SQLite migrations...")
    p = config.get_personality_key()

    # Migrate history
    history_path = config.USER_DATA_DIR / config.HISTORY_FILE
    if history_path.exists():
        try:
            with history_path.open() as f:
                history = json.load(f)
            with conn:
                for item in history:
                    conn.execute("INSERT INTO history (personality, role, content) VALUES (?, ?, ?)", 
                                 (p, item["role"], json.dumps(item["content"]) if isinstance(item["content"], (list, dict)) else item["content"]))
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
                    conn.execute("INSERT OR IGNORE INTO memory_facts (personality, fact, is_longterm) VALUES (?, ?, 0)", (p, str(f),))
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
                    conn.execute("INSERT OR IGNORE INTO memory_facts (personality, fact, is_longterm) VALUES (?, ?, 1)", (p, str(f),))
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

    # Mark migration done
    with conn:
        conn.execute("INSERT OR REPLACE INTO kv_store (key, value) VALUES ('migrated_json', 'true')")
    print("[db] Migrations finished.")


# ── History API ─────────────────────────────────────────────────────────────

def append_history(role: str, content, personality: Optional[str] = None):
    conn = _get_conn()
    p = _current_personality(personality)
    if isinstance(content, (list, dict)):
        content = json.dumps(content)
    with conn:
        conn.execute("INSERT INTO history (personality, role, content) VALUES (?, ?, ?)", (p, role, content))
        
        # Enforce history limit per personality
        limit = config.HISTORY_LIMIT
        conn.execute(
            f"DELETE FROM history WHERE personality = ? AND id NOT IN (SELECT id FROM history WHERE personality = ? ORDER BY id DESC LIMIT {limit})",
            (p, p)
        )

def get_history(personality: Optional[str] = None) -> list[dict]:
    conn = _get_conn()
    p = _current_personality(personality)
    cursor = conn.execute("SELECT role, content FROM history WHERE personality = ? ORDER BY id ASC", (p,))
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

def clear_history(personality: Optional[str] = None):
    conn = _get_conn()
    p = _current_personality(personality)
    with conn:
        conn.execute("DELETE FROM history WHERE personality = ?", (p,))

# ── Memory API ──────────────────────────────────────────────────────────────

def get_memory_facts(longterm: bool, personality: Optional[str] = None) -> list[str]:
    conn = _get_conn()
    p = _current_personality(personality)
    cursor = conn.execute(
        "SELECT fact FROM memory_facts WHERE is_longterm = ? AND personality = ? ORDER BY id ASC",
        (1 if longterm else 0, p)
    )
    return [row['fact'] for row in cursor.fetchall()]

def add_memory_fact(fact: str, longterm: bool = False, personality: Optional[str] = None):
    conn = _get_conn()
    p = _current_personality(personality)
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO memory_facts (personality, fact, is_longterm) VALUES (?, ?, ?)",
            (p, fact, 1 if longterm else 0)
        )

def remove_memory_fact(fact: str, longterm: bool = False, personality: Optional[str] = None):
    conn = _get_conn()
    p = _current_personality(personality)
    with conn:
        conn.execute(
            "DELETE FROM memory_facts WHERE fact = ? AND is_longterm = ? AND personality = ?",
            (fact, 1 if longterm else 0, p)
        )
        
def enforce_memory_limit(limit: int, personality: Optional[str] = None):
    conn = _get_conn()
    p = _current_personality(personality)
    with conn:
        conn.execute(
            f"DELETE FROM memory_facts WHERE is_longterm = 0 AND personality = ? AND id NOT IN (SELECT id FROM memory_facts WHERE is_longterm = 0 AND personality = ? ORDER BY id DESC LIMIT {limit})",
            (p, p)
        )

def update_memory_fact(old_fact: str, new_fact: str, longterm: bool = False, personality: Optional[str] = None):
    conn = _get_conn()
    p = _current_personality(personality)
    with conn:
        conn.execute(
            "UPDATE memory_facts SET fact = ? WHERE fact = ? AND is_longterm = ? AND personality = ?",
            (new_fact, old_fact, 1 if longterm else 0, p)
        )

def remove_facts_by_name(name: str, personality: Optional[str] = None) -> int:
    conn = _get_conn()
    name_like = f"%{name}%"
    with conn:
        if personality:
            p = _current_personality(personality)
            cursor = conn.execute("DELETE FROM memory_facts WHERE fact LIKE ? AND personality = ?", (name_like, p))
        else:
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
