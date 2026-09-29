#!/usr/bin/env bash
# Run all AOMQTT v1.0.0 evaluation scenarios.
#
# Usage:
#   RUN_ID=run-v100-final ./experiments/run_all_v100_scenarios.sh
#
# This script acts as a v1.0.0 orchestration wrapper. It keeps the top-level
# v1.0.0 result directory under results/<RUN_ID>/ and records scenario logs
# under results/<RUN_ID>/raw/.
#
# The individual scenario scripts are executed with scenario-specific RUN_IDs
# to avoid overwriting raw outputs from different scenarios.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_ID="${RUN_ID:-run-v100-final}"
EXPERIMENT_ID="${EXPERIMENT_ID:-exp-v100-final}"
RESULTS_DIR="${RESULTS_DIR:-${ROOT_DIR}/results/${RUN_ID}}"

mkdir -p "${RESULTS_DIR}/config" \
         "${RESULTS_DIR}/raw" \
         "${RESULTS_DIR}/derived" \
         "${RESULTS_DIR}/paper/tables" \
         "${RESULTS_DIR}/paper/figures"

GIT_COMMIT="unknown"
if command -v git >/dev/null 2>&1; then
  GIT_COMMIT="$(cd "${ROOT_DIR}" && git rev-parse HEAD 2>/dev/null || echo unknown)"
fi

CREATED_AT="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

cat > "${RESULTS_DIR}/config/experiment_config.yaml" <<EOF
schema_version: 1
project: AOMQTT Client SDK
version: v1.0.0
experiment_id: ${EXPERIMENT_ID}
run_id: ${RUN_ID}
created_at: ${CREATED_AT}
git_commit: ${GIT_COMMIT}
scenarios:
  - static_policy
  - observation_policy
  - rejected_policy_feedback
outputs:
  config: config/
  raw: raw/
  derived: derived/
  paper: paper/
EOF

python - <<PY
import json
from pathlib import Path

results_dir = Path("${RESULTS_DIR}")
manifest = {
    "schema_version": 1,
    "project": "AOMQTT Client SDK",
    "version": "v1.0.0",
    "experiment_id": "${EXPERIMENT_ID}",
    "run_id": "${RUN_ID}",
    "created_at": "${CREATED_AT}",
    "git_commit": "${GIT_COMMIT}",
    "scenarios": [
        "static_policy",
        "observation_policy",
        "rejected_policy_feedback",
    ],
    "outputs": {
        "config": "config/",
        "raw": "raw/",
        "derived": "derived/",
        "paper": "paper/",
    },
}
(results_dir / "manifest.json").write_text(
    json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
    encoding="utf-8",
)
PY

run_scenario() {
  local scenario_name="$1"
  local script_path="$2"
  local scenario_run_id="$3"
  local log_path="${RESULTS_DIR}/raw/${scenario_name}.log"

  if [[ ! -f "${ROOT_DIR}/${script_path}" ]]; then
    echo "[ERROR] Missing scenario script: ${script_path}" | tee -a "${log_path}"
    exit 1
  fi

  echo "[INFO] Running ${scenario_name}" | tee "${log_path}"
  echo "[INFO] Scenario RUN_ID=${scenario_run_id}" | tee -a "${log_path}"

  (
    cd "${ROOT_DIR}"
    RUN_ID="${scenario_run_id}" \
    AOMQTT_PARENT_RUN_ID="${RUN_ID}" \
    AOMQTT_PARENT_RESULTS_DIR="${RESULTS_DIR}" \
    bash "${script_path}"
  ) 2>&1 | tee -a "${log_path}"

  echo "[OK] Completed ${scenario_name}" | tee -a "${log_path}"
}

run_scenario "static_policy" \
  "experiments/run_static_policy.sh" \
  "${RUN_ID}-static"

run_scenario "observation_policy" \
  "experiments/run_observation_policy.sh" \
  "${RUN_ID}-observation"

run_scenario "rejected_policy_feedback" \
  "experiments/run_rejected_policy_feedback.sh" \
  "${RUN_ID}-rejected"

echo "[INFO] Collecting v1.0.0 evaluation tables"
(
  cd "${ROOT_DIR}"
  RUN_ID="${RUN_ID}" \
  RESULTS_DIR="${RESULTS_DIR}" \
  bash "experiments/collect_v100_evaluation_table.sh"
)

echo "[OK] All v1.0.0 scenarios completed"
echo "[OK] Results directory: ${RESULTS_DIR}"
