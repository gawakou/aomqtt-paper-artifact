#!/usr/bin/env bash
set -euo pipefail

RUN_ID="${RUN_ID:-run-v120-multisig-transparency-001}"
RESULT_DIR="results/${RUN_ID}"
SUMMARY_JSON="${RESULT_DIR}/v120_multisig_transparency_summary.json"
OUT_CSV="${RESULT_DIR}/v120_release_table.csv"

if [ ! -f "${SUMMARY_JSON}" ]; then
  echo "missing ${SUMMARY_JSON}" >&2
  echo "run: RUN_ID=${RUN_ID} ./experiments/run_v120_multisig_transparency_scenarios.sh" >&2
  exit 1
fi

python - <<PY
import csv
import json
from pathlib import Path

summary_path = Path("${SUMMARY_JSON}")
out_csv = Path("${OUT_CSV}")

with summary_path.open() as f:
    data = json.load(f)

rows = [
    ["category", "name", "count"],
    ["aggregate", "accepted", data.get("accepted", 0)],
    ["aggregate", "rejected", data.get("rejected", 0)],
    ["aggregate", "total", data.get("total", 0)],
]

for reason, count in sorted(data.get("reason_counts", {}).items()):
    rows.append(["reason_code", reason, count])

tlog = data.get("transparency_log", {})
rows.append(["transparency_log", "accepted", str(tlog.get("accepted"))])
rows.append(["transparency_log", "verified_entries", tlog.get("verified_entries", 0)])
rows.append(["transparency_log", "reason_code", tlog.get("reason_code", "")])

out_csv.parent.mkdir(parents=True, exist_ok=True)
with out_csv.open("w", newline="") as f:
    writer = csv.writer(f)
    writer.writerows(rows)

print(f"wrote {out_csv}")
with out_csv.open() as f:
    print(f.read(), end="")
PY
