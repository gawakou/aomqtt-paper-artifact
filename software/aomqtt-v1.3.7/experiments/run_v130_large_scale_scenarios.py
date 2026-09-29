#!/usr/bin/env python3
"""Generate v1.3.0 large-scale and adversarial evaluation scenario artifacts.

This runner is intentionally safe by default.  It does not generate network
traffic and does not contact a broker.  It creates a reproducible evaluation
plan and synthetic accounting artifacts for local/authorized experiments.

Actual high-rate MQTT load generation should be performed only on local or
explicitly authorized infrastructure.  Public-broker evaluation must remain
low-rate compatibility probing and must not use DoS-like workloads.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


def build_large_scale_rows() -> list[dict[str, Any]]:
    """Return deterministic v1.3.0 scenario definitions.

    The numbers are scenario design parameters, not measured performance data.
    They are intended to standardize later real measurements on local broker,
    mdx, Starlink, and public-broker environments.
    """

    return [
        {
            "scenario_id": "plain_mqtt_baseline_6000",
            "category": "baseline",
            "environment": "local_or_authorized",
            "target_scope": "data_plane",
            "clients": 1,
            "publishers": 1,
            "subscribers": 1,
            "logical_messages": 6000,
            "expected_mqtt_messages": 6000,
            "control_messages": 0,
            "transparency_entries": 0,
            "max_publish_rate_mps": 100,
            "allowed_on_public_broker": False,
            "purpose": "plain MQTT baseline for overhead comparison",
            "safety_note": "Use local or explicitly authorized broker only.",
        },
        {
            "scenario_id": "aomqtt_basic_6000",
            "category": "aomqtt_data_plane",
            "environment": "local_or_authorized",
            "target_scope": "data_plane",
            "clients": 2,
            "publishers": 1,
            "subscribers": 1,
            "logical_messages": 6000,
            "expected_mqtt_messages": 6000,
            "control_messages": 0,
            "transparency_entries": 0,
            "max_publish_rate_mps": 100,
            "allowed_on_public_broker": False,
            "purpose": "AOMQTT basic overhead comparison",
            "safety_note": "Use local or explicitly authorized broker only.",
        },
        {
            "scenario_id": "aomqtt_padding512_6000",
            "category": "aomqtt_data_plane",
            "environment": "local_or_authorized",
            "target_scope": "data_plane",
            "clients": 2,
            "publishers": 1,
            "subscribers": 1,
            "logical_messages": 6000,
            "expected_mqtt_messages": 6000,
            "control_messages": 0,
            "transparency_entries": 0,
            "max_publish_rate_mps": 100,
            "allowed_on_public_broker": False,
            "purpose": "fixed padding overhead comparison",
            "safety_note": "Use local or explicitly authorized broker only.",
        },
        {
            "scenario_id": "aomqtt_padding512_rotation30_overlap5_6000",
            "category": "aomqtt_data_plane",
            "environment": "local_or_authorized",
            "target_scope": "data_plane",
            "clients": 2,
            "publishers": 1,
            "subscribers": 1,
            "logical_messages": 6000,
            "expected_mqtt_messages": 7003,
            "control_messages": 0,
            "transparency_entries": 0,
            "max_publish_rate_mps": 100,
            "allowed_on_public_broker": False,
            "purpose": "token rotation overlap duplicate accounting",
            "safety_note": "Use local or explicitly authorized broker only.",
        },
        {
            "scenario_id": "v120_multisig_policy_batch_1000",
            "category": "control_plane",
            "environment": "local_or_authorized",
            "target_scope": "control_plane",
            "clients": 50,
            "publishers": 0,
            "subscribers": 50,
            "logical_messages": 0,
            "expected_mqtt_messages": 0,
            "control_messages": 1000,
            "transparency_entries": 1000,
            "max_publish_rate_mps": 20,
            "allowed_on_public_broker": False,
            "purpose": "multi-signature policy and transparency log growth evaluation",
            "safety_note": "Run only on local or explicitly authorized test broker.",
        },
        {
            "scenario_id": "policy_storm_controlled_local",
            "category": "adversarial_control_plane",
            "environment": "local_only",
            "target_scope": "control_plane",
            "clients": 100,
            "publishers": 0,
            "subscribers": 100,
            "logical_messages": 0,
            "expected_mqtt_messages": 0,
            "control_messages": 5000,
            "transparency_entries": 5000,
            "max_publish_rate_mps": 50,
            "allowed_on_public_broker": False,
            "purpose": "controlled policy-storm resilience evaluation",
            "safety_note": "Do not run against public brokers. Local isolated broker only.",
        },
        {
            "scenario_id": "ack_storm_controlled_local",
            "category": "adversarial_control_plane",
            "environment": "local_only",
            "target_scope": "control_plane",
            "clients": 500,
            "publishers": 0,
            "subscribers": 500,
            "logical_messages": 0,
            "expected_mqtt_messages": 0,
            "control_messages": 500,
            "transparency_entries": 500,
            "max_publish_rate_mps": 50,
            "allowed_on_public_broker": False,
            "purpose": "controlled ACK aggregation stress evaluation",
            "safety_note": "Do not run against public brokers. Local isolated broker only.",
        },
        {
            "scenario_id": "public_broker_compatibility_probe",
            "category": "compatibility_probe",
            "environment": "public_broker_with_permission",
            "target_scope": "compatibility_only",
            "clients": 2,
            "publishers": 1,
            "subscribers": 1,
            "logical_messages": 10,
            "expected_mqtt_messages": 10,
            "control_messages": 0,
            "transparency_entries": 0,
            "max_publish_rate_mps": 1,
            "allowed_on_public_broker": True,
            "purpose": "low-rate public broker compatibility probe",
            "safety_note": "Do not use for load or DoS evaluation. Confirm broker policy and permission.",
        },
        {
            "scenario_id": "starlink_field_eval_low_rate",
            "category": "field_environment",
            "environment": "starlink",
            "target_scope": "data_plane",
            "clients": 2,
            "publishers": 1,
            "subscribers": 1,
            "logical_messages": 6000,
            "expected_mqtt_messages": 6000,
            "control_messages": 0,
            "transparency_entries": 0,
            "max_publish_rate_mps": 20,
            "allowed_on_public_broker": False,
            "purpose": "Starlink latency and delivery evaluation under controlled rate",
            "safety_note": "Use owned endpoints and respect network policy.",
        },
        {
            "scenario_id": "mdx_authorized_eval",
            "category": "field_environment",
            "environment": "mdx",
            "target_scope": "data_and_control_plane",
            "clients": 100,
            "publishers": 50,
            "subscribers": 50,
            "logical_messages": 60000,
            "expected_mqtt_messages": 60000,
            "control_messages": 1000,
            "transparency_entries": 1000,
            "max_publish_rate_mps": 200,
            "allowed_on_public_broker": False,
            "purpose": "authorized mdx-scale deployment evaluation",
            "safety_note": "Run only on allocated and authorized mdx resources.",
        },
    ]


def build_environment_rows() -> list[dict[str, Any]]:
    return [
        {
            "environment": "local",
            "allowed_workloads": "baseline; AOMQTT data-plane; control-plane stress; policy storm; ACK storm",
            "disallowed_workloads": "none if isolated and authorized",
            "required_permission": "owned local environment",
            "recommended_rate_limit": "experiment-dependent; start low and increase gradually",
        },
        {
            "environment": "public_broker",
            "allowed_workloads": "low-rate compatibility probe only",
            "disallowed_workloads": "DoS-like load; policy storm; ACK storm; large-scale throughput tests",
            "required_permission": "explicit broker policy compliance or written permission",
            "recommended_rate_limit": "10 messages total, <=1 message/sec",
        },
        {
            "environment": "mdx",
            "allowed_workloads": "large-scale and adversarial evaluation within allocated resources",
            "disallowed_workloads": "traffic outside approved scope",
            "required_permission": "allocated project resources and approved test plan",
            "recommended_rate_limit": "start at low rate; document rate, clients, and resource limits",
        },
        {
            "environment": "starlink",
            "allowed_workloads": "field data-plane evaluation; controlled policy deployment tests",
            "disallowed_workloads": "unbounded load; traffic to third-party brokers without permission",
            "required_permission": "owned Starlink link and owned/authorized broker endpoints",
            "recommended_rate_limit": "controlled low/medium rate; record obstruction and latency metrics",
        },
    ]


def summarize(rows: list[dict[str, Any]], environment_rows: list[dict[str, Any]]) -> dict[str, Any]:
    category_counts: dict[str, int] = {}
    total_logical = 0
    total_mqtt = 0
    total_control = 0
    total_tlog = 0
    public_safe = 0

    for row in rows:
        category_counts[row["category"]] = category_counts.get(row["category"], 0) + 1
        total_logical += int(row["logical_messages"])
        total_mqtt += int(row["expected_mqtt_messages"])
        total_control += int(row["control_messages"])
        total_tlog += int(row["transparency_entries"])
        if row["allowed_on_public_broker"]:
            public_safe += 1

    return {
        "scenario_count": len(rows),
        "category_counts": category_counts,
        "environment_count": len(environment_rows),
        "planned_logical_messages": total_logical,
        "planned_expected_mqtt_messages": total_mqtt,
        "planned_control_messages": total_control,
        "planned_transparency_entries": total_tlog,
        "public_broker_allowed_scenarios": public_safe,
        "public_broker_disallowed_scenarios": len(rows) - public_safe,
        "safety_policy": "DoS-like and high-rate workloads are limited to local or explicitly authorized environments.",
    }


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_json(data: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(data, f, indent=2, sort_keys=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", default="results/run-v130-large-scale-evaluation-001")
    args = parser.parse_args(argv)

    out_dir = Path(args.out_dir)
    rows = build_large_scale_rows()
    env_rows = build_environment_rows()
    summary = summarize(rows, env_rows)

    write_csv(rows, out_dir / "large_scale_scenario_plan.csv")
    write_json({"rows": rows}, out_dir / "large_scale_scenario_plan.json")
    write_csv(env_rows, out_dir / "environment_safety_matrix.csv")
    write_json({"rows": env_rows}, out_dir / "environment_safety_matrix.json")
    write_json(summary, out_dir / "v130_large_scale_summary.json")

    print(json.dumps(summary, indent=2, sort_keys=True))
    print(f"wrote v1.3.0 scenario artifacts under {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

