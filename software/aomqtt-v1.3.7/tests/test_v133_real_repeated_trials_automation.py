from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_v133_local_trial_dry_run_generates_plan(tmp_path: Path) -> None:
    out_dir = tmp_path / "trial"
    subprocess.run(
        [
            sys.executable,
            "experiments/run_v133_real_local_trial.py",
            "--run-id",
            "run-test-v133-trial",
            "--out-dir",
            str(out_dir),
            "--count",
            "10",
            "--dry-run",
        ],
        check=True,
    )

    plan = json.loads((out_dir / "v133_trial_plan.json").read_text())
    assert plan["run_id"] == "run-test-v133-trial"
    assert plan["count"] == 10
    assert plan["broker"] == "localhost:1883"
    assert "plain_mqtt_baseline" in plan["scenarios"]
    assert "aomqtt_padding512_rotation30_overlap5" in plan["scenarios"]

    commands = [" ".join(step["command"]) for step in plan["steps"]]
    assert any("run_v131_plain_mqtt_measurement.py" in c for c in commands)
    assert any("subscriber_example.py" in c for c in commands)
    assert any("publisher_example.py" in c for c in commands)
    assert any("collect_v131_local_comparison_table.py" in c for c in commands)


def test_v133_repeated_trials_dry_run_generates_manifest(tmp_path: Path) -> None:
    out_dir = tmp_path / "repeated"
    subprocess.run(
        [
            sys.executable,
            "experiments/run_v133_real_repeated_trials.py",
            "--run-id",
            "run-test-v133-repeated",
            "--out-dir",
            str(out_dir),
            "--trial-count",
            "2",
            "--count",
            "10",
            "--dry-run",
        ],
        check=True,
    )

    manifest = json.loads((out_dir / "v133_repeated_trials_manifest.json").read_text())
    assert manifest["run_id"] == "run-test-v133-repeated"
    assert manifest["trial_count"] == 2
    assert manifest["mode"] == "dry-run"
    assert len(manifest["trial_commands"]) == 2

    assert (out_dir / "trials" / "trial-01" / "v133_trial_plan.json").exists()
    assert (out_dir / "trials" / "trial-02" / "v133_trial_plan.json").exists()


def test_v133_local_trial_rejects_non_local_broker_by_default(tmp_path: Path) -> None:
    out_dir = tmp_path / "trial"
    result = subprocess.run(
        [
            sys.executable,
            "experiments/run_v133_real_local_trial.py",
            "--run-id",
            "run-test-v133-trial",
            "--out-dir",
            str(out_dir),
            "--broker",
            "example.com",
            "--dry-run",
        ],
        text=True,
        capture_output=True,
    )

    assert result.returncode != 0
    assert "refusing non-local broker" in result.stderr

