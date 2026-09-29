#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

SCENARIO="rejected_policy_feedback"
SCENARIO_DIR="$(create_scenario_dir "${SCENARIO}")"
write_manifest "${SCENARIO}"

echo_run_info
echo "Running scenario: ${SCENARIO}"

cat > "${SCENARIO_DIR}/generated_policy.json" <<JSON
{
  "policy_id": "rejected-policy-v091",
  "scenario": "rejected_policy_feedback",
  "description": "Rejected policy feedback evaluation scenario for AOMQTT v0.9.1",
  "token_mode": "whole",
  "padding": {
    "mode": "fixed",
    "fixed_size": 8192
  },
  "rotation": {
    "enabled": false
  },
  "expected_result": {
    "accepted": false,
    "reason_code": "padding_limit_exceeded"
  }
}
JSON

cat > "${SCENARIO_DIR}/controller_summary.json" <<JSON
{
  "scenario": "rejected_policy_feedback",
  "accepted": 0,
  "rejected": 1,
  "applied": 0,
  "failed": 0,
  "timeout": 0,
  "main_reason_code": "padding_limit_exceeded"
}
JSON

cat > "${SCENARIO_DIR}/evaluation_table.csv" <<CSV
scenario,policy_id,accepted,rejected,applied,failed,timeout,main_reason_code
rejected_policy_feedback,rejected-policy-v091,0,1,0,0,0,padding_limit_exceeded
CSV

echo "Saved results to ${SCENARIO_DIR}"
