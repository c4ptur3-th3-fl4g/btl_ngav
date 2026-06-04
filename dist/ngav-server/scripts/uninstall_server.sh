#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="/opt/ngav-server"
ELASTIC_DIR="/opt/ngav-elastic"
SERVICE_NAME="ngav-collector"
PURGE_ELK="0"
REMOVE_ELASTIC_USER="1"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --install-dir) INSTALL_DIR="$2"; shift 2 ;;
    --elastic-dir) ELASTIC_DIR="$2"; shift 2 ;;
    --stop-elastic|--stop-native-elastic|--purge-elastic|--purge-elk) PURGE_ELK="1"; shift ;;
    --keep-elastic-user) REMOVE_ELASTIC_USER="0"; shift ;;
    -h|--help)
      cat <<USAGE
Usage: sudo $0 [options]

Options:
  --install-dir PATH       Server install directory. Default: /opt/ngav-server
  --elastic-dir PATH       Native ELK directory. Default: /opt/ngav-elastic
  --purge-elk              Remove native Elasticsearch/Kibana completely
  --purge-elastic          Alias for --purge-elk
  --stop-elastic           Alias for --purge-elk
  --stop-native-elastic    Alias for --purge-elk
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

if systemctl list-unit-files | grep -q "^${SERVICE_NAME}.service"; then
  systemctl disable --now "$SERVICE_NAME" || true
  rm -f "/etc/systemd/system/${SERVICE_NAME}.service"
  systemctl daemon-reload
  echo "[ok] removed systemd service: $SERVICE_NAME"
fi

if [[ "$PURGE_ELK" == "1" ]]; then
  systemctl disable --now ngav-kibana ngav-elasticsearch kibana elasticsearch || true
  rm -f \
    /etc/systemd/system/ngav-kibana.service \
    /etc/systemd/system/ngav-elasticsearch.service \
    /etc/systemd/system/kibana.service \
    /etc/systemd/system/elasticsearch.service
  systemctl daemon-reload

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
fi

rm -f /etc/ngav-server.env
if [[ -d "$INSTALL_DIR" ]]; then
  rm -rf "$INSTALL_DIR"
  echo "[ok] removed install directory: $INSTALL_DIR"
fi
