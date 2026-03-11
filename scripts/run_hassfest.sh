#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
HA_CORE_DIR="${HA_CORE_DIR:-$ROOT_DIR/local_dev/ha-core}"
INTEGRATION_PATH="${INTEGRATION_PATH:-$ROOT_DIR/custom_components/oig_cloud}"

if [[ ! -d "$HA_CORE_DIR/.git" ]]; then
  git clone --depth=1 https://github.com/home-assistant/core.git "$HA_CORE_DIR"
fi

if [[ ! -d "$HA_CORE_DIR/.venv" ]]; then
  python3 -m venv "$HA_CORE_DIR/.venv"
fi

VENV_PY="$HA_CORE_DIR/.venv/bin/python"
VENV_PIP="$HA_CORE_DIR/.venv/bin/pip"

"$VENV_PIP" install --upgrade pip

(
  cd "$HA_CORE_DIR"
  "$VENV_PIP" install -e . -r requirements_test_all.txt colorlog
  "$VENV_PY" -m script.hassfest --integration-path "$INTEGRATION_PATH"
)
