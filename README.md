# Hermes Tailchat

A tailnet-only chat app that wraps a local Hermes backend.

Current MVP:
- FastAPI backend
- SQLite persistence
- SSE live updates
- Static single-page chat UI
- Hermes integration through the local Hermes API server (`/v1/runs`)

Current assumptions:
- The app binds to localhost
- Exposure to other devices should happen via Tailscale (`tailscale serve`)
- Hermes API server also binds to localhost and is protected by a bearer token

## Architecture

See `docs/architecture.md`.

## MVP features

- Create conversations
- Send messages
- Stream Hermes deltas, tool events, and final responses into the UI
- Keep a persistent local transcript
- Let Hermes work asynchronously in the background after the HTTP request returns

## Not done yet

- Tailscale identity auth
- Structured approval prompts bridged from Hermes
- Persistent worker queue
- Multi-user permissions
- Attachment upload
- Robust reconnect/replay by event cursor

## Local run

1. Create a venv and install deps
2. Start Hermes gateway with API server enabled on localhost
3. Start this app
4. Optionally expose it with `tailscale serve`

Example:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
uvicorn app.main:app --host 127.0.0.1 --port 8765 --reload
```

Then open:
- `http://127.0.0.1:8765` locally
- or a tailnet URL once `tailscale serve` is configured

## Hermes API server env

The backend expects:
- `HERMES_API_BASE_URL` default: `http://127.0.0.1:8642`
- `HERMES_API_KEY`
- `TAILCHAT_DB_PATH` default: `./tailchat.db`

## Suggested next steps

- Add Tailscale auth headers or serve-based access control
- Add approval workflow plumbing
- Add persistent job queue and scheduled/server-initiated messages
- Add tests and packaging
