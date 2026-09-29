from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path


def test_v130_large_scale_scenario_plan_is_generated(tmp_path: Path) -> None:
    out_dir = tmp_path / "v130"
    subprocess.run(
        [
            sys.executable,
            "experiments/run_v130_large_scale_scenarios.py",
            "--out-dir",
            str(out_dir),
        ],
        check=True,
    )

    plan_csv = out_dir / "large_scale_scenario_plan.csv"
    safety_csv = out_dir / "environment_safety_matrix.csv"
    summary_json = out_dir / "v130_large_scale_summary.json"

    assert plan_csv.exists()
    assert safety_csv.exists()
    assert summary_json.exists()

    rows = list(csv.DictReader(plan_csv.open()))
    assert len(rows) >= 8

    public_rows = [row for row in rows if row["environment"] == "public_broker_with_permission"]
    assert public_rows
    assert all(row["allowed_on_public_broker"] == "True" for row in public_rows)
    assert all(int(row["max_publish_rate_mps"]) <= 1 for row in public_rows)

    local_adversarial = [row for row in rows if row["category"] == "adversarial_control_plane"]
    assert local_adversarial
    assert all(row["allowed_on_public_broker"] == "False" for row in local_adversarial)

    summary = json.loads(summary_json.read_text())
    assert summary["public_broker_allowed_scenarios"] == 1
    assert summary["public_broker_disallowed_scenarios"] >= 1
    assert "DoS-like" in summary["safety_policy"]


def test_v130_release_table_is_collected(tmp_path: Path) -> None:
    out_dir = tmp_path / "v130"
    subprocess.run(
        [
            sys.executable,
            "experiments/run_v130_large_scale_scenarios.py",
            "--out-dir",
            str(out_dir),
        ],
        check=True,
    )
    subprocess.run(
        [
            sys.executable,
            "experiments/collect_v130_evaluation_table.py",
            "--result-dir",
            str(out_dir),
        ],
        check=True,
    )

    release_csv = out_dir / "v130_release_table.csv"
    assert release_csv.exists()

    rows = list(csv.DictReader(release_csv.open()))
    names = {row["name"]: row["value"] for row in rows}
    assert int(names["scenario_count"]) >= 8
    assert int(names["public_broker_allowed_scenarios"]) == 1
    assert int(names["public_broker_disallowed_scenarios"]) >= 1


def test_v130_safety_matrix_documents_public_broker_limits(tmp_path: Path) -> None:
    out_dir = tmp_path / "v130"
    subprocess.run(
        [
            sys.executable,
            "experiments/run_v130_large_scale_scenarios.py",
            "--out-dir",
            str(out_dir),
        ],
        check=True,
    )

    safety_rows = list(csv.DictReader((out_dir / "environment_safety_matrix.csv").open()))
    public = [row for row in safety_rows if row["environment"] == "public_broker"]
    assert public
    assert "low-rate compatibility probe only" in public[0]["allowed_workloads"]
    assert "DoS-like load" in public[0]["disallowed_workloads"]

