from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path


def write_summary_files(tmp_path: Path) -> tuple[Path, Path]:
    v110 = {
        "accepted": 1,
        "rejected": 4,
        "total": 5,
        "reason_counts": {
            "OK": 1,
            "UNKNOWN_SIGNING_KEY": 1,
            "REVOKED_SIGNING_KEY": 1,
            "POLICY_SIGNATURE_INVALID": 1,
            "PADDING_TOO_LARGE": 1,
        },
    }
    v120 = {
        "accepted": 1,
        "rejected": 5,
        "total": 6,
        "reason_counts": {
            "OK": 1,
            "MULTISIG_THRESHOLD_NOT_MET": 1,
            "MULTISIG_REQUIRED_ROLE_MISSING": 1,
            "REVOKED_SIGNING_KEY": 1,
            "POLICY_SIGNATURE_INVALID": 1,
            "PADDING_TOO_LARGE": 1,
        },
        "transparency_log": {
            "accepted": True,
            "reason_code": "OK",
            "verified_entries": 6,
            "failed_index": None,
        },
    }

    v110_path = tmp_path / "v110_summary.json"
    v120_path = tmp_path / "v120_summary.json"
    v110_path.write_text(json.dumps(v110))
    v120_path.write_text(json.dumps(v120))
    return v110_path, v120_path


def test_security_evolution_table_is_generated(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    subprocess.run(
        [
            sys.executable,
            "experiments/collect_v121_security_evolution_table.py",
            "--out-dir",
            str(out_dir),
        ],
        check=True,
    )

    csv_path = out_dir / "security_evolution_table.csv"
    assert csv_path.exists()
    rows = list(csv.DictReader(csv_path.open()))
    assert [row["version"] for row in rows] == ["v1.0.2", "v1.1.0", "v1.2.0"]
    assert "Multi-Signature" in rows[-1]["release_theme"]


def test_policy_decision_matrix_is_generated_from_summaries(tmp_path: Path) -> None:
    v110_path, v120_path = write_summary_files(tmp_path)
    out_dir = tmp_path / "out"

    subprocess.run(
        [
            sys.executable,
            "experiments/collect_v121_policy_decision_matrix.py",
            "--v110-summary",
            str(v110_path),
            "--v120-summary",
            str(v120_path),
            "--out-dir",
            str(out_dir),
        ],
        check=True,
    )

    csv_path = out_dir / "policy_decision_matrix.csv"
    assert csv_path.exists()
    rows = list(csv.DictReader(csv_path.open()))
    reason_codes = {row["expected_reason_code"] for row in rows}
    assert "MULTISIG_THRESHOLD_NOT_MET" in reason_codes
    assert "MULTISIG_REQUIRED_ROLE_MISSING" in reason_codes
    assert "UNKNOWN_SIGNING_KEY" in reason_codes

    threshold_rows = [row for row in rows if row["expected_reason_code"] == "MULTISIG_THRESHOLD_NOT_MET"]
    assert threshold_rows[0]["observed_count"] == "1"


def test_paper_summary_table_is_generated(tmp_path: Path) -> None:
    v110_path, v120_path = write_summary_files(tmp_path)
    out_dir = tmp_path / "out"

    subprocess.run(
        [
            sys.executable,
            "experiments/collect_v121_paper_summary_table.py",
            "--v110-summary",
            str(v110_path),
            "--v120-summary",
            str(v120_path),
            "--test-count",
            "156",
            "--out-dir",
            str(out_dir),
        ],
        check=True,
    )

    csv_path = out_dir / "paper_summary_table.csv"
    assert csv_path.exists()
    rows = list(csv.DictReader(csv_path.open()))
    metrics = {row["metric"]: row["value"] for row in rows}
    assert metrics["unit_and_scenario_tests"] == "156"
    assert metrics["v1.2.0_transparency_log_verified_entries"] == "6"
    assert metrics["v1.2.0_transparency_log_result"] == "True"

