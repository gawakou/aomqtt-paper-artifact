#!/usr/bin/env python3
"""Collect v1.3.1 unified local measurement CSV into release and paper tables."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open() as f:
        return list(csv.DictReader(f))


def to_float(value: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def collect_release_rows(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    release_rows: list[dict[str, Any]] = [
        {"category": "aggregate", "name": "scenario_count", "value": len(rows)},
        {"category": "aggregate", "name": "total_logical_messages", "value": int(sum(to_float(r.get("logical_messages", "")) for r in rows))},
        {"category": "aggregate", "name": "total_mqtt_messages", "value": int(sum(to_float(r.get("mqtt_messages", "")) for r in rows))},
        {"category": "aggregate", "name": "total_success_messages", "value": int(sum(to_float(r.get("success_messages", "")) for r in rows))},
        {"category": "aggregate", "name": "total_failed_messages", "value": int(sum(to_float(r.get("failed_messages", "")) for r in rows))},
        {"category": "aggregate", "name": "total_duplicates", "value": int(sum(to_float(r.get("duplicates", "")) for r in rows))},
        {"category": "control_plane", "name": "total_control_accepted", "value": int(sum(to_float(r.get("control_accepted", "")) for r in rows))},
        {"category": "control_plane", "name": "total_control_rejected", "value": int(sum(to_float(r.get("control_rejected", "")) for r in rows))},
        {"category": "transparency_log", "name": "total_transparency_entries", "value": int(sum(to_float(r.get("transparency_entries", "")) for r in rows))},
        {"category": "transparency_log", "name": "total_transparency_verified_entries", "value": int(sum(to_float(r.get("transparency_verified_entries", "")) for r in rows))},
    ]

    for row in rows:
        release_rows.append(
            {
                "category": "scenario",
                "name": row.get("scenario_id", ""),
                "value": row.get("status", ""),
            }
        )
    return release_rows


def collect_paper_rows(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    paper_rows: list[dict[str, Any]] = []
    for row in rows:
        paper_rows.append(
            {
                "scenario_id": row.get("scenario_id", ""),
                "logical_messages": row.get("logical_messages", ""),
                "mqtt_messages": row.get("mqtt_messages", ""),
                "success_messages": row.get("success_messages", ""),
                "failed_messages": row.get("failed_messages", ""),
                "duplicates": row.get("duplicates", ""),
                "delivery_latency_ms_p95": row.get("delivery_latency_ms_p95", ""),
                "publish_complete_ms_p95": row.get("publish_complete_ms_p95", ""),
                "payload_encrypted_bytes_avg": row.get("payload_encrypted_bytes_avg", ""),
                "control_accepted": row.get("control_accepted", ""),
                "control_rejected": row.get("control_rejected", ""),
                "transparency_verified_entries": row.get("transparency_verified_entries", ""),
                "status": row.get("status", ""),
            }
        )
    return paper_rows


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("")
        return
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_json(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"rows": rows}, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result-dir", default="results/run-v131-local-measurements-001")
    args = parser.parse_args(argv)

    result_dir = Path(args.result_dir)
    unified_csv = result_dir / "unified_measurements.csv"
    if not unified_csv.exists():
        raise SystemExit(f"missing {unified_csv}; run experiments/run_v131_local_measurements.py first")

    rows = read_rows(unified_csv)
    release_rows = collect_release_rows(rows)
    paper_rows = collect_paper_rows(rows)

    write_csv(release_rows, result_dir / "v131_release_table.csv")
    write_json(release_rows, result_dir / "v131_release_table.json")
    write_csv(paper_rows, result_dir / "v131_paper_measurement_table.csv")
    write_json(paper_rows, result_dir / "v131_paper_measurement_table.json")

    print(f"wrote {result_dir / 'v131_release_table.csv'}")
    print(f"wrote {result_dir / 'v131_paper_measurement_table.csv'}")
    with (result_dir / "v131_release_table.csv").open() as f:
        print(f.read(), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

