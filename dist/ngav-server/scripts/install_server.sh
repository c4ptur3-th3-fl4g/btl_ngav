#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="/opt/ngav-server"
ELASTIC_DIR="/opt/ngav-elastic"
ELASTIC_VERSION="8.14.3"
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
  --elastic-dir PATH   Native Elastic directory. Default: /opt/ngav-elastic
  --elastic-version V  Elastic/Kibana version. Default: 8.14.3
  --host HOST          Bind host for collector. Default: 0.0.0.0
  --port PORT          Bind port for collector. Default: 8000
  --server-ip IP       IP agents should connect to. Default: first local non-loopback IP
  --no-elastic         Skip native Elasticsearch/Kibana install
  --elastic-native     Accepted for compatibility; native install is now the default

After install:
  systemctl status ngav-collector
  systemctl status ngav-elasticsearch
  systemctl status ngav-kibana
  journalctl -u ngav-collector -f
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --install-dir) INSTALL_DIR="$2"; shift 2 ;;
    --elastic-dir) ELASTIC_DIR="$2"; shift 2 ;;
    --elastic-version) ELASTIC_VERSION="$2"; shift 2 ;;
    --host) HOST="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    --server-ip) SERVER_IP="$2"; shift 2 ;;
    --no-elastic) NO_ELASTIC="1"; shift ;;
    --elastic-native) shift ;;
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

ensure_elastic_user() {
  if ! id elasticsearch >/dev/null 2>&1; then
    local nologin="/usr/sbin/nologin"
    if [[ ! -x "$nologin" ]]; then
      nologin="/usr/bin/nologin"
    fi
    useradd --system --home-dir "$ELASTIC_DIR" --shell "$nologin" elasticsearch
  fi
}

install_elastic_native() {
  local arch
  arch="$(uname -m)"
  if [[ "$arch" != "x86_64" ]]; then
    echo "[error] native tarball install currently supports x86_64 only; detected $arch"
    exit 1
  fi
  if ! command -v curl >/dev/null 2>&1 || ! command -v tar >/dev/null 2>&1; then
    echo "[error] native Elastic install requires curl and tar"
    exit 1
  fi

  ensure_elastic_user

  local es_url="https://artifacts.elastic.co/downloads/elasticsearch/elasticsearch-${ELASTIC_VERSION}-linux-x86_64.tar.gz"
  local kibana_url="https://artifacts.elastic.co/downloads/kibana/kibana-${ELASTIC_VERSION}-linux-x86_64.tar.gz"
  local cache_dir="/tmp/ngav-elastic-install"
  local es_tar="$cache_dir/elasticsearch-${ELASTIC_VERSION}-linux-x86_64.tar.gz"
  local kibana_tar="$cache_dir/kibana-${ELASTIC_VERSION}-linux-x86_64.tar.gz"

  echo "[info] installing native Elasticsearch/Kibana ${ELASTIC_VERSION} to $ELASTIC_DIR"
  mkdir -p "$cache_dir" "$ELASTIC_DIR"

  if [[ ! -f "$es_tar" ]]; then
    curl -fL "$es_url" -o "$es_tar"
  fi
  if [[ ! -f "$kibana_tar" ]]; then
    curl -fL "$kibana_url" -o "$kibana_tar"
  fi

  rm -rf "$ELASTIC_DIR/elasticsearch" "$ELASTIC_DIR/kibana"
  tar -xzf "$es_tar" -C "$ELASTIC_DIR"
  tar -xzf "$kibana_tar" -C "$ELASTIC_DIR"
  mv "$ELASTIC_DIR/elasticsearch-${ELASTIC_VERSION}" "$ELASTIC_DIR/elasticsearch"
  mv "$ELASTIC_DIR/kibana-${ELASTIC_VERSION}" "$ELASTIC_DIR/kibana"

  mkdir -p "$ELASTIC_DIR/elasticsearch-data" "$ELASTIC_DIR/elasticsearch-logs" "$ELASTIC_DIR/kibana-data"

  cat >"$ELASTIC_DIR/elasticsearch/config/elasticsearch.yml" <<ESCONF
cluster.name: ngav-cluster
node.name: ngav-server
path.data: $ELASTIC_DIR/elasticsearch-data
path.logs: $ELASTIC_DIR/elasticsearch-logs
network.host: 127.0.0.1
http.port: 9200
discovery.type: single-node
xpack.security.enabled: false
ESCONF

  cat >"$ELASTIC_DIR/kibana/config/kibana.yml" <<KIBCONF
server.host: "0.0.0.0"
server.port: 5601
elasticsearch.hosts: ["http://localhost:9200"]
path.data: "$ELASTIC_DIR/kibana-data"
KIBCONF

  chown -R elasticsearch:elasticsearch "$ELASTIC_DIR"

  cat >/etc/systemd/system/ngav-elasticsearch.service <<SERVICE
[Unit]
Description=NGAV Native Elasticsearch
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=elasticsearch
Group=elasticsearch
WorkingDirectory=$ELASTIC_DIR/elasticsearch
Environment=ES_HOME=$ELASTIC_DIR/elasticsearch
Environment=ES_PATH_CONF=$ELASTIC_DIR/elasticsearch/config
ExecStart=$ELASTIC_DIR/elasticsearch/bin/elasticsearch
Restart=always
RestartSec=10
LimitNOFILE=65535
LimitNPROC=4096
TimeoutStartSec=180

[Install]
WantedBy=multi-user.target
SERVICE

  cat >/etc/systemd/system/ngav-kibana.service <<SERVICE
[Unit]
Description=NGAV Native Kibana
After=network-online.target ngav-elasticsearch.service
Wants=network-online.target

[Service]
Type=simple
User=elasticsearch
Group=elasticsearch
WorkingDirectory=$ELASTIC_DIR/kibana
ExecStart=$ELASTIC_DIR/kibana/bin/kibana
Restart=always
RestartSec=10
TimeoutStartSec=180

[Install]
WantedBy=multi-user.target
SERVICE

  systemctl daemon-reload
  systemctl enable --now ngav-elasticsearch
  echo "[info] waiting for native Elasticsearch at http://localhost:9200"
  for _ in $(seq 1 60); do
    if curl -fsS http://localhost:9200 >/dev/null 2>&1; then
      echo "[ok] native Elasticsearch is ready"
      systemctl enable --now ngav-kibana
      return 0
    fi
    sleep 2
  done
  echo "[warn] Elasticsearch did not respond yet; check: journalctl -u ngav-elasticsearch -f"
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
  install_elastic_native
fi

cat >/etc/ngav-server.env <<ENV
ELASTICSEARCH_URL=$ELASTIC_URL
PYTHONUNBUFFERED=1
ENV

cat >/etc/systemd/system/${SERVICE_NAME}.service <<SERVICE
[Unit]
Description=NGAV Collector Server
After=network-online.target ngav-elasticsearch.service
Wants=network-online.target ngav-elasticsearch.service

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
echo "  systemctl status ngav-elasticsearch"
echo "  systemctl status ngav-kibana"
echo "  journalctl -u $SERVICE_NAME -f"
echo "  curl $COLLECTOR_URL/agents"
