# Codex reviewer AGENTS guidance

Audience: Codex agents acting as reviewers.

## Mission

Review implementation slices through explicit review beads, leave actionable feedback, and make readiness legible in both the bead graph and the Agent Mail thread.

## Intake

Accept review work through:
- a sidecar review bead
- an explicit `[review-request][<impl-bead>]`
- a PR/MR that references both the implementation bead and review bead

Use the implementation bead ID as the primary `thread_id` unless a repo-specific exception is documented.

## Review context to inspect

Check:
- implementation bead intent
- review bead scope
- changed files
- tests run and whether they match the bead claims
- commit/PR traceability evidence
- follow-up beads or known deferrals

## Non-trivial review targets

Expect a sidecar review bead when the implementation slice is non-trivial, meaning it changes executable behavior, spans multiple subsystems, changes policy/workflow/agent behavior, or introduces new regression obligations.

## Review outputs

Use one of:
- `[review-feedback][<impl-bead>]` with blocking findings
- `[done][<review-bead>]` when review is complete and non-blocking
- `[blocker][<impl-bead>]` if larger coordination is required

Each review response should include:
- reviewed scope
- evidence checked
- result: approve / request-changes / blocked
- follow-up bead IDs if new work was discovered
- recommended next step

## Blocking conditions

Block review completion when:
- git-visible evidence is missing
- required tests were not run or justified
- bead decomposition is hiding meaningful unresolved work
- acceptance criteria are not met
- a non-trivial slice lacks an appropriate sidecar review record

## Review disposition recording

A review bead is not truly complete until:
- the target implementation artifact exists
- the outcome is recorded in the review bead or PR notes
- blocking findings are linked to follow-up beads when needed
- the implementation bead can point to the review disposition

## Follow-up beads

If review reveals new work, create or request:
- bugfix beads
- test beads
- docs beads
- additional sidecar review beads for risky follow-up slices

Prefer explicit beads over burying unresolved work in prose comments.
