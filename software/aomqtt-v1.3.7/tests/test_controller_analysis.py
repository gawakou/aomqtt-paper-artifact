import csv
import json
from pathlib import Path

from aomqtt.controller_analysis import (
    aggregate_deployment,
    aggregate_reason_codes,
    load_controller_events,
    write_analysis_outputs,
)


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def test_load_and_aggregate_controller_feedback(tmp_path: Path) -> None:
    results = tmp_path / "results"
    scenario_dir = results / "run-a" / "static_policy"

    write_csv(
        scenario_dir / "controller_ack.csv",
        [
            {
                "timestamp": "2026-06-04T10:00:00",
                "client_id": "publisher-1",
                "policy_id": "policy-static",
                "sequence_no": "1",
                "ack_status": "accepted",
                "reason_code": "ok",
            },
            {
                "timestamp": "2026-06-04T10:00:01",
                "client_id": "subscriber-1",
                "policy_id": "policy-static",
                "sequence_no": "1",
                "ack_status": "rejected",
                "reason_code": "invalid_policy",
            },
            {
                "timestamp": "2026-06-04T10:00:02",
                "client_id": "subscriber-2",
                "policy_id": "policy-static",
                "sequence_no": "1",
                "ack_status": "timeout",
                "reason_code": "missing_ack",
            },
        ],
    )

    write_csv(
        scenario_dir / "controller_status.csv",
        [
            {
                "timestamp": "2026-06-04T10:00:03",
                "client_id": "publisher-1",
                "policy_id": "policy-static",
                "sequence_no": "1",
                "application_status": "applied",
                "reason_code": "ok",
            },
            {
                "timestamp": "2026-06-04T10:00:04",
                "client_id": "subscriber-1",
                "policy_id": "policy-static",
                "sequence_no": "1",
                "application_status": "failed",
                "reason_code": "padding_limit_exceeded",
            },
        ],
    )

    events = load_controller_events(results)

    assert len(events) == 5
    assert {event.kind for event in events} == {"ack", "status"}

    rows = aggregate_deployment(events)

    assert len(rows) == 1
    row = rows[0]

    assert row["run_id"] == "run-a"
    assert row["scenario"] == "static_policy"

    assert row["ack_total"] == "3"
    assert row["ack_accepted"] == "1"
    assert row["ack_rejected"] == "1"
    assert row["ack_timeout"] == "1"
    assert row["ack_accepted_rate"] == "0.333333"

    assert row["status_total"] == "2"
    assert row["status_applied"] == "1"
    assert row["status_failed"] == "1"
    assert row["status_applied_rate"] == "0.500000"

    reason_rows = aggregate_reason_codes(events)

    assert any(
        r["reason_code"] == "invalid_policy" and r["count"] == "1"
        for r in reason_rows
    )


def test_jsonl_feedback_and_output_files(tmp_path: Path) -> None:
    results = tmp_path / "results"
    scenario_dir = results / "run-b" / "observation_policy"
    scenario_dir.mkdir(parents=True)

    jsonl_path = scenario_dir / "controller_feedback.jsonl"
    jsonl_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "event_type": "ack",
                        "client": "publisher-1",
                        "policy_id": "policy-auto",
                        "status": "accepted",
                    }
                ),
                json.dumps(
                    {
                        "event_type": "status",
                        "client": "publisher-1",
                        "policy_id": "policy-auto",
                        "status": "applied",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    events = load_controller_events(results)

    assert len(events) == 2

    output_dir = tmp_path / "analysis"
    paths = write_analysis_outputs(events, output_dir)

    for path in paths.values():
        assert path.exists()

    summary = json.loads(paths["deployment_json"].read_text(encoding="utf-8"))

    assert summary["schema_version"] == 1
    assert summary["event_count"] == 2
    assert summary["deployment_summary"][0]["status_applied_rate"] == "1.000000"
