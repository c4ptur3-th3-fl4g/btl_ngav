#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${OUT_DIR:-$ROOT/dist}"
BUNDLE_NAME="${BUNDLE_NAME:-ngav-server}"
STAGE="$OUT_DIR/$BUNDLE_NAME"
ZIP_PATH="$OUT_DIR/$BUNDLE_NAME.zip"
TAR_PATH="$OUT_DIR/$BUNDLE_NAME.tar.gz"

cd "$ROOT"
mkdir -p "$OUT_DIR"
rm -rf "$STAGE" "$ZIP_PATH" "$TAR_PATH"
mkdir -p "$STAGE"

copy_path() {
  local src="$1"
  local dst="$2"
  if [[ -e "$src" ]]; then
    mkdir -p "$(dirname "$dst")"
    cp -a "$src" "$dst"
  fi
}

copy_path "agent" "$STAGE/agent"
copy_path "config/config.example.yaml" "$STAGE/config/config.example.yaml"
copy_path "docker-compose.elastic.yml" "$STAGE/docker-compose.elastic.yml"
copy_path "INSTALL.md" "$STAGE/INSTALL.md"
copy_path "requirements.txt" "$STAGE/requirements.txt"
copy_path "requirements-gpu.txt" "$STAGE/requirements-gpu.txt"
copy_path "scripts" "$STAGE/scripts"
copy_path "server" "$STAGE/server"

if [[ -d "models" ]]; then
  mkdir -p "$STAGE/models"
  find models -maxdepth 1 -type f -name "*.pkl" -exec cp -a {} "$STAGE/models/" \;
fi

find "$STAGE" -type d -name "__pycache__" -prune -exec rm -rf {} +
find "$STAGE" -type f -name "*.pyc" -delete
find "$STAGE" -type d -name "logs" -path "*/server/logs" -prune -exec rm -rf {} +

chmod +x "$STAGE/scripts/install_server.sh" "$STAGE/scripts/uninstall_server.sh" "$STAGE/scripts/one_click_agent_bundle.sh" "$STAGE/scripts/package_server_bundle.sh"

(
  cd "$OUT_DIR"
  if command -v zip >/dev/null 2>&1; then
    zip -qr "$ZIP_PATH" "$BUNDLE_NAME"
  else
    python3 - "$BUNDLE_NAME" "$ZIP_PATH" <<'PY'
import sys
import zipfile
from pathlib import Path

root = Path(sys.argv[1])
zip_path = Path(sys.argv[2])
with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
    for path in root.rglob("*"):
        if path.is_file():
            zf.write(path, path)
PY
  fi
  tar -czf "$TAR_PATH" "$BUNDLE_NAME"
)

echo "[ok] server bundle directory: $STAGE"
echo "[ok] zip archive: $ZIP_PATH"
echo "[ok] tar archive: $TAR_PATH"
echo
echo "Deploy on server:"
echo "  unzip $BUNDLE_NAME.zip"
echo "  cd $BUNDLE_NAME"
echo "  sudo scripts/install_server.sh --server-ip <SERVER_IP>"
