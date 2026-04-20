# Deterministic Hermes dreaming toolkit

Date: 2026-04-18
Bead: `hermes-tailchat-zum`
Status: initial implementation

## Goal

Start with small deterministic tools that are useful on their own and can later be composed into a fuller Hermes "dreaming" subsystem.

## Implemented now

### 1. Hourly activity-gated collector

`scripts/hermes_dream.py`

- exports Hermes sessions with `hermes sessions export`
- terminates early in a structured way when no recent conversation happened
- writes deterministic artifacts under `~/.local/state/hermes-tailchat/dreaming/`
- separates skill usage from memory usage
- records reflection windows around `skill_view`, `skill_manage`, `memory`, and `session_search`
- derives AI-review candidates that recommend the smallest useful window/session bundles before spending tokens
- snapshots local Hermes overlay state and exports patch artifacts for safer local maintenance

Artifacts:

- `latest-summary.json` — latest machine-readable summary
- `windows.json` — transcript windows around skill/memory/session-search events
- `analysis-candidates.json` — ranked recommendations for AI review scopes (single window vs whole session)
- `overlay-report.json` — local Hermes overlay status and exported patch metadata
- `overlay/patches/` — patch series for local overlay commits ahead of upstream
- `overlay/working-tree.diff` — current uncommitted delta
- `runs.jsonl` — append-only run history for later analysis

These logs are intentionally richer than the first analysis pass needs, so later AI analysis can choose among:

- single-session review
- delta-since-last-run review
- multi-session longitudinal review

without changing the collector first.

### 2. AI-bundle selector

Deterministic bundle ranking is now part of `scripts/hermes_dream.py` via `analysis-candidates.json`.

It scores windows and sessions using only deterministic signals such as:

- whether a skill was patched (`skill_manage`)
- whether memory was replaced/removed (churn)
- how dense a session is with dream-relevant signals
- how frequently a skill was used in the current lookback window
- whether cross-session recall (`session_search`) happened

This lets later analyzers choose among:

- the single highest-value window
- the highest-signal whole session
- repeated high-frequency skills across sessions

without first dumping everything into an LLM.

### 3. SSH/MOTD summary surface

`scripts/render_hermes_motd.py`
`scripts/install-hermes-motd.sh`

The renderer prints:

- dream status
- most recent chat title/session id
- recent skill and memory activity
- Hermes overlay status for `~/.hermes/hermes-agent`
- paths to the richer JSON artifacts

This makes SSH login useful without forcing the full Ubuntu news MOTD.

### 4. Hourly user-level timer installer

`scripts/install-hermes-dream.sh`
`systemd/hermes-tailchat-dream.service`
`systemd/hermes-tailchat-dream.timer`

This follows the same local-first systemd pattern already used in the repo.

### 5. 429 retry policy hardening

Retry helpers are centralized in `app/retry_policy.py` and shared by both Tailchat Hermes and Codex execution paths.

Policy now:

- 503/timeout/overload-style transient failures may auto-retry when still pre-side-effect
- 429/rate-limit failures are treated as transient for messaging, but **not** auto-retried in-turn

Reason:

- 429s often need a longer cool-down than a short exponential backoff
- repeated immediate retries waste quota and attention
- avoiding blind in-turn retries is safer and more predictable

## Why skills and memories are tracked differently

Skills and memories both cost context, but they are not the same object.

Current deterministic treatment:

- **skills**
  - count `skill_view` and `skill_manage`
  - track top skill names
  - capture transcript windows around skill use and patching
- **memory**
  - count `memory` calls separately
  - track actions (`add`, `replace`, `remove`)
  - capture transcript windows around memory changes

Known limitation:

- this initial collector sees explicit tool usage, not hidden prompt-injection-side memory retrieval or latent utility
- that is acceptable for the first pass because it gives us reviewable provenance without requiring Hermes core changes yet

## Local overlay maintenance

Local Hermes divergence now gets a deterministic maintenance surface instead of relying on stash/unstash habits.

Current deterministic treatment:

- `scripts/hermes_overlay_report.py` exports a machine-readable `overlay-report.json`
- ahead-of-upstream commits are exported as a patch series under `overlay/patches/`
- uncommitted changes are exported as `overlay/working-tree.diff`
- MOTD shows branch/upstream drift and exported patch count

This is intentionally local-first: it gives us reviewable evidence, patch portability, and a path toward upstreaming without forcing immediate invasive Hermes-core changes.

## AI usage philosophy

The collector is deterministic on purpose.

Use AI later for:

- evaluating whether a skill helped or hurt in context
- deciding whether a memory should be kept, revised, or removed
- comparing multiple sessions or deltas across runs

Do **not** spend tokens on work that a script can do first:

- session export
- event extraction
- usage counting
- transcript windowing
- skip/idle gating
- artifact bundling

This preserves quota for the places where judgment matters.
