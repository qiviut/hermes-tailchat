from __future__ import annotations

import importlib
import os
import sys
import types
from pathlib import Path

from fastapi.testclient import TestClient


class DummyHermesProviderError(RuntimeError):
    pass


class DummyLocalHermesProvider:
    async def run_turn(self, session_id, conversation_history, user_message, on_event):
        await on_event({"event": "run.completed", "output": f"dummy response for: {user_message}"})

    async def resolve_approval(self, approval_id, decision):
        return {
            "approval_id": approval_id,
            "decision": decision,
            "resolved_count": 1,
        }


def load_app(tmp_path: Path):
    db_path = tmp_path / "tailchat-test.db"
    os.environ["TAILCHAT_DB_PATH"] = str(db_path)
    os.environ.setdefault("HERMES_API_KEY", "test-key")

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
