# Secure GitHub Actions policy for untrusted pull requests

Bead: `hermes-tailchat-mbw`
Date: 2026-04-11

## Why this matters

The goal is to ship quickly without letting untrusted pull requests execute attacker-controlled code with secrets or elevated repository permissions.

The user specifically wants:
- feature-branch development
- mandatory review before merge
- fast merges once criteria are met
- pipelines that do not execute untrusted code from someone else's pull request in privileged contexts

## Current repo state

Observed live state on GitHub and locally:
- repository: `qiviut/hermes-tailchat`
- default branch: `main`
- admin permission: yes
- merge methods allowed: merge, rebase, squash
- delete branch on merge: false
- current PR exists for the working branch: `#1`
- current branch protection on `main`: none
- current CI workflows in repo: none
- current PR checks: none

Implication:
- today, PRs can be merged without meaningful GitHub-enforced gates
- a helper script can speed PR creation/merge, but it is not yet backed by safe policy
- before enabling true auto-merge as a routine, the repo should gain a minimal trusted check set and branch protection

## GitHub documentation signals consulted

### 1. Events that trigger workflows
References:
- `pull_request`: <https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#pull_request>
- `pull_request_target`: <https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#pull_request_target>

Operational takeaway:
- `pull_request` is the safer default for running checks on pull requests because the workflow runs in the PR context and does not automatically grant the same privileged behavior as a base-branch-triggered context
- `pull_request_target` is dangerous if it checks out and executes code from the pull request, because it runs in the context of the base repository and can access elevated permissions/secrets depending on workflow design

Practical rule for this repo:
- use `pull_request` for normal CI on proposed code
- do not use `pull_request_target` for running repository code, tests, package scripts, or arbitrary shell from PR contents
- if `pull_request_target` is ever introduced, restrict it to metadata-only actions that do not check out or execute PR code

### 2. Secure use reference
Reference:
- <https://docs.github.com/en/actions/reference/security/secure-use>

Key security guidance relevant here:
- keep `GITHUB_TOKEN` permissions minimal
- do not treat secrets as safely redacted in all transformed forms
- audit third-party actions and token usage
- prefer least privilege by default, escalating only for the exact jobs that need more

Practical rule for this repo:
- set workflow-level permissions to read-only by default
- grant extra permissions per job only when required
- never put real secrets in workflows or in PR-executed steps
- avoid using broad PATs in automation where `GITHUB_TOKEN` can do the job

### 3. Protected branches
Reference:
- <https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches>

Key guidance relevant here:
- protect `main`
- require pull request review before merging
- require status checks before merging
- optionally require linear history
- optionally enable auto-merge once requirements are meaningful

Practical rule for this repo:
- do not rely on convention alone
- put the intended merge discipline into GitHub branch protection or rulesets

## Threat model for this repo

### Threat 1: Untrusted PR executes attacker-controlled code in a privileged workflow
Examples:
- workflow uses `pull_request_target` and checks out PR HEAD
- PR code runs package scripts under elevated token scope
- PR gets secrets indirectly via environment, artifacts, or inherited permissions

Mitigation:
- no privileged execution of PR code
- default to `pull_request`
- use read-only `GITHUB_TOKEN` unless explicitly needed

### Threat 2: Third-party action compromise
Examples:
- action referenced by mutable tag such as `@v4`
- maintainer account compromise changes released tag target

Mitigation:
- pin third-party actions to full commit SHAs
- prefer official GitHub actions when practical
- keep the action list small

### Threat 3: Artifact, cache, or workflow handoff trust confusion
Examples:
- later privileged workflow trusts artifacts from an untrusted workflow run
- caches populated by attacker-controlled inputs are later consumed in a trusted job
- `workflow_run` becomes an unintended privilege boundary bypass

Mitigation:
- do not create privileged follow-up workflows that consume untrusted artifacts without validation
- treat caches/artifacts from PR contexts as tainted
- keep early CI simple and self-contained

### Threat 4: Overpowered token use
Examples:
- workflow grants unnecessary write permissions
- automation can push, merge, edit releases, or alter workflow files when it only needed read access

Mitigation:
- workflow-level `permissions: { contents: read }` default
- raise permissions job-by-job only where actually needed

## Recommended policy for Hermes Tailchat

### Phase 1: immediately useful and safe enough
1. Protect `main`
2. Require pull requests before merge
3. Require at least 1 review before merge
4. Require a minimal trusted check set before merge
5. Set repository default workflow permissions to read-only if possible
6. Use squash merge as the default merge method for small iterative branches
7. Enable auto-merge only after required review/checks exist

### Phase 2: workflow design rules
For the first CI workflow set:
- trigger normal CI on `pull_request`
- optionally trigger same checks on `push` to your own branches
- do not use `pull_request_target` for code execution
- pin third-party actions to full commit SHA
- use minimal permissions

Example baseline policy shape:
- `lint-and-smoke.yml`
  - triggers: `pull_request`, `push`
  - permissions: `contents: read`
  - runs fast syntax/import/smoke checks only
- no release workflow yet
- no artifact-handoff workflow yet

### Phase 3: branch protection settings to adopt
When the first CI check exists, configure `main` with:
- require pull request before merging
- require 1 approving review
- require status checks to pass
- require branches to be up to date before merging
- include administrators in the rule
- disallow force-pushes
- disallow deletions
- optionally require linear history
- optionally allow auto-merge

Because this is a personal repo optimized for speed, I would not start with merge queue or heavy policy ceremony.

## Fast shipping recommendation

The repo can still move quickly with the following short loop:
1. small feature branch
2. small PR immediately
3. one lightweight review
4. fast trusted checks
5. auto-merge after those checks/review pass

The important thing is that the checks are:
- fast
- trustworthy
- non-privileged in untrusted PR contexts

## Explicit do/don't list

### Do
- use `pull_request` for normal CI
- pin actions by commit SHA
- keep token permissions read-only by default
- require review on `main`
- keep checks fast so merge frequency stays high

### Don't
- do not run PR code under `pull_request_target`
- do not expose secrets to PR jobs
- do not trust caches/artifacts from untrusted PR runs as privileged inputs
- do not leave `main` unprotected once minimal CI is in place

## Recommended follow-up beads

Immediate next implementation beads unlocked by this research:
- `hermes-tailchat-j04` document branch protection and mandatory-review policy
- `hermes-tailchat-nkr` implement least-privilege CI workflow defaults

Then:
- `hermes-tailchat-g53` cache/artifact/workflow handoff hardening details
- `hermes-tailchat-6ml` review third-party action pinning and workflow supply-chain exposure

## Bottom line

For this repo, the right fast-and-safe model is:
- branch PRs for everything
- trusted, minimal, read-only CI on `pull_request`
- no privileged execution of PR code
- one required review
- auto-merge after review + checks once those protections exist
