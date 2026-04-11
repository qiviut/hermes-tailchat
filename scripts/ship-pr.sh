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
  - If the repository lacks required reviews/checks, --arm-auto or --merge-now
    may merge immediately. Use those flags intentionally.
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

PR_JSON=$(gh pr view "$BRANCH" --json number,url,title,reviewDecision,state,mergeStateStatus,statusCheckRollup 2>/dev/null || true)
if [[ -z "$PR_JSON" ]]; then
  LAST_SUBJECT=$(git log -1 --pretty=%s)
  LAST_BODY=$(git log -1 --pretty=%b)
  BODY=$(cat <<EOF
## Summary
- ${LAST_SUBJECT}

## Notes
- Created by scripts/ship-pr.sh to keep changes flowing through PRs.
- Review before merge.

${LAST_BODY}
EOF
)
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
