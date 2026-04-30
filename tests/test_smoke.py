from __future__ import annotations

import asyncio
import importlib
import json
import os
import sys
import types
from pathlib import Path
import time

from fastapi.testclient import TestClient


class DummyHermesProviderError(RuntimeError):
    pass


class DummyLocalHermesProvider:
    titles: dict[str, str] = {}
    session_messages: dict[str, list[dict]] = {}
    scripted_events: list[dict] | None = None
    pending_approvals: dict[str, dict] = {}
    run_turn_calls: list[dict] = []

    async def run_turn(self, session_id, conversation_history, user_message, on_event):
        self.run_turn_calls.append({
            'session_id': session_id,
            'conversation_history': [dict(item) for item in conversation_history],
            'user_message': user_message,
        })
        if self.scripted_events is not None:
            for event in self.scripted_events:
                await on_event(dict(event))
            return
        await on_event({"event": "run.completed", "output": f"dummy response for: {user_message}"})

    async def rehydrate_pending_approvals(self, approvals):
        self.pending_approvals = {}
        for item in approvals:
            details = item.get('details', {})
            provider_approval_id = details.get('approval_id', item['id'])
            self.pending_approvals[provider_approval_id] = {
                'session_id': details.get('session_id'),
                'restored': True,
            }

    async def resolve_approval(self, approval_id, decision):
        restored = self.pending_approvals.pop(approval_id, None)
        payload = {
            "approval_id": approval_id,
            "decision": decision,
            "resolved_count": 1,
        }
        if restored:
            payload.update({
                'session_id': restored.get('session_id'),
                'restored': True,
                'resume_required': True,
            })
        return payload

    async def set_session_title(self, session_id, title):
        for existing_session_id, existing_title in self.titles.items():
            if existing_session_id != session_id and existing_title == title:
                raise DummyHermesProviderError(f"Title '{title}' is already in use by session {existing_session_id}")
        self.titles[session_id] = title
        return title

    async def get_session_title(self, session_id):
        preset_titles = {'existing-alpha': 'Existing Alpha', 'existing-beta': 'Existing Beta'}
        return self.titles.get(session_id, preset_titles.get(session_id))

    async def get_session(self, session_id):
        preset_titles = {'existing-alpha': 'Existing Alpha', 'existing-beta': 'Existing Beta'}
        title = self.titles.get(session_id, preset_titles.get(session_id))
        if title is None and not session_id.startswith('existing-'):
            return None
        return {
            'id': session_id,
            'source': 'cli',
            'title': title,
            'started_at': 123.0,
        }

    async def list_sessions(self, source=None, limit=20):
        base = [
            {'id': 'existing-alpha', 'title': 'Existing Alpha', 'source': 'cli', 'started_at': 111.0, 'ended_at': None, 'message_count': 3, 'preview': 'alpha preview', 'last_active': 222.0},
            {'id': 'existing-beta', 'title': 'Existing Beta', 'source': 'cli', 'started_at': 112.0, 'ended_at': None, 'message_count': 4, 'preview': 'beta preview', 'last_active': 223.0},
        ]
        for session_id, title in self.titles.items():
            if session_id not in {item['id'] for item in base}:
                base.append({'id': session_id, 'title': title, 'source': 'api_server', 'started_at': 120.0, 'ended_at': None, 'message_count': 1, 'preview': '', 'last_active': 224.0})
        return base[:limit]

    async def get_session_messages(self, session_id):
        return list(self.session_messages.get(session_id, []))


def load_app(tmp_path: Path):
    db_path = tmp_path / "tailchat-test.db"
    os.environ["TAILCHAT_DB_PATH"] = str(db_path)
    os.environ.setdefault("HERMES_API_KEY", "test-key")
    DummyLocalHermesProvider.titles = {}
    DummyLocalHermesProvider.scripted_events = None
    DummyLocalHermesProvider.pending_approvals = {}
    DummyLocalHermesProvider.run_turn_calls = []
    DummyLocalHermesProvider.session_messages = {
        'existing-alpha': [
            {'id': 1, 'role': 'user', 'content': 'hello from cli', 'timestamp': 10.0},
            {'id': 2, 'role': 'assistant', 'content': '', 'timestamp': 11.0, 'finish_reason': 'tool_calls'},
            {'id': 3, 'role': 'tool', 'content': '{\"ok\":true}', 'timestamp': 12.0},
            {'id': 4, 'role': 'assistant', 'content': 'hello from hermes cli', 'timestamp': 13.0},
        ],
        'existing-beta': [
            {'id': 10, 'role': 'user', 'content': 'beta question', 'timestamp': 20.0},
            {'id': 11, 'role': 'assistant', 'content': 'beta answer', 'timestamp': 21.0},
        ],
    }

    stub = types.ModuleType("app.hermes_provider")
    stub.HermesProviderError = DummyHermesProviderError
    stub.LocalHermesProvider = DummyLocalHermesProvider
    sys.modules["app.hermes_provider"] = stub

    for name in ["app.config", "app.store", "app.main"]:
        sys.modules.pop(name, None)

    main = importlib.import_module("app.main")
    main = importlib.reload(main)
    return main.app, db_path


def test_health_endpoint_works_from_root_and_hermes_prefix(tmp_path: Path):
    app, db_path = load_app(tmp_path)

    with TestClient(app) as client:
        root = client.get("/health")
        assert root.status_code == 200
        assert root.json()["ok"] is True
        assert root.json()["db_path"] == str(db_path)
        assert root.json()["session_linkage_mode"] == "session-aware-abstraction-layer"

        prefixed = client.get("/hermes/health")
        assert prefixed.status_code == 200
        assert prefixed.json()["ok"] is True
        assert prefixed.json()["db_path"] == str(db_path)



def test_conversation_routes_work_through_root_and_hermes_prefix(tmp_path: Path):
    app, _db_path = load_app(tmp_path)

    with TestClient(app) as client:
        created = client.post("/api/conversations", json={"title": "smoke convo"})
        assert created.status_code == 200
        convo = created.json()
        assert convo["title"] == "smoke convo"

        listed = client.get("/hermes/api/conversations")
        assert listed.status_code == 200
        conversations = listed.json()
        assert any(item["id"] == convo["id"] for item in conversations)

        messages = client.get(f"/hermes/api/conversations/{convo['id']}/messages")
        assert messages.status_code == 200
        assert messages.json() == []



def test_job_creation_works_through_hermes_prefix(tmp_path: Path):
    app, _db_path = load_app(tmp_path)

    with TestClient(app) as client:
        created = client.post("/hermes/api/conversations", json={"title": "job smoke"})
        convo = created.json()

        queued = client.post(
            f"/hermes/api/conversations/{convo['id']}/jobs",
            json={"prompt": "background smoke", "delay_seconds": 0},
        )
        assert queued.status_code == 200
        job = queued.json()
        assert job["prompt"] == "background smoke"
        assert job["executor"] == "hermes"

        jobs = client.get(f"/api/conversations/{convo['id']}/jobs")
        assert jobs.status_code == 200
        listed_jobs = jobs.json()
        assert any(item["id"] == job["id"] for item in listed_jobs)


def test_conversation_linkage_metadata_is_backfilled_and_serialized(tmp_path: Path):
    import sqlite3

    db_path = tmp_path / "tailchat-test.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE conversations (id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
    conn.execute("INSERT INTO conversations (id, title) VALUES (?, ?)", ("legacy-convo", "Legacy chat"))
    conn.commit()
    conn.close()

    app, _db_path = load_app(tmp_path)

    with TestClient(app) as client:
        listed = client.get("/api/conversations")
        assert listed.status_code == 200
        legacy = next(item for item in listed.json() if item["id"] == "legacy-convo")
        assert legacy["hermes_session_id"] == "legacy-convo"
        assert legacy["sync_state"] == "linked"
        assert legacy["link_mode"] == "owned"
        assert legacy["cli_resume_command"] == "hermes --resume legacy-convo"

        created = client.post("/api/conversations", json={"title": "linked convo"})
        assert created.status_code == 200
        convo = created.json()
        assert convo["hermes_session_id"] == convo["id"]
        assert convo["sync_state"] == "linked"
        assert convo["link_mode"] == "owned"
        assert convo["cli_resume_command"] == f"hermes --resume {convo['id']}"


def test_new_conversation_syncs_title_to_hermes(tmp_path: Path):
    app, _db_path = load_app(tmp_path)

    with TestClient(app) as client:
        created = client.post("/api/conversations", json={"title": "Project Atlas"})
        assert created.status_code == 200
        convo = created.json()
        assert convo["hermes_title"] == "Project Atlas"
        assert convo["sync_state"] == "linked"
        assert convo["sync_error"] is None


def test_title_collision_keeps_tailchat_conversation_but_marks_sync_error(tmp_path: Path):
    app, _db_path = load_app(tmp_path)

    with TestClient(app) as client:
        first = client.post("/api/conversations", json={"title": "Shared Name"})
        assert first.status_code == 200
        second = client.post("/api/conversations", json={"title": "Shared Name"})
        assert second.status_code == 200
        convo = second.json()
        assert convo["title"] == "Shared Name"
        assert convo["sync_state"] == "sync_error"
        assert "already in use" in convo["sync_error"]
        assert convo["hermes_title"] is None


def test_patch_conversation_title_updates_hermes_title(tmp_path: Path):
    app, _db_path = load_app(tmp_path)

    with TestClient(app) as client:
        created = client.post("/api/conversations", json={"title": "Old Title"})
        convo = created.json()
        updated = client.patch(f"/api/conversations/{convo['id']}", json={"title": "New Title"})
        assert updated.status_code == 200
        body = updated.json()
        assert body["title"] == "New Title"
        assert body["hermes_title"] == "New Title"
        assert body["sync_state"] == "linked"
        assert body["sync_error"] is None


def test_attach_existing_hermes_session_creates_attached_conversation(tmp_path: Path):
    app, _db_path = load_app(tmp_path)

    with TestClient(app) as client:
        sessions = client.get('/api/hermes/sessions')
        assert sessions.status_code == 200
        listed = sessions.json()
        assert any(item['id'] == 'existing-alpha' for item in listed)

        attached = client.post('/api/conversations/attach', json={'hermes_session_id': 'existing-alpha'})
        assert attached.status_code == 200
        convo = attached.json()
        assert convo['hermes_session_id'] == 'existing-alpha'
        assert convo['link_mode'] == 'attached'
        assert convo['title'] == 'Attached existing-alp' or convo['title'] == 'Existing Alpha'


def test_attach_existing_session_prefers_hermes_title(tmp_path: Path):
    app, _db_path = load_app(tmp_path)

    with TestClient(app) as client:
        client.post('/api/conversations', json={'title': 'seed title'})
        attach = client.post('/api/conversations/attach', json={'hermes_session_id': 'existing-beta'})
        assert attach.status_code == 200
        convo = attach.json()
        assert convo['title'] == 'Existing Beta'
        assert convo['hermes_title'] == 'Existing Beta'


def test_attach_rejects_duplicate_hermes_session_links(tmp_path: Path):
    app, _db_path = load_app(tmp_path)

    with TestClient(app) as client:
        first = client.post('/api/conversations/attach', json={'hermes_session_id': 'existing-alpha'})
        assert first.status_code == 200
        second = client.post('/api/conversations/attach', json={'hermes_session_id': 'existing-alpha'})
        assert second.status_code == 409


def test_post_message_uses_attached_hermes_session_id(tmp_path: Path):
    app, _db_path = load_app(tmp_path)

    calls = []

    async def recording_run_turn(session_id, conversation_history, user_message, on_event):
        calls.append(session_id)
        await on_event({'event': 'run.completed', 'output': f'dummy response for: {user_message}'})

    import app.main as main_module
    main_module.hermes.run_turn = recording_run_turn

    with TestClient(app) as client:
        attached = client.post('/api/conversations/attach', json={'hermes_session_id': 'existing-alpha'})
        convo = attached.json()
        posted = client.post(f"/api/conversations/{convo['id']}/messages", json={'content': 'hello from tailchat'})
        assert posted.status_code == 200
        for _ in range(20):
            if calls:
                break
            time.sleep(0.01)
        assert calls == ['existing-alpha']


def test_attached_conversation_imports_curated_hermes_transcript(tmp_path: Path):
    app, _db_path = load_app(tmp_path)

    with TestClient(app) as client:
        attached = client.post('/api/conversations/attach', json={'hermes_session_id': 'existing-alpha'})
        convo = attached.json()

        messages = client.get(f"/api/conversations/{convo['id']}/messages")
        assert messages.status_code == 200
        body = messages.json()
        assert [item['role'] for item in body] == ['user', 'assistant']
        assert [item['content'] for item in body] == ['hello from cli', 'hello from hermes cli']
        assert all(item['origin'] == 'hermes_import' for item in body)


def test_attached_conversation_import_is_idempotent(tmp_path: Path):
    app, _db_path = load_app(tmp_path)

    with TestClient(app) as client:
        attached = client.post('/api/conversations/attach', json={'hermes_session_id': 'existing-alpha'})
        convo = attached.json()

        first = client.get(f"/api/conversations/{convo['id']}/messages")
        second = client.get(f"/api/conversations/{convo['id']}/messages")
        assert first.status_code == 200
        assert second.status_code == 200
        assert len(first.json()) == 2
        assert len(second.json()) == 2


def test_attached_import_cursor_allows_new_external_turns(tmp_path: Path):
    app, _db_path = load_app(tmp_path)

    with TestClient(app) as client:
        attached = client.post('/api/conversations/attach', json={'hermes_session_id': 'existing-beta'})
        convo = attached.json()

        first = client.get(f"/api/conversations/{convo['id']}/messages")
        assert len(first.json()) == 2

        DummyLocalHermesProvider.session_messages['existing-beta'].append(
            {'id': 12, 'role': 'assistant', 'content': 'later external note', 'timestamp': 25.0}
        )
        second = client.get(f"/api/conversations/{convo['id']}/messages")
        contents = [item['content'] for item in second.json()]
        assert contents == ['beta question', 'beta answer', 'later external note']


def test_startup_recovery_marks_incomplete_runs_jobs_and_preserves_pending_approvals(tmp_path: Path):
    import sqlite3

    db_path = tmp_path / "tailchat-test.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE conversations (id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE messages (id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'complete', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE runs (id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, trigger_type TEXT NOT NULL, trigger_text TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'queued', assistant_message_id TEXT, job_id TEXT, error_text TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE jobs (id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, prompt TEXT NOT NULL, executor TEXT NOT NULL DEFAULT 'hermes', status TEXT NOT NULL DEFAULT 'pending', delay_seconds INTEGER NOT NULL DEFAULT 0, run_after TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, lease_until TEXT, claimed_by TEXT, result_message_id TEXT, artifact_dir TEXT, metadata_json TEXT NOT NULL DEFAULT '{}', error_text TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE approvals (id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, run_id TEXT, status TEXT NOT NULL DEFAULT 'pending', summary TEXT NOT NULL, details_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, resolved_at TEXT, resolution TEXT);
        CREATE TABLE run_events (id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id TEXT NOT NULL, run_id TEXT, event_type TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        """
    )
    conn.execute("INSERT INTO conversations (id, title) VALUES (?, ?)", ("c1", "Recovered convo"))
    conn.execute("INSERT INTO messages (id, conversation_id, role, content, status) VALUES (?, ?, ?, ?, ?)", ("m1", "c1", "assistant", "partial output", "streaming"))
    conn.execute("INSERT INTO runs (id, conversation_id, trigger_type, status, assistant_message_id) VALUES (?, ?, ?, ?, ?)", ("r1", "c1", "user_message", "running", "m1"))
    conn.execute("INSERT INTO jobs (id, conversation_id, prompt, status, run_after, metadata_json) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, '{}')", ("j1", "c1", "do thing", "running"))
    conn.execute("INSERT INTO approvals (id, conversation_id, run_id, status, summary, details_json) VALUES (?, ?, ?, ?, ?, '{}')", ("a1", "c1", "r1", "pending", "needs approval"))
    conn.commit()
    conn.close()

    app, _db_path = load_app(tmp_path)

    with TestClient(app) as client:
        health = client.get('/health')
        assert health.status_code == 200
        recovery = health.json()['startup_recovery_summary']
        assert recovery['runs'] == 1
        assert recovery['jobs'] == 1
        assert recovery['approvals'] == 1
        assert recovery['messages'] == 1

        messages = client.get('/api/conversations/c1/messages').json()
        assert messages[0]['status'] == 'error'
        assert 'Tailchat interrupted this run during a restart' in messages[0]['content']

        approvals = client.get('/api/conversations/c1/approvals').json()
        assert approvals[0]['status'] == 'pending'


def test_rate_limited_text_only_retry_resets_partial_output(tmp_path: Path):
    app, _db_path = load_app(tmp_path)
    DummyLocalHermesProvider.scripted_events = [
        {'event': 'message.delta', 'delta': 'partial '},
        {'event': 'run.retrying', 'attempt': 1, 'next_attempt': 2, 'backoff_seconds': 1, 'error': '429 rate limit', 'reset_output': True},
        {'event': 'message.delta', 'delta': 'final answer'},
        {'event': 'run.completed', 'output': ''},
    ]

    with TestClient(app) as client:
        convo = client.post('/api/conversations', json={'title': 'retry chat'}).json()
        posted = client.post(f"/api/conversations/{convo['id']}/messages", json={'content': 'trigger retry'})
        assert posted.status_code == 200
        for _ in range(50):
            messages = client.get(f"/api/conversations/{convo['id']}/messages").json()
            assistant = next((message for message in reversed(messages) if message['role'] == 'assistant'), None)
            if assistant and assistant['status'] == 'complete':
                break
            time.sleep(0.01)
        messages = client.get(f"/api/conversations/{convo['id']}/messages").json()
        assistant = next(message for message in reversed(messages) if message['role'] == 'assistant')
        assert assistant['content'] == 'final answer'
        history = client.get(f"/api/conversations/{convo['id']}/events/history?limit=20").json()
        assert any(item['payload']['event'] == 'message.retry_reset' for item in history)



def test_resolving_rehydrated_approval_retries_interrupted_run(tmp_path: Path):
    import sqlite3

    db_path = tmp_path / "tailchat-test.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE conversations (id TEXT PRIMARY KEY, title TEXT NOT NULL, hermes_session_id TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE messages (id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'complete', metadata_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE runs (id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, trigger_type TEXT NOT NULL, trigger_text TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'queued', assistant_message_id TEXT, job_id TEXT, error_text TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE jobs (id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, prompt TEXT NOT NULL, executor TEXT NOT NULL DEFAULT 'hermes', status TEXT NOT NULL DEFAULT 'pending', delay_seconds INTEGER NOT NULL DEFAULT 0, run_after TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, lease_until TEXT, claimed_by TEXT, result_message_id TEXT, artifact_dir TEXT, metadata_json TEXT NOT NULL DEFAULT '{}', error_text TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE approvals (id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, run_id TEXT, status TEXT NOT NULL DEFAULT 'pending', summary TEXT NOT NULL, details_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, resolved_at TEXT, resolution TEXT);
        CREATE TABLE run_events (id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id TEXT NOT NULL, run_id TEXT, event_type TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        """
    )
    conn.execute("INSERT INTO conversations (id, title, hermes_session_id) VALUES (?, ?, ?)", ("c1", "Recovered approval convo", "session-1"))
    conn.execute("INSERT INTO messages (id, conversation_id, role, content, status, metadata_json) VALUES (?, ?, ?, ?, ?, '{}')", ("u1", "c1", "user", "please continue", "complete"))
    conn.execute("INSERT INTO messages (id, conversation_id, role, content, status, metadata_json) VALUES (?, ?, ?, ?, ?, '{}')", ("m1", "c1", "assistant", "[Tailchat interrupted this run during a restart. Please retry.]", "error"))
    conn.execute(
        "INSERT INTO runs (id, conversation_id, trigger_type, trigger_text, status, assistant_message_id, error_text) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("r1", "c1", "user_message", "please continue", "waiting_approval", "m1", ""),
    )
    conn.execute(
        "INSERT INTO approvals (id, conversation_id, run_id, status, summary, details_json) VALUES (?, ?, ?, ?, ?, ?)",
        ("a1", "c1", "r1", "pending", "needs approval", '{"approval_id":"provider-a1","session_id":"session-1","pattern_keys":["shell command via -c/-lc flag"],"command":"bash -lc echo hi","description":"Dangerous command requires approval"}'),
    )
    conn.commit()
    conn.close()

    app, _db_path = load_app(tmp_path)
    DummyLocalHermesProvider.scripted_events = [{'event': 'run.completed', 'output': 'replayed after restart'}]

    with TestClient(app) as client:
        resolved = client.post('/api/approvals/a1/resolve', json={'resolution': 'approved'})
        assert resolved.status_code == 200
        body = resolved.json()
        assert body['approval']['status'] == 'resolved'
        assert body['provider_result']['restored'] is True
        assert body['replay'] is not None

        for _ in range(50):
            messages = client.get('/api/conversations/c1/messages').json()
            if any(message['content'] == 'replayed after restart' for message in messages):
                break
            time.sleep(0.01)
        messages = client.get('/api/conversations/c1/messages').json()
        assert any(message['content'] == 'replayed after restart' and message['status'] == 'complete' for message in messages)



def test_post_message_marks_run_waiting_approval_when_approval_requested(tmp_path: Path):
    app, _db_path = load_app(tmp_path)
    DummyLocalHermesProvider.scripted_events = [
        {'event': 'approval.requested', 'approval': {'description': 'Dangerous command requires approval', 'command': 'rm -rf /tmp/nope'}},
    ]

    with TestClient(app) as client:
        convo = client.post('/api/conversations', json={'title': 'Approval chat'}).json()
        posted = client.post(f"/api/conversations/{convo['id']}/messages", json={'content': 'please ask approval'})
        assert posted.status_code == 200
        run_id = posted.json()['run_id']
        for _ in range(30):
            approvals = client.get(f"/api/conversations/{convo['id']}/approvals").json()
            if approvals:
                break
            time.sleep(0.01)
        approvals = client.get(f"/api/conversations/{convo['id']}/approvals").json()
        assert approvals
        import app.main as main_module
        run = main_module.store.get_run(run_id)
        assert run['status'] == 'waiting_approval'



def test_post_message_rejects_second_foreground_run_while_first_is_active(tmp_path: Path):
    app, _db_path = load_app(tmp_path)
    started = asyncio.Event()
    release = asyncio.Event()

    async def blocked_run_turn(session_id, conversation_history, user_message, on_event):
        started.set()
        await release.wait()
        await on_event({'event': 'run.completed', 'output': f'done: {user_message}'})

    import app.main as main_module
    main_module.hermes.run_turn = blocked_run_turn

    with TestClient(app) as client:
        convo = client.post('/api/conversations', json={'title': 'Serialized chat'}).json()
        first = client.post(f"/api/conversations/{convo['id']}/messages", json={'content': 'first'})
        assert first.status_code == 200
        for _ in range(50):
            if started.is_set():
                break
            time.sleep(0.01)
        assert started.is_set()

        second = client.post(f"/api/conversations/{convo['id']}/messages", json={'content': 'second'})
        assert second.status_code == 409
        payload = second.json()['detail']
        assert payload['status'] in {'queued', 'running', 'waiting_approval'}
        assert payload['run_id'] == first.json()['run_id']

        release.set()
        for _ in range(50):
            messages = client.get(f"/api/conversations/{convo['id']}/messages").json()
            if any(message['role'] == 'assistant' and message['status'] == 'complete' for message in messages):
                break
            time.sleep(0.01)
        messages = client.get(f"/api/conversations/{convo['id']}/messages").json()
        assert any(message['content'] == 'done: first' for message in messages)



def test_event_history_supports_after_id_cursor(tmp_path: Path):
    app, _db_path = load_app(tmp_path)

    with TestClient(app) as client:
        convo = client.post('/api/conversations', json={'title': 'Cursor chat'}).json()
        first = client.post(f"/api/conversations/{convo['id']}/messages", json={'content': 'first'})
        assert first.status_code == 200
        for _ in range(30):
            history = client.get(f"/api/conversations/{convo['id']}/events/history?limit=20").json()
            if history:
                break
            time.sleep(0.01)
        history = client.get(f"/api/conversations/{convo['id']}/events/history?limit=20").json()
        assert len(history) >= 2
        cursor = history[0]['id']
        later = client.get(f"/api/conversations/{convo['id']}/events/history?after_id={cursor}&limit=20")
        assert later.status_code == 200
        later_events = later.json()
        assert all(item['id'] > cursor for item in later_events)
        assert any(item['payload']['event'] == 'message.completed' for item in later_events)


def test_replay_run_turn_trims_original_user_prompt_from_history(tmp_path: Path):
    app, _db_path = load_app(tmp_path)

    import app.main as main_module

    with TestClient(app) as client:
        convo = client.post('/api/conversations', json={'title': 'Replay chat'}).json()
        user_msg = main_module.store.add_message(convo['id'], 'user', 'repeat me', status='complete')
        interrupted_msg = main_module.store.add_message(
            convo['id'],
            'assistant',
            '[Tailchat interrupted this run during a restart. Please retry.]',
            status='error',
        )
        interrupted_run = main_module.store.create_run(
            convo['id'],
            'user_message',
            trigger_text='repeat me',
            assistant_message_id=interrupted_msg['id'],
        )
        main_module.store.update_run(interrupted_run['id'], status='error', error_text=main_module.RESTART_INTERRUPTED_ERROR)

        replay = asyncio.run(main_module.retry_interrupted_run(main_module.store.get_run(interrupted_run['id'])))
        assert replay is not None
        for _ in range(50):
            messages = client.get(f"/api/conversations/{convo['id']}/messages").json()
            if any(message['id'] == replay['assistant_message_id'] and message['status'] == 'complete' for message in messages):
                break
            time.sleep(0.01)

        assert DummyLocalHermesProvider.run_turn_calls
        last_call = DummyLocalHermesProvider.run_turn_calls[-1]
        assert last_call['user_message'] == 'repeat me'
        assert all(item['content'] != 'repeat me' for item in last_call['conversation_history'])
        assert all('interrupted this run during a restart' not in item['content'] for item in last_call['conversation_history'])


def test_event_stream_after_id_replays_history_without_duplicates(tmp_path: Path):
    app, _db_path = load_app(tmp_path)

    import app.main as main_module

    async def collect_events():
        convo = main_module.store.create_conversation('SSE replay chat')
        event_one = {'event': 'message.created', 'message': {'id': 'm1'}}
        event_two = {'event': 'message.completed', 'message_id': 'm1', 'content': 'done'}
        first_id = main_module.store.append_run_event(convo['id'], None, event_one['event'], json.dumps(event_one))
        second_id = main_module.store.append_run_event(convo['id'], None, event_two['event'], json.dumps(event_two))
        duplicate_live = dict(event_two)
        duplicate_live['_event_id'] = second_id
        fresh_live = {'event': 'message.created', 'message': {'id': 'm2'}, '_event_id': second_id + 1}

        stream = await main_module.events(convo['id'], after_id=first_id)
        generator = stream.body_iterator
        first_payload = json.loads((await generator.__anext__())['data'])
        assert first_payload['_event_id'] == second_id

        await main_module.broker.publish(convo['id'], duplicate_live)
        await main_module.broker.publish(convo['id'], fresh_live)
        second_payload = json.loads((await generator.__anext__())['data'])
        assert second_payload['_event_id'] == second_id + 1
        await generator.aclose()

    asyncio.run(collect_events())


def test_resolving_non_pending_approval_returns_conflict(tmp_path: Path):
    app, _db_path = load_app(tmp_path)

    with TestClient(app) as client:
        convo = client.post('/api/conversations', json={'title': 'Expired approval chat'}).json()
        import app.main as main_module
        approval = main_module.store.create_approval(convo['id'], 'stale approval', {'approval_id': 'provider-1'})
        main_module.store.update_approval_status(approval['id'], 'expired', 'restart')
        resolved = client.post(f"/api/approvals/{approval['id']}/resolve", json={'resolution': 'approved'})
        assert resolved.status_code == 409
