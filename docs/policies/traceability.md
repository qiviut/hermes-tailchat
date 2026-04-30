# Traceability policy

Goal: maintain lightweight traceability between requirements/planning, implementation, validation, and releases.

## Objects we want to connect

- beads
- branches
- commits
- pull requests
- CI checks
- releases/tags

## Current practical policy

### 1. Beads are the planning / requirement anchor
Each meaningful unit of work should have a bead.

Use beads for:
- planned work
- research
- implementation
- tests
- review
- release-prep follow-ups

### 2. Branches should ideally reference a primary bead
Preferred style when practical:

```text
feat/hermes-tailchat-sju-smoke-checks
fix/hermes-tailchat-wiq-mobile-layout
```

This is not mandatory for every emergency branch, but it is the preferred pattern.

### 3. Commits should reference bead IDs
Best practice:
- include one or more bead IDs in the commit body footer
- for multi-agent slices, treat this as required completion evidence rather than a nice-to-have

Example:

```text
Refs: hermes-tailchat-sju
```

or

```text
Refs: hermes-tailchat-j04, hermes-tailchat-nkr
```

Why:
- lets us answer which commit changed which bead IDs
- makes later release/report generation much easier

### 4. PR bodies should list the beads they advance
Recommended PR body section:

For multi-agent slices, PRs should also record tests run and any review-bead IDs that gate readiness.

```markdown
## Beads
- hermes-tailchat-sju
- hermes-tailchat-j04
```

Recommended additional sections:
- Summary
- Tests
- Security notes
- Follow-up beads

### 5. CI checks are validation evidence
Required checks should be attached to the PR and merge record.

At minimum, we want:
- quick-checks

Later, we may add:
- AI review summary
- code scanning
- secret scanning
- release/integrity checks

### 6. Releases should summarize shipped beads
When creating a release/tag, include:
- merged PRs
- bead IDs shipped in that release
- important follow-up beads still open

## Automation included now

A reporting script exists:

```bash
scripts/traceability_report.py
```

Default usage:

```bash
scripts/traceability_report.py
```

This reports for `main..HEAD`:
- beads created in the range
- beads progressed in the range
- beads completed in the range
- commits in the range and any bead IDs referenced in commit messages

You can also pass an explicit revision range:

```bash
scripts/traceability_report.py origin/main..HEAD
scripts/traceability_report.py HEAD~5..HEAD
```

## Current limitation

The script can always infer bead status changes from `.beads/issues.jsonl`, but commit-to-bead linkage is strongest when commit messages explicitly reference bead IDs.

So the next behavioral improvement is simple:
- start including `Refs: hermes-tailchat-...` in commit messages consistently

## Future direction

Later, we can extend traceability to include:
- PR template enforcement for bead IDs
- release-note generation by bead ID
- signed attestations for AI review and release readiness
- checklist-specific review evidence stored in tags or release metadata
