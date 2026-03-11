#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

COMPOSE_FILE="docker-compose.sonarqube.yml"
SONAR_PORT="${SONAR_PORT:-9001}"
SONAR_HOST_URL="${SONAR_HOST_URL:-http://localhost:${SONAR_PORT}}"

cmd="${1:-}"

usage() {
  cat <<'TXT'
Usage:
  scripts/sonar_local.sh start        # start SonarQube (Docker)
  scripts/sonar_local.sh stop         # stop + remove container + volumes
  scripts/sonar_local.sh logs         # tail logs
  scripts/sonar_local.sh status       # show container status
  scripts/sonar_local.sh coverage     # run pytest with coverage.xml
  scripts/sonar_local.sh scan         # run sonar-scanner (requires SONAR_TOKEN)

Env:
  SONAR_PORT=9001                     # host port mapped to SonarQube 9000
  SONAR_HOST_URL=http://localhost:9001
  SONAR_TOKEN=...                     # required for 'scan'
  SONAR_PROJECT_KEY=oig_cloud         # default is 'oig_cloud'
TXT
}

wait_for_sonarqube() {
  echo "Waiting for SonarQube at ${SONAR_HOST_URL} ..."
  # First boot can take a while (image pull, DB migrations, indexing).
  for _ in $(seq 1 360); do
    if curl -fsS "${SONAR_HOST_URL}/api/system/status" >/dev/null 2>&1; then
      status="$(curl -fsS "${SONAR_HOST_URL}/api/system/status" | sed -n 's/.*\"status\":\"\\([A-Z]*\\)\".*/\\1/p')"
      if [[ "$status" == "UP" ]]; then
        echo "SonarQube is UP: ${SONAR_HOST_URL}"
        return 0
      fi
    fi
    sleep 2
  done
  echo "Timed out waiting for SonarQube. Try: scripts/sonar_local.sh logs"
  return 1
}

start() {
  docker compose -f "$COMPOSE_FILE" up -d
  wait_for_sonarqube
  cat <<TXT

Open: ${SONAR_HOST_URL}
Default credentials: admin / admin (you will be prompted to change password).

Next:
  1) Create project key (recommended): oig_cloud
  2) Create token and export:
       export SONAR_TOKEN="..."
  3) Run:
       scripts/sonar_local.sh scan
TXT
}

stop() {
  docker compose -f "$COMPOSE_FILE" down -v
}

logs() {
  docker logs -f oig_sonarqube
}

status() {
  docker ps --filter "name=oig_sonarqube" --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
}

coverage() {
  .venv/bin/python -m pytest -q --cov=custom_components/oig_cloud --cov-report=xml
  echo "Wrote: coverage.xml"
}

scan() {
  : "${SONAR_TOKEN:?SONAR_TOKEN is required for scan}"
  SONAR_PROJECT_KEY="${SONAR_PROJECT_KEY:-oig_cloud}"

  if [[ ! -f coverage.xml ]]; then
    coverage
  fi

  if command -v sonar-scanner >/dev/null 2>&1; then
    sonar-scanner \
      -Dsonar.host.url="${SONAR_HOST_URL}" \
      -Dsonar.login="${SONAR_TOKEN}" \
      -Dsonar.projectKey="${SONAR_PROJECT_KEY}"
    echo "Scan submitted. Check: ${SONAR_HOST_URL}"
    return 0
  fi

  # Use host.docker.internal for Docker Desktop (macOS/Windows), fallback to localhost otherwise.
  scanner_host="http://host.docker.internal:${SONAR_PORT}"
  scanner_platform="${SONAR_SCANNER_PLATFORM:-}"
  if [[ -z "$scanner_platform" ]]; then
    if [[ "$(uname -m)" == "arm64" ]]; then
      echo "Note: sonar-scanner image is amd64-only; using emulation on arm64."
      scanner_platform="linux/amd64"
    fi
  fi
  docker run --rm \
    ${scanner_platform:+--platform "${scanner_platform}"} \
    -e "SONAR_HOST_URL=${scanner_host}" \
    -e "SONAR_TOKEN=${SONAR_TOKEN}" \
    -v "$PWD:/usr/src" \
    -w /usr/src \
    sonarsource/sonar-scanner-cli:latest \
    -Dsonar.projectKey="${SONAR_PROJECT_KEY}"

  echo "Scan submitted. Check: ${SONAR_HOST_URL}"
}

case "$cmd" in
  start) start ;;
  stop) stop ;;
  logs) logs ;;
  status) status ;;
  coverage) coverage ;;
  scan) scan ;;
  ""|-h|--help|help) usage ;;
  *) echo "Unknown command: $cmd"; usage; exit 2 ;;
esac
