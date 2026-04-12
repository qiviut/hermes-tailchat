# Branch protection and PR flow policy

Bead: `hermes-tailchat-j04`
Date: 2026-04-11

## Goal

Ship quickly without letting untrusted pull requests execute privileged automation or letting `main` drift into an unreviewed integration branch.

## Core rules

1. Do not commit directly to `main`.
2. Use short-lived feature branches.
3. Open a PR immediately after pushing meaningful work.
4. Require review before merge.
5. Use auto-merge only after GitHub protections and trusted checks are in place.

## User-specific trust model

This repo should not run CI on code from someone else's forked pull request.

Practical interpretation:
- CI may run on pushes to branches in this repository.
- CI may run on pull requests only when the PR head repository is this repository.
- Pull requests from forks should not execute repository CI jobs that install or run project code.
- External contributions can still be reviewed manually and, if desired, tested by a maintainer in a trusted branch or local environment.

This is stricter than the default "read-only token on pull_request is safe enough" posture, and that is intentional.

## Minimal GitHub settings to apply on `main`

Once the first trusted check exists, configure branch protection for `main` with:
- require a pull request before merging
- require at least 1 approving review
- require status checks to pass before merging
- require branches to be up to date before merging
- apply the rule to administrators too
- disallow force-pushes
- disallow branch deletion
- allow auto-merge
- prefer squash merge as the default merge style

Optional later additions:
- require conversation resolution
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
- short-lived feature branches
- protected `main`
- required trusted checks
- auto-merge after checks pass
- squash merge by default

Why this is the right current baseline:
- fast iteration on a single-user project
- clean `main` history
- good fit for many small fixup commits
- easier release-note and traceability grouping once PRs consistently list bead IDs

Security reasoning:
- squash merge is not itself the main security control
- the security value comes from protected `main`, trusted CI, traceability, and a gradual increase in validation rigor
- squash merge reduces history noise, which makes review and forensic reading of `main` easier in practice

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

Normal flow:
1. create branch
2. commit small slice
3. push branch
4. open PR immediately
5. get review
6. let trusted checks pass
7. merge via squash

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

## Auto-merge policy

Auto-merge is acceptable only after:
- branch protection is enabled
- at least one trusted required check exists
- review is required on `main`

Before that, auto-merge is just convenience, not a security control.

## Why this policy exists

This policy is optimized for two goals at once:
- frequent merges and fast shipping
- no accidental privileged execution of untrusted PR code

That means:
- we accept a little manual friction for fork PRs
- we optimize the happy path for trusted branches and small PRs
- we keep `main` stable enough that fast auto-merge can become useful later
