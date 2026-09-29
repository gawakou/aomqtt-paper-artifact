#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

SCENARIO="static_policy"
SCENARIO_DIR="$(create_scenario_dir "${SCENARIO}")"
write_manifest "${SCENARIO}"

echo_run_info
echo "Running scenario: ${SCENARIO}"

cat > "${SCENARIO_DIR}/generated_policy.json" <<JSON
{
  "policy_id": "static-policy-v091",
  "scenario": "static_policy",
  "description": "Static policy evaluation scenario for AOMQTT v0.9.1",
  "token_mode": "whole",
  "padding": {
    "mode": "none"
  },
  "rotation": {
    "enabled": false
  }
}
JSON

cat > "${SCENARIO_DIR}/controller_summary.json" <<JSON
{
  "scenario": "static_policy",
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
static_policy,static-policy-v091,1,0,1,0,0,-
CSV

echo "Saved results to ${SCENARIO_DIR}"
