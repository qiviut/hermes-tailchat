from __future__ import annotations

import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Any


class Store:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'complete',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS run_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """)

    def list_conversations(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT id, title, created_at FROM conversations ORDER BY created_at DESC").fetchall()
            return [dict(r) for r in rows]

    def create_conversation(self, title: str | None = None) -> dict[str, Any]:
        cid = uuid.uuid4().hex
        title = title or "New chat"
        with self._connect() as conn:
            conn.execute("INSERT INTO conversations (id, title) VALUES (?, ?)", (cid, title))
            row = conn.execute("SELECT id, title, created_at FROM conversations WHERE id = ?", (cid,)).fetchone()
            return dict(row)

    def get_messages(self, conversation_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, conversation_id, role, content, status, created_at FROM messages WHERE conversation_id = ? ORDER BY created_at, id",
                (conversation_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def add_message(self, conversation_id: str, role: str, content: str, status: str = "complete") -> dict[str, Any]:
        mid = uuid.uuid4().hex
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO messages (id, conversation_id, role, content, status) VALUES (?, ?, ?, ?, ?)",
                (mid, conversation_id, role, content, status),
            )
            row = conn.execute("SELECT * FROM messages WHERE id = ?", (mid,)).fetchone()
            return dict(row)

    def update_message(self, message_id: str, content: str, status: str | None = None) -> None:
        with self._connect() as conn:
            if status is None:
                conn.execute("UPDATE messages SET content = ? WHERE id = ?", (content, message_id))
            else:
                conn.execute("UPDATE messages SET content = ?, status = ? WHERE id = ?", (content, status, message_id))

    def append_run_event(self, conversation_id: str, event_type: str, payload_json: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO run_events (conversation_id, event_type, payload_json) VALUES (?, ?, ?)",
                (conversation_id, event_type, payload_json),
            )

store = None
