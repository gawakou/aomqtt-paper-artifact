import json
import os
import subprocess
import sys
from pathlib import Path


def test_v120_multisig_transparency_scenario_runner(tmp_path):
    run_id = "pytest-v120-multisig-transparency"
    env = os.environ.copy()
    env["RUN_ID"] = run_id
    subprocess.run(
        [sys.executable, "experiments/run_v120_multisig_transparency_scenarios.py"],
        check=True,
        env=env,
    )

    summary_path = Path("results") / run_id / "v120_multisig_transparency_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    assert summary["accepted"] == 1
    assert summary["rejected"] == 5
    assert summary["total"] == 6
    assert summary["reason_counts"]["OK"] == 1
    assert summary["reason_counts"]["MULTISIG_THRESHOLD_NOT_MET"] == 1
    assert summary["reason_counts"]["MULTISIG_REQUIRED_ROLE_MISSING"] == 1
    assert summary["reason_counts"]["REVOKED_SIGNING_KEY"] == 1
    assert summary["reason_counts"]["POLICY_SIGNATURE_INVALID"] == 1
    assert summary["reason_counts"]["PADDING_TOO_LARGE"] == 1
    assert summary["transparency_log"]["accepted"] is True
    assert summary["transparency_log"]["verified_entries"] == 6
