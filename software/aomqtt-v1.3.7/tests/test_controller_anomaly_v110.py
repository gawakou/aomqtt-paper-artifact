from aomqtt.controller_anomaly import AnomalyRuleConfig, detect_controller_anomalies, write_anomaly_reports


def test_detects_rejected_ack_spike_and_dangerous_reason():
    records = [
        {"status": "rejected", "reason_code": "ENCRYPTION_DISABLED"},
        {"status": "rejected", "reason_code": "ENCRYPTION_DISABLED"},
        {"status": "rejected", "reason_code": "REVOKED_SIGNING_KEY"},
        {"status": "rejected", "reason_code": "REVOKED_SIGNING_KEY"},
        {"status": "rejected", "reason_code": "REVOKED_SIGNING_KEY"},
        {"status": "accepted", "reason_code": "OK"},
    ]

    anomalies = detect_controller_anomalies(records, AnomalyRuleConfig(rejected_count_threshold=5, rejected_ratio_threshold=0.5))

    reason_codes = {a.reason_code for a in anomalies}
    assert "REJECTED_ACK_SPIKE" in reason_codes
    assert "ENCRYPTION_DISABLED" in reason_codes
    assert "REVOKED_SIGNING_KEY" in reason_codes


def test_writes_anomaly_reports(tmp_path):
    records = [{"status": "rejected", "reason_code": "UNKNOWN_SIGNING_KEY"} for _ in range(5)]
    anomalies = detect_controller_anomalies(records)

    csv_path, json_path = write_anomaly_reports(anomalies, tmp_path)

    assert csv_path.exists()
    assert json_path.exists()
    assert "UNKNOWN_SIGNING_KEY" in json_path.read_text()


def test_detects_suspicious_policy_values():
    records = [{"status": "accepted", "reason_code": "OK", "policy": {"rotation": {"interval": 1}, "padding": {"fixed_size": 8192}}}]

    anomalies = detect_controller_anomalies(records)
    reason_codes = {a.reason_code for a in anomalies}

    assert "ROTATION_INTERVAL_TOO_SHORT" in reason_codes
    assert "PADDING_TOO_LARGE" in reason_codes
