# Smoke harness research for Hermes Tailchat

Bead: `hermes-tailchat-47o`
Date: 2026-04-11

## Goal

Choose the fastest stable test harness that will help this repo ship improvements faster by catching regressions in the working `/hermes` deployment shape without introducing a heavy testing burden.

## Current codebase shape

Relevant observations:
- there is currently no `tests/` directory
- the app is a small FastAPI service with a static frontend and SQLite store
- the live chat stream uses in-memory broker queues plus persisted SQLite state
- the Hermes runtime path is real and relatively expensive compared to ordinary HTTP route checks
- `/hermes` support depends on both frontend base-path awareness and backend prefix stripping

Important code facts:
- backend endpoints exist for conversations/messages/jobs/approvals
- `/api/conversations/{conversation_id}/events` is SSE-only and queue-backed
- `/api/conversations/{conversation_id}/events/history` exists and is persisted
- the frontend currently embeds its JS inside `app/static/index.html`
- the app can be imported directly as `app.main:app`

## What we most need from a smoke harness

The harness should protect these high-value regression targets:
1. app boots successfully
2. `/health` works
3. `/hermes` subpath hosting still works
4. conversations can be created and listed
5. a basic user-message flow at least reaches the app correctly
6. ideally, one opt-in real Hermes-backed prompt confirms end-to-end usefulness

Because the user wants rapid iteration, the harness should not make every change expensive.

## Candidate harnesses considered

### Option A: FastAPI `TestClient` / in-process pytest smoke
Pros:
- very fast
- easy to run in CI
- no network or Tailscale needed
- can directly hit `/health`, `/api/conversations`, `/hermes/api/conversations`
- ideal for catching route and prefix regressions

Cons:
- does not verify deployed process wiring by itself
- does not prove the real Hermes backend path works unless explicitly mocked or environment-backed
- SSE coverage is possible but more awkward than plain request/response checks

Assessment:
- this should be the foundation

### Option B: Local HTTP smoke script against a running process
Pros:
- tests the app more like an operator uses it
- can verify a live uvicorn instance and subpath behavior
- straightforward for shell/Python scripting

Cons:
- slower and more brittle than in-process tests
- requires process lifecycle management
- less ideal as the very first CI safety net

Assessment:
- useful as a second layer, especially for deploy/runbook validation
- not the first thing I would build before pytest-level smoke exists

### Option C: Browser-level smoke (Playwright or similar)
Pros:
- verifies real UI behavior
- good for mobile layout regression coverage later
- best for end-to-end confidence once the app matures a bit

Cons:
- heavier setup
- slower
- more moving parts than needed for the first smoke layer
- likely overkill as the first regression net for this repo

Assessment:
- valuable later for mobile/layout and reconnect-focused checks
- not the first harness to implement

### Option D: Real Hermes-backed smoke only
Pros:
- highest realism
- proves the real value path still works

Cons:
- slower
- depends on local credentials/runtime/environment
- can fail for reasons unrelated to app correctness
- bad candidate for required PR checks in every context

Assessment:
- should exist, but as opt-in or separately gated smoke rather than the base CI check

## Recommended harness strategy

### Best first move: layered smoke, starting with in-process pytest
Use a two-layer approach.

#### Layer 1: required fast smoke
Implement first using pytest + FastAPI in-process requests:
- import the app directly
- use a temporary SQLite DB path
- verify:
  - `/health`
  - `/api/conversations`
  - conversation creation
  - message placeholder creation path if feasible without real Hermes
  - `/hermes/api/conversations` through the mounted-prefix path

Why this is best:
- fastest feedback
- catches the most likely regressions from current development
- low operational burden
- safe for CI on `pull_request`

#### Layer 2: opt-in real Hermes-backed smoke
Add a second smoke path that runs only when explicitly enabled by environment, for example:
- requires `HERMES_API_KEY`
- sends a deterministic prompt like `Reply with exactly: tailchat smoke test ok`
- verifies exact response

Why this is best:
- preserves realism without making every branch/PR depend on a live privileged environment
- suitable for trusted contexts, local verification, or later scheduled runs

## Specific recommendation for this repo

### For `hermes-tailchat-sju`
Implement:
- pytest-based in-process smoke
- temporary database isolation
- direct route tests for both root and `/hermes` prefixed access

Minimum set:
1. app import succeeds
2. `GET /health` returns 200
3. `GET /api/conversations` returns 200
4. `POST /api/conversations` creates a conversation
5. `GET /hermes/api/conversations` works through prefix stripping

Nice-to-have in same bead if cheap:
- `POST /api/conversations/{id}/jobs`
- `GET /api/conversations/{id}/messages`

### For `hermes-tailchat-uao`
Implement separately:
- environment-gated real Hermes smoke
- use real runtime only when secrets/runtime are present
- make failure output obvious and operator-friendly

### For `hermes-tailchat-kbq`
Use the review bead to verify the smoke suite would have caught:
- `/hermes` prefix regressions
- import/runtime mismatch issues
- basic startup failures

## Why not start with Playwright

For this repo right now, Playwright-first would be the wrong optimization because:
- the biggest need is protecting routing/startup/basic API behavior quickly
- there is no existing test harness yet
- the user wants faster shipping, not a large test-infrastructure project

Playwright should come later when:
- the mobile layout bead needs visual regression checks
- reconnect flows need browser-realistic verification

## Proposed implementation order

1. `hermes-tailchat-sju`
   Add fast local API and `/hermes` route smoke checks with pytest
2. `hermes-tailchat-kbq`
   Review that coverage against known regressions
3. `hermes-tailchat-uao`
   Add opt-in real Hermes-backed end-to-end smoke
4. later, introduce browser/UI smoke for mobile layout and reconnect behavior if needed

## Minimal test stack recommendation

Add dev dependencies along these lines:
- `pytest`
- `httpx` is already present
- if needed, FastAPI/Starlette test client support via existing dependency chain

Keep the first smoke test file very small and intentionally boring.

## Bottom line

The fastest stable choice is:
- first: pytest-based in-process smoke for app boot + `/hermes` routing + basic conversation endpoints
- second: environment-gated real Hermes smoke
- only later: browser-level smoke

That gives the repo the highest immediate leverage: better confidence, faster merges, and lower risk while continuing to iterate on mobile UX and reconnect behavior.
