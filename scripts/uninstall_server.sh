#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="/opt/ngav-server"
ELASTIC_DIR="/opt/ngav-elastic"
SERVICE_NAME="ngav-collector"
PURGE_ELK="1"
PURGE_CONFIG="1"
REMOVE_ELASTIC_USER="1"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --install-dir) INSTALL_DIR="$2"; shift 2 ;;
    --elastic-dir) ELASTIC_DIR="$2"; shift 2 ;;
    --stop-elastic|--stop-native-elastic|--purge-elastic|--purge-elk) PURGE_ELK="1"; shift ;;
    --keep-elk|--keep-elastic) PURGE_ELK="0"; shift ;;
    --purge-config) PURGE_CONFIG="1"; shift ;;
    --keep-config) PURGE_CONFIG="0"; shift ;;
    --keep-elastic-user) REMOVE_ELASTIC_USER="0"; shift ;;
    -h|--help)
      cat <<USAGE
Usage: sudo $0 [options]

Options:
  --install-dir PATH       Server install directory. Default: /opt/ngav-server
  --elastic-dir PATH       Native ELK directory. Default: /opt/ngav-elastic
  --purge-elk              Remove native Elasticsearch/Kibana completely. Default
  --purge-elastic          Alias for --purge-elk
  --stop-elastic           Alias for --purge-elk
  --stop-native-elastic    Alias for --purge-elk
  --keep-elk               Keep native Elasticsearch/Kibana
  --keep-elastic           Alias for --keep-elk
  --purge-config           Remove NGAV config/data/log files. Default
  --keep-config            Keep NGAV config/data/log files
  --keep-elastic-user      Do not remove the elasticsearch system user/group
USAGE
      exit 0
      ;;
    *) echo "[error] unknown option: $1"; exit 1 ;;
  esac
done

if [[ "$(id -u)" -ne 0 ]]; then
  echo "[error] please run as root: sudo $0"
  exit 1
fi

systemctl disable --now "$SERVICE_NAME" >/dev/null 2>&1 || true
systemctl stop "$SERVICE_NAME" >/dev/null 2>&1 || true
pkill -f "$INSTALL_DIR/.venv/bin/uvicorn server.collector:app" >/dev/null 2>&1 || true
pkill -f "uvicorn server.collector:app" >/dev/null 2>&1 || true
rm -f "/etc/systemd/system/${SERVICE_NAME}.service"
rm -rf "/etc/systemd/system/${SERVICE_NAME}.service.d"
rm -f "/etc/systemd/system/multi-user.target.wants/${SERVICE_NAME}.service"
systemctl daemon-reload
systemctl reset-failed "$SERVICE_NAME" >/dev/null 2>&1 || true
echo "[ok] removed systemd service: $SERVICE_NAME"

if [[ "$PURGE_ELK" == "1" ]]; then
  systemctl disable --now ngav-kibana ngav-elasticsearch kibana elasticsearch >/dev/null 2>&1 || true
  systemctl stop ngav-kibana ngav-elasticsearch kibana elasticsearch >/dev/null 2>&1 || true
  pkill -f "$ELASTIC_DIR/elasticsearch" >/dev/null 2>&1 || true
  pkill -f "$ELASTIC_DIR/kibana" >/dev/null 2>&1 || true
  pkill -f "org.elasticsearch.bootstrap.Elasticsearch" >/dev/null 2>&1 || true
  pkill -f "kibana/bin/../src/cli/dist" >/dev/null 2>&1 || true
  rm -f \
    /etc/systemd/system/ngav-kibana.service \
    /etc/systemd/system/ngav-elasticsearch.service \
    /etc/systemd/system/kibana.service \
    /etc/systemd/system/elasticsearch.service \
    /etc/systemd/system/multi-user.target.wants/ngav-kibana.service \
    /etc/systemd/system/multi-user.target.wants/ngav-elasticsearch.service \
    /etc/systemd/system/multi-user.target.wants/kibana.service \
    /etc/systemd/system/multi-user.target.wants/elasticsearch.service
  rm -rf \
    /etc/systemd/system/ngav-kibana.service.d \
    /etc/systemd/system/ngav-elasticsearch.service.d \
    /etc/systemd/system/kibana.service.d \
    /etc/systemd/system/elasticsearch.service.d
  systemctl daemon-reload
  systemctl reset-failed ngav-kibana ngav-elasticsearch kibana elasticsearch >/dev/null 2>&1 || true

  if [[ -d "$ELASTIC_DIR" ]]; then
    rm -rf "$ELASTIC_DIR"
  fi

  rm -rf /tmp/ngav-elastic-install
  rm -rf /var/lib/elasticsearch /var/log/elasticsearch /etc/elasticsearch
  rm -rf /var/lib/kibana /var/log/kibana /etc/kibana
  rm -f /etc/apt/sources.list.d/elastic-8.x.list /usr/share/keyrings/elasticsearch-keyring.gpg

  if command -v pacman >/dev/null 2>&1; then
    pacman -Rns --noconfirm elasticsearch kibana >/dev/null 2>&1 || true
  fi
  if command -v apt-get >/dev/null 2>&1; then
    apt-get purge -y elasticsearch kibana >/dev/null 2>&1 || true
    apt-get autoremove -y >/dev/null 2>&1 || true
  fi

  if [[ "$REMOVE_ELASTIC_USER" == "1" ]]; then
    userdel elasticsearch >/dev/null 2>&1 || true
    groupdel elasticsearch >/dev/null 2>&1 || true
  fi

  echo "[ok] purged Elasticsearch/Kibana services, files, cache, and package traces"
else
  echo "[info] kept Elasticsearch/Kibana because --keep-elk was used"
fi

if [[ "$PURGE_CONFIG" == "1" ]]; then
  rm -f /etc/ngav-server.env
  rm -rf \
    /etc/ngav-server \
    /var/lib/ngav-server \
    /var/log/ngav-server \
    /var/cache/ngav-server \
    /run/ngav-server
  echo "[ok] removed NGAV config, data, log, cache, and runtime files"
else
  echo "[info] kept NGAV config/data/log files"
fi

if [[ -d "$INSTALL_DIR" ]]; then
  rm -rf "$INSTALL_DIR"
  echo "[ok] removed install directory: $INSTALL_DIR"
fi
