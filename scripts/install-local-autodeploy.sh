#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
USER_SYSTEMD_DIR=${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user
mkdir -p "$USER_SYSTEMD_DIR"

install -m 0644 "$ROOT_DIR/systemd/hermes-tailchat-deploy.service" "$USER_SYSTEMD_DIR/hermes-tailchat-deploy.service"
install -m 0644 "$ROOT_DIR/systemd/hermes-tailchat-deploy.path" "$USER_SYSTEMD_DIR/hermes-tailchat-deploy.path"
chmod 0755 "$ROOT_DIR/scripts/deploy-local.sh"

systemctl --user daemon-reload
systemctl --user enable --now hermes-tailchat-deploy.path

echo "Installed and started hermes-tailchat-deploy.path"
systemctl --user status hermes-tailchat-deploy.path --no-pager -n 20
