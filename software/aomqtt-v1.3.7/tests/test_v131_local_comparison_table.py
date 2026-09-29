from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path


FIELDNAMES = [
    "run_id",
    "scenario_id",
    "scenario_type",
    "environment",
    "broker",
    "qos",
    "logical_messages",
    "mqtt_messages",
    "success_messages",
    "failed_messages",
    "duplicates",
    "missing_messages",
    "publish_complete_ms_avg",
    "publish_complete_ms_p50",
    "publish_complete_ms_p95",
    "publish_complete_ms_p99",
    "delivery_latency_ms_avg",
    "delivery_latency_ms_p50",
    "delivery_latency_ms_p95",
    "delivery_latency_ms_p99",
    "payload_plain_bytes_avg",
    "payload_padded_bytes_avg",
    "payload_encrypted_bytes_avg",
    "padding_added_bytes_avg",
    "rotation_overlap_duplicates",
    "control_accepted",
    "control_rejected",
    "transparency_entries",
    "transparency_verified_entries",
    "status",
    "notes",
]


def write_unified(path: Path, row: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = {field: row.get(field, "") for field in FIELDNAMES}
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerow(normalized)


def test_collect_v131_local_comparison_table(tmp_path: Path) -> None:
    plain = tmp_path / "plain" / "unified_measurements.csv"
    basic = tmp_path / "basic" / "unified_measurements.csv"
    rotation = tmp_path / "rotation" / "unified_measurements.csv"
    out_dir = tmp_path / "comparison"

    write_unified(
        plain,
        {
            "run_id": "plain",
            "scenario_id": "plain_mqtt_baseline",
            "logical_messages": 6000,
            "mqtt_messages": 6000,
            "success_messages": 6000,
            "failed_messages": 0,
            "duplicates": 0,
            "delivery_latency_ms_p95": 1.2,
            "publish_complete_ms_p95": 1.3,
            "status": "measured",
        },
    )
    write_unified(
        basic,
        {
            "run_id": "basic",
            "scenario_id": "aomqtt_basic",
            "logical_messages": 6000,
            "mqtt_messages": 6000,
            "success_messages": 6000,
            "failed_messages": 0,
            "duplicates": 0,
            "delivery_latency_ms_p95": 1.3,
            "publish_complete_ms_p95": 1.2,
            "payload_encrypted_bytes_avg": 216,
            "status": "measured",
        },
    )
    write_unified(
        rotation,
        {
            "run_id": "rotation",
            "scenario_id": "aomqtt_padding512_rotation30_overlap5",
            "logical_messages": 6000,
            "mqtt_messages": 9880,
            "success_messages": 6000,
            "failed_messages": 0,
            "duplicates": 3192,
            "delivery_latency_ms_p95": 1.8,
            "publish_complete_ms_p95": 1.25,
            "payload_encrypted_bytes_avg": 802,
            "rotation_overlap_duplicates": 3880,
            "status": "measured",
        },
    )

    subprocess.run(
        [
            sys.executable,
            "experiments/collect_v131_local_comparison_table.py",
            "--inputs",
            str(plain),
            str(basic),
            str(rotation),
            "--out-dir",
            str(out_dir),
        ],
        check=True,
    )

    table = out_dir / "v131_local_comparison_table.csv"
    summary = out_dir / "v131_local_comparison_summary.json"
    assert table.exists()
    assert summary.exists()

    rows = list(csv.DictReader(table.open()))
    assert [row["scenario_id"] for row in rows] == [
        "plain_mqtt_baseline",
        "aomqtt_basic",
        "aomqtt_padding512_rotation30_overlap5",
    ]
    assert rows[-1]["rotation_overlap_duplicates"] == "3880"

    data = json.loads(summary.read_text())
    assert data["scenario_count"] == 3
    assert data["total_logical_messages"] == 18000
    assert data["total_mqtt_messages"] == 21880
    assert data["total_duplicates"] == 3192

    rotation_summary = [row for row in data["scenarios"] if row["scenario_id"] == "aomqtt_padding512_rotation30_overlap5"][0]
    assert round(rotation_summary["mqtt_expansion_ratio"], 3) == 1.647
    assert round(rotation_summary["duplicate_ratio_vs_logical"], 3) == 0.532

