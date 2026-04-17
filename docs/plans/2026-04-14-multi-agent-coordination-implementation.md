# Multi-agent coordination implementation plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Turn the Hermes/Codex/beads/Agent Mail design into testable repository behavior without making Hermes the dispatcher for routine work.

**Architecture:** `br`/`bv` remain the source of truth for work selection, Agent Mail carries lateral worker coordination plus selective Hermes escalation, and repo helpers enforce traceable completion evidence. Start with schemas and harnesses, then add policy helpers, then add end-to-end integration tests.

**Tech Stack:** Python, pytest, markdown policy docs, `.beads/issues.jsonl`, existing Tailchat/Codex runner scripts.

---

## Implementation order

1. `hermes-tailchat-dnl` — role-specific guidance kept current
2. `hermes-tailchat-w2n` — message envelope schema and taxonomy
3. `hermes-tailchat-v6g` — fake coordination harness
4. `hermes-tailchat-kh1` — fixtures/helpers built on schema
5. `hermes-tailchat-y5k` — non-trivial classification and sidecar-review requirement helper
6. `hermes-tailchat-z8q` — review disposition and closeability helper
7. `hermes-tailchat-3wt` — bead helper workflow
8. `hermes-tailchat-3p8` — Hermes escalation intake
9. `hermes-tailchat-h7m` — traceability field enforcement
10. `hermes-tailchat-lx3` — traceability/reporting integration
11. `hermes-tailchat-4pc` — integration loop tests

---

## Testability anchors

Each implementation slice should land with at least one of:
- fixture/schema test
- unit test over helper behavior
- integration test over fake mail/bead/git harness
- policy-doc regression test when the slice is doc-driven

A slice is not ready to close if it only updates docs without updating the relevant test or policy assertion.

---

## Cross-cutting acceptance criteria

- Hermes is not required for routine bead selection
- Codex workers have a clear clarify/escalate path to Hermes
- non-trivial slices require sidecar review evidence
- degraded mode without `am` remains safe through worktree isolation rules
- commit/PR/review metadata can be mapped back to bead IDs in tests
