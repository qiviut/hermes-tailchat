from __future__ import annotations

import importlib
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

    async def run_turn(self, session_id, conversation_history, user_message, on_event):
        await on_event({"event": "run.completed", "output": f"dummy response for: {user_message}"})

    async def resolve_approval(self, approval_id, decision):
        return {
            "approval_id": approval_id,
            "decision": decision,
            "resolved_count": 1,
        }

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
