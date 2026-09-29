#!/usr/bin/env bash
set -euo pipefail

RUN_ID="${RUN_ID:-run-v133-real-local-repeated-001}"
TRIAL_COUNT="${TRIAL_COUNT:-3}"
COUNT="${COUNT:-100}"
BROKER="${BROKER:-localhost}"
PORT="${PORT:-1883}"
QOS="${QOS:-1}"
EXECUTE="${EXECUTE:-0}"
RESULT_DIR="results/${RUN_ID}"

echo "[v1.3.3] running tests"
python -m pytest -q

MODE_ARG="--dry-run"
if [ "${EXECUTE}" = "1" ]; then
  MODE_ARG="--execute"
fi

echo "[v1.3.3] running repeated local trials: EXECUTE=${EXECUTE}, TRIAL_COUNT=${TRIAL_COUNT}, COUNT=${COUNT}"
python experiments/run_v133_real_repeated_trials.py \
  --run-id "${RUN_ID}" \
  --out-dir "${RESULT_DIR}" \
  --trial-count "${TRIAL_COUNT}" \
  --broker "${BROKER}" \
  --port "${PORT}" \
  --count "${COUNT}" \
  --qos "${QOS}" \
  "${MODE_ARG}"

