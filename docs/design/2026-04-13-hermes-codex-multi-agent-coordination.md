# Hermes/Codex multi-agent coordination design

Date: 2026-04-13
Bead: `hermes-tailchat-jfk`
Status: approved design / implementation backlog defined

## Goal

Design a durable, testable operating model for parallel background work where:

- Hermes stays user-facing and high-level
- Codex agents do most repo-facing implementation and review work
- `br` / `bv` own work discovery and dependency-aware task selection
- Agent Mail (`am`) carries inter-agent coordination without making Hermes a bottleneck
- git / review / test expectations are explicit enough to encode in `AGENTS.md`

## Non-goals

This design does **not** make Hermes the planner for every next task, and it does **not** require Hermes to read all agent-to-agent traffic.

It also does not require multiple Agent Mail instances for ordinary per-task isolation; we prefer one instance per trust domain and scope work with `project_key`, `thread_id`, bead IDs, and file reservations.

---

## Recommendation in one paragraph

Use `br` and `bv` as the primary work graph and ready-work selector; let Codex agents pull ready beads directly from that graph, coordinate laterally with each other through Agent Mail, and escalate only high-level ambiguity, lessons, or human-needed decisions to a dedicated Hermes overseer mailbox. Hermes should not assign routine work or watch all mail; it should answer clarification requests, curate process memory and skills, and decide when an issue is important enough to escalate to the human. Each meaningful implementation slice should have an implementation bead, explicit test linkage, and a sidecar review bead when the slice is non-trivial before the slice is considered fully done in git.

---

## Core design choices

1. **Work discovery belongs to `br` / `bv`.**
   Workers should self-select ready work from the bead graph.
2. **Hermes is a selective escalation and memory service.**
   Hermes is not the routine dispatcher.
3. **Codex agents coordinate laterally.**
   Worker-to-worker review, handoff, and blocker traffic should stay peer-to-peer.
4. **One Agent Mail instance is enough by default.**
   Use `project_key`, `thread_id`, and bead IDs instead of multiplying mail servers.
5. **Completion requires evidence, not optimism.**
   Tests, commit refs, PR state, and review disposition must be legible.
6. **The system must degrade safely.**
   If `am` is unavailable, agents fall back to worktree isolation instead of pretending reservations still exist.

---

## System roles

### Human
Owns product intent, risk tolerance, and final judgment when Hermes escalates.

### Hermes overseer
Owns:
- human-facing conversation
- clarification triage
- escalation triage
- long-term memory and lessons learned
- process/skills curation
- high-level synthesis across beads or agents

Hermes overseer does **not** own:
- choosing the next normal implementation bead
- reading every Codex↔Codex coordination message
- approving ordinary bead splits that do not change acceptance scope
- doing all code review itself

### Codex implementation agents
Own:
- selecting ready work from `br` / `bv`
- claiming scope
- implementing code/docs/tests
- opening commits/PRs/MRs according to repo policy
- requesting peer review
- escalating uncertainty that cannot be settled locally

### Codex review agents
Own:
- reviewing implementation slices through sidecar review beads
- giving bead-thread feedback via Agent Mail
- confirming or rejecting readiness for merge/close

### Agent Mail
Owns:
- agent identity
- inboxes
- threadable coordination
- file reservations
- selective escalation to Hermes

### `br` / `bv`
Own:
- work graph
- dependency structure
- ready-work triage
- parallelization visibility

---

## Coordination planes

### 1. Work graph plane: `br` / `bv`
Use beads as the canonical unit of planned work.

Rules:
- every meaningful change has a bead
- dependency edges, not prose, encode ordering
- implementation, tests, and review each get explicit beads when non-trivial
- agents should use `bv --robot-*` and `br --json`, never bare `bv`

### 2. Communication plane: Agent Mail
Use Agent Mail for:
- start/handoff/progress/blocker/review/done messages
- file reservations
- clarification requests to Hermes
- lesson/pattern proposals to Hermes

Do **not** use Agent Mail as the source of truth for work readiness; that stays in beads.

### 3. Conversation and memory plane: Hermes
Use Hermes for:
- answering clarifications
- deciding whether an ambiguity can be resolved from existing docs/policy/memory
- escalating to the human when needed
- converting useful repeated lessons into skills, docs, or durable memory

### 4. Source-control plane: git + PR/MR
Use git artifacts as completion evidence.

A bead is not functionally done until its required git artifact exists:
- commit at minimum for local slices
- PR/MR when repo policy requires review before merge

---

## Protocol matrix: who talks to whom, and about what

| Sender | Recipient | Primary purpose | Typical trigger | Required evidence in message |
| --- | --- | --- | --- | --- |
| Codex worker | `br` / `bv` | discover and claim ready work | starting or re-entering work | bead ID, current dependency state |
| Codex worker | Codex worker | handoff / review / blocker coordination | implementation crosses file or review boundary | thread ID, affected files, tests run or needed |
| Codex worker | Hermes overseer | clarification / policy / memory / human escalation request | ambiguity changes behavior or user-visible semantics | bead ID, options considered, recommended option, impact if unanswered |
| Hermes overseer | Codex worker | decision / policy answer / re-scope guidance | Hermes can resolve the issue without human input | authoritative doc or policy pointer, explicit next step |
| Hermes overseer | Human | product-risk or ambiguous business decision | Hermes cannot safely resolve from repo context | concise options, recommendation, impact of each option |

### Design rule
Hermes should be addressable as a dedicated mailbox, not as a passive subscriber to all worker traffic. Codex workers should know exactly when to send direct mail to Hermes, and otherwise should coordinate directly with each other.

---

## Mailbox topology

### Single Agent Mail instance by default
Preferred topology:
- one Agent Mail instance per trust domain / workspace class
- one `project_key` per repo or worktree family
- one `thread_id` per implementation bead
- review beads attach to the implementation-bead thread rather than inventing a second routine thread

Why:
- lower operational complexity
- easier search and auditability
- enough existing scoping primitives without multiplying services

### Named agent roles
Recommended mailbox identities:
- `HermesOverseer` — dedicated escalation and policy mailbox
- role-prefixed Codex workers such as `CodexBuilder-*` and `CodexReviewer-*`

Hermes should subscribe to:
- direct mail to `HermesOverseer`
- messages marked `[clarify]`, `[escalation]`, or `[lesson]`
- optional summary digests from active execution pools

Hermes should not subscribe to all worker mail by default.

### “Channels” without extra Agent Mail instances
Agent Mail does not need Slack-style channels for this workflow.

Use instead:
- `project_key` for repo scope
- `thread_id` for the implementation bead
- review bead IDs as related metadata inside the same thread
- subject prefixes for routing semantics

---

## Execution-context policy

Before claiming a bead, the agent chooses the lightest safe execution context.

### Coordinated mode
Use when `am` is available.

Allowed:
- shared checkout for narrow, non-overlapping edits
- file or directory reservations
- worker-to-worker coordination in bead threads

### Degraded mode
Use when `am` is unavailable, broken, or intentionally off.

Required guardrail:
- prefer a dedicated worktree for write-heavy or overlapping edits
- do not assume reservations exist when they do not
- record in notes/PR that work ran in degraded coordination mode

This matches the current runner behavior: Agent Mail is optional in tooling, so safety must come from the workflow contract when mail is absent.

---

## Claiming and stale-claim protocol

### Claiming
Normal path:
1. pick ready work with `bv --robot-next`, `bv --recipe actionable --robot-plan`, or `br ready --json`
2. inspect the bead with `br show <bead> --json`
3. claim it with `br update <bead> --status in_progress`
4. establish reservations or an isolated worktree
5. announce `[start][<bead>]`

### If claim fails or scope is already owned
- do not argue in chat first
- reselect work unless a small handoff or coordination message will unblock things immediately

### Stale in-progress work
If a bead appears abandoned:
- inspect the latest mail / PR / commit evidence
- create a follow-up or handoff bead if needed
- ask Hermes only if ownership is ambiguous in a way that changes product or policy scope

---

## Message taxonomy

Every coordination message should have:
- `thread_id` = implementation bead ID
- a subject prefix from the taxonomy below
- a concise structured body
- a stable message envelope with sender, recipients, related bead IDs, and schema version

The canonical executable contract for this section lives in:
- `docs/specs/multi-agent-message-contract.md`
- `docs/specs/multi-agent-message-fixtures.json`

### Worker-to-worker subjects
- `[start][bead-id]`
- `[handoff][bead-id]`
- `[review-request][bead-id]`
- `[review-feedback][bead-id]`
- `[blocker][bead-id]`
- `[done][bead-id]`

### Worker-to-Hermes subjects
- `[clarify][bead-id]`
- `[escalation][bead-id]`
- `[lesson][bead-id]`
- `[memory-request][bead-id]`

### Hermes-to-worker subjects
- `[decision][bead-id]`
- `[policy][bead-id]`
- `[split-guidance][bead-id]`
- `[escalate-human][bead-id]`

### Minimum body contract
Each non-trivial message should include:
- current goal
- current state / findings
- concrete ask or update
- affected files or scope
- recommended next step

---

## Routing policy

### Codex ↔ Codex
Use for:
- implementation handoffs
- review requests and review feedback
- blocker negotiation
- coordination around reservations

Hermes is not an automatic recipient.

### Codex → Hermes
Use only for:
- ambiguity that changes implementation behavior or user-visible semantics
- policy or security uncertainty
- human-risk decisions
- reusable lessons worth codifying
- requests to re-scope when the acceptance scope itself changes

Ordinary child-bead creation does not need Hermes approval.

### Hermes → Human
Use only when Hermes cannot safely resolve the question from:
- repo docs
- policy docs
- skills
- durable memory
- current task context

---

## Bead design rules

### Parent/child structure
Use parent/child dependencies for deliverable decomposition:
- parent bead = user-visible outcome or larger implementation track
- child bead = a separable implementation, test, docs, review, or harness slice

### Blocking structure
Use `blocks` when one bead must complete before another can proceed.

### Sidecar review bead
For non-trivial slices, create a sidecar review bead that:
- references the implementation bead in title/description
- keeps the implementation bead as the thread anchor
- records reviewer disposition and any follow-up beads
- is required before marking the implementation slice complete

### Test beads
Use explicit test beads when:
- a test strategy is substantial enough to stand alone
- multiple implementation beads depend on the same new test harness
- regression coverage is a deliverable in its own right

### Split triggers
A Codex agent should create more beads when:
- one bead covers more than one independently completable change
- different file clusters could be worked in parallel
- there is a distinct review, test, migration, or rollout concern
- a blocker needs separate ownership

---

## AGENTS.md layering

We want several agent-facing instruction layers.

### A. Root `AGENTS.md` (repo-wide)
Audience:
- Hermes
- Codex
- other workers

Contains:
- repo safety rules
- git/PR/MR expectations
- bead discipline
- test/traceability policy
- link-outs to role-specific docs

### B. Codex worker guidance
Audience:
- implementation-focused Codex workers

Must define:
- how to pick work with `br` / `bv`
- how to claim beads
- how to reserve files / use worktrees
- when to create child beads
- how to connect work to tests
- when a commit is mandatory
- when a PR/MR is mandatory
- how to request review
- when to escalate to Hermes

### C. Codex reviewer guidance
Audience:
- review-focused Codex workers

Must define:
- how to accept review work
- what evidence to inspect
- how to report review findings in bead/mail threads
- how to request follow-up beads
- what blocks approval

### D. Hermes overseer guidance
Audience:
- Hermes or Hermes-backed overseers

Must define:
- what traffic Hermes should read
- what Hermes should ignore
- when Hermes answers directly vs escalates to human
- how Hermes curates lessons into memory/skills/docs
- how Hermes summarizes multi-agent progress back to the human

### E. Skills and durable-memory layer
Audience:
- Hermes primarily, but discoverable by Codex workers through repo guidance

Must define:
- where reusable procedures become skills
- how lessons are promoted from ad hoc mail into durable memory or docs
- how Codex workers discover approved process patterns without depending on chat history
- how stale guidance gets patched when implementation teaches a better workflow

---

## Required Codex worker behavior

A Codex worker should treat a bead as not done until all applicable items are satisfied:

1. scope claimed in `br`
2. reservations/worktree established
3. implementation completed
4. tests added/updated as required
5. tests run and recorded
6. commit created with bead refs
7. PR/MR opened if required by policy
8. sidecar review requested if non-trivial
9. review disposition recorded if non-trivial
10. `.beads/` synced

This must be explicit in Codex-facing instructions.

---

## Clarification contract: Codex → Hermes

Codex agents should not ask Hermes "what should I work on next?" under normal operation.

They should ask Hermes only when they need:
- requirement clarification
- a policy or security decision
- memory/history beyond the local repo context
- help choosing between materially different user-visible approaches
- confirmation that a human decision is required
- escalation because docs conflict or risk tolerance is unclear

### Clarification message body shape
- bead ID
- concise problem statement
- what was already checked
- options considered
- recommended option
- impact if unanswered

### Hermes response options
- answer directly with a decision
- point to existing policy/skill/doc
- ask for a bead split only when acceptance scope is wrong
- escalate to human and keep the worker blocked or redirected

---

## Lessons learned contract

When a worker encounters a reusable lesson, it should send `[lesson]` to Hermes with:
- the problem
- the resolution
- the reusable rule
- suggested destination: memory, skill, AGENTS guidance, or repo docs

Hermes then decides whether to:
- update durable memory
- create/patch a skill
- patch AGENTS guidance
- add a repo doc
- do nothing if it is too local or temporary

This prevents fragmented undocumented lore.

---

## Git and traceability policy for the multi-agent system

### Branching
Preferred branch naming:
- `feat/<bead-id>-short-name`
- `fix/<bead-id>-short-name`
- `review/<bead-id>-short-name`

### Commits
Commits should include bead references, for example:

```text
feat: add Hermes escalation mailbox contract

Refs: hermes-tailchat-abc
```

### Pull requests / merge requests
PRs/MRs should include:
- bead IDs advanced
- tests run
- review bead IDs
- follow-up beads created

AI/Codex sidecar review helps bead readiness, but it does not replace repository branch-protection requirements described in `docs/policies/branch-protection-and-pr-flow.md`.

This aligns with `docs/policies/traceability.md` and `docs/policies/branch-protection-and-pr-flow.md`.

---

## Testability requirements

The design must be testable in implementation. Every implementation slice should be able to prove its behavior via one or more of the following:

### 1. Schema or fixture-level tests
Message payload examples for:
- clarification
- review request
- lesson proposal
- blocker notification
- done notification
- Hermes decision / policy responses

### 2. Integration tests
Examples:
- Codex worker can post a `[clarify]` mail that Hermes triage recognizes
- Codex worker can create a sidecar review bead and link it correctly
- a bead cannot be considered done by the policy helper until commit evidence exists
- degraded mode forces safer execution-context rules

### 3. Repository policy tests
Examples:
- AGENTS docs contain required sections
- helper scripts emit required bead/PR metadata
- traceability report can map commits back to bead IDs
- review-disposition metadata is preserved

### 4. End-to-end workflow tests
Examples:
- pick ready bead → claim → reserve → implement → request review → close beads → sync
- clarification to Hermes → Hermes decision → worker continues
- degraded mode without Agent Mail still preserves safe write isolation

### 5. Negative-path tests
Examples:
- a worker marks a bead done without commit evidence and the policy helper rejects it
- Hermes receives routine worker chatter without a `[clarify]`, `[escalation]`, or `[lesson]` subject and ignores it
- a sidecar review bead is missing and a non-trivial implementation slice remains uncloseable
- malformed subjects or missing envelope fields are rejected by classifiers

### Recommended initial automated test matrix
| Slice | Proof artifact |
| --- | --- |
| role-specific AGENTS docs exist and contain required headings | `pytest` content assertions over markdown files |
| message fixtures follow subject/body contract | fixture-schema tests |
| common message envelope fields stay present across required message types | schema-style JSON tests |
| bead helper emits implementation/test/review relationships | helper unit tests against generated bead payloads |
| Hermes escalation intake filters only high-signal mail | intake unit tests with mixed subject samples |
| traceability helper requires bead refs/tests/review IDs | script/unit tests with valid and invalid commit/PR metadata |
| coordination loop stays reproducible | integration test with fake mail + fake bead store + fake git evidence |

---

## Implementation backlog mapping

Parent feature:
- `hermes-tailchat-bar` — Build Hermes/Codex multi-agent coordination workflow

Primary child slices already defined:
- `hermes-tailchat-dnl` — Publish role-specific AGENTS guidance for Hermes and Codex agents
- `hermes-tailchat-kh1` — Implement message-contract helpers and fixtures for Agent Mail coordination
- `hermes-tailchat-3wt` — Implement bead-splitting and sidecar-review helper workflow
- `hermes-tailchat-3p8` — Implement Hermes escalation intake for clarify, escalation, and lesson mail
- `hermes-tailchat-lx3` — Extend traceability helpers for bead-linked commits, PRs, and review beads
- `hermes-tailchat-4pc` — Add integration tests for the multi-agent coordination loop

Additional enabling slices recommended by this design:
- `hermes-tailchat-v6g` — Build fake coordination harness for Agent Mail / bead / git tests
- `hermes-tailchat-w2n` — Formalize message envelope schema and required subject taxonomy
- `hermes-tailchat-y5k` — Enforce non-trivial classification and sidecar review requirements
- `hermes-tailchat-z8q` — Record review disposition and closeability evidence for implementation beads
- `hermes-tailchat-h7m` — Enforce PR/commit/review traceability fields for multi-agent work

### Suggested implementation order
1. `hermes-tailchat-dnl`
2. `hermes-tailchat-w2n`
3. `hermes-tailchat-v6g`
4. `hermes-tailchat-kh1`
5. `hermes-tailchat-y5k`
6. `hermes-tailchat-z8q`
7. `hermes-tailchat-3wt`
8. `hermes-tailchat-3p8`
9. `hermes-tailchat-h7m`
10. `hermes-tailchat-lx3`
11. `hermes-tailchat-4pc`

---

## Risks and guardrails

### Risk: Hermes becomes a bottleneck
Guardrail:
- Hermes does not assign normal work or inspect all mail
- normal bead splitting does not require Hermes approval

### Risk: Codex workers skip bead hygiene
Guardrail:
- explicit AGENTS rules
- helper scripts
- tests for traceability and review-bead creation

### Risk: sidecar reviews become ceremonial
Guardrail:
- review bead cannot close without recorded outcome
- implementation bead should reference review disposition
- non-trivial threshold is explicit instead of hand-wavy

### Risk: too many mail channels / instances
Guardrail:
- default to one Agent Mail instance per trust domain
- use threads and subject taxonomy instead of multiplying services

### Risk: "done" means dirty working tree only
Guardrail:
- policy says completion requires git artifact evidence

### Risk: Agent Mail is missing but workers still collide
Guardrail:
- degraded mode requires worktree isolation for write-heavy tasks

---

## Success criteria for the design

This design is successful when:
- Hermes is not needed for routine bead selection
- Codex workers know exactly when and how to ask Hermes for help
- bead graphs encode implementation, test, and review work clearly
- AGENTS guidance is specific enough to drive consistent behavior
- git artifacts provide traceable evidence for "done"
- the system can be validated with repeatable tests rather than chat-only conventions

---

## Immediate implementation checklist

- [x] add role-specific AGENTS guidance docs
- [ ] formalize message envelope schema and required subjects
- [ ] add message contract fixtures and tests
- [ ] add sidecar review bead helper / workflow docs
- [ ] add non-trivial classification and review-disposition helpers
- [ ] add Hermes escalation inbox triage path
- [ ] add traceability enforcement/helpers for commits and PRs
- [ ] add integration tests for the coordination loop
