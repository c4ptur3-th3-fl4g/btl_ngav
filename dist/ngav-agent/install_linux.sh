#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"

cd "$ROOT"
"$PYTHON_BIN" -m venv .venv
".venv/bin/pip" install --upgrade pip
".venv/bin/pip" install -r requirements-agent.txt

chmod +x run_agent.sh

if [[ "${1:-}" == "--systemd" ]]; then
  if [[ "$(id -u)" -ne 0 ]]; then
    echo "[error] --systemd requires sudo/root"
    exit 1
  fi
  INSTALL_DIR="${INSTALL_DIR:-/opt/ngav-agent}"
  mkdir -p "$INSTALL_DIR"
  rsync -a --delete "$ROOT/" "$INSTALL_DIR/"
  cat >/etc/systemd/system/ngav-agent.service <<SERVICE
[Unit]
Description=NGAV Agent
After=network-online.target
Wants=network-online.target

[Service]
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/.venv/bin/python $INSTALL_DIR/agent/ngav_agent.py --config $INSTALL_DIR/config/config.yaml --realtime --monitor-network
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SERVICE
  systemctl daemon-reload
  systemctl enable --now ngav-agent
  echo "[ok] systemd service installed: ngav-agent"
else
  echo "[ok] installed. Run ./run_agent.sh"
fi
