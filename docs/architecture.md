# Tailnet-only Hermes Chat App Architecture

## Recommendation in one line
Use a Python FastAPI backend with PostgreSQL, Redis, and a small React/Next.js frontend served only on the Tailscale interface; integrate Hermes through a long-lived local subprocess/session adapter first, while keeping an internal provider interface that can later switch to Hermes's gateway/API surfaces.

## Why this stack
- Python fits Hermes best because Hermes already exists locally as Python CLI/gateway tooling.
- FastAPI + asyncio makes SSE/WebSocket endpoints, background orchestration, and approval wait states straightforward.
- PostgreSQL gives durable chat/session/job storage without inventing custom persistence.
- Redis gives simple pub/sub, transient event fanout, resumable job progress, and rate-limiting/locks if needed.
- React/Next.js gives a practical chat UI and approval modal flow; can be replaced later without changing backend contracts.
- Everything can stay bound to `127.0.0.1` or the Tailscale IP / `tailscale serve`.

## Concrete stack
- Backend API: Python 3.13 + FastAPI + Uvicorn
- ORM/query layer: SQLAlchemy + Alembic
- DB: PostgreSQL 16
- Event fanout/cache: Redis
- Job runner: ARQ or Dramatiq (favor ARQ for asyncio/Python simplicity)
- Frontend: Next.js/React + TypeScript
- Realtime transport: SSE first, WebSocket only if/when bidirectional live typing or richer state sync becomes necessary
- Reverse access:
  - simplest: bind backend/frontend to localhost and expose with `tailscale serve`
  - alternative: bind directly to tailnet IP and firewall to `tailscale0`
- Process manager: systemd units for api, worker, frontend
- Optional packaging later: docker-compose or podman-compose, but do not start there unless deployment repeatability becomes painful

## Core architectural choice: how to talk to Hermes
### Phase-1 default: Hermes subprocess/session adapter
Wrap Hermes as a managed local subprocess per active conversation/run, not by scraping CLI text output ad hoc, but by owning the session lifecycle in a thin adapter.

Recommended adapter contract:
- `create_session(session_id, model, tools_profile, cwd)`
- `send_user_message(session_id, message, attachments?)`
- `stream_events(session_id)` -> token deltas, tool-start/tool-end, status updates, approval-requested, final-response
- `approve(approval_id, decision, scope?)`
- `interrupt(run_id)`
- `resume(run_id/session_id)`

Why subprocess first:
- Lowest integration friction with current Hermes installation.
- Preserves parity with Hermes CLI behavior and existing tools/approvals.
- Lets you ship quickly without depending on stabilizing an external API surface.

How to implement safely:
- Start Hermes in PTY/background mode only through the backend, never from the browser.
- Parse structured callbacks/events if Hermes exposes them; otherwise wrap Hermes through its gateway/API surfaces where they exist.
- One OS process per active run, not one permanent process per user forever.
- Persist app-level state separately from Hermes process state so runs can be recovered or marked failed on restart.

### Phase-2 evolution path: internal "Hermes provider" interface
Do not let the web app depend directly on subprocess details. Build an internal provider interface with implementations such as:
- `SubprocessHermesProvider`
- `GatewayApiHermesProvider`
- later maybe `MCPHermesProvider`

This gives you a migration path if Hermes's API/gateway becomes the cleaner integration point.

### Practical note from local codebase inspection
The local Hermes tree already has:
- a gateway/session store with persisted sessions
- an API server adapter with `POST /v1/runs` and `GET /v1/runs/{run_id}/events` SSE
- an MCP bridge with polling/waiting events and approval request handling

That means the best pragmatic implementation is likely:
1. start with a direct Python-side wrapper around Hermes/gateway internals or the existing API server surface
2. normalize those events into your own app event model
3. only fall back to raw CLI subprocess control where the higher-level surface is missing

## App components
### 1) Web frontend
Responsibilities:
- chat list + conversation view
- composer + file attach
- live event stream subscription
- job status pane
- approval inbox/modal
- reconnect/resume from last event cursor

Keep frontend dumb:
- it renders state from backend APIs/events
- it never talks to Hermes directly
- it never decides approval policy itself

### 2) API server
Responsibilities:
- authn/authz for tailnet users
- CRUD for chats, messages, jobs, approvals
- run creation and attachment upload
- SSE endpoint for session events
- HTTP endpoints to approve/deny requests
- translate Hermes-native events into app-native events

Suggested endpoints:
- `POST /api/chats`
- `GET /api/chats`
- `GET /api/chats/:id/messages`
- `POST /api/chats/:id/messages`
- `POST /api/chats/:id/runs`
- `GET /api/chats/:id/events?cursor=...` (SSE)
- `GET /api/jobs/:id`
- `POST /api/approvals/:id/resolve`
- `POST /api/runs/:id/cancel`

### 3) Hermes adapter service
A Python module inside the backend, not a separate microservice at first.

Responsibilities:
- manage Hermes sessions/runs
- map Hermes events to app events
- capture approval prompts as first-class objects
- enforce timeout/cancel/retry behavior
- recover orphaned runs after backend restart

### 4) Worker
Responsibilities:
- long-running jobs initiated by user or server
- job retries, backoff, scheduled follow-ups
- post async results back into chat as assistant/system messages

Pattern:
- API creates job record and enqueues work
- worker executes Hermes run or side task
- worker publishes progress to Redis
- API fanouts progress to connected SSE subscribers
- final output is committed to DB and appears in the conversation

### 5) Persistence layer
Use PostgreSQL for durable app state. Suggested tables:
- `users`
- `chat_sessions`
- `chat_messages`
- `runs`
- `run_events`
- `approval_requests`
- `background_jobs`
- `attachments`
- `idempotency_keys`

Model guidance:
- `chat_sessions`: stable conversation identity owned by your app
- `runs`: one user send or async task execution attempt
- `chat_messages`: canonical transcript shown to users
- `run_events`: append-only event log for replay/resume/debugging
- `approval_requests`: explicit pending/resolved records with audit info

Store both:
- canonical message transcript for UX
- append-only event log for replay and debugging

### 6) Event bus
Use Redis pub/sub or Redis streams.

Recommendation:
- Redis pub/sub for simple live fanout now
- add Redis streams only if you need broker-level replay beyond DB event log

Backend flow:
- event saved to Postgres
- event published to Redis channel `chat:{session_id}`
- SSE subscribers receive it immediately
- reconnecting clients request missed events from Postgres by cursor

## Realtime transport choice
Use SSE first.

Why SSE is the right default here:
- server-to-client is the dominant need: token stream, tool progress, job updates, approval prompts, completion notices
- simpler than WebSockets through proxies and Tailscale serve
- built-in reconnection semantics are good enough
- easier backend implementation and debugging

Use WebSocket only if later needed for:
- collaborative presence
- streaming audio
- live cursor/edit coauthoring
- high-frequency client events beyond standard POSTs

## Data flow
### Normal chat turn
1. Browser POSTs user message to backend.
2. Backend persists user message and creates a `run` row.
3. Backend asks Hermes adapter to start/resume the session.
4. Hermes emits token/tool/progress events.
5. Backend stores normalized events in `run_events`, publishes to Redis, and streams them over SSE.
6. When complete, backend writes final assistant message to `chat_messages` and marks run complete.

### Long-running/background task
1. User starts task or Hermes decides to spawn background work.
2. Backend creates `background_job` + chat message like "started job...".
3. Worker performs the task and emits progress events.
4. Progress appears live in chat via SSE.
5. On completion/failure, worker writes final chat message and updates job state.

### Server-initiated/asynchronous message
Examples: scheduled reminder, finished crawl, approval timeout, external webhook translated into a chat update.
1. Worker/scheduler creates a system or assistant message linked to session.
2. Event is committed to DB and published.
3. Connected clients see it immediately; disconnected ones catch up from persisted messages/events.

## Approval prompt architecture
Treat approvals as workflow objects, not transient text.

### Required behavior
When Hermes needs approval:
- pause the run in backend state
- create `approval_requests` row with structured payload
- emit `approval_requested` event to the UI
- show a modal/drawer with explicit action, scope, risk, command preview, cwd, and timeout
- only resume the run when the backend receives a signed approval decision

### Approval object fields
- `approval_id`
- `run_id`
- `session_id`
- `kind` (`shell`, `network`, `file_write`, `dangerous_tool`, etc.)
- `summary`
- `details_json`
- `risk_level`
- `requested_at`
- `expires_at`
- `status`
- `resolved_by`
- `resolution`
- `resolution_note`

### UX recommendation
- default deny on timeout
- offer `approve once`, `deny`, and later `approve for this run` / `approve for this session`
- never hide raw command/file path/network target details
- require a second confirmation for clearly destructive actions
- show exactly what will execute, not a paraphrase only
- keep an audit trail visible in the conversation or side panel

### Important safety rule
The browser should not directly unblock Hermes. All approval decisions must go through the backend, which validates session ownership, decision scope, and run state before signaling Hermes.

## Persistence and recovery
Design for restart safety from day one.

On backend restart:
- reconstruct active SSE subscriptions from clients reconnecting
- mark orphaned in-flight runs as `recovering`
- ask Hermes adapter whether the run/session still exists
- if recoverable, resume event streaming
- otherwise mark failed/interrupted and append a system message explaining what happened

For persistent chat sessions:
- app session IDs remain stable forever
- Hermes session IDs may be rotated or recreated under the hood
- app owns mapping from app session -> Hermes session

## Auth/access in a tailnet-only app
Keep it simple but do not skip auth just because Tailscale is present.

Recommended pattern:
- expose app only via Tailscale (`tailscale serve` or bind to `tailscale0`)
- require Tailscale identity headers if using `tailscale serve`/funnel-disabled setup, or use Tailscale OAuth/Serve auth where practical
- map allowed tailnet users/groups to app roles
- add app session cookies/JWT on top for normal web UX

If you want the simplest acceptable initial model:
- Tailscale network restriction + single local admin login seeded from env

If multi-user is expected soon:
- use Tailscale identity as SSO and enforce per-user session ownership in Postgres

## Deployment topology
Recommended first deployment on one Linux machine:
- `chat-api.service` -> FastAPI/Uvicorn on 127.0.0.1:8080
- `chat-worker.service` -> ARQ worker
- `chat-web.service` -> Next.js on 127.0.0.1:3000 or static export served by API
- Postgres local
- Redis local
- `tailscale serve` routes tailnet HTTPS -> web/app

Simplest external shape:
- browser on tailnet -> Tailscale HTTPS -> Next.js/UI
- UI calls backend via same origin `/api/*`
- backend talks locally to Hermes subprocess/API

## Concrete recommendation summary
If building this today, I would choose:
- FastAPI backend
- Postgres
- Redis
- ARQ worker
- Next.js frontend
- SSE for live updates
- Hermes integrated through a provider abstraction, implemented first by wrapping the existing local Hermes gateway/API/subprocess capabilities
- Approval requests as explicit DB-backed workflow entities

## Main risks and mitigations
### 1) Hermes integration surface may change
Mitigation: isolate behind `HermesProvider` interface and normalize events at your boundary.

### 2) Approval prompts can deadlock runs
Mitigation: explicit paused state, timeout handling, resume/deny endpoints, and clear operator UI.

### 3) Lost live updates on reconnect
Mitigation: append-only `run_events` with cursor replay; SSE is only a transport, not the source of truth.

### 4) Long-running jobs can outlive HTTP requests
Mitigation: worker queue + persisted job state; never couple long work to the request lifecycle.

### 5) Single-box operational complexity
Mitigation: use systemd + local Postgres/Redis first; avoid Kubernetes/extra services.

## Phased implementation plan
### Phase 0: thin vertical slice
- FastAPI app
- Postgres schema for chats/messages/runs/events/approvals
- SSE endpoint
- single-user auth
- Hermes provider using local subprocess or existing API surface
- basic React chat UI

Goal: one persistent chat with streamed responses and manual approval handling.

### Phase 1: make it robust
- Redis pub/sub fanout
- ARQ worker for long jobs
- resumable runs and replay-from-cursor
- approval audit log and timeout policy
- cancel/retry controls

Goal: reliable daily-use internal tool.

### Phase 2: multi-user and better ops
- Tailscale identity-based auth
- per-user/persession permissions
- attachment handling
- admin view for stuck runs/jobs/approvals
- metrics/logging/tracing

Goal: stable team tool on the tailnet.

### Phase 3: evolve integration
- switch Hermes provider from subprocess-heavy control to cleaner gateway/API/MCP integration where available
- richer approval scopes/policies
- optional WebSocket features if truly needed

## Opinionated simplifications to avoid overengineering
- Do not split into microservices initially.
- Do not use Kafka/NATS first; Postgres + Redis is enough.
- Do not start with WebSockets if SSE works.
- Do not couple frontend directly to Hermes event formats.
- Do not treat approval prompts as plain assistant text.
- Do not rely on in-memory only session/job state.
