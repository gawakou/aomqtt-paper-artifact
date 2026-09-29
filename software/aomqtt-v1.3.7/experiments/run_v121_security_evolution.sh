#!/usr/bin/env bash
set -euo pipefail

RUN_ID="${RUN_ID:-run-v121-evaluation-reproducibility-001}"
V110_RUN_ID="${V110_RUN_ID:-${RUN_ID}-v110}"
V120_RUN_ID="${V120_RUN_ID:-${RUN_ID}-v120}"
RESULT_DIR="results/${RUN_ID}"

mkdir -p "${RESULT_DIR}"

echo "[v1.2.1] running tests"
TEST_OUTPUT="$(python -m pytest -q)"
printf '%s\n' "${TEST_OUTPUT}"
TEST_COUNT="$(printf '%s
' "${TEST_OUTPUT}" | grep -Eo '[0-9]+ passed' | tail -1 | awk '{print $1}')"
if [ -z "${TEST_COUNT}" ]; then
  TEST_COUNT="0"
fi

echo "[v1.2.1] running v1.1.0 trust scenario: ${V110_RUN_ID}"
RUN_ID="${V110_RUN_ID}" ./experiments/run_v110_trust_scenarios.sh

echo "[v1.2.1] running v1.2.0 multisig transparency scenario: ${V120_RUN_ID}"
RUN_ID="${V120_RUN_ID}" ./experiments/run_v120_multisig_transparency_scenarios.sh

V110_SUMMARY="results/${V110_RUN_ID}/v110_trust_scenario_summary.json"
V120_SUMMARY="results/${V120_RUN_ID}/v120_multisig_transparency_summary.json"

python experiments/collect_v121_security_evolution_table.py \
  --out-dir "${RESULT_DIR}"

python experiments/collect_v121_policy_decision_matrix.py \
  --v110-summary "${V110_SUMMARY}" \
  --v120-summary "${V120_SUMMARY}" \
  --out-dir "${RESULT_DIR}"

python experiments/collect_v121_paper_summary_table.py \
  --v110-summary "${V110_SUMMARY}" \
  --v120-summary "${V120_SUMMARY}" \
  --test-count "${TEST_COUNT:-0}" \
  --out-dir "${RESULT_DIR}"

python - <<PY
import json
from pathlib import Path

result_dir = Path("${RESULT_DIR}")
manifest = {
    "run_id": "${RUN_ID}",
    "v110_run_id": "${V110_RUN_ID}",
    "v120_run_id": "${V120_RUN_ID}",
    "artifacts": {
        "security_evolution_table_csv": str(result_dir / "security_evolution_table.csv"),
        "policy_decision_matrix_csv": str(result_dir / "policy_decision_matrix.csv"),
        "paper_summary_table_csv": str(result_dir / "paper_summary_table.csv"),
        "security_evolution_table_json": str(result_dir / "security_evolution_table.json"),
        "policy_decision_matrix_json": str(result_dir / "policy_decision_matrix.json"),
        "paper_summary_table_json": str(result_dir / "paper_summary_table.json"),
    },
}
manifest_path = result_dir / "v121_evaluation_manifest.json"
manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True))
print(json.dumps(manifest, indent=2, sort_keys=True))
print(f"wrote {manifest_path}")
PY

