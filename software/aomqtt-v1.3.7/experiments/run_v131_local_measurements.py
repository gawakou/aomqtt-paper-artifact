#!/usr/bin/env python3
"""v1.3.1 local broker measurement runner.

Modes:

- plan: generate scenario plan only.
- sample: generate deterministic sample measurements and unified CSV.
- execute-plain: run only the direct plain MQTT local measurement.
- collect: collect existing summary JSON files into unified CSV.

The sample mode is intended for reproducibility tests.  Actual MQTT measurement
requires a local or explicitly authorized broker.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from v131_measurement_schema import UNIFIED_MEASUREMENT_FIELDS, empty_unified_row, scenario_dicts


def write_csv(rows: list[dict[str, Any]], path: Path, fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        fieldnames = list(rows[0].keys()) if rows else []
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_json(data: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True))


def generate_plan(out_dir: Path) -> list[dict[str, Any]]:
    rows = scenario_dicts()
    write_csv(rows, out_dir / "local_measurement_scenario_plan.csv")
    write_json({"rows": rows}, out_dir / "local_measurement_scenario_plan.json")
    return rows


def sample_unified_rows(run_id: str, broker: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    def row(**kwargs: Any) -> dict[str, Any]:
        base = {field: "" for field in UNIFIED_MEASUREMENT_FIELDS}
        base.update(kwargs)
        return base

    rows.append(
        row(
            run_id=run_id,
            scenario_id="plain_mqtt_baseline",
            scenario_type="plain_mqtt",
            environment="local_broker",
            broker=broker,
            qos=1,
            logical_messages=6000,
            mqtt_messages=6000,
            success_messages=6000,
            failed_messages=0,
            duplicates=0,
            missing_messages=0,
            publish_complete_ms_avg=0.10,
            publish_complete_ms_p50=0.09,
            publish_complete_ms_p95=0.16,
            publish_complete_ms_p99=0.20,
            delivery_latency_ms_avg=0.20,
            delivery_latency_ms_p50=0.18,
            delivery_latency_ms_p95=0.35,
            delivery_latency_ms_p99=0.50,
            payload_plain_bytes_avg=72,
            status="sample",
            notes="deterministic sample row; replace with execute-mode measurement for paper results",
        )
    )
    rows.append(
        row(
            run_id=run_id,
            scenario_id="aomqtt_basic",
            scenario_type="aomqtt_data_plane",
            environment="local_broker",
            broker=broker,
            qos=1,
            logical_messages=6000,
            mqtt_messages=6000,
            success_messages=6000,
            failed_messages=0,
            duplicates=0,
            missing_messages=0,
            publish_complete_ms_avg=0.28,
            publish_complete_ms_p50=0.26,
            publish_complete_ms_p95=0.39,
            publish_complete_ms_p99=0.45,
            delivery_latency_ms_avg=0.37,
            delivery_latency_ms_p50=0.35,
            delivery_latency_ms_p95=0.57,
            delivery_latency_ms_p99=0.61,
            payload_plain_bytes_avg=72,
            payload_encrypted_bytes_avg=209,
            status="sample",
            notes="deterministic sample row; based on local-run schema",
        )
    )
    rows.append(
        row(
            run_id=run_id,
            scenario_id="aomqtt_padding512",
            scenario_type="aomqtt_data_plane",
            environment="local_broker",
            broker=broker,
            qos=1,
            logical_messages=6000,
            mqtt_messages=6000,
            success_messages=6000,
            failed_messages=0,
            duplicates=0,
            missing_messages=0,
            delivery_latency_ms_avg=0.52,
            delivery_latency_ms_p50=0.51,
            delivery_latency_ms_p95=0.72,
            delivery_latency_ms_p99=0.76,
            payload_plain_bytes_avg=72,
            payload_padded_bytes_avg=512,
            payload_encrypted_bytes_avg=802,
            padding_added_bytes_avg=440,
            status="sample",
            notes="deterministic sample row; fixed padding schema",
        )
    )
    rows.append(
        row(
            run_id=run_id,
            scenario_id="aomqtt_padding512_rotation30_overlap5",
            scenario_type="aomqtt_data_plane",
            environment="local_broker",
            broker=broker,
            qos=1,
            logical_messages=6000,
            mqtt_messages=7003,
            success_messages=6000,
            failed_messages=0,
            duplicates=1003,
            missing_messages=0,
            publish_complete_ms_avg=0.28,
            publish_complete_ms_p50=0.26,
            publish_complete_ms_p95=0.38,
            publish_complete_ms_p99=0.41,
            payload_plain_bytes_avg=72,
            payload_padded_bytes_avg=512,
            payload_encrypted_bytes_avg=802,
            padding_added_bytes_avg=440,
            rotation_overlap_duplicates=1003,
            status="sample",
            notes="deterministic sample row; token overlap duplicate accounting",
        )
    )
    rows.append(
        row(
            run_id=run_id,
            scenario_id="v120_multisig_control_plane",
            scenario_type="control_plane",
            environment="local_process",
            broker="none",
            qos=0,
            logical_messages=6,
            mqtt_messages=0,
            success_messages=1,
            failed_messages=5,
            control_accepted=1,
            control_rejected=5,
            transparency_entries=6,
            transparency_verified_entries=6,
            status="sample",
            notes="deterministic sample row; v1.2.0 control-plane scenario normalization",
        )
    )
    return rows


def write_unified(rows: list[dict[str, Any]], out_dir: Path) -> None:
    write_csv(rows, out_dir / "unified_measurements.csv", UNIFIED_MEASUREMENT_FIELDS)
    write_json({"rows": rows}, out_dir / "unified_measurements.json")


def collect_summary_jsons(run_id: str, out_dir: Path, broker: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted((out_dir / "summaries").glob("*.json")):
        data = json.loads(path.read_text())
        row = {field: "" for field in UNIFIED_MEASUREMENT_FIELDS}
        for field in UNIFIED_MEASUREMENT_FIELDS:
            if field in data:
                row[field] = data[field]
        row.setdefault("run_id", run_id)
        if not row["run_id"]:
            row["run_id"] = run_id
        if not row["broker"]:
            row["broker"] = broker
        rows.append(row)
    return rows


def write_manifest(run_id: str, out_dir: Path, mode: str) -> None:
    manifest = {
        "run_id": run_id,
        "release": "v1.3.1",
        "mode": mode,
        "artifacts": {
            "local_measurement_scenario_plan_csv": str(out_dir / "local_measurement_scenario_plan.csv"),
            "local_measurement_scenario_plan_json": str(out_dir / "local_measurement_scenario_plan.json"),
            "unified_measurements_csv": str(out_dir / "unified_measurements.csv"),
            "unified_measurements_json": str(out_dir / "unified_measurements.json"),
            "v131_measurement_summary_json": str(out_dir / "v131_measurement_summary.json"),
        },
    }
    write_json(manifest, out_dir / "v131_measurement_manifest.json")


def summarize_unified(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def num(row: dict[str, Any], field: str) -> float:
        value = row.get(field, "")
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    return {
        "scenario_count": len(rows),
        "scenario_ids": [row.get("scenario_id", "") for row in rows],
        "total_logical_messages": int(sum(num(row, "logical_messages") for row in rows)),
        "total_mqtt_messages": int(sum(num(row, "mqtt_messages") for row in rows)),
        "total_success_messages": int(sum(num(row, "success_messages") for row in rows)),
        "total_failed_messages": int(sum(num(row, "failed_messages") for row in rows)),
        "total_duplicates": int(sum(num(row, "duplicates") for row in rows)),
        "total_control_accepted": int(sum(num(row, "control_accepted") for row in rows)),
        "total_control_rejected": int(sum(num(row, "control_rejected") for row in rows)),
        "total_transparency_entries": int(sum(num(row, "transparency_entries") for row in rows)),
        "total_transparency_verified_entries": int(sum(num(row, "transparency_verified_entries") for row in rows)),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default="run-v131-local-measurements-001")
    parser.add_argument("--out-dir", default="")
    parser.add_argument("--broker", default="localhost:1883")
    parser.add_argument("--mode", choices=["plan", "sample", "collect"], default="sample")
    args = parser.parse_args(argv)

    out_dir = Path(args.out_dir or f"results/{args.run_id}")
    generate_plan(out_dir)

    rows: list[dict[str, Any]]
    if args.mode == "plan":
        rows = [
            empty_unified_row(args.run_id, s["scenario_id"], s["scenario_type"], s["environment"], args.broker, int(s["qos"]))
            for s in scenario_dicts()
        ]
    elif args.mode == "sample":
        rows = sample_unified_rows(args.run_id, args.broker)
    else:
        rows = collect_summary_jsons(args.run_id, out_dir, args.broker)

    write_unified(rows, out_dir)
    summary = summarize_unified(rows)
    write_json(summary, out_dir / "v131_measurement_summary.json")
    write_manifest(args.run_id, out_dir, args.mode)

    print(json.dumps(summary, indent=2, sort_keys=True))
    print(f"wrote v1.3.1 local measurement artifacts under {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

