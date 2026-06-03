#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COLLECTOR_URL="${1:-${COLLECTOR_URL:-}}"

if [[ -z "$COLLECTOR_URL" ]]; then
  echo "Usage: $0 http://COLLECTOR_HOST:8000"
  echo "Or set COLLECTOR_URL=http://COLLECTOR_HOST:8000"
  exit 1
fi

cd "$ROOT"
PYTHON_BIN="${PYTHON_BIN:-.venv/bin/python}"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="python3"
fi

exec "$PYTHON_BIN" scripts/package_agent.py --collector-url "$COLLECTOR_URL"
