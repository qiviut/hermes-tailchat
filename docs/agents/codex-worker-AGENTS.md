# Codex worker AGENTS guidance

Audience: Codex implementation agents working in this repo.

## Mission

Pick ready work from the bead graph, implement it safely, connect it to tests, and leave git-visible evidence before considering the work done.

## Work selection

Use the bead graph, not Hermes, for routine next-task selection.

Preferred commands:
- `bv --recipe actionable --robot-plan`
- `bv --robot-next`
- `br ready --json` when reliable
- `br show <bead-id> --json` before editing

Do not ask Hermes what to work on next unless the graph is genuinely ambiguous or broken.

## Claiming work

1. `br update <bead-id> --status in_progress`
2. establish your execution context:
   - shared checkout + reservations when `am` is available and edit scope is narrow
   - isolated git worktree when edits are broad, long-running, or `am` is unavailable
3. bootstrap Agent Mail if available
4. announce `[start][<bead-id>]`

If another agent already holds the bead or scope, reselect work instead of negotiating in the abstract.

## Execution modes

### Coordinated mode
Use this when `am` is available.

Required:
- reserve files or directories before editing shared scope
- use the implementation bead ID as the `thread_id`
- send worker-to-worker mail for handoffs, blockers, and review requests

### Degraded mode
Use this when `am` is unavailable or unhealthy.

Required:
- prefer a dedicated worktree for write-heavy tasks
- avoid overlapping edits in the same checkout
- document in the bead/PR that the task ran without Agent Mail reservations

Do not treat degraded mode as permission to edit shared scope recklessly.

## Splitting work into beads

Create child beads when:
- the work naturally splits into independent slices
- a distinct test harness or regression task is needed
- there is a separate docs, migration, or rollout deliverable
- a sidecar review bead is appropriate
- a blocker needs separate ownership

Use:
- parent/child for decomposition
- `blocks` for true ordering constraints

### When you may split without Hermes
You may create normal implementation, docs, test, blocker, and review child beads without asking Hermes first when the acceptance scope stays the same.

### When to ask Hermes before re-scoping
Ask Hermes only when the split would change:
- user-visible semantics
- policy/security posture
- product scope
- whether a human decision is required

## Non-trivial change threshold
Treat a slice as non-trivial if any of the following is true:
- it changes executable behavior outside docs/tests-only scope
- it spans more than one subsystem or file cluster
- it changes policy, workflow, or agent behavior
- it introduces or changes review/traceability enforcement
- it requires new regression coverage or unusual validation

Non-trivial slices should get sidecar review.

## Test linkage

Every implementation bead should identify:
- what test proves completion
- whether tests must be added or updated
- exact commands run
- any justified deferrals

Do not consider a bead done if the required tests were not run or explicitly deferred and documented.

## Git policy

A bead is not done if the work only exists in a dirty working tree.

Required minimum:
- commit with `Refs: <bead-id>`
- recorded validation commands/results

When repo policy requires review before merge:
- push a branch
- open a PR/MR
- include bead IDs, tests, security notes, and follow-up beads

## Review policy

For non-trivial work:
- create or request a sidecar review bead
- keep the implementation bead ID as the primary `thread_id`
- reference the review bead ID in mail/PR/bead notes
- send `[review-request][<bead-id>]` to a reviewer
- do not claim full completion until review disposition is recorded

## Worker-to-worker message contract

Use these subjects:
- `[start][<bead-id>]`
- `[handoff][<bead-id>]`
- `[review-request][<bead-id>]`
- `[review-feedback][<bead-id>]`
- `[blocker][<bead-id>]`
- `[done][<bead-id>]`

Each non-trivial message should include:
- current goal
- current state/findings
- affected files or scope
- concrete ask or update
- recommended next step

## When to ask Hermes

Ask Hermes only for:
- requirement clarification
- policy/security decisions
- conflicting docs or historical context
- major approach choices with user-visible impact
- escalation to the human

Do not ask Hermes for routine task selection or ordinary bead splitting.

## Clarification message contract

Subject:
- `[clarify][<bead-id>] short question`

Body:
- current goal
- what you checked
- ambiguity
- options considered
- recommended option
- impact if unanswered

## Lessons learned

If you find a reusable pattern or pitfall, send:
- `[lesson][<bead-id>] ...`

Include:
- problem
- resolution
- reusable rule
- suggested destination: memory / skill / AGENTS / repo doc

## Definition of done

A slice is not done until all applicable items are satisfied:
1. bead claimed
2. safe execution context established
3. implementation completed
4. tests added/updated as needed
5. validation run and recorded
6. commit created with bead refs
7. PR/MR opened if required by policy
8. sidecar review requested and dispositioned if non-trivial
9. `.beads/` synced
