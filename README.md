# Hermes Tailchat

A tailnet-only chat app that wraps a local Hermes backend.

Current MVP:
- FastAPI backend
- SQLite persistence
- SSE live updates
- Static single-page chat UI
- Local Hermes integration via `app/hermes_provider.py`
- Tailscale Serve-friendly routing, including subpath hosting at `/hermes`

Current assumptions:
- this is a single-user personal tool optimized for fast iteration
- the app binds to localhost
- exposure to other devices happens through Tailscale Serve
- Hermes itself stays local to the machine

## Architecture

See `docs/architecture.md`.

## What works today

- create conversations
- send messages
- stream Hermes deltas, tool events, and final responses into the UI
- persist local transcript state in SQLite
- queue background jobs that continue server-side after the HTTP request returns
- run behind Tailscale Serve at either `/` or a subpath such as `/hermes`

## Current gaps

- no mobile-focused offline/resume UX yet
- no Tailscale identity auth or app auth yet
- no comprehensive automated tests yet
- no CI, dependency update automation, or SAST yet
- no polished deployment packaging beyond a local user systemd service

## Repo safety / secrets

Do not commit real secrets.

Safe patterns:
- keep `HERMES_API_KEY` outside git in the environment or a host-local env file
- keep `tailchat.db` local only
- keep systemd service files with real secrets outside the repo, or use `EnvironmentFile=` pointing at an ignored file

Ignored by git already:
- `.env`
- `.venv/`
- `*.db`
- `*.db-shm`
- `*.db-wal`

## Configuration

Environment variables used by the app:
- `HERMES_API_BASE_URL` default: `http://127.0.0.1:8642`
- `HERMES_API_KEY`
- `TAILCHAT_DB_PATH` default: `./tailchat.db`

Example local env file:

```bash
cp .env.example .env
# then edit .env locally with your real values
```

## Local development run

Requirements:
- Python 3.11+
- a working Hermes installation on the same machine
- Hermes credentials configured locally

Create a venv and install deps:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Run Tailchat directly:

```bash
export HERMES_API_KEY=replace-me
uvicorn app.main:app --host 127.0.0.1 --port 8766 --reload
```

Then open:
- `http://127.0.0.1:8766` locally

If you want to test subpath hosting locally, these also work because the app strips the `/hermes` prefix:
- `http://127.0.0.1:8766/hermes`
- `http://127.0.0.1:8766/hermes/`

## Persistent local service

A practical single-user setup is a user systemd service that binds Tailchat to localhost.

Example unit:

```ini
[Unit]
Description=Hermes Tailchat
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=%h/.openclaw/workspace/hermes-tailchat
Environment=PYTHONPATH=%h/.openclaw/workspace/hermes-tailchat
EnvironmentFile=%h/.config/hermes-tailchat.env
ExecStart=%h/.hermes/hermes-agent/venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8766
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
```

Example env file referenced by `EnvironmentFile=`:

```bash
HERMES_API_KEY=replace-me
# optional overrides
# HERMES_API_BASE_URL=http://127.0.0.1:8642
# TAILCHAT_DB_PATH=/path/to/tailchat.db
```

Then:

```bash
systemctl --user daemon-reload
systemctl --user enable --now hermes-tailchat.service
systemctl --user status hermes-tailchat.service
```

## Tailscale Serve

Recommended pattern:
- keep OpenClaw or other control UI on `/`
- expose Tailchat on `/hermes`
- keep both backends bound to localhost only

Example:

```bash
tailscale serve --bg http://127.0.0.1:18789
tailscale serve --bg --set-path /hermes http://127.0.0.1:8766
```

With that in place, the app is reachable at:
- `https://YOUR-NODE.ts.net/hermes`

The frontend is prefix-aware, and the backend strips `/hermes`, so subpath hosting works without a separate reverse proxy.

## Quick verification

Local health checks:

```bash
curl http://127.0.0.1:8766/health
curl http://127.0.0.1:8766/hermes/api/conversations
```

Tailnet verification:

```bash
tailscale serve status
```

Smoke test prompt:
- send `Reply with exactly: tailchat smoke test ok`
- expect `tailchat smoke test ok`

## Fast shipping workflow

Recommended short-loop flow for this repo:

1. work on a feature branch
2. commit small, reviewable slices
3. push the branch
4. create a PR immediately
5. merge quickly once review/criteria are satisfied

A helper script is included:

```bash
scripts/ship-pr.sh
```

Policy reference:
- `docs/policies/branch-protection-and-pr-flow.md`

That script:
- refuses to run from `main`
- refuses to run with a dirty worktree
- creates a PR for the current branch if one does not exist
- prints review/check status

Optional modes:

```bash
scripts/ship-pr.sh --arm-auto
scripts/ship-pr.sh --merge-now
```

Notes:
- `--arm-auto` enables GitHub auto-merge using squash merge.
- `--merge-now` merges immediately using squash merge.
- if the repository lacks required review/check protections, these modes may merge immediately, so add GitHub protections before relying on them as policy.

## Suggested next steps

Near-term roadmap themes:
- mobile-friendly UX and reconnect behavior
- better background-job visibility and resumability
- project hygiene: tests, CI, Dependabot, SAST
- lightweight hardening without slowing down iteration
