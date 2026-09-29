"""Shared schema helpers for v1.3.1 local broker measurement artifacts."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


UNIFIED_MEASUREMENT_FIELDS = [
    "run_id",
    "scenario_id",
    "scenario_type",
    "environment",
    "broker",
    "qos",
    "logical_messages",
    "mqtt_messages",
    "success_messages",
    "failed_messages",
    "duplicates",
    "missing_messages",
    "publish_complete_ms_avg",
    "publish_complete_ms_p50",
    "publish_complete_ms_p95",
    "publish_complete_ms_p99",
    "delivery_latency_ms_avg",
    "delivery_latency_ms_p50",
    "delivery_latency_ms_p95",
    "delivery_latency_ms_p99",
    "payload_plain_bytes_avg",
    "payload_padded_bytes_avg",
    "payload_encrypted_bytes_avg",
    "padding_added_bytes_avg",
    "rotation_overlap_duplicates",
    "control_accepted",
    "control_rejected",
    "transparency_entries",
    "transparency_verified_entries",
    "status",
    "notes",
]


@dataclass(frozen=True)
class MeasurementScenario:
    scenario_id: str
    scenario_type: str
    environment: str
    description: str
    default_count: int
    qos: int
    requires_broker: bool
    command_hint: str
    safety_note: str


def v131_scenarios() -> list[MeasurementScenario]:
    return [
        MeasurementScenario(
            scenario_id="plain_mqtt_baseline",
            scenario_type="plain_mqtt",
            environment="local_broker",
            description="Plain MQTT baseline measurement for latency and throughput comparison.",
            default_count=6000,
            qos=1,
            requires_broker=True,
            command_hint="experiments/run_v131_plain_mqtt_measurement.py",
            safety_note="Local or explicitly authorized broker only.",
        ),
        MeasurementScenario(
            scenario_id="aomqtt_basic",
            scenario_type="aomqtt_data_plane",
            environment="local_broker",
            description="AOMQTT basic topic obfuscation and payload encryption measurement.",
            default_count=6000,
            qos=1,
            requires_broker=True,
            command_hint="examples/subscriber_example.py + examples/publisher_example.py",
            safety_note="Local or explicitly authorized broker only.",
        ),
        MeasurementScenario(
            scenario_id="aomqtt_padding512",
            scenario_type="aomqtt_data_plane",
            environment="local_broker",
            description="AOMQTT fixed 512-byte padding measurement.",
            default_count=6000,
            qos=1,
            requires_broker=True,
            command_hint="examples/subscriber_example.py + examples/publisher_example.py --padding-mode fixed --padding-fixed-size 512",
            safety_note="Local or explicitly authorized broker only.",
        ),
        MeasurementScenario(
            scenario_id="aomqtt_padding512_rotation30_overlap5",
            scenario_type="aomqtt_data_plane",
            environment="local_broker",
            description="AOMQTT fixed 512-byte padding with token rotation and overlap.",
            default_count=6000,
            qos=1,
            requires_broker=True,
            command_hint="examples/subscriber_example.py + examples/publisher_example.py --rotation --rotation-interval 30 --rotation-overlap 5",
            safety_note="Local or explicitly authorized broker only.",
        ),
        MeasurementScenario(
            scenario_id="v120_multisig_control_plane",
            scenario_type="control_plane",
            environment="local_process",
            description="v1.2.0 multi-signature control-plane scenario normalized into the unified measurement schema.",
            default_count=6,
            qos=0,
            requires_broker=False,
            command_hint="experiments/run_v120_multisig_transparency_scenarios.sh",
            safety_note="Broker-independent local scenario.",
        ),
    ]


def scenario_dicts() -> list[dict[str, Any]]:
    return [asdict(s) for s in v131_scenarios()]


def empty_unified_row(run_id: str, scenario_id: str, scenario_type: str, environment: str, broker: str, qos: int) -> dict[str, Any]:
    row = {field: "" for field in UNIFIED_MEASUREMENT_FIELDS}
    row.update(
        {
            "run_id": run_id,
            "scenario_id": scenario_id,
            "scenario_type": scenario_type,
            "environment": environment,
            "broker": broker,
            "qos": qos,
            "status": "planned",
        }
    )
    return row

