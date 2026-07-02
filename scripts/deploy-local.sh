#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT_DIR"

SERVICE_NAME=${SERVICE_NAME:-hermes-tailchat.service}
STATE_DIR=${STATE_DIR:-$HOME/.local/state/hermes-tailchat}
REV_FILE="$STATE_DIR/deployed-rev"
HEALTH_URL=${HEALTH_URL:-http://127.0.0.1:8766/health}
TIMEOUT_SECONDS=${TIMEOUT_SECONDS:-20}
FORCE_DEPLOY=${FORCE_DEPLOY:-0}

mkdir -p "$STATE_DIR"

current_branch=$(git branch --show-current)
current_rev=$(git rev-parse HEAD)
previous_rev=""
if [[ -f "$REV_FILE" ]]; then
  previous_rev=$(<"$REV_FILE")
fi

if [[ "$current_branch" != "main" ]]; then
  echo "Refusing to deploy from branch '$current_branch' (expected main)" >&2
  exit 1
fi

if [[ "$FORCE_DEPLOY" != "1" && "$current_rev" == "$previous_rev" ]]; then
  echo "No deploy needed: $SERVICE_NAME already recorded at $current_rev"
  exit 0
fi

# Clear stale Python bytecode cache in hermes-agent venv to prevent ImportError
# after code updates (e.g. new functions added to modules)
echo "→ Clearing stale Python bytecode cache..."
python3 <<'PYEOF'
import os, shutil
hermes_root = os.path.expanduser('~/.hermes/hermes-agent')
removed = 0
for root, dirs, files in os.walk(hermes_root):
    # Skip venv, .git, node_modules
    dirs[:] = [d for d in dirs if d not in {'venv', '.venv', '.git', 'node_modules', '.worktrees'}]
    if os.path.basename(root) == '__pycache__':
        try:
            shutil.rmtree(root)
            removed += 1
        except OSError:
            pass
    for f in files:
        if f.endswith('.pyc'):
            try:
                os.unlink(os.path.join(root, f))
            except OSError:
                pass
suffix = 'y' if removed == 1 else 'ies'
print(f'  ✓ Cleared {removed} __pycache__ director{suffix}')
PYEOF

systemctl --user restart "$SERVICE_NAME"

deadline=$((SECONDS + TIMEOUT_SECONDS))
while (( SECONDS < deadline )); do
  if curl -fsS "$HEALTH_URL" >/dev/null 2>&1; then
    printf '%s
' "$current_rev" > "$REV_FILE"
    echo "Deployed $SERVICE_NAME at $current_rev"
    exit 0
  fi
  sleep 1
done

echo "Timed out waiting for $SERVICE_NAME health check at $HEALTH_URL" >&2
exit 1
