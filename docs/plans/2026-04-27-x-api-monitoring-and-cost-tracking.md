# X API Monitoring and Cost Tracking Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Set up X API access and a reusable monitor for swyx plus other high-value accounts, with explicit cost/rate-limit accounting before broad polling.

**Architecture:** Use `xurl` as the operator-facing X API client and wrap it with a small Python monitor that reads a watchlist, polls bounded endpoints, writes raw responses to the untrusted-ingestion spool, records per-call usage, and emits daily/monthly cost forecasts. Authentication remains a human-owned one-time setup because app secrets must never enter chat or git.

**Tech Stack:** `xurl` v1.1.0, Python stdlib, existing untrusted-ingestion reducer, JSON/JSONL state files, cron/heartbeat later for scheduling, pytest.

**Bead:** `hermes-tailchat-pyy`

---

## Current local setup status

- `xurl` has been installed via `go install github.com/xdevplatform/xurl@latest`.
- Binary path: `~/go/bin/xurl`.
- Current auth status: no X apps registered yet.
- Next required step is user-owned X developer portal setup and OAuth; do not paste secrets into chat.

## Human-owned X app setup

The user should do this outside the agent session:

1. Open the X developer portal and create/select an app.
2. Choose the lowest plan that supports the needed read endpoints and expected monthly volume.
3. Set callback/redirect URI: `http://localhost:8080/callback`.
4. Copy Client ID and Client Secret locally, not into chat.
5. Run:

```bash
export PATH="$HOME/go/bin:$PATH"
xurl auth apps add monitoring --client-id YOUR_CLIENT_ID --client-secret YOUR_CLIENT_SECRET
xurl auth oauth2 --app monitoring YOUR_X_HANDLE
xurl auth default monitoring YOUR_X_HANDLE
xurl auth status
xurl whoami
```

Important:
- Do not use `--verbose` in agent sessions.
- Do not read or print `~/.xurl`.
- If `xurl auth status` shows `oauth2: (none)` on the default app, set the named app as default again.

## Monitoring targets

Create a watchlist config:

```json
{
  "accounts": [
    {
      "handle": "swyx",
      "priority": 1,
      "sources": ["user_timeline", "recent_search_mentions"],
      "poll_interval_minutes": 60,
      "max_results_per_poll": 20,
      "notes": "Agent skills, AI engineering, Latent Space, smol.ai"
    }
  ],
  "global": {
    "monthly_call_budget": 1000,
    "monthly_read_post_budget": 10000,
    "stop_at_budget_fraction": 0.8
  }
}
```

Initial high-value account fields:
- `handle`
- `user_id` once resolved
- `priority`
- `topics`
- `poll_interval_minutes`
- `max_results_per_poll`
- `last_seen_post_id`
- `enabled`

## Endpoint strategy

Prefer low-volume account timeline polling over broad searches:

1. Resolve handle to user id: `xurl user swyx`.
2. Poll user timeline: `GET /2/users/:id/tweets` via `xurl` shortcut/raw endpoint.
3. Use recent search only for cross-account discovery and mentions when budget allows.
4. Deduplicate by post id and content hash.
5. Spool raw X payloads, then reduce with `app.untrusted_ingest` using source type `x`.

Relevant official rate-limit examples observed from current X docs:
- Recent search `GET /2/tweets/search/recent`: 450 app / 15 min, 300 user / 15 min, max 100 results.
- User timeline `GET /2/users/:id/tweets`: 10,000 app / 15 min, 900 user / 15 min.

These are rate ceilings, not cost ceilings. The billing plan and monthly post/read quotas still need to be configured from the current X portal at setup time.

## Cost tracking model

Do not hardcode X pricing in code. X plan prices/quotas change and may depend on portal enrollment.

Instead, store operator-provided plan metadata:

```json
{
  "plan_name": "basic-or-other",
  "monthly_usd": 0,
  "included_read_posts": 0,
  "included_write_posts": 0,
  "overage_usd_per_1000_reads": null,
  "billing_cycle_start": "YYYY-MM-DD",
  "source": "X developer portal, captured manually YYYY-MM-DD"
}
```

Track actual usage in append-only JSONL:

```json
{
  "ts": "2026-04-27T00:00:00Z",
  "endpoint": "/2/users/:id/tweets",
  "target": "swyx",
  "http_status": 200,
  "requests": 1,
  "posts_returned": 12,
  "new_posts": 3,
  "rate_limit_remaining": 899,
  "rate_limit_reset": 1770000000,
  "estimated_included_reads_used": 12
}
```

Daily report should include:
- calls by endpoint
- returned posts
- new unique posts
- duplicate ratio
- estimated included quota consumed
- forecast month-end usage at current rate
- warning when `stop_at_budget_fraction` is crossed

## Task 1: Persist PATH/operator note

**Objective:** Ensure operators know `xurl` is installed under `~/go/bin`.

**Files:**
- Modify: `README.md` or a new `docs/operations/x-api-monitoring.md`

**Steps:**
1. Document `export PATH="$HOME/go/bin:$PATH"`.
2. Document the no-secrets setup commands.
3. Run docs spell/sanity check manually.
4. Commit with `Refs: hermes-tailchat-pyy`.

## Task 2: Add watchlist and billing config schemas

**Objective:** Make account targets and cost assumptions explicit and reviewable.

**Files:**
- Create: `docs/specs/x-monitor-watchlist.schema.json`
- Create: `docs/specs/x-api-billing-plan.schema.json`
- Test: `tests/test_x_monitor.py`

**Steps:**
1. Add JSON schemas for watchlist and billing plan.
2. Add valid/invalid fixtures.
3. Test schema validation.
4. Run: `pytest -q tests/test_x_monitor.py`.
5. Commit with `Refs: hermes-tailchat-pyy`.

## Task 3: Add xurl wrapper with safe auth check

**Objective:** Call X without exposing credentials.

**Files:**
- Create: `app/x_monitor/xurl_client.py`
- Test: `tests/test_x_monitor.py`

**Steps:**
1. Implement `xurl_available()` using PATH plus `~/go/bin` fallback.
2. Implement `auth_status()` by running `xurl auth status`; never read `~/.xurl`.
3. Implement JSON command wrapper that rejects `--verbose` and inline secret flags.
4. Test missing-auth and command construction paths with mocks.
5. Run: `pytest -q tests/test_x_monitor.py`.
6. Commit with `Refs: hermes-tailchat-pyy`.

## Task 4: Add timeline poller

**Objective:** Fetch posts from configured accounts with dedupe and budget checks.

**Files:**
- Create: `app/x_monitor/poller.py`
- Create: `scripts/x_monitor.py`
- Test: `tests/test_x_monitor.py`

**Steps:**
1. Load watchlist and state.
2. Resolve handles to user ids when missing.
3. Poll `/2/users/:id/tweets` with max results.
4. Deduplicate by post id and source ref.
5. Write raw payloads to `data/x/raw/`.
6. Run: `pytest -q tests/test_x_monitor.py`.
7. Commit with `Refs: hermes-tailchat-pyy`.

## Task 5: Add usage ledger and cost forecast

**Objective:** Track request/read volume and forecast monthly cost pressure.

**Files:**
- Create: `app/x_monitor/costs.py`
- Modify: `scripts/x_monitor.py`
- Test: `tests/test_x_monitor.py`

**Steps:**
1. Append one ledger row per API call.
2. Parse rate-limit headers where available from xurl/raw output if exposed; otherwise record nulls.
3. Count returned posts and new unique posts.
4. Forecast month-end included-read consumption.
5. Stop or warn at configured budget threshold.
6. Run: `pytest -q tests/test_x_monitor.py`.
7. Commit with `Refs: hermes-tailchat-pyy`.

## Task 6: Wire X output into swyx-to-skills pipeline

**Objective:** Ensure monitored X posts feed candidate-skill extraction safely.

**Files:**
- Modify: `app/swyx_ingest/sources.py` or `app/x_monitor/poller.py`
- Modify: `scripts/swyx_to_skills.py`
- Test: `tests/test_swyx_ingest.py tests/test_x_monitor.py`

**Steps:**
1. Convert new X raw payloads into `SourceItem` records.
2. Run deterministic untrusted ingestion with `source_type=x`.
3. Make model-backed extraction optional and off by default.
4. Test that hostile post text remains data and emits risk hints.
5. Run: `pytest -q tests/test_swyx_ingest.py tests/test_x_monitor.py tests/test_untrusted_ingest.py`.
6. Commit with `Refs: hermes-tailchat-pyy hermes-tailchat-u52`.

## Final verification

After user completes X auth:

```bash
export PATH="$HOME/go/bin:$PATH"
xurl auth status
xurl whoami
python3 scripts/x_monitor.py check-config --watchlist config/x-watchlist.json --billing config/x-billing-plan.json
python3 scripts/x_monitor.py poll --watchlist config/x-watchlist.json --billing config/x-billing-plan.json --dry-run
python3 scripts/x_monitor.py report-costs --ledger data/x/usage.jsonl --billing config/x-billing-plan.json
```

Expected:
- no secrets printed
- dry-run shows planned endpoints/calls
- cost report shows monthly forecast and budget threshold
- no raw X content goes directly to privileged skill generation
