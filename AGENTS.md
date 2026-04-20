# AGENTS.md - Hermes Tailchat

This file gives repo-specific guidance for coding agents working on Hermes Tailchat.

## Project identity

Hermes Tailchat is a tailnet-only web chat for a local Hermes backend.

Current design center:
- single-user
- fast iteration
- tailnet-only exposure
- localhost-bound services behind Tailscale Serve
- practical security improvements that do not kill shipping velocity

## What matters most here

1. Keep the app useful as a chat product, not just as a pile of infra/process work.
2. Preserve the secure solo-maintainer shipping model.
3. Maintain traceability between beads, commits, PRs, checks, and later releases.
4. Do not leak secrets into git.

## Before making changes

1. Read `README.md`.
2. Read relevant docs under `docs/policies/`, `docs/design/`, and `docs/research/`.
3. If you are acting in a specialized role, also read the matching role guidance under `docs/agents/`:
   - `docs/agents/codex-worker-AGENTS.md`
   - `docs/agents/codex-reviewer-AGENTS.md`
   - `docs/agents/hermes-overseer-AGENTS.md`
4. Check the current beads state using robot-safe tooling:
   - `bv --recipe actionable --robot-plan`
   - `bv --robot-next`
   - `br ready --json`
   - `br show BEAD_ID --json`
5. Claim the bead before substantial work:
   - `br update BEAD_ID --status in_progress`
6. If `am` is unavailable, do not rely on shared-checkout coordination alone for overlapping edits; use an isolated worktree for write-heavy tasks.

## Planning / execution conventions

### Use beads as the requirement anchor
Work should map to beads whenever practical.

Preferred bead types:
- research
- task
- feature
- test
- review
- epic

### Branch naming
Preferred branch style when practical:
- `feat/hermes-tailchat-<bead>-short-name`
- `fix/hermes-tailchat-<bead>-short-name`

Examples:
- `feat/hermes-tailchat-sju-smoke-checks`
- `feat/hermes-tailchat-qvf-reconnect-resume`

### Commit traceability
Commit bodies for meaningful work should include bead references.

Preferred footer format:

```text
Refs: hermes-tailchat-sju
```

or

```text
Refs: hermes-tailchat-j04, hermes-tailchat-nkr
```

This is important for traceability reporting.

### Pull request structure
PRs should include:
- Summary
- Beads
- Tests
- Security notes
- Release / operator impact

Use the PR template and/or `scripts/ship-pr.sh`.

## Security / secrets rules

Never commit:
- `.env`
- real API keys or tokens
- credentials in systemd units
- local DB artifacts

Use:
- ignored local env files
- `EnvironmentFile=` for host-local services
- environment variables provided outside git

If a change touches:
- `.github/workflows/`
- dependency/update automation
- secrets/token handling
- release or signing logic

then be extra conservative and document the security impact.

## CI / merge model

Current intended merge model:
- protected `main`
- required checks
- pull requests are the normal merge path
- review is required before merge per `docs/policies/branch-protection-and-pr-flow.md`
- Codex/Hermes sidecar review improves bead readiness but does not replace repository branch protection by itself
- auto-merge permitted only after the required review and checks pass

Do not weaken this casually.
If you change merge/security policy, update:
- `docs/policies/branch-protection-and-pr-flow.md`
- `docs/policies/traceability.md`

## Product priorities

Do not let repo-process work completely crowd out chat improvements.

High-value product areas include:
- mobile layout
- reconnect/resume UX
- background-job visibility
- real Hermes-backed smoke/e2e
- operator clarity in the chat UI

When choosing between equally useful chores, prefer the one that unlocks better chat behavior or faster safe shipping.

## Verification expectations

Before committing, run the smallest relevant validation set.

Common commands:
```bash
python -m py_compile app/*.py tests/*.py
pytest -q tests/test_smoke.py
```

If you touch CI/workflow docs or traceability tooling, also sanity-check scripts:
```bash
bash -n scripts/ship-pr.sh
python3 scripts/traceability_report.py main..HEAD
```

## Helpful local tools

- `scripts/ship-pr.sh` — PR creation / auto-merge helper
- `scripts/traceability_report.py` — report bead/commit linkage and bead state transitions
- `scripts/review_requirements.py` — classify a slice as trivial/non-trivial and decide whether sidecar review is required
- `br` / `bv` — backlog and dependency graph tooling

## When closing work

1. Run `scripts/review_requirements.py` on the staged slice if the change may be non-trivial, and make sure any required sidecar review bead is identified before committing.
2. Update bead status only after the slice has the required evidence.
3. `br sync --flush-only`
4. Commit with bead references.
5. Record the exact tests/validation run.
6. Push branch.
7. Open/update PR.
8. If the slice is non-trivial, make sure sidecar review disposition is recorded before treating it as done.

If the work changes policy, workflow, or release behavior, make sure the docs are updated in the same branch.
