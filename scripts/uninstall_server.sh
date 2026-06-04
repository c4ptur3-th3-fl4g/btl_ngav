#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="/opt/ngav-server"
ELASTIC_DIR="/opt/ngav-elastic"
SERVICE_NAME="ngav-collector"
STOP_ELASTIC="0"
STOP_NATIVE_ELASTIC="0"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --install-dir) INSTALL_DIR="$2"; shift 2 ;;
    --elastic-dir) ELASTIC_DIR="$2"; shift 2 ;;
    --stop-elastic) STOP_ELASTIC="1"; STOP_NATIVE_ELASTIC="1"; shift ;;
    --stop-native-elastic) STOP_NATIVE_ELASTIC="1"; shift ;;
    -h|--help)
      echo "Usage: sudo $0 [--install-dir /opt/ngav-server] [--stop-elastic] [--stop-native-elastic]"
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

if [[ "$STOP_NATIVE_ELASTIC" == "1" ]]; then
  systemctl disable --now ngav-kibana ngav-elasticsearch || true
  rm -f /etc/systemd/system/ngav-kibana.service /etc/systemd/system/ngav-elasticsearch.service
  systemctl daemon-reload
  if [[ -d "$ELASTIC_DIR" ]]; then
    rm -rf "$ELASTIC_DIR"
  fi
  echo "[ok] removed native Elasticsearch/Kibana services and files"
fi

rm -f /etc/ngav-server.env
if [[ -d "$INSTALL_DIR" ]]; then
  rm -rf "$INSTALL_DIR"
  echo "[ok] removed install directory: $INSTALL_DIR"
fi
