# Multi-agent message contract

Status: canonical repository contract for Hermes/Codex/Agent Mail coordination fixtures
Schema version: `1`
Primary bead: `hermes-tailchat-w2n`

## Purpose

This document formalizes the message envelope and subject taxonomy for multi-agent coordination in Hermes Tailchat.

It exists so that:
- fixtures stay stable
- future helper code can classify and validate messages consistently
- Hermes intake can route only the traffic it should care about
- Codex workers and reviewers share the same contract without depending on chat history

## Canonical thread anchor

The canonical rule is:
- `thread_id = implementation bead ID`

Review beads, follow-up beads, and related work should be carried in `related_bead_ids` instead of inventing a new routine thread.

## Envelope fields

### Required envelope fields

Every coordination message must include:
- `schema_version`
- `message_id`
- `project_key`
- `thread_id`
- `from`
- `to`
- `subject`
- `related_bead_ids`
- `body`
- `created_at`

### Optional envelope fields

When needed, messages may also include:
- `reply_to`
- `in_reply_to`
- `metadata`

## Envelope semantics

- `schema_version`: contract version used by fixtures/helpers/classifiers
- `message_id`: stable message identifier for deduplication and audit trails
- `project_key`: repo/workspace scope such as `hermes-tailchat`
- `thread_id`: implementation bead ID that anchors the workstream
- `from`: sending agent identity
- `to`: recipient mailbox identities
- `subject`: routing prefix plus concise summary
- `related_bead_ids`: implementation bead plus any review/follow-up beads
- `body`: structured payload specific to the subject class
- `created_at`: UTC ISO-8601 timestamp
- `reply_to` / `in_reply_to`: optional threading helpers for mail backends
- `metadata`: optional transport-specific or helper-specific extension bucket

## Subject taxonomy

### worker_to_worker
- `[start][bead-id]`
- `[handoff][bead-id]`
- `[review-request][bead-id]`
- `[review-feedback][bead-id]`
- `[blocker][bead-id]`
- `[done][bead-id]`

### worker_to_hermes
- `[clarify][bead-id]`
- `[escalation][bead-id]`
- `[lesson][bead-id]`
- `[memory-request][bead-id]`

### hermes_to_worker
- `[decision][bead-id]`
- `[policy][bead-id]`
- `[split-guidance][bead-id]`
- `[escalate-human][bead-id]`

## Body contract

### Always
Every non-trivial coordination message body should include:
- `goal`
- `state`
- `recommended_next_step`

### Per-subject expectations

- `start`: scope, reservations or worktree choice, initial plan
- `handoff`: transferred scope, current findings, unresolved risks
- `review-request`: affected files, tests run, explicit ask
- `review-feedback`: reviewed scope, evidence checked, result, follow-ups
- `blocker`: blocking condition, affected files or scope, unblock ask
- `done`: outcome, evidence checked, closeability guidance
- `clarify`: checked docs, ambiguity, options, recommended option, impact if unanswered
- `escalation`: risk, why Hermes cannot settle locally, options, recommendation
- `lesson`: problem, resolution, reusable rule, suggested durable destination
- `memory-request`: what historical rationale is needed and why
- `decision`: authoritative answer, basis, concrete next step
- `policy`: rule to apply, source of authority, enforcement note
- `split-guidance`: suggested bead decomposition and why
- `escalate-human`: concise human-facing decision request and impact

## Routing expectations

- Codex workers should use worker-to-worker subjects for implementation/review coordination.
- Hermes should only be the recipient for worker_to_hermes traffic or direct mail to `HermesOverseer`.
- Hermes should not subscribe to routine worker chatter by default.
- Helpers/classifiers should reject malformed subjects or missing required envelope fields.
- Review-related messages should keep the implementation bead thread anchor even when a review bead exists.

## Fixture source of truth

`docs/specs/multi-agent-message-fixtures.json` is the executable fixture companion to this contract. Future helpers should derive validations from these same field names and subject labels rather than inventing parallel schemas.
