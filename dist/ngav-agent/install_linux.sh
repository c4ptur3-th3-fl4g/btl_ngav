#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
SYSTEMD="0"
SERVER_IP="${SERVER_IP:-}"
SERVER_URL="${SERVER_URL:-}"
API_KEY="${API_KEY:-}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --systemd) SYSTEMD="1"; shift ;;
    --server-ip) SERVER_IP="$2"; shift 2 ;;
    --server-url) SERVER_URL="$2"; shift 2 ;;
    --api-key) API_KEY="$2"; shift 2 ;;
    -h|--help)
      cat <<USAGE
Usage: $0 [--systemd] [--server-ip IP | --server-url URL] [--api-key KEY]
USAGE
      exit 0
      ;;
    *) echo "[error] unknown option: $1"; exit 1 ;;
  esac
done

cd "$ROOT"
"$PYTHON_BIN" -m venv .venv
".venv/bin/pip" install --upgrade pip
".venv/bin/pip" install -r requirements-agent.txt

chmod +x run_agent.sh

if [[ -z "$SERVER_URL" ]]; then
  if [[ -z "$SERVER_IP" && -t 0 ]]; then
    read -r -p "NGAV server IP: " SERVER_IP
  fi
  if [[ -n "$SERVER_IP" ]]; then
    SERVER_URL="http://${SERVER_IP}:8000"
  fi
fi
if [[ -z "$API_KEY" && -t 0 ]]; then
  read -r -p "NGAV API key from Server UI Connect button: " API_KEY
fi

if [[ -n "$SERVER_URL" || -n "$API_KEY" ]]; then
  SERVER_URL="$SERVER_URL" API_KEY="$API_KEY" ".venv/bin/python" - <<'PY'
import os
from pathlib import Path
import yaml

config_path = Path("config/config.yaml")
raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
if os.environ.get("SERVER_URL"):
    raw.setdefault("collector", {})["url"] = os.environ["SERVER_URL"].rstrip("/")
raw.setdefault("collector", {})["api_key_path"] = "../agent/api_key.txt"
config_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")

api_key = os.environ.get("API_KEY", "").strip()
if api_key:
    key_path = Path("agent/api_key.txt")
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_text(api_key + "\n", encoding="utf-8")
PY
fi

if [[ "$SYSTEMD" == "1" ]]; then
  if [[ "$(id -u)" -ne 0 ]]; then
    echo "[error] --systemd requires sudo/root"
    exit 1
  fi
  INSTALL_DIR="${INSTALL_DIR:-/opt/ngav-agent}"
  mkdir -p "$INSTALL_DIR"
  cp -a "$ROOT/." "$INSTALL_DIR/"
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
