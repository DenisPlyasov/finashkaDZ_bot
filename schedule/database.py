import sqlite3
from typing import Optional, Dict
from config import DB_PATH

def _conn():
    return sqlite3.connect(DB_PATH)
#bxb
def init_db():
    with _conn() as conn:
        c = conn.cursor()
        c.execute("""
        CREATE TABLE IF NOT EXISTS users(
            chat_id INTEGER PRIMARY KEY,
            kind TEXT NOT NULL,      -- 'group' | 'teacher' | 'auditory'
            obj_id INTEGER NOT NULL,
            obj_name TEXT NOT NULL
        )
        """)
        conn.commit()

def save_user_selection(chat_id: int, kind: str, obj_id: int, obj_name: str):
    with _conn() as conn:
        c = conn.cursor()
        c.execute("""
        INSERT INTO users(chat_id, kind, obj_id, obj_name)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(chat_id) DO UPDATE SET
            kind=excluded.kind,
            obj_id=excluded.obj_id,
            obj_name=excluded.obj_name
        """, (chat_id, kind, obj_id, obj_name))
        conn.commit()

def get_user_selection(chat_id: int) -> Optional[Dict]:
    with _conn() as conn:
        c = conn.cursor()
        c.execute("SELECT kind, obj_id, obj_name FROM users WHERE chat_id=?", (chat_id,))
        row = c.fetchone()
    if not row:
        return None
    return {"kind": row[0], "id": row[1], "name": row[2]}