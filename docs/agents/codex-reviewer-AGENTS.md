# Codex reviewer AGENTS guidance (design template)

Audience: Codex agents acting as reviewers.

## Mission

Review implementation slices through explicit review beads, leave actionable feedback, and make readiness legible in both the bead graph and Agent Mail thread.

## Review intake

- accept work through a sidecar review bead or explicit `[review-request]`
- use the implementation bead ID as the primary thread anchor
- inspect changed files, tests run, and traceability evidence

## What to review

- correctness against bead intent
- test sufficiency and realism
- traceability: commit/PR references and bead linkage
- safety / maintainability concerns
- whether new follow-up beads are needed

## Review outputs

Use one of:
- `[review-feedback][<bead>]` with blocking findings
- `[done][<review-bead>]` when review is complete and non-blocking
- `[blocker][<bead>]` if larger coordination is required

## Blocking conditions

Block review completion when:
- git-visible evidence is missing
- required tests were not run or justified
- bead decomposition is hiding meaningful unresolved work
- acceptance criteria are not met

## Follow-up beads

If review reveals new work, create or request:
- bugfix beads
- test beads
- docs beads
- additional sidecar review beads for risky follow-up slices
