# Codex worker AGENTS guidance (design template)

Audience: Codex implementation agents working in this repo.

## Mission

Pick ready work from the bead graph, implement it safely, connect it to tests, and leave git-visible evidence before considering the work done.

## Work selection

- Prefer `bv --recipe actionable --robot-plan` or `bv --robot-next`
- Use `br ready --json` where reliable
- Do not ask Hermes what to work on next unless the graph is ambiguous or broken

## Claiming work

1. `br update <bead> --status in_progress`
2. bootstrap Agent Mail session
3. reserve files or create/use the assigned worktree
4. announce `[start][<bead>]`

## Splitting work into beads

Create child beads when:
- the work naturally splits into independent slices
- a distinct test harness or regression task is needed
- there is a separate docs or migration deliverable
- a sidecar review bead is appropriate
- a blocker needs separate ownership

Use:
- parent/child for decomposition
- `blocks` for true ordering constraints

## Test linkage

Every implementation bead should identify:
- what test proves completion
- whether tests must be added or updated
- what commands were run

Do not consider a bead done if the required tests were not run or explicitly deferred and documented.

## Git policy

A bead is not done if the work only exists in a dirty working tree.

Required minimum:
- commit with `Refs: <bead-id>`

When repo policy requires review before merge:
- push a branch
- open a PR/MR
- include bead IDs, tests, security notes, and follow-up beads

## Review policy

For non-trivial work:
- create or request a sidecar review bead
- send `[review-request][<bead>]` to a reviewer
- do not claim full completion until review disposition is recorded

## When to ask Hermes

Ask Hermes only for:
- requirement clarification
- policy decisions
- historical context or reusable process memory
- major approach choices with user-visible impact
- permission to re-scope by creating a larger bead split
- escalation to the human

Do not ask Hermes for routine task selection.

## Clarification message contract

Subject:
- `[clarify][<bead>] short question`

Body:
- current goal
- what you checked
- ambiguity
- options considered
- recommended option
- impact if unanswered

## Lessons learned

If you find a reusable pattern or pitfall, send:
- `[lesson][<bead>] ...`

Include:
- problem
- resolution
- reusable rule
- suggested destination: memory / skill / AGENTS / repo doc
