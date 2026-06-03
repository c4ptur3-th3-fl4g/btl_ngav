#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="/opt/ngav-server"
HOST="0.0.0.0"
PORT="8000"
SERVER_IP=""
NO_ELASTIC="0"
SERVICE_NAME="ngav-collector"

usage() {
  cat <<USAGE
Usage: sudo $0 [options]

Options:
  --install-dir PATH   Install directory. Default: /opt/ngav-server
  --host HOST          Bind host for collector. Default: 0.0.0.0
  --port PORT          Bind port for collector. Default: 8000
  --server-ip IP       IP agents should connect to. Default: first local non-loopback IP
  --no-elastic         Skip Docker Elasticsearch/Kibana startup

After install:
  systemctl status ngav-collector
  journalctl -u ngav-collector -f
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --install-dir) INSTALL_DIR="$2"; shift 2 ;;
    --host) HOST="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    --server-ip) SERVER_IP="$2"; shift 2 ;;
    --no-elastic) NO_ELASTIC="1"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "[error] unknown option: $1"; usage; exit 1 ;;
  esac
done

if [[ "$(id -u)" -ne 0 ]]; then
  echo "[error] please run as root: sudo $0"
  exit 1
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"

detect_ip() {
  if command -v hostname >/dev/null 2>&1; then
    hostname -I 2>/dev/null | tr ' ' '\n' | grep -E '^[0-9]+\.' | grep -v '^127\.' | head -n 1 || true
  fi
}

if [[ -z "$SERVER_IP" ]]; then
  SERVER_IP="$(detect_ip)"
fi
if [[ -z "$SERVER_IP" ]]; then
  echo "[error] could not detect server IP. Pass --server-ip <IP>"
  exit 1
fi

echo "[info] installing NGAV server to $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"

tar \
  --exclude='.git' \
  --exclude='.venv' \
  --exclude='dist' \
  --exclude='data' \
  --exclude='datasets' \
  --exclude='notebooks' \
  --exclude='server/logs' \
  --exclude='__pycache__' \
  -C "$ROOT" -cf - . | tar -C "$INSTALL_DIR" -xf -

cd "$INSTALL_DIR"
"$PYTHON_BIN" -m venv .venv
".venv/bin/pip" install --upgrade pip
".venv/bin/pip" install -r requirements.txt

ELASTIC_URL="http://localhost:9200"
if [[ "$NO_ELASTIC" != "1" ]]; then
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    echo "[info] starting Elasticsearch and Kibana with Docker Compose"
    docker compose -f docker-compose.elastic.yml up -d
  else
    echo "[warn] docker compose not found; skipping Elasticsearch startup"
  fi
fi

cat >/etc/ngav-server.env <<ENV
ELASTICSEARCH_URL=$ELASTIC_URL
PYTHONUNBUFFERED=1
ENV

cat >/etc/systemd/system/${SERVICE_NAME}.service <<SERVICE
[Unit]
Description=NGAV Collector Server
After=network-online.target docker.service
Wants=network-online.target

[Service]
WorkingDirectory=$INSTALL_DIR
EnvironmentFile=/etc/ngav-server.env
ExecStart=$INSTALL_DIR/.venv/bin/uvicorn server.collector:app --host $HOST --port $PORT
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SERVICE

systemctl daemon-reload
systemctl enable --now "$SERVICE_NAME"

if command -v ufw >/dev/null 2>&1; then
  ufw allow "$PORT"/tcp >/dev/null 2>&1 || true
  ufw allow 5601/tcp >/dev/null 2>&1 || true
fi

COLLECTOR_URL="http://${SERVER_IP}:${PORT}"
echo "[info] building endpoint agent bundle for $COLLECTOR_URL"
".venv/bin/python" scripts/package_agent.py --collector-url "$COLLECTOR_URL" --output-dir "$INSTALL_DIR/dist"

echo "[ok] NGAV collector installed and started"
echo "[ok] collector URL for agents: $COLLECTOR_URL"
echo "[ok] web console: $COLLECTOR_URL/ui"
echo "[ok] generated agent bundle: $INSTALL_DIR/dist/ngav-agent.zip"
echo
echo "Useful commands:"
echo "  systemctl status $SERVICE_NAME"
echo "  journalctl -u $SERVICE_NAME -f"
echo "  curl $COLLECTOR_URL/agents"
