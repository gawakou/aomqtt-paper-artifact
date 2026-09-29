#!/usr/bin/env bash
set -euo pipefail

RUN_ID="${RUN_ID:-run-v132-repeated-trials-001}"
TRIAL_COUNT="${TRIAL_COUNT:-5}"
RESULT_DIR="results/${RUN_ID}"
TRIAL_DIR="${RESULT_DIR}/trials"

echo "[v1.3.2] running tests"
python -m pytest -q

echo "[v1.3.2] generating deterministic sample trial inputs"
python experiments/generate_v132_sample_trials.py \
  --out-dir "${TRIAL_DIR}" \
  --trial-count "${TRIAL_COUNT}"

echo "[v1.3.2] collecting repeated-trial statistics"
python experiments/collect_v132_repeated_trial_statistics.py \
  --inputs "${TRIAL_DIR}"/trial-*/v131_local_comparison_table.csv \
  --out-dir "${RESULT_DIR}"

python - <<PY
import json
from pathlib import Path

result_dir = Path("${RESULT_DIR}")
manifest = {
    "run_id": "${RUN_ID}",
    "release": "v1.3.2",
    "trial_count": int("${TRIAL_COUNT}"),
    "mode": "sample",
    "artifacts": {
        "repeated_trial_measurements_csv": str(result_dir / "repeated_trial_measurements.csv"),
        "repeated_trial_statistics_csv": str(result_dir / "repeated_trial_statistics.csv"),
        "v132_paper_statistics_table_csv": str(result_dir / "v132_paper_statistics_table.csv"),
        "v132_repeated_trial_summary_json": str(result_dir / "v132_repeated_trial_summary.json"),
    },
}
manifest_path = result_dir / "v132_repeated_trials_manifest.json"
manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True))
print(json.dumps(manifest, indent=2, sort_keys=True))
print(f"wrote {manifest_path}")
PY

