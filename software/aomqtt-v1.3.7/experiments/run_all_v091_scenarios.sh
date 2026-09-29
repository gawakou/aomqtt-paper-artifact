#!/usr/bin/env bash
set -euo pipefail

if [ -z "${RUN_ID:-}" ]; then
  export RUN_ID="run-$(date +%Y%m%d-%H%M%S)"
else
  export RUN_ID
fi

echo "Running all AOMQTT v0.9.1 evaluation scenarios"
echo "RUN_ID=${RUN_ID}"
echo

./experiments/run_static_policy.sh
echo

./experiments/run_observation_policy.sh
echo

./experiments/run_rejected_policy_feedback.sh
echo

./experiments/collect_v091_evaluation_table.sh

echo "All scenarios completed."
echo "Results: results/${RUN_ID}"
