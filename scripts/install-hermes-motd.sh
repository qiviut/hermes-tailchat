#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
STATE_DIR="${HOME}/.local/state/hermes-tailchat/dreaming"
TARGET_BIN=/usr/local/bin/hermes-render-motd
TARGET_SCRIPT=/etc/update-motd.d/80-hermes-tailchat

sudo tee "$TARGET_BIN" >/dev/null <<EOF
#!/bin/sh
exec /usr/bin/env python3 "$ROOT_DIR/scripts/render_hermes_motd.py" --state-dir "$STATE_DIR"
EOF
sudo chmod 0755 "$TARGET_BIN"
sudo tee "$TARGET_SCRIPT" >/dev/null <<'EOF'
#!/bin/sh
exec /usr/local/bin/hermes-render-motd
EOF
sudo chmod 0755 "$TARGET_SCRIPT"

if [ -f /etc/default/motd-news ]; then
  sudo python3 - <<'PY'
from pathlib import Path
path = Path('/etc/default/motd-news')
text = path.read_text()
if 'ENABLED=1' in text:
    path.write_text(text.replace('ENABLED=1', 'ENABLED=0', 1))
PY
fi

for path in /etc/update-motd.d/00-header /etc/update-motd.d/10-help-text /etc/update-motd.d/50-landscape-sysinfo; do
  if [ -f "$path" ]; then
    sudo chmod -x "$path"
  fi
done

sudo run-parts /etc/update-motd.d | sudo tee /var/run/motd.dynamic >/dev/null
printf 'Installed Hermes MOTD at %s\n' "$TARGET_SCRIPT"
