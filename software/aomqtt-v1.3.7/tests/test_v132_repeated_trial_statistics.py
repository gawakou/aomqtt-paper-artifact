from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path


FIELDS = [
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


def write_trial(path: Path, delivery: float, publish: float, mqtt_messages: int = 6000, duplicates: int = 0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "scenario_id": "aomqtt_basic",
        "logical_messages": 6000,
        "mqtt_messages": mqtt_messages,
        "success_messages": 6000,
        "failed_messages": 0,
        "duplicates": duplicates,
        "delivery_latency_ms_p95": delivery,
        "publish_complete_ms_p95": publish,
        "payload_plain_bytes_avg": 72,
        "payload_encrypted_bytes_avg": 216,
        "rotation_overlap_duplicates": 0,
        "status": "measured",
    }
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerow(row)


def test_collect_v132_repeated_trial_statistics(tmp_path: Path) -> None:
    t1 = tmp_path / "trial-01" / "v131_local_comparison_table.csv"
    t2 = tmp_path / "trial-02" / "v131_local_comparison_table.csv"
    out_dir = tmp_path / "stats"

    write_trial(t1, delivery=1.0, publish=2.0)
    write_trial(t2, delivery=3.0, publish=4.0)

    subprocess.run(
        [
            sys.executable,
            "experiments/collect_v132_repeated_trial_statistics.py",
            "--inputs",
            str(t1),
            str(t2),
            "--out-dir",
            str(out_dir),
        ],
        check=True,
    )

    stats_csv = out_dir / "repeated_trial_statistics.csv"
    paper_csv = out_dir / "v132_paper_statistics_table.csv"
    summary_json = out_dir / "v132_repeated_trial_summary.json"

    assert stats_csv.exists()
    assert paper_csv.exists()
    assert summary_json.exists()

    stats = list(csv.DictReader(stats_csv.open()))
    delivery = [
        row for row in stats
        if row["scenario_id"] == "aomqtt_basic" and row["metric"] == "delivery_latency_ms_p95"
    ][0]
    assert delivery["n"] == "2"
    assert float(delivery["mean"]) == 2.0
    assert float(delivery["stddev"]) > 0.0

    paper = list(csv.DictReader(paper_csv.open()))
    assert paper[0]["scenario_id"] == "aomqtt_basic"
    assert float(paper[0]["delivery_p95_mean_ms"]) == 2.0
    assert float(paper[0]["publish_p95_mean_ms"]) == 3.0

    summary = json.loads(summary_json.read_text())
    assert summary["trial_file_count"] == 2
    assert summary["scenario_count"] == 1


def test_generate_v132_sample_trials_and_collect(tmp_path: Path) -> None:
    trial_dir = tmp_path / "trials"
    out_dir = tmp_path / "stats"

    subprocess.run(
        [
            sys.executable,
            "experiments/generate_v132_sample_trials.py",
            "--out-dir",
            str(trial_dir),
            "--trial-count",
            "5",
        ],
        check=True,
    )

    trial_files = sorted(trial_dir.glob("trial-*/v131_local_comparison_table.csv"))
    assert len(trial_files) == 5

    subprocess.run(
        [
            sys.executable,
            "experiments/collect_v132_repeated_trial_statistics.py",
            "--inputs",
            *[str(p) for p in trial_files],
            "--out-dir",
            str(out_dir),
        ],
        check=True,
    )

    paper_rows = list(csv.DictReader((out_dir / "v132_paper_statistics_table.csv").open()))
    scenario_ids = {row["scenario_id"] for row in paper_rows}
    assert "plain_mqtt_baseline" in scenario_ids
    assert "aomqtt_basic" in scenario_ids
    assert "aomqtt_padding512" in scenario_ids
    assert "aomqtt_padding512_rotation30_overlap5" in scenario_ids

    rotation = [row for row in paper_rows if row["scenario_id"] == "aomqtt_padding512_rotation30_overlap5"][0]
    assert round(float(rotation["mqtt_expansion_ratio_mean"]), 3) == 1.647
    assert round(float(rotation["duplicate_ratio_vs_logical_mean"]), 3) == 0.532

