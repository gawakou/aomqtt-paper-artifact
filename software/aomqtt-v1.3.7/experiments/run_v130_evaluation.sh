#!/usr/bin/env bash
set -euo pipefail

RUN_ID="${RUN_ID:-run-v130-large-scale-evaluation-001}"
RESULT_DIR="results/${RUN_ID}"

echo "[v1.3.0] running tests"
python -m pytest -q

echo "[v1.3.0] generating large-scale and safety scenario plan"
python experiments/run_v130_large_scale_scenarios.py \
  --out-dir "${RESULT_DIR}"

echo "[v1.3.0] collecting evaluation table"
python experiments/collect_v130_evaluation_table.py \
  --result-dir "${RESULT_DIR}"

python - <<PY
import json
from pathlib import Path

result_dir = Path("${RESULT_DIR}")
manifest = {
    "run_id": "${RUN_ID}",
    "release": "v1.3.0",
    "artifacts": {
        "large_scale_scenario_plan_csv": str(result_dir / "large_scale_scenario_plan.csv"),
        "large_scale_scenario_plan_json": str(result_dir / "large_scale_scenario_plan.json"),
        "environment_safety_matrix_csv": str(result_dir / "environment_safety_matrix.csv"),
        "environment_safety_matrix_json": str(result_dir / "environment_safety_matrix.json"),
        "v130_large_scale_summary_json": str(result_dir / "v130_large_scale_summary.json"),
        "v130_release_table_csv": str(result_dir / "v130_release_table.csv"),
        "v130_release_table_json": str(result_dir / "v130_release_table.json"),
    },
    "safety_policy": "DoS-like and high-rate workloads are limited to local or explicitly authorized environments. Public-broker evaluation is limited to low-rate compatibility probing.",
}
manifest_path = result_dir / "v130_evaluation_manifest.json"
manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True))
print(json.dumps(manifest, indent=2, sort_keys=True))
print(f"wrote {manifest_path}")
PY

