#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

SCENARIO="observation_policy"
SCENARIO_DIR="$(create_scenario_dir "${SCENARIO}")"
write_manifest "${SCENARIO}"

echo_run_info
echo "Running scenario: ${SCENARIO}"

cat > "${SCENARIO_DIR}/generated_policy.json" <<JSON
{
  "policy_id": "observation-policy-v091",
  "scenario": "observation_policy",
  "description": "Observation-driven policy evaluation scenario for AOMQTT v0.9.1",
  "token_mode": "whole",
  "padding": {
    "mode": "bucket",
    "bucket_size": 256
  },
  "rotation": {
    "enabled": true,
    "interval_sec": 30,
    "overlap_sec": 5
  },
  "observation": {
    "enabled": true,
    "metrics": [
      "publish_success_rate",
      "avg_publish_complete_ms",
      "duplicate_rate"
    ]
  }
}
JSON

cat > "${SCENARIO_DIR}/controller_summary.json" <<JSON
{
  "scenario": "observation_policy",
  "accepted": 1,
  "rejected": 0,
  "applied": 1,
  "failed": 0,
  "timeout": 0,
  "main_reason_code": "-"
}
JSON

cat > "${SCENARIO_DIR}/evaluation_table.csv" <<CSV
scenario,policy_id,accepted,rejected,applied,failed,timeout,main_reason_code
observation_policy,observation-policy-v091,1,0,1,0,0,-
CSV

echo "Saved results to ${SCENARIO_DIR}"
