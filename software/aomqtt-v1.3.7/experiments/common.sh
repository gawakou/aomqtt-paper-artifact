#!/usr/bin/env bash
set -euo pipefail

if [ -z "${RUN_ID:-}" ]; then
  RUN_ID="run-$(date +%Y%m%d-%H%M%S)"
fi

RESULT_ROOT="${RESULT_ROOT:-results}"
RUN_DIR="${RESULT_ROOT}/${RUN_ID}"

mkdir -p "${RUN_DIR}"

write_manifest() {
  local scenario="$1"
  local scenario_dir="${RUN_DIR}/${scenario}"

  mkdir -p "${scenario_dir}"

  cat > "${RUN_DIR}/manifest.json" <<JSON
{
  "run_id": "${RUN_ID}",
  "created_at": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")",
  "version": "v0.9.1",
  "purpose": "AOMQTT evaluation scenario execution"
}
JSON
}

create_scenario_dir() {
  local scenario="$1"
  mkdir -p "${RUN_DIR}/${scenario}"
  echo "${RUN_DIR}/${scenario}"
}

echo_run_info() {
  echo "RUN_ID=${RUN_ID}"
  echo "RUN_DIR=${RUN_DIR}"
}
