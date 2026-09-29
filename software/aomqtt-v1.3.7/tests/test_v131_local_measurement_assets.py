from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path


def test_v131_sample_measurement_outputs_unified_schema(tmp_path: Path) -> None:
    out_dir = tmp_path / "v131"
    subprocess.run(
        [
            sys.executable,
            "experiments/run_v131_local_measurements.py",
            "--run-id",
            "run-test-v131",
            "--out-dir",
            str(out_dir),
            "--mode",
            "sample",
        ],
        check=True,
    )

    unified_csv = out_dir / "unified_measurements.csv"
    assert unified_csv.exists()

    rows = list(csv.DictReader(unified_csv.open()))
    assert len(rows) == 5

    scenario_ids = {row["scenario_id"] for row in rows}
    assert "plain_mqtt_baseline" in scenario_ids
    assert "aomqtt_basic" in scenario_ids
    assert "aomqtt_padding512" in scenario_ids
    assert "aomqtt_padding512_rotation30_overlap5" in scenario_ids
    assert "v120_multisig_control_plane" in scenario_ids

    rotation = [row for row in rows if row["scenario_id"] == "aomqtt_padding512_rotation30_overlap5"][0]
    assert rotation["logical_messages"] == "6000"
    assert rotation["mqtt_messages"] == "7003"
    assert rotation["rotation_overlap_duplicates"] == "1003"

    summary = json.loads((out_dir / "v131_measurement_summary.json").read_text())
    assert summary["scenario_count"] == 5
    assert summary["total_logical_messages"] == 24006
    assert summary["total_control_accepted"] == 1
    assert summary["total_control_rejected"] == 5
    assert summary["total_transparency_verified_entries"] == 6


def test_v131_measurement_table_collector_generates_release_and_paper_tables(tmp_path: Path) -> None:
    out_dir = tmp_path / "v131"
    subprocess.run(
        [
            sys.executable,
            "experiments/run_v131_local_measurements.py",
            "--run-id",
            "run-test-v131",
            "--out-dir",
            str(out_dir),
            "--mode",
            "sample",
        ],
        check=True,
    )
    subprocess.run(
        [
            sys.executable,
            "experiments/collect_v131_measurement_table.py",
            "--result-dir",
            str(out_dir),
        ],
        check=True,
    )

    release_csv = out_dir / "v131_release_table.csv"
    paper_csv = out_dir / "v131_paper_measurement_table.csv"
    assert release_csv.exists()
    assert paper_csv.exists()

    release_rows = list(csv.DictReader(release_csv.open()))
    names = {row["name"]: row["value"] for row in release_rows}
    assert names["scenario_count"] == "5"
    assert names["total_logical_messages"] == "24006"
    assert names["total_mqtt_messages"] == "25003"

    paper_rows = list(csv.DictReader(paper_csv.open()))
    assert len(paper_rows) == 5
    assert {row["scenario_id"] for row in paper_rows} >= {
        "plain_mqtt_baseline",
        "aomqtt_basic",
        "aomqtt_padding512",
        "aomqtt_padding512_rotation30_overlap5",
        "v120_multisig_control_plane",
    }


def test_v131_plan_mode_marks_rows_as_planned(tmp_path: Path) -> None:
    out_dir = tmp_path / "v131"
    subprocess.run(
        [
            sys.executable,
            "experiments/run_v131_local_measurements.py",
            "--run-id",
            "run-test-v131",
            "--out-dir",
            str(out_dir),
            "--mode",
            "plan",
        ],
        check=True,
    )

    rows = list(csv.DictReader((out_dir / "unified_measurements.csv").open()))
    assert len(rows) == 5
    assert all(row["status"] == "planned" for row in rows)

