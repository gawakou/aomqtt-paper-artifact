from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class PublishMetric:
    """One MQTT PUBLISH observation record.

    For QoS 1/2, publish_complete_ms approximates PUBACK/PUBCOMP completion
    latency. For QoS 0, it is the time until Paho marks the publish operation as
    complete, not a broker acknowledgement.
    """

    timestamp: float
    client_id: str
    policy_id: str
    policy_name: str
    plaintext_topic: str
    token_topic: str
    token_mode: str
    rotation_enabled: bool
    rotation_epoch: str
    rotation_in_overlap: bool
    overlap_duplicate: bool
    mqtt_messages_for_logical: int
    logical_seq: str
    message_id: str
    qos: int
    retain: bool
    payload_plain_bytes: int
    payload_padded_bytes: int
    payload_encrypted_bytes: int
    padding_enabled: bool
    padding_mode: str
    padding_added_bytes: int
    padding_overhead_ratio: float
    payload_total_overhead_bytes: int
    mid: int
    rc: int
    success: bool
    wait_for_publish: bool
    publish_complete_ms: float
    reconnect_count: int
    error: str = ""

    def to_row(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PublishSummary:
    total: int
    success: int
    failed: int
    success_rate: float
    avg_publish_complete_ms: float
    p95_publish_complete_ms: float
    reconnect_count: int


def summarize_publish_metrics(metrics: list[PublishMetric]) -> PublishSummary:
    total = len(metrics)
    success = sum(1 for m in metrics if m.success)
    failed = total - success
    latencies = sorted(m.publish_complete_ms for m in metrics if m.success)
    if latencies:
        avg = sum(latencies) / len(latencies)
        p95_index = min(len(latencies) - 1, int(0.95 * (len(latencies) - 1)))
        p95 = latencies[p95_index]
    else:
        avg = 0.0
        p95 = 0.0
    reconnect_count = metrics[-1].reconnect_count if metrics else 0
    return PublishSummary(
        total=total,
        success=success,
        failed=failed,
        success_rate=(success / total) if total else 0.0,
        avg_publish_complete_ms=avg,
        p95_publish_complete_ms=p95,
        reconnect_count=reconnect_count,
    )
