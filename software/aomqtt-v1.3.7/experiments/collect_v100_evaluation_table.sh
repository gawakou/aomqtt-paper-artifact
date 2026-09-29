#!/usr/bin/env bash
# Collect AOMQTT v1.0.0 evaluation summaries.
#
# Usage:
#   RUN_ID=run-v100-final ./experiments/collect_v100_evaluation_table.sh
#
# This script creates derived CSV/JSON summaries under:
#   results/<RUN_ID>/derived/
#
# It is designed to be tolerant of partially available raw files. If expected
# raw files are missing, it still creates empty summary files with headers so
# downstream paper-ready scripts can run reproducibly.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_ID="${RUN_ID:-run-v100-final}"
RESULTS_DIR="${RESULTS_DIR:-${ROOT_DIR}/results/${RUN_ID}}"

mkdir -p "${RESULTS_DIR}/derived"

python - <<'PY'
from __future__ import annotations

import csv
import json
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

root_dir = Path(os.environ.get("ROOT_DIR", ".")).resolve()
run_id = os.environ.get("RUN_ID", "run-v100-final")
results_dir = Path(os.environ.get("RESULTS_DIR", root_dir / "results" / run_id)).resolve()
derived_dir = results_dir / "derived"
derived_dir.mkdir(parents=True, exist_ok=True)


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, fieldnames: list[str], rows: Iterable[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})


def find_csvs(patterns: list[str]) -> list[Path]:
    candidates: list[Path] = []
    search_roots = [results_dir]

    # Scenario-specific runs created by run_all_v100_scenarios.sh.
    parent_results = results_dir.parent
    for suffix in ("-static", "-observation", "-rejected"):
        scenario_dir = parent_results / f"{run_id}{suffix}"
        if scenario_dir.exists():
            search_roots.append(scenario_dir)

    for search_root in search_roots:
        for pattern in patterns:
            candidates.extend(search_root.rglob(pattern))

    # Keep stable order and remove duplicates.
    seen = set()
    unique = []
    for path in sorted(candidates):
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(path)
    return unique


def collect_rows(patterns: list[str]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for path in find_csvs(patterns):
        for row in read_csv(path):
            row.setdefault("_source_file", str(path))
            rows.append(row)
    return rows


def first_present(row: dict[str, str], keys: list[str], default: str = "") -> str:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return default


def normalize_status(value: str, default: str = "unknown") -> str:
    value = (value or "").strip()
    return value if value else default


ack_rows = collect_rows([
    "controller_ack_log.csv",
    "*ack*log*.csv",
    "*ack*summary*.csv",
])

status_rows = collect_rows([
    "controller_status_log.csv",
    "*status*log*.csv",
    "*status*summary*.csv",
])

deployment_rows = collect_rows([
    "controller_deployment_events.csv",
    "*deployment*events*.csv",
    "deployment_summary.csv",
])

policy_rows = collect_rows([
    "policy_comparison_summary.csv",
    "*policy*comparison*.csv",
])

# ACK status summary.
ack_counter: Counter[str] = Counter()
for row in ack_rows:
    status = first_present(row, ["ack_status", "status", "result"], "unknown")
    ack_counter[normalize_status(status)] += 1

ack_total = sum(ack_counter.values())
ack_summary_rows = [
    {
        "run_id": run_id,
        "scenario": "all",
        "ack_status": status,
        "count": count,
        "ratio": f"{(count / ack_total):.6f}" if ack_total else "0.000000",
    }
    for status, count in sorted(ack_counter.items())
]

write_csv(
    derived_dir / "ack_status_summary.csv",
    ["run_id", "scenario", "ack_status", "count", "ratio"],
    ack_summary_rows,
)

# Reason code summary from ACK and status rows.
reason_counter: Counter[str] = Counter()
for row in ack_rows + status_rows:
    reason = first_present(row, ["reason_code", "reason", "error_code"], "unknown")
    reason_counter[normalize_status(reason)] += 1

reason_total = sum(reason_counter.values())
reason_summary_rows = [
    {
        "run_id": run_id,
        "scenario": "all",
        "reason_code": reason,
        "count": count,
        "ratio": f"{(count / reason_total):.6f}" if reason_total else "0.000000",
    }
    for reason, count in sorted(reason_counter.items())
]

write_csv(
    derived_dir / "reason_code_summary.csv",
    ["run_id", "scenario", "reason_code", "count", "ratio"],
    reason_summary_rows,
)

# Deployment summary.
accepted_count = sum(
    1 for row in ack_rows
    if normalize_status(first_present(row, ["ack_status", "status", "result"], "")).lower() == "accepted"
)
rejected_count = sum(
    1 for row in ack_rows
    if normalize_status(first_present(row, ["ack_status", "status", "result"], "")).lower() == "rejected"
)
expired_count = sum(
    1 for row in ack_rows
    if "expired" in normalize_status(first_present(row, ["ack_status", "status", "result", "reason_code"], "")).lower()
)
invalid_count = sum(
    1 for row in ack_rows
    if "invalid" in normalize_status(first_present(row, ["ack_status", "status", "result", "reason_code"], "")).lower()
)
applied_count = sum(
    1 for row in status_rows
    if normalize_status(first_present(row, ["apply_status", "status", "result"], "")).lower() == "applied"
)
failed_count = sum(
    1 for row in status_rows
    if normalize_status(first_present(row, ["apply_status", "status", "result"], "")).lower() == "failed"
)
timeout_count = sum(
    1 for row in status_rows
    if normalize_status(first_present(row, ["apply_status", "status", "result", "reason_code"], "")).lower() == "timeout"
)

target_clients = max(
    len({
        first_present(row, ["client_id", "client", "node_id"], "")
        for row in ack_rows + status_rows
        if first_present(row, ["client_id", "client", "node_id"], "")
    }),
    0,
)

ack_total = len(ack_rows)
status_total = len(status_rows)

deployment_summary_row = {
    "run_id": run_id,
    "scenario": "all",
    "group_id": first_present(ack_rows[0], ["group_id"], "") if ack_rows else "",
    "policy_id": first_present(ack_rows[0], ["policy_id"], "") if ack_rows else "",
    "sequence_no": first_present(ack_rows[0], ["sequence_no"], "") if ack_rows else "",
    "target_clients": target_clients,
    "accepted_count": accepted_count,
    "rejected_count": rejected_count,
    "expired_count": expired_count,
    "invalid_count": invalid_count,
    "applied_count": applied_count,
    "failed_count": failed_count,
    "timeout_count": timeout_count,
    "accept_rate": f"{(accepted_count / ack_total):.6f}" if ack_total else "0.000000",
    "apply_rate": f"{(applied_count / status_total):.6f}" if status_total else "0.000000",
    "reject_rate": f"{(rejected_count / ack_total):.6f}" if ack_total else "0.000000",
    "timeout_rate": f"{(timeout_count / status_total):.6f}" if status_total else "0.000000",
}

deployment_fields = [
    "run_id",
    "scenario",
    "group_id",
    "policy_id",
    "sequence_no",
    "target_clients",
    "accepted_count",
    "rejected_count",
    "expired_count",
    "invalid_count",
    "applied_count",
    "failed_count",
    "timeout_count",
    "accept_rate",
    "apply_rate",
    "reject_rate",
    "timeout_rate",
]

write_csv(
    derived_dir / "deployment_summary.csv",
    deployment_fields,
    [deployment_summary_row],
)

(derived_dir / "deployment_summary.json").write_text(
    json.dumps([deployment_summary_row], indent=2, ensure_ascii=False) + "\n",
    encoding="utf-8",
)

# Policy comparison summary.
policy_fields = [
    "run_id",
    "scenario",
    "policy_id",
    "token_mode",
    "padding_mode",
    "rotation_enabled",
    "publish_count",
    "receive_count",
    "duplicate_count",
    "loss_count",
    "success_rate",
    "delivery_rate",
    "duplicate_rate",
    "avg_publish_complete_ms",
    "p95_publish_complete_ms",
    "avg_padding_added_bytes",
    "avg_encrypted_bytes",
]

normalized_policy_rows: list[dict[str, object]] = []
for row in policy_rows:
    normalized = {field: row.get(field, "") for field in policy_fields}
    normalized["run_id"] = normalized.get("run_id") or run_id
    normalized["scenario"] = normalized.get("scenario") or "all"
    normalized_policy_rows.append(normalized)

write_csv(
    derived_dir / "policy_comparison_summary.csv",
    policy_fields,
    normalized_policy_rows,
)

print(f"[OK] Wrote {derived_dir / 'ack_status_summary.csv'}")
print(f"[OK] Wrote {derived_dir / 'reason_code_summary.csv'}")
print(f"[OK] Wrote {derived_dir / 'deployment_summary.csv'}")
print(f"[OK] Wrote {derived_dir / 'deployment_summary.json'}")
print(f"[OK] Wrote {derived_dir / 'policy_comparison_summary.csv'}")
PY

echo "[OK] v1.0.0 evaluation tables collected under ${RESULTS_DIR}/derived"
