from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def test_aomqtt_measurement_collector_generates_summary(tmp_path: Path) -> None:
    pub = tmp_path / "publisher_metrics.csv"
    sub = tmp_path / "subscriber_metrics.csv"
    summary = tmp_path / "summaries" / "aomqtt_basic.json"

    write_csv(
        pub,
        [
            {
                "logical_seq": 0,
                "success": 1,
                "publish_complete_ms": 0.2,
                "payload_plain_bytes": 72,
                "payload_encrypted_bytes": 209,
            },
            {
                "logical_seq": 1,
                "success": 1,
                "publish_complete_ms": 0.4,
                "payload_plain_bytes": 74,
                "payload_encrypted_bytes": 211,
            },
        ],
    )
    write_csv(
        sub,
        [
            {"logical_seq": 0, "decrypt_success": 1, "delivery_latency_ms": 0.5},
            {"logical_seq": 1, "decrypt_success": 1, "delivery_latency_ms": 0.7},
        ],
    )

    subprocess.run(
        [
            sys.executable,
            "experiments/collect_v131_aomqtt_measurement.py",
            "--run-id",
            "run-test",
            "--scenario-id",
            "aomqtt_basic",
            "--publisher-csv",
            str(pub),
            "--subscriber-csv",
            str(sub),
            "--summary-json",
            str(summary),
        ],
        check=True,
    )

    data = json.loads(summary.read_text())
    assert data["scenario_id"] == "aomqtt_basic"
    assert data["logical_messages"] == 2
    assert data["mqtt_messages"] == 2
    assert data["success_messages"] == 2
    assert data["failed_messages"] == 0
    assert data["payload_plain_bytes_avg"] == "73.0"
    assert data["payload_encrypted_bytes_avg"] == "210.0"
    assert data["publish_complete_ms_p95"] == "0.4"
    assert data["delivery_latency_ms_p95"] == "0.7"


def test_aomqtt_measurement_collector_accounts_rotation_duplicates(tmp_path: Path) -> None:
    pub = tmp_path / "publisher_metrics.csv"
    sub = tmp_path / "subscriber_metrics.csv"
    summary = tmp_path / "summaries" / "aomqtt_rotation.json"

    write_csv(
        pub,
        [
            {"logical_seq": 0, "success": 1, "publish_complete_ms": 0.2, "overlap_duplicate": 0},
            {"logical_seq": 1, "success": 1, "publish_complete_ms": 0.3, "overlap_duplicate": 0},
            {"logical_seq": 1, "success": 1, "publish_complete_ms": 0.4, "overlap_duplicate": 1},
        ],
    )
    write_csv(
        sub,
        [
            {"logical_seq": 0, "decrypt_success": 1, "delivery_latency_ms": 0.5},
            {"logical_seq": 1, "decrypt_success": 1, "delivery_latency_ms": 0.7},
            {"logical_seq": 1, "decrypt_success": 1, "delivery_latency_ms": 0.8},
        ],
    )

    subprocess.run(
        [
            sys.executable,
            "experiments/collect_v131_aomqtt_measurement.py",
            "--run-id",
            "run-test",
            "--scenario-id",
            "aomqtt_padding512_rotation30_overlap5",
            "--publisher-csv",
            str(pub),
            "--subscriber-csv",
            str(sub),
            "--summary-json",
            str(summary),
        ],
        check=True,
    )

    data = json.loads(summary.read_text())
    assert data["logical_messages"] == 2
    assert data["mqtt_messages"] == 3
    assert data["success_messages"] == 2
    assert data["duplicates"] == 1
    assert data["rotation_overlap_duplicates"] == 1

