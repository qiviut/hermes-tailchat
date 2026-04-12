from __future__ import annotations

import json
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
                hermes_session_id TEXT,
                hermes_title TEXT,
                sync_state TEXT NOT NULL DEFAULT 'linked',
                sync_error TEXT,
                link_mode TEXT NOT NULL DEFAULT 'owned',
                last_hermes_import_at TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'complete',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                trigger_type TEXT NOT NULL,
                trigger_text TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'queued',
                assistant_message_id TEXT,
                job_id TEXT,
                error_text TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                prompt TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                delay_seconds INTEGER NOT NULL DEFAULT 0,
                run_after TEXT NOT NULL,
                lease_until TEXT,
                claimed_by TEXT,
                result_message_id TEXT,
                error_text TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS approvals (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                run_id TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                summary TEXT NOT NULL,
                details_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                resolved_at TEXT,
                resolution TEXT
            );
            CREATE TABLE IF NOT EXISTS run_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                run_id TEXT,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """)

            self._ensure_column(conn, 'conversations', 'hermes_session_id', 'TEXT')
            self._ensure_column(conn, 'conversations', 'hermes_title', 'TEXT')
            self._ensure_column(conn, 'conversations', 'sync_state', "TEXT NOT NULL DEFAULT 'linked'")
            self._ensure_column(conn, 'conversations', 'sync_error', 'TEXT')
            self._ensure_column(conn, 'conversations', 'link_mode', "TEXT NOT NULL DEFAULT 'owned'")
            self._ensure_column(conn, 'conversations', 'last_hermes_import_at', 'TEXT')
            conn.execute("UPDATE conversations SET hermes_session_id = COALESCE(hermes_session_id, id)")
            conn.execute("UPDATE conversations SET sync_state = COALESCE(NULLIF(sync_state, ''), 'linked')")
            conn.execute("UPDATE conversations SET link_mode = COALESCE(NULLIF(link_mode, ''), 'owned')")

            self._ensure_column(conn, 'messages', 'metadata_json', "TEXT NOT NULL DEFAULT '{}'" )
            self._ensure_column(conn, 'runs', 'job_id', 'TEXT')
            self._ensure_column(conn, 'runs', 'error_text', "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(conn, 'jobs', 'result_message_id', 'TEXT')
            self._ensure_column(conn, 'jobs', 'error_text', "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(conn, 'run_events', 'run_id', 'TEXT')

    def _ensure_column(self, conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
        cols = {row['name'] for row in conn.execute(f'PRAGMA table_info({table})').fetchall()}
        if column not in cols:
            conn.execute(f'ALTER TABLE {table} ADD COLUMN {column} {ddl}')

    def _conversation_select(self) -> str:
        return """
                SELECT c.id, c.title, c.hermes_session_id, c.hermes_title, c.sync_state, c.sync_error, c.link_mode, c.last_hermes_import_at, c.created_at,
                       COALESCE(MAX(m.created_at), c.created_at) AS last_activity_at
                FROM conversations c
                LEFT JOIN messages m ON m.conversation_id = c.id
                GROUP BY c.id, c.title, c.hermes_session_id, c.hermes_title, c.sync_state, c.sync_error, c.link_mode, c.last_hermes_import_at, c.created_at
                """

    def _conversation_payload(self, row: sqlite3.Row | None) -> dict[str, Any]:
        if row is None:
            return {}
        item = dict(row)
        hermes_session_id = item.get('hermes_session_id')
        item['cli_resume_command'] = f'hermes --resume {hermes_session_id}' if hermes_session_id else None
        return item

    def list_conversations(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                self._conversation_select() + """
                ORDER BY last_activity_at DESC, c.created_at DESC
                """
            ).fetchall()
            return [self._conversation_payload(r) for r in rows]

    def create_conversation(self, title: str | None = None) -> dict[str, Any]:
        cid = uuid.uuid4().hex
        title = title or 'New chat'
        with self._connect() as conn:
            conn.execute(
                'INSERT INTO conversations (id, title, hermes_session_id, hermes_title, sync_state, sync_error, link_mode) VALUES (?, ?, ?, ?, ?, ?, ?)',
                (cid, title, cid, None, 'linked', None, 'owned'),
            )
            row = conn.execute(
                self._conversation_select() + " HAVING c.id = ?",
                (cid,),
            ).fetchone()
            return self._conversation_payload(row)

    def get_conversation(self, conversation_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                self._conversation_select() + " HAVING c.id = ?",
                (conversation_id,),
            ).fetchone()
            return self._conversation_payload(row)

    def update_conversation_title(self, conversation_id: str, title: str) -> dict[str, Any]:
        with self._connect() as conn:
            conn.execute('UPDATE conversations SET title = ? WHERE id = ?', (title, conversation_id))
            row = conn.execute(
                self._conversation_select() + " HAVING c.id = ?",
                (conversation_id,),
            ).fetchone()
            return self._conversation_payload(row)

    def update_conversation_sync(self, conversation_id: str, *, hermes_title: str | None = None, sync_state: str | None = None, sync_error: str | None = None) -> dict[str, Any]:
        parts = []
        args: list[Any] = []
        if hermes_title is not None or hermes_title is None:
            parts.append('hermes_title = ?')
            args.append(hermes_title)
        if sync_state is not None:
            parts.append('sync_state = ?')
            args.append(sync_state)
        if sync_error is not None or sync_error is None:
            parts.append('sync_error = ?')
            args.append(sync_error)
        if not parts:
            return self.get_conversation(conversation_id)
        args.append(conversation_id)
        with self._connect() as conn:
            conn.execute(f"UPDATE conversations SET {', '.join(parts)} WHERE id = ?", args)
            row = conn.execute(
                self._conversation_select() + " HAVING c.id = ?",
                (conversation_id,),
            ).fetchone()
            return self._conversation_payload(row)

    def conversation_exists(self, conversation_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute('SELECT 1 FROM conversations WHERE id = ?', (conversation_id,)).fetchone()
            return row is not None

    def get_messages(self, conversation_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                'SELECT id, conversation_id, role, content, status, metadata_json, created_at FROM messages WHERE conversation_id = ? ORDER BY created_at, rowid',
                (conversation_id,),
            ).fetchall()
            items = []
            for row in rows:
                item = dict(row)
                item['metadata'] = json.loads(item.pop('metadata_json') or '{}')
                items.append(item)
            return items

    def add_message(self, conversation_id: str, role: str, content: str, status: str = 'complete', metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        mid = uuid.uuid4().hex
        payload = json.dumps(metadata or {})
        with self._connect() as conn:
            conn.execute(
                'INSERT INTO messages (id, conversation_id, role, content, status, metadata_json) VALUES (?, ?, ?, ?, ?, ?)',
                (mid, conversation_id, role, content, status, payload),
            )
            row = conn.execute('SELECT * FROM messages WHERE id = ?', (mid,)).fetchone()
            item = dict(row)
            item['metadata'] = json.loads(item.pop('metadata_json') or '{}')
            return item

    def update_message(self, message_id: str, content: str, status: str | None = None, metadata: dict[str, Any] | None = None) -> None:
        with self._connect() as conn:
            if status is None and metadata is None:
                conn.execute('UPDATE messages SET content = ? WHERE id = ?', (content, message_id))
            elif metadata is None:
                conn.execute('UPDATE messages SET content = ?, status = ? WHERE id = ?', (content, status, message_id))
            elif status is None:
                conn.execute('UPDATE messages SET content = ?, metadata_json = ? WHERE id = ?', (content, json.dumps(metadata), message_id))
            else:
                conn.execute('UPDATE messages SET content = ?, status = ?, metadata_json = ? WHERE id = ?', (content, status, json.dumps(metadata), message_id))

    def create_run(self, conversation_id: str, trigger_type: str, trigger_text: str = '', assistant_message_id: str | None = None, job_id: str | None = None) -> dict[str, Any]:
        run_id = uuid.uuid4().hex
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO runs (id, conversation_id, trigger_type, trigger_text, assistant_message_id, job_id)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (run_id, conversation_id, trigger_type, trigger_text, assistant_message_id, job_id),
            )
            row = conn.execute('SELECT * FROM runs WHERE id = ?', (run_id,)).fetchone()
            return dict(row)

    def get_run(self, run_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute('SELECT * FROM runs WHERE id = ?', (run_id,)).fetchone()
            return dict(row) if row else {}

    def update_run(self, run_id: str, *, status: str | None = None, error_text: str | None = None, assistant_message_id: str | None = None) -> None:
        parts = []
        args: list[Any] = []
        if status is not None:
            parts.append('status = ?')
            args.append(status)
        if error_text is not None:
            parts.append('error_text = ?')
            args.append(error_text)
        if assistant_message_id is not None:
            parts.append('assistant_message_id = ?')
            args.append(assistant_message_id)
        parts.append("updated_at = CURRENT_TIMESTAMP")
        args.append(run_id)
        with self._connect() as conn:
            conn.execute(f"UPDATE runs SET {', '.join(parts)} WHERE id = ?", args)

    def list_jobs(self, conversation_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                'SELECT * FROM jobs WHERE conversation_id = ? ORDER BY created_at DESC, id DESC',
                (conversation_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def create_job(self, conversation_id: str, prompt: str, delay_seconds: int = 0) -> dict[str, Any]:
        job_id = uuid.uuid4().hex
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO jobs (id, conversation_id, prompt, delay_seconds, run_after)
                VALUES (?, ?, ?, ?, datetime('now', printf('+%d seconds', ?)))
                """,
                (job_id, conversation_id, prompt, delay_seconds, delay_seconds),
            )
            row = conn.execute('SELECT * FROM jobs WHERE id = ?', (job_id,)).fetchone()
            return dict(row)

    def claim_due_jobs(self, worker_id: str, limit: int = 5) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id FROM jobs
                WHERE status = 'pending'
                  AND run_after <= CURRENT_TIMESTAMP
                  AND (lease_until IS NULL OR lease_until < CURRENT_TIMESTAMP)
                ORDER BY run_after, created_at
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            claimed = []
            for row in rows:
                job_id = row['id']
                updated = conn.execute(
                    """
                    UPDATE jobs
                    SET status = 'running',
                        claimed_by = ?,
                        lease_until = datetime('now', '+5 minutes'),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ? AND status = 'pending'
                      AND (lease_until IS NULL OR lease_until < CURRENT_TIMESTAMP)
                    """,
                    (worker_id, job_id),
                )
                if updated.rowcount:
                    claimed.append(dict(conn.execute('SELECT * FROM jobs WHERE id = ?', (job_id,)).fetchone()))
            return claimed

    def update_job(self, job_id: str, *, status: str | None = None, error_text: str | None = None, result_message_id: str | None = None) -> None:
        parts = []
        args: list[Any] = []
        if status is not None:
            parts.append('status = ?')
            args.append(status)
        if error_text is not None:
            parts.append('error_text = ?')
            args.append(error_text)
        if result_message_id is not None:
            parts.append('result_message_id = ?')
            args.append(result_message_id)
        if status in {'complete', 'error'}:
            parts.append('lease_until = NULL')
        parts.append("updated_at = CURRENT_TIMESTAMP")
        args.append(job_id)
        with self._connect() as conn:
            conn.execute(f"UPDATE jobs SET {', '.join(parts)} WHERE id = ?", args)

    def create_approval(self, conversation_id: str, summary: str, details: dict[str, Any], run_id: str | None = None) -> dict[str, Any]:
        approval_id = uuid.uuid4().hex
        payload = json.dumps(details)
        with self._connect() as conn:
            conn.execute(
                'INSERT INTO approvals (id, conversation_id, run_id, summary, details_json) VALUES (?, ?, ?, ?, ?)',
                (approval_id, conversation_id, run_id, summary, payload),
            )
            row = conn.execute('SELECT * FROM approvals WHERE id = ?', (approval_id,)).fetchone()
            item = dict(row)
            item['details'] = json.loads(item.pop('details_json') or '{}')
            return item

    def list_approvals(self, conversation_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute('SELECT * FROM approvals WHERE conversation_id = ? ORDER BY created_at DESC, id DESC', (conversation_id,)).fetchall()
            items = []
            for row in rows:
                item = dict(row)
                item['details'] = json.loads(item.pop('details_json') or '{}')
                items.append(item)
            return items

    def resolve_approval(self, approval_id: str, resolution: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE approvals SET status = 'resolved', resolved_at = CURRENT_TIMESTAMP, resolution = ? WHERE id = ?",
                (resolution, approval_id),
            )
            row = conn.execute('SELECT * FROM approvals WHERE id = ?', (approval_id,)).fetchone()
            if not row:
                return None
            item = dict(row)
            item['details'] = json.loads(item.pop('details_json') or '{}')
            return item

    def append_run_event(self, conversation_id: str, run_id: str | None, event_type: str, payload_json: str) -> None:
        with self._connect() as conn:
            conn.execute(
                'INSERT INTO run_events (conversation_id, run_id, event_type, payload_json) VALUES (?, ?, ?, ?)',
                (conversation_id, run_id, event_type, payload_json),
            )

    def list_run_events(self, conversation_id: str, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                'SELECT id, conversation_id, run_id, event_type, payload_json, created_at FROM run_events WHERE conversation_id = ? ORDER BY id DESC LIMIT ?',
                (conversation_id, limit),
            ).fetchall()
            items = []
            for row in reversed(rows):
                item = dict(row)
                item['payload'] = json.loads(item.pop('payload_json') or '{}')
                items.append(item)
            return items

store = None
