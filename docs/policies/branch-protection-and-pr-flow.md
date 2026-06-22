# Branch protection and PR flow policy

Bead: `hermes-tailchat-j04`
Date: 2026-04-11

## Goal

Ship quickly without letting untrusted pull requests execute privileged automation, while letting trusted in-repository branches promote themselves to `main` after the fast required checks pass.

## Core rules

1. Do not hand-edit `main`; work on short-lived feature branches.
2. CI may automatically fast-forward `main` to a trusted branch commit after `quick-checks` passes.
3. The auto-promotion path is branch-push only; it must not run for fork pull requests.
4. If a branch is behind `main` or cannot fast-forward cleanly, rebase/update the branch rather than force-pushing `main`.
5. Use PRs and sidecar review when they add useful review evidence, but the solo-maintainer fast path is trusted branch → green CI → `main`.

## User-specific trust model

This repo should not run CI on code from someone else's forked pull request.

Practical interpretation:
- CI may run on pushes to branches in this repository.
- CI may run on pull requests only when the PR head repository is this repository.
- Pull requests from forks should not execute repository CI jobs that install or run project code.
- External contributions can still be reviewed manually and, if desired, tested by a maintainer in a trusted branch or local environment.

This is stricter than the default "read-only token on pull_request is safe enough" posture, and that is intentional.

## Minimal GitHub settings to apply on `main`

With trusted branch auto-promotion enabled, configure branch protection for `main` with:
- require status checks to pass before merging
- require branches to be up to date before merging
- require the `quick-checks` status check
- apply the rule to administrators too
- disallow force-pushes
- disallow branch deletion

Do **not** require pull requests for every update if the trusted branch fast path is desired. The promotion job fast-forwards `main` from a branch commit that already has a passing `quick-checks` result.

Optional later additions:
- require conversation resolution for PR-based work
- require linear history
- require signed commits

## Required check strategy

Start with one fast trusted check only:
- `ci / quick-checks`

That job should stay:
- fast
- deterministic
- non-privileged
- limited to trusted branch contexts

Do not make the first required check depend on:
- browser-heavy E2E
- live secrets
- privileged release workflows
- untrusted artifact handoff

## Merge strategy for improving security over time

Current default for this repo:
- short-lived trusted feature branches
- protected `main`
- required trusted `quick-checks`
- automatic fast-forward promotion from green in-repository branches to `main`
- PRs and sidecar reviews when the change deserves extra review evidence

Why this is the right current baseline:
- fast iteration on a single-user project
- `main` only advances to commits that passed the required check
- avoids privileged automation for fork PR code
- preserves branch/commit/check traceability without turning every small slice into review ceremony

Security reasoning:
- the security value comes from protected `main`, trusted CI, traceability, and a clearly branch-push-only promotion job
- the promotion job performs a fast-forward only; it does not resolve conflicts, force-push, or merge stale branches
- fork PRs can be reviewed manually and copied into trusted branches when worth testing

How to improve the strategy over time:
1. keep required checks fast enough that developers do not route around them
2. add stronger validation as separate checks rather than replacing the fast lane
3. keep trusted and untrusted execution contexts clearly separated
4. attach more evidence to PRs and releases (traceability, AI review summaries, later signed attestations)
5. only add heavier controls when they improve assurance more than they slow shipping

Recommended maturity path:
- Stage 1: quick-checks only
- Stage 2: smoke + secret scanning + dependency automation
- Stage 3: AI review summary check
- Stage 4: stronger provenance/release attestation and checklist-linked evidence

This repo should get more secure by accumulating better evidence and safer automation, not by making every merge painfully manual.

## Merge flow

Trusted branch fast path:
1. create branch from current `main`
2. commit a small slice
3. push branch
4. CI runs `quick-checks`
5. if checks pass and the branch can fast-forward from `main`, CI pushes that commit to `main`
6. if promotion fails, update/rebase the branch and push again

PR/review flow remains available for non-trivial or collaborative slices:
1. create branch
2. commit small slice
3. push branch
4. open PR with bead/test/security notes
5. get review or sidecar review when useful
6. let trusted checks pass
7. merge normally or let the branch auto-promote if it is still a clean fast-forward

Helper script:

```bash
scripts/ship-pr.sh
```

Useful modes:

```bash
scripts/ship-pr.sh --create-only
scripts/ship-pr.sh --arm-auto
scripts/ship-pr.sh --merge-now
```

## Auto-promotion policy

Trusted branch auto-promotion is acceptable because:
- it only runs for `push` events on branches in this repository
- fork pull requests do not run privileged promotion logic
- the promotion job depends on `quick-checks`
- `main` is updated with `git merge --ff-only`, never force-pushed
- dependency bot branches are excluded until they have their own policy

This is convenience plus a lightweight safety gate, not a substitute for human review on risky changes.

## Why this policy exists

This policy is optimized for two goals at once:
- frequent trusted-branch merges and fast shipping
- no accidental privileged execution of untrusted PR code

That means:
- we accept a little manual friction for fork PRs
- we optimize the happy path for trusted branches and small PRs
- we keep `main` stable by requiring a green fast check and fast-forward-only promotion
