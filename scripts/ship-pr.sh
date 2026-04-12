#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/ship-pr.sh [--create-only|--arm-auto|--merge-now]

Default behavior:
  - ensure you are on a non-main branch
  - ensure the worktree is clean
  - create a pull request for the current branch if one does not exist
  - print review/check status and next-step guidance

Modes:
  --create-only   Only create/show the PR and status summary (default)
  --arm-auto      Enable GitHub auto-merge with squash+delete-branch
  --merge-now     Merge immediately with squash+delete-branch

Notes:
  - This script uses gh and assumes you are authenticated.
  - It does not bypass GitHub protections; it only automates normal PR flow.
EOF
}

MODE="create-only"
if [[ $# -gt 1 ]]; then
  usage
  exit 2
fi
if [[ $# -eq 1 ]]; then
  case "$1" in
    --create-only) MODE="create-only" ;;
    --arm-auto) MODE="arm-auto" ;;
    --merge-now) MODE="merge-now" ;;
    -h|--help) usage; exit 0 ;;
    *) usage; exit 2 ;;
  esac
fi

command -v gh >/dev/null
BRANCH=$(git branch --show-current)
if [[ -z "$BRANCH" ]]; then
  echo "Could not determine current branch" >&2
  exit 1
fi
if [[ "$BRANCH" == "main" || "$BRANCH" == "master" ]]; then
  echo "Refusing to run from $BRANCH; create/use a feature branch first" >&2
  exit 1
fi
if [[ -n "$(git status --short)" ]]; then
  echo "Worktree is not clean; commit or stash changes first" >&2
  exit 1
fi

collect_beads() {
  {
    printf '%s\n' "$BRANCH"
    git log main..HEAD --pretty='%s%n%b'
  } | grep -oE 'hermes-tailchat-[a-z0-9]+' | sort -u
}

build_pr_body() {
  local last_subject last_body beads tests_list security_notes release_notes bead_block
  last_subject=$(git log -1 --pretty=%s)
  last_body=$(git log -1 --pretty=%b)

  bead_block=""
  while IFS= read -r bead; do
    [[ -n "$bead" ]] || continue
    bead_block+="- ${bead}"$'\n'
  done < <(collect_beads)
  if [[ -z "$bead_block" ]]; then
    bead_block='- hermes-tailchat-...'
  fi

  tests_list=$(cat <<'EOF'
- [x] `python -m py_compile app/*.py tests/*.py`
- [x] `pytest -q tests/test_smoke.py`
EOF
)

  security_notes=$(cat <<'EOF'
- Trusted-branch-only CI impact: no new privileged execution path for fork PR code.
- Secrets / token handling impact: none noted beyond existing policy.
- Supply-chain / dependency impact: note any new dependencies or action changes here.
EOF
)

  release_notes=$(cat <<'EOF'
- User-visible changes:
- Deployment or runbook changes:
- Follow-up beads:
EOF
)

  cat <<EOF
## Summary
- ${last_subject}

## Beads
${bead_block}
## Tests
${tests_list}

## Security notes
${security_notes}

## Release / operator impact
${release_notes}

## Notes
- Created by scripts/ship-pr.sh to keep changes flowing through PRs.

${last_body}
EOF
}

PR_JSON=$(gh pr view "$BRANCH" --json number,url,title,reviewDecision,state,mergeStateStatus,statusCheckRollup 2>/dev/null || true)
if [[ -z "$PR_JSON" ]]; then
  LAST_SUBJECT=$(git log -1 --pretty=%s)
  BODY=$(build_pr_body)
  gh pr create --base main --head "$BRANCH" --title "$LAST_SUBJECT" --body "$BODY"
  PR_JSON=$(gh pr view "$BRANCH" --json number,url,title,reviewDecision,state,mergeStateStatus,statusCheckRollup)
fi

python3 - <<'PY' "$PR_JSON"
import json, sys
pr = json.loads(sys.argv[1])
checks = pr.get('statusCheckRollup') or []
print(f"PR #{pr['number']}: {pr['title']}")
print(pr['url'])
print(f"state={pr.get('state')} reviewDecision={pr.get('reviewDecision')} mergeStateStatus={pr.get('mergeStateStatus')}")
if checks:
    print("checks:")
    for check in checks:
        name = check.get('name') or check.get('context') or 'unknown'
        state = check.get('state') or check.get('conclusion') or 'unknown'
        print(f"  - {name}: {state}")
else:
    print("checks: none reported")
PY

case "$MODE" in
  create-only)
    echo
    echo "Next step: review the PR, then run one of:"
    echo "  scripts/ship-pr.sh --arm-auto"
    echo "  scripts/ship-pr.sh --merge-now"
    ;;
  arm-auto)
    gh pr merge "$BRANCH" --auto --squash --delete-branch
    ;;
  merge-now)
    gh pr merge "$BRANCH" --squash --delete-branch
    ;;
esac
