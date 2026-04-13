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

## Repository guidance

Repo-specific agent/operator guidance lives in `AGENTS.md`.

Important project docs:
- `docs/policies/branch-protection-and-pr-flow.md`
- `docs/policies/traceability.md`
- `docs/design/2026-04-13-hermes-codex-multi-agent-coordination.md`
- `docs/agents/`
- `docs/research/`


## What works today

- create conversations
- send messages
- stream Hermes deltas, tool events, and final responses into the UI
- persist local transcript state in SQLite
- queue background jobs that continue server-side after the HTTP request returns
- route background jobs to either Hermes or Codex, with Codex artifacts captured under `.tailchat/codex-jobs/`
- run behind Tailscale Serve at either `/` or a subpath such as `/hermes`

## Current gaps

- no mobile-focused offline/resume UX yet
- no Tailscale identity auth or app auth yet
- no comprehensive automated tests beyond the initial smoke suite yet
- CI exists with trusted-branch quick checks, but dependency update automation, richer SAST, and AI review are still upcoming
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
- for Codex background jobs: `codex` on `PATH`
- for Hermes↔Codex coordination: `am` on `PATH` (optional but recommended; the runner will use Agent Mail when available)

Create a venv and install deps:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Run Tailchat directly:

```bash
export HERMES_API_KEY=***
uvicorn app.main:app --host 127.0.0.1 --port 8766 --reload
```

Then open:
- `http://127.0.0.1:8766` locally

If you want to test subpath hosting locally, these also work because the app strips the `/hermes` prefix:
- `http://127.0.0.1:8766/hermes`
- `http://127.0.0.1:8766/hermes/`

## Background executors

Tailchat now supports two background-job executors:

- `hermes` — the existing in-process Hermes provider path
- `codex` — a Codex CLI worker path backed by `scripts/run_codex_background.py`

The web UI exposes a small executor picker next to **Queue job**.

Codex job behavior:
- runs `codex exec --json --full-auto`
- writes raw artifacts under `.tailchat/codex-jobs/<job-id>/`
- stores the final assistant-style summary in the conversation transcript
- uses Agent Mail bootstrap / reservation / notification hooks when `am` is available

Important notes:
- Codex jobs are intended for repo-facing implementation/review work while Tailchat stays responsive as the user-facing surface.
- Agent Mail is used as a coordination supplement; the primary Tailchat job state still lives in SQLite.
- For the architectural review and tradeoff analysis that led to this implementation, see `docs/research/2026-04-13-parallel-background-orchestration-research.md`.

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
HERMES_API_KEY=***
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

### Local-first auto-redeploy on `main`

If this host is the place where changes are made first, the main failure mode is usually:
- local `main` changes
- the running systemd service keeps serving the old loaded code
- nobody restarts it

This repo now includes a local-first deploy path:
- `scripts/deploy-local.sh`
- `scripts/install-local-autodeploy.sh`
- `systemd/hermes-tailchat-deploy.service`
- `systemd/hermes-tailchat-deploy.path`

Manual deploy from local `main`:

```bash
scripts/deploy-local.sh
```

That script:
- refuses to deploy from non-`main`
- restarts `hermes-tailchat.service`
- waits for `/health`
- records the deployed git revision in `~/.local/state/hermes-tailchat/deployed-rev`

Install automatic local redeploy when `.git/refs/heads/main` changes:

```bash
scripts/install-local-autodeploy.sh
```

That installs a user-level path unit which watches:
- `%h/.openclaw/workspace/hermes-tailchat/.git/refs/heads/main`

When local `main` advances, systemd runs `scripts/deploy-local.sh` automatically.

Useful commands:

```bash
systemctl --user status hermes-tailchat-deploy.path
systemctl --user status hermes-tailchat-deploy.service
journalctl --user -u hermes-tailchat-deploy.service -n 50 --no-pager
```

If you need to force a restart even when the deployed revision file already matches:

```bash
FORCE_DEPLOY=1 scripts/deploy-local.sh
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
- `docs/policies/traceability.md`

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
