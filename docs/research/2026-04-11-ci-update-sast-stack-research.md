# Light CI + dependency + SAST stack research

Bead: `hermes-tailchat-dj7`
Date: 2026-04-11

## Goal

Choose the lightest stack that still helps Hermes Tailchat ship improvements quickly while supporting:
- frequent PRs and merges
- safe auto-merge later
- aggressive dependency updates, including major versions
- useful supply-chain and secret-leak detection without turning the repo into compliance theater

## Current repo state

Observed locally and on GitHub:
- public GitHub repository
- no `.github/workflows/` directory yet
- no branch protection on `main`
- no required checks yet
- PR #1 exists but has no checks
- current project dependencies are minimal:
  - fastapi
  - uvicorn
  - httpx
  - sse-starlette
  - pydantic
- pytest is already installed in the Hermes venv on this machine
- there is no current test suite in the repo yet

Important implication:
- the repo needs a very small first CI step that is trusted, fast, and stable
- anything slower or more elaborate than that will delay the moment when auto-merge becomes useful

## GitHub feature availability relevant to this repo

### Dependabot version updates
GitHub docs indicate:
- Dependabot version updates are available for all repositories

This is important because the user explicitly wants aggressive updates, including major versions.

### Dependabot alerts
GitHub docs indicate:
- Dependabot alerts are available for user-owned and organization-owned repositories

This makes it a good default supply-chain signal source even before adding extra tools.

### Code scanning
GitHub docs indicate:
- code scanning is available for public repositories on GitHub.com

This makes CodeQL a viable option here without private-repo licensing concerns.

### Secret scanning
GitHub docs indicate:
- secret scanning runs automatically for free on public repositories

This means the repo already benefits from a GitHub-native secret safety net at the platform layer, even before adding repository-local checks.

## Candidate stack components

### 1. Minimal trusted CI workflow
Purpose:
- provide the first required status check for PRs
- stay fast enough that frequent merges remain pleasant

Best first contents:
- run on `pull_request` and `push`
- permissions: `contents: read`
- setup Python
- install package + test dependencies
- run syntax/import checks
- run the first smoke tests once they exist

Good first commands:
- `python -m py_compile app/*.py`
- `pytest -q` after smoke tests are added

Why not more initially:
- a long matrix or heavy browser test job would slow shipping immediately
- the first requirement is trust and speed, not maximum depth

### 2. Dependabot version updates
Purpose:
- satisfy the user’s explicit preference for staying current, including major versions
- keep changes small and frequent

Recommended initial policy:
- enable for Python dependencies
- enable for GitHub Actions references
- weekly cadence to start
- keep PRs small and reviewable
- do not suppress major versions by default
- group only when grouping reduces noise without creating giant risky PRs

Important policy choice:
- if the repo truly wants to stay on its toes, prefer many small update PRs over waiting for large quarterly upgrade events

### 3. Dependabot alerts
Purpose:
- built-in dependency vulnerability signal
- low setup burden

Recommendation:
- treat this as baseline, not the whole story
- use alongside version updates

### 4. Secret scanning
Purpose:
- catch committed credentials and token leaks

Recommendation:
- rely on GitHub’s free public-repo secret scanning as a platform baseline
- add local/CI gitleaks as a second layer because it gives faster feedback in the PR workflow and can be tuned inside the repo

### 5. Gitleaks
Purpose:
- repository-local secret scanning in CI
- fast, focused, immediately actionable

Why it fits this repo:
- simple to add
- quick enough for a required PR check
- complements GitHub’s platform secret scanning

Recommendation:
- add as part of the early CI stack
- keep the rule set practical and non-noisy

### 6. CodeQL
Purpose:
- GitHub-native SAST with alerting and code scanning UI

Pros:
- free on public repos
- integrates well with branch protection and PR review
- gives a durable SAST baseline

Cons:
- slower than a tiny smoke/lint check
- more overhead than the first CI workflow should carry if the immediate goal is fast shipping

Recommendation:
- add it, but as a second-stage security workflow rather than the very first required gate
- do not block the repo on CodeQL before the minimal trusted CI lane exists

### 7. Socket.dev and similar public scanners
Purpose:
- external/open-source-facing package reputation and supply-chain signals

Recommendation:
- treat these as additive signal sources rather than primary merge gates
- keep this in the separate research bead about free public repo scanners
- useful for visibility and heuristics, but not the first required path to green merges

## Recommended staged stack

### Stage 1: smallest useful trusted merge gate
Implement first:
1. one minimal CI workflow on `pull_request` / `push`
2. read-only token permissions
3. syntax/import checks
4. local API + `/hermes` smoke checks once bead `hermes-tailchat-sju` lands
5. gitleaks check

Why this stage first:
- fast enough to run on every PR
- trusted enough to become required in branch protection
- small enough that it will actually be maintained

### Stage 2: update pressure and visibility
Add next:
1. Dependabot version updates for Python and GitHub Actions
2. Dependabot alerts enabled and watched
3. explicit policy that major versions are in scope
4. later, integrity/hash pinning work from bead `hermes-tailchat-ujg`

Why this stage next:
- it directly supports the user’s update philosophy
- it increases shipping cadence with manageable PRs

### Stage 3: deeper security signal
Add after Stage 1 is stable:
1. CodeQL workflow
2. review of third-party action pinning
3. cache/artifact/workflow handoff hardening
4. optional external/public scanner integration research results

Why not Stage 1:
- useful, but not the fastest path to trusted auto-merge

## Concrete recommendation for Hermes Tailchat

### First required PR check should be
A single workflow roughly like:
- trigger: `pull_request`, `push`
- permissions: `contents: read`
- jobs:
  - `quick-checks`
    - checkout
    - setup python
    - install package + test deps
    - `python -m py_compile app/*.py`
    - run pytest smoke when available
    - run gitleaks

This should become the first required check in branch protection.

### First automation stack to implement
1. `hermes-tailchat-sju`
   local API and `/hermes` smoke checks
2. `hermes-tailchat-j04`
   document branch protection and mandatory-review policy
3. `hermes-tailchat-nkr`
   implement least-privilege CI workflow defaults
4. `hermes-tailchat-w9u`
   dependency update automation
5. `hermes-tailchat-ujg`
   hash/integrity pinning where practical
6. `hermes-tailchat-6qp` / `hermes-tailchat-gi6`
   code scanning + repo-local secret scanning

## Recommended initial branch protection policy once Stage 1 lands
For `main`:
- require pull request before merging
- require 1 approving review
- require the minimal CI check to pass
- require branches to be up to date before merging
- include administrators
- allow auto-merge
- use squash merge as default

This is enough to speed shipping while still enforcing a real gate.

## Bottom line

The lightest useful stack for this repo is:
- minimal trusted CI on `pull_request`
- fast smoke tests
- gitleaks in CI
- Dependabot version updates
- Dependabot alerts
- GitHub free public-repo secret scanning
- CodeQL added shortly after, but not as the first blocker

That is the best balance between:
- speed
- update pressure
- security signal
- keeping the repo easy to iterate on
