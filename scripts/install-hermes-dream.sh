#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
USER_SYSTEMD_DIR=${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user
mkdir -p "$USER_SYSTEMD_DIR"

install -m 0644 "$ROOT_DIR/systemd/hermes-tailchat-dream.service" "$USER_SYSTEMD_DIR/hermes-tailchat-dream.service"
install -m 0644 "$ROOT_DIR/systemd/hermes-tailchat-dream.timer" "$USER_SYSTEMD_DIR/hermes-tailchat-dream.timer"
chmod 0755 "$ROOT_DIR/scripts/hermes_dream.py"

systemctl --user daemon-reload
systemctl --user enable --now hermes-tailchat-dream.timer
systemctl --user start hermes-tailchat-dream.service

echo "Installed and started hermes-tailchat-dream.timer"
systemctl --user status hermes-tailchat-dream.timer --no-pager -n 20
