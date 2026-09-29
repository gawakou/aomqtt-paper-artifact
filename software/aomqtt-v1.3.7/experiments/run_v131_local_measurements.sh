#!/usr/bin/env bash
set -euo pipefail

RUN_ID="${RUN_ID:-run-v131-local-measurements-001}"
MODE="${MODE:-sample}"
BROKER="${BROKER:-localhost:1883}"
RESULT_DIR="results/${RUN_ID}"

echo "[v1.3.1] running tests"
python -m pytest -q

echo "[v1.3.1] generating local measurement artifacts: mode=${MODE}"
python experiments/run_v131_local_measurements.py \
  --run-id "${RUN_ID}" \
  --out-dir "${RESULT_DIR}" \
  --broker "${BROKER}" \
  --mode "${MODE}"

echo "[v1.3.1] collecting measurement tables"
python experiments/collect_v131_measurement_table.py \
  --result-dir "${RESULT_DIR}"

python - <<PY
import json
from pathlib import Path

result_dir = Path("${RESULT_DIR}")
manifest = {
    "run_id": "${RUN_ID}",
    "release": "v1.3.1",
    "mode": "${MODE}",
    "broker": "${BROKER}",
    "artifacts": {
        "local_measurement_scenario_plan_csv": str(result_dir / "local_measurement_scenario_plan.csv"),
        "unified_measurements_csv": str(result_dir / "unified_measurements.csv"),
        "v131_measurement_summary_json": str(result_dir / "v131_measurement_summary.json"),
        "v131_release_table_csv": str(result_dir / "v131_release_table.csv"),
        "v131_paper_measurement_table_csv": str(result_dir / "v131_paper_measurement_table.csv"),
    },
}
manifest_path = result_dir / "v131_local_measurement_manifest.json"
manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True))
print(json.dumps(manifest, indent=2, sort_keys=True))
print(f"wrote {manifest_path}")
PY

