#!/usr/bin/env bash
set -euo pipefail

if [ -z "${RUN_ID:-}" ]; then
  echo "ERROR: RUN_ID is not set."
  echo "Usage: RUN_ID=run-YYYYMMDD-HHMMSS ./experiments/collect_v091_evaluation_table.sh"
  exit 1
fi

RESULT_ROOT="${RESULT_ROOT:-results}"
RUN_DIR="${RESULT_ROOT}/${RUN_ID}"
OUT="${RUN_DIR}/evaluation_table.csv"

if [ ! -d "${RUN_DIR}" ]; then
  echo "ERROR: RUN directory not found: ${RUN_DIR}"
  exit 1
fi

echo "scenario,policy_id,accepted,rejected,applied,failed,timeout,main_reason_code" > "${OUT}"

for scenario in static_policy observation_policy rejected_policy_feedback; do
  TABLE="${RUN_DIR}/${scenario}/evaluation_table.csv"

  if [ ! -f "${TABLE}" ]; then
    echo "ERROR: missing evaluation table: ${TABLE}"
    exit 1
  fi

  tail -n +2 "${TABLE}" >> "${OUT}"
done

echo "Saved merged evaluation table: ${OUT}"
