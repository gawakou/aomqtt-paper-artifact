#!/usr/bin/env bash
set -euo pipefail

RUN_ID="${RUN_ID:-run-v110-trust-scenarios-001}"
RESULTS_ROOT="${RESULTS_ROOT:-results}"
CLIENT_ID="${CLIENT_ID:-subscriber-v110-scenario}"

python experiments/run_v110_trust_scenarios.py \
  --run-id "${RUN_ID}" \
  --results-root "${RESULTS_ROOT}" \
  --client-id "${CLIENT_ID}"
