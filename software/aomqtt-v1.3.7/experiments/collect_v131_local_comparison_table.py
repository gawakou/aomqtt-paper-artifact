#!/usr/bin/env python3
"""Collect multiple v1.3.1 unified measurement CSV files into one comparison table."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


DEFAULT_INPUTS = [
    "results/run-v131-plain-local-6000-001/unified_measurements.csv",
    "results/run-v131-aomqtt-basic-6000-001/unified_measurements.csv",
    "results/run-v131-aomqtt-padding512-6000-001/unified_measurements.csv",
    "results/run-v131-aomqtt-padding512-rotation30-overlap5-6000-001/unified_measurements.csv",
]


PAPER_FIELDS = [
    "scenario_id",
    "logical_messages",
    "mqtt_messages",
    "success_messages",
    "failed_messages",
    "duplicates",
    "delivery_latency_ms_p95",
    "publish_complete_ms_p95",
    "payload_plain_bytes_avg",
    "payload_encrypted_bytes_avg",
    "rotation_overlap_duplicates",
    "status",
]


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def write_csv(rows: list[dict[str, Any]], path: Path, fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_json(data: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True))


def to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def build_summary(rows: list[dict[str, str]]) -> dict[str, Any]:
    scenario_summaries = []
    for row in rows:
        logical = to_float(row.get("logical_messages"))
        mqtt = to_float(row.get("mqtt_messages"))
        success = to_float(row.get("success_messages"))
        duplicates = to_float(row.get("duplicates"))
        scenario_summaries.append(
            {
                "scenario_id": row.get("scenario_id", ""),
                "logical_messages": int(logical),
                "mqtt_messages": int(mqtt),
                "success_messages": int(success),
                "failed_messages": int(to_float(row.get("failed_messages"))),
                "duplicates": int(duplicates),
                "mqtt_expansion_ratio": mqtt / logical if logical else 0.0,
                "success_ratio": success / logical if logical else 0.0,
                "duplicate_ratio_vs_logical": duplicates / logical if logical else 0.0,
                "delivery_latency_ms_p95": to_float(row.get("delivery_latency_ms_p95")),
                "publish_complete_ms_p95": to_float(row.get("publish_complete_ms_p95")),
                "payload_encrypted_bytes_avg": to_float(row.get("payload_encrypted_bytes_avg")),
                "status": row.get("status", ""),
            }
        )

    return {
        "scenario_count": len(rows),
        "total_logical_messages": int(sum(to_float(row.get("logical_messages")) for row in rows)),
        "total_mqtt_messages": int(sum(to_float(row.get("mqtt_messages")) for row in rows)),
        "total_success_messages": int(sum(to_float(row.get("success_messages")) for row in rows)),
        "total_failed_messages": int(sum(to_float(row.get("failed_messages")) for row in rows)),
        "total_duplicates": int(sum(to_float(row.get("duplicates")) for row in rows)),
        "scenarios": scenario_summaries,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--inputs",
        nargs="*",
        default=DEFAULT_INPUTS,
        help="Input unified_measurements.csv files.",
    )
    parser.add_argument(
        "--out-dir",
        default="results/run-v131-local-comparison-6000-001",
        help="Output directory.",
    )
    args = parser.parse_args(argv)

    rows: list[dict[str, str]] = []
    full_fieldnames: list[str] | None = None

    missing: list[str] = []
    for item in args.inputs:
        path = Path(item)
        if not path.exists():
            missing.append(item)
            continue
        current = read_rows(path)
        if full_fieldnames is None and current:
            full_fieldnames = list(current[0].keys())
        rows.extend(current)

    if missing:
        raise SystemExit("missing input files:\n" + "\n".join(missing))
    if not rows:
        raise SystemExit("no measurement rows found")

    out_dir = Path(args.out_dir)
    full_fieldnames = full_fieldnames or list(rows[0].keys())

    write_csv(rows, out_dir / "unified_measurements.csv", full_fieldnames)

    paper_rows = [{k: row.get(k, "") for k in PAPER_FIELDS} for row in rows]
    write_csv(paper_rows, out_dir / "v131_local_comparison_table.csv", PAPER_FIELDS)

    summary = build_summary(rows)
    write_json(summary, out_dir / "v131_local_comparison_summary.json")

    manifest = {
        "release": "v1.3.1",
        "input_files": args.inputs,
        "artifacts": {
            "unified_measurements_csv": str(out_dir / "unified_measurements.csv"),
            "v131_local_comparison_table_csv": str(out_dir / "v131_local_comparison_table.csv"),
            "v131_local_comparison_summary_json": str(out_dir / "v131_local_comparison_summary.json"),
        },
    }
    write_json(manifest, out_dir / "v131_local_comparison_manifest.json")

    print(f"wrote {out_dir / 'v131_local_comparison_table.csv'}")
    print(f"wrote {out_dir / 'v131_local_comparison_summary.json'}")
    with (out_dir / "v131_local_comparison_table.csv").open() as f:
        print(f.read(), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

