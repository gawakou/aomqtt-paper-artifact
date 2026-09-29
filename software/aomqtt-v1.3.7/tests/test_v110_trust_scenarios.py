import csv
import json

from experiments.run_v110_trust_scenarios import run_scenarios, v110_policy_guard


def test_v110_scenario_runner_creates_expected_ack_records(tmp_path):
    result = run_scenarios(tmp_path)
    records = result["records"]

    assert len(records) == 5
    by_scenario = {row["scenario"]: row for row in records}
    assert by_scenario["safe_signed_policy"]["status"] == "accepted"
    assert by_scenario["safe_signed_policy"]["reason_code"] == "OK"
    assert by_scenario["unknown_signing_key"]["reason_code"] == "UNKNOWN_SIGNING_KEY"
    assert by_scenario["revoked_signing_key"]["reason_code"] == "REVOKED_SIGNING_KEY"
    assert by_scenario["invalid_signature"]["reason_code"] == "POLICY_SIGNATURE_INVALID"
    assert by_scenario["unsafe_policy_guard"]["reason_code"] == "PADDING_TOO_LARGE"


def test_v110_scenario_runner_writes_ack_and_anomaly_artifacts(tmp_path):
    result = run_scenarios(tmp_path)
    artifacts = result["summary"]["artifacts"]

    for path in artifacts.values():
        assert path

    ack_csv = tmp_path / "control_ack_summary.csv"
    ack_json = tmp_path / "control_ack_summary.json"
    anomaly_csv = tmp_path / "controller_anomaly_report.csv"
    anomaly_json = tmp_path / "controller_anomaly_report.json"
    summary_json = tmp_path / "v110_trust_scenario_summary.json"

    assert ack_csv.exists()
    assert ack_json.exists()
    assert anomaly_csv.exists()
    assert anomaly_json.exists()
    assert summary_json.exists()

    with ack_csv.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 5
    assert {row["scenario"] for row in rows} >= {"safe_signed_policy", "revoked_signing_key"}

    with ack_json.open(encoding="utf-8") as f:
        data = json.load(f)
    assert len(data["acks"]) == 5

    with anomaly_json.open(encoding="utf-8") as f:
        anomaly_data = json.load(f)
    reasons = {row["reason_code"] for row in anomaly_data["anomalies"]}
    assert "REVOKED_SIGNING_KEY" in reasons
    assert "UNKNOWN_SIGNING_KEY" in reasons

    with summary_json.open(encoding="utf-8") as f:
        summary = json.load(f)
    assert summary["total"] == 5
    assert summary["accepted"] == 1
    assert summary["rejected"] == 4


def test_v110_policy_guard_rejects_unsafe_values():
    assert v110_policy_guard({"encryption": {"enabled": False}})["reason_code"] == "ENCRYPTION_DISABLED"
    assert v110_policy_guard({"topic_obfuscation": {"enabled": False}})["reason_code"] == "TOPIC_OBFUSCATION_DISABLED"
    assert v110_policy_guard({"padding": {"fixed_size": 999999}})["reason_code"] == "PADDING_TOO_LARGE"
    assert v110_policy_guard({"rotation": {"interval": 1}})["reason_code"] == "ROTATION_INTERVAL_TOO_SHORT"
    assert v110_policy_guard({"encryption": {"enabled": True}, "padding": {"fixed_size": 512}}) is None
