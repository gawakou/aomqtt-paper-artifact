#!/usr/bin/env bash
set -euo pipefail

RESULTS_DIR="${RESULTS_DIR:-results}"
OUTPUT_DIR="${OUTPUT_DIR:-results/v092_controller_analysis}"
RUN_ID="${RUN_ID:-}"

args=(
  --results-dir "$RESULTS_DIR"
  --output-dir "$OUTPUT_DIR"
)

if [[ -n "$RUN_ID" ]]; then
  args+=(--run-id "$RUN_ID")
fi

python -m aomqtt.controller_analysis "${args[@]}"
