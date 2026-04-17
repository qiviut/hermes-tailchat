# Hermes + Codex background parallelization: doc review, decision, implementation

Date: 2026-04-13
Bead: `hermes-tailchat-ood`

## Goal

Use the latest Hermes and Codex docs to decide how Hermes Tailchat should coordinate background parallel work, especially when Hermes is the user-facing orchestrator and Codex is the repo-facing coding worker.

## Latest-doc takeaways that mattered

### Hermes docs

From the current Hermes CLI/reference docs:

- Hermes supports `--worktree` / `-w` for isolated git worktrees in parallel-agent workflows.
- Hermes `chat -q` supports one-shot non-interactive execution.
- Hermes has slash/background concepts such as `/background` and queueing, but those are session-native behaviors rather than a repo-wide orchestration contract.
- Hermes has `delegate_task` for isolated subagents, but those are better for bounded subtasks than for durable background repo workers.
- Hermes also supports cron jobs and spawned standalone processes, which reinforces the idea that Hermes can be the orchestrator while other workers run independently.

### Codex docs

From the current Codex docs:

- `codex exec` is the correct non-interactive automation surface.
- `codex exec --json` emits machine-readable JSONL events.
- `codex exec --output-last-message <path>` can write the final message into a stable artifact file.
- Codex subagents exist and are useful, but they are explicitly spawned inside Codex’s own orchestration model.
- Codex subagents inherit sandbox/approval defaults from the parent, which is convenient but not the same thing as repo-level collision control.
- Codex supports custom agents, but custom agents are still subordinate to Codex’s internal orchestration rather than a Tailchat-wide task ledger.

### Agent Mail relevance

`am` is available locally and gives us:

- agent identity bootstrap
- file reservations
- inbox / mail threads
- thread IDs for work tracking

That makes Agent Mail a good coordination supplement across Hermes and Codex workers, even though neither tool natively depends on it.

## Critical review of candidate setups

Detailed option analysis lives in:

- `docs/research/2026-04-13-parallel-background-orchestration-research.md`

Short version:

1. **Shared checkout + reservations only**
   - tempting but brittle
   - too easy for one worker to ignore the contract and dirty the main tree

2. **Native subagents inside one Hermes or Codex parent run**
   - good for internal fan-out
   - weak as the primary Tailchat-level orchestration story
   - hard to make visible and controllable from the app

3. **Separate daemon/orchestrator service**
   - architecturally powerful
   - overkill for the current repo stage

4. **Tailchat-managed jobs + standalone workers + Agent Mail coordination**
   - best safety/scope tradeoff
   - keeps Tailchat as the user-facing control plane
   - lets Codex do coding work without making Tailchat depend on Codex internals for everything

## Chosen approach

We implemented the smallest coherent version of option 4:

- Tailchat background jobs can now target either `hermes` or `codex`
- Codex jobs run through a dedicated wrapper: `scripts/run_codex_background.py`
- Codex artifacts are stored under `.tailchat/codex-jobs/<job-id>/`
- Tailchat persists job state in SQLite and surfaces the final Codex result back into the conversation
- Agent Mail is used opportunistically for:
  - session bootstrap
  - reservations
  - notification hooks

This keeps the separation clear:

- **Hermes/Tailchat** = conversation + orchestration + state
- **Codex** = coding worker
- **Agent Mail** = coordination protocol

## What changed

### Backend

- `app/store.py`
  - jobs now store `executor`, `artifact_dir`, and `metadata_json`
  - added parsed job payloads and `get_job()`

- `app/codex_runner.py`
  - new async adapter that invokes the Codex background wrapper and reads artifacts/results

- `app/main.py`
  - `JobCreate` now accepts:
    - `executor`
    - `thread_id`
    - `bead_id`
    - `reserve_paths`
    - `notify_to`
    - `reservation_reason`
  - background jobs now branch between Hermes and Codex execution
  - Codex job completion/failure is written back into the same conversation transcript

### Runner

- `scripts/run_codex_background.py`
  - bootstraps Agent Mail when enabled/available
  - records status to `status.json`
  - records raw Codex JSONL events to `events.jsonl`
  - captures stderr in `stderr.log`
  - stores the final Codex message in `final.md`
  - releases reservations at the end

### Frontend

- `app/static/index.html`
  - added a background executor picker (`Hermes job` / `Codex job`)
  - job list now shows executor, thread metadata, and artifact directory

### Tests

- `tests/test_codex_background.py`
  - verifies the standalone Codex runner with fake `codex` and fake `am`
  - verifies that a queued Codex job completes through the Tailchat background poller and posts its final result into the conversation
  - verifies transient Codex provider failures are retried only before any events/output exist
  - verifies Tailchat refuses to auto-retry Codex runs once events have already been emitted

- `tests/test_smoke.py`
  - verifies Hermes text-only transient retry resets partial assistant output before the successful retry completes

## Why this is the right current slice

Because it makes the architecture real without overcommitting:

- we did **not** build a separate orchestration daemon
- we did **not** try to make Tailchat stream every Codex internal event live in v1
- we did **not** force all concurrency through native subagent APIs
- we did **not** rely on reservations alone as the only collision-defense mechanism

Instead, we created a durable seam:

- Tailchat owns job state
- Codex owns coding execution
- Agent Mail can coordinate workers across tool/runtime boundaries

That seam is useful immediately and still leaves room for future upgrades such as:

- dedicated worktree-per-edit-task creation before Codex launch
- richer Tailchat UI for artifacts and logs
- explicit Hermes worker launch alongside Codex worker launch
- stronger bead/thread linkage in the UI
- more aggressive reservation policies for overlapping tasks

## Validation target

The intended validation set for this change is:

```bash
python -m py_compile app/*.py tests/*.py scripts/run_codex_background.py
pytest -q tests/test_smoke.py tests/test_traceability_and_mobile_layout.py tests/test_codex_background.py
```

## Follow-up resilience hardening

A later in-flight hardening pass extended the first implementation with stricter transient-error handling:

- Hermes foreground turns now retry only when the failure looks transient and no tool/approval side-effect risk has appeared yet.
- If the first attempt streamed text but then hit a transient provider failure, Tailchat emits a retry-reset event and clears the partial assistant output before retrying.
- Codex background jobs now retry only when the wrapper failed before producing any JSONL events or final output.
- Once Codex artifacts show that work had already started, Tailchat surfaces the transient failure instead of risking duplicate repo mutations.

This keeps retries aggressive for obvious provider hiccups while preserving the repo-safety rule that retries must not duplicate side effects.

## Bottom line

Yes: Hermes should use Codex as a delegated coding worker when that improves throughput.

But the important part is not merely "spawn Codex"; it is to do so with a stable coordination model:

- explicit executor choice
- durable Tailchat job tracking
- artifact capture
- Agent Mail-compatible identity and reservations
- a clear boundary between orchestrator and worker

That is what this implementation establishes.
