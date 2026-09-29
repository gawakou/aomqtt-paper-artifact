#!/usr/bin/env bash
set -euo pipefail

RUN_ID="${RUN_ID:-run-v110-trust-scenarios-001}"
RESULT_DIR="results/${RUN_ID}"
SUMMARY_JSON="${RESULT_DIR}/v110_trust_scenario_summary.json"
OUT_CSV="${RESULT_DIR}/v110_release_table.csv"

if [[ ! -f "${SUMMARY_JSON}" ]]; then
  echo "missing ${SUMMARY_JSON}" >&2
  echo "run: RUN_ID=${RUN_ID} ./experiments/run_v110_trust_scenarios.sh" >&2
  exit 1
fi

python - <<'PY'
import csv
import json
import os
from pathlib import Path

run_id = os.environ.get("RUN_ID", "run-v110-trust-scenarios-001")
result_dir = Path("results") / run_id
summary_path = result_dir / "v110_trust_scenario_summary.json"
out_csv = result_dir / "v110_release_table.csv"

summary = json.loads(summary_path.read_text(encoding="utf-8"))
reason_counts = summary.get("reason_counts", {})

rows = []
rows.append({"category": "aggregate", "name": "accepted", "count": summary.get("accepted", 0)})
rows.append({"category": "aggregate", "name": "rejected", "count": summary.get("rejected", 0)})
rows.append({"category": "aggregate", "name": "total", "count": summary.get("total", 0)})

for reason_code in sorted(reason_counts):
    rows.append({"category": "reason_code", "name": reason_code, "count": reason_counts[reason_code]})

with out_csv.open("w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=["category", "name", "count"])
    writer.writeheader()
    writer.writerows(rows)

print(f"wrote {out_csv}")
PY

cat "${OUT_CSV}"
