# Modeling hypothesis trial — hermes-tailchat

## Hypothesis

Using standard lightweight views instead of a custom modeling framework will produce actionable insight at acceptable cost.

Views tried:
- C4-lite: context/container/component
- runtime/event-flow reading
- lightweight trust-boundary review
- executable evidence review

## Inputs used

- `docs/architecture.md`
- `docs/design/2026-04-21-untrusted-ingestion-foundation.md`
- `app/main.py`
- `app/hermes_provider.py`
- `app/codex_runner.py`
- `.hermes/codebase-model/report.md`
- design-artifact tests under `tests/`

## C4-lite read

### Context
- Single-user tailnet-only chat UI wrapping a local Hermes backend.
- External/runtime dependencies include local Hermes internals, SQLite, optional Codex CLI worker, Tailscale Serve, and Agent Mail.

### Containers
- Web/API server: FastAPI app with SSE/static UI (`app/main.py:106-109`).
- Persistence: local SQLite store (`app/main.py:74-79`; config/env surfaced in the generated model).
- Hermes execution path: embedded local provider around Hermes gateway/session internals (`app/hermes_provider.py:8-18`, `49-56`, `123-143`).
- Codex background execution path: subprocess runner with artifact directory and retry policy (`app/codex_runner.py:34-45`, `61-153`).
- Browser/UI static assets mounted by FastAPI (`app/main.py:108-109`).

### Components worth naming
- conversation/job API + lifecycle orchestration in `app/main.py`
- event broker + append-only run-event publishing (`app/main.py:112-116`)
- approval rehydration + session locking in `app/hermes_provider.py:57-81`, `145-218`
- background Codex artifact management in `app/codex_runner.py`
- untrusted-ingestion pipeline as a separate trust-reduction subsystem from the design doc

## Runtime/event-flow insight

This repo yields meaningful insight when modeled as flows over time, not just as components.

High-value flows surfaced by the trial:
1. app startup recovery:
   - recover incomplete state
   - rehydrate pending approvals
   - start job poller (`app/main.py:84-103`)
2. interactive run flow:
   - persist messages
   - create run
   - stream events/deltas
   - append run events to store
   - publish over broker/SSE (`app/main.py:112-116`, `211+`)
3. Hermes execution flow:
   - create agent from local Hermes internals
   - run with per-session lock
   - emit text/tool events
   - handle approvals
   - retry only when safe and pre-side-effect (`app/hermes_provider.py:123-143`, `145-218`)
4. Codex background flow:
   - spawn background script
   - collect artifacts/status/final output
   - retry only before any output/events exist (`app/codex_runner.py:25-31`, `109-153`)
5. untrusted-ingestion flow:
   - deterministic reduction
   - bounded normalized artifact
   - optional low-privilege Codex sanitizer
   - only then escalation (`docs/design/2026-04-21-untrusted-ingestion-foundation.md:37-52`)

## Trust-boundary insight

This is where the modeling paid off most.

Useful findings:
1. The core architecture question is not just “what components exist?” but **which execution path has which authority**.
2. There are at least three materially different authority zones:
   - browser/UI
   - Tailchat app process with DB + local Hermes access
   - reduced-authority Codex sanitizer/background worker path
3. Retry policy is acting as a safety boundary, not just reliability behavior:
   - Hermes retries only when no side-effect risk or blocking approval exists (`app/hermes_provider.py:202-218`)
   - Codex retries only before any output/events are produced (`app/codex_runner.py:25-31`, `142-153`)
4. Approval state is first-class runtime structure, not incidental UI text:
   - it is persisted, rehydrated, and tied to run/session state (`app/main.py:84-89`, `app/hermes_provider.py:57-74`, `176-179`)
5. The untrusted-ingestion design is best understood as a trust-boundary model, not merely a feature doc.

## Executable-evidence insight

The repo already contains evidence-bearing artifacts that function like executable architecture:
- code paths in `app/main.py`, `app/hermes_provider.py`, `app/codex_runner.py`
- schema-bound/untrusted-ingestion design
- tests that enforce presence of design and coordination artifacts (`tests/test_multi_agent_design_artifacts.py`)

The generated bottom-up model was useful for orientation, but the meaningful insight came from combining:
- component view
- runtime flow
- trust-boundary analysis

## Cost vs. insight

### Cost
Moderate.
- static inventory alone was not enough
- reading architecture and a few implementation files produced most of the value
- still well below the cost of any heavy formal framework

### Insight gained
High.
This trial clarified that Tailchat should be modeled primarily with:
1. C4-lite structure
2. sequence/event-flow views for run/job/approval/sanitization behavior
3. trust-boundary/authority model

This is better than treating it as a normal CRUD web app or inventing a custom framework name.

## Verdict

Hypothesis looks good for this repo.

Worth keeping:
- C4-lite structural view
- one or two sequence/event-flow views for critical paths
- explicit trust-boundary/authority notes

Not worth adding yet:
- bespoke meta-framework terminology
- formal methods / AADL-like machinery
- diagramming every internal module

## Recommended next artifact if we continue

A very small set of standard artifacts only:
- C4 context/container for Tailchat
- sequence diagram for run + approval + retry behavior
- trust-boundary diagram for untrusted ingestion and background execution
