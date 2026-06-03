#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

exec .venv/bin/python agent/ngav_agent.py \
  --config config/config.yaml \
  --realtime \
  --monitor-network \
  "$@"
