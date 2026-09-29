from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

from ..evaluation import (
    DEFAULT_EXPERIMENT_ID,
    DEFAULT_RUN_ID,
    METRICS_SCHEMA_VERSION,
    REPRODUCIBILITY_FIELDS_V1,
)


@dataclass(frozen=True)
class DeliveryMetric:
    """One subscriber-side delivery/decryption observation record.

    The record is intentionally application-level. ``message_id`` and
    ``publisher_timestamp`` are extracted from decrypted payloads when present.
    This makes loss/duplicate/end-to-end latency evaluation possible without
    changing the MQTT broker or packet format.
    """

    timestamp: float
    client_id: str
    policy_id: str
    policy_name: str
    plaintext_filter: str
    token_topic: str
    token_mode: str
    rotation_enabled: bool
    message_id: str
    logical_seq: str
    publisher_timestamp: float
    delivery_latency_ms: float
    decrypt_success: bool
    duplicate: bool
    payload_bytes: int
    error: str = ""

    def to_row(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DeliverySummary:
    total_received: int
    decrypt_success: int
    decrypt_failed: int
    unique_messages: int
    duplicates: int
    duplicate_rate: float
    avg_delivery_latency_ms: float
    p95_delivery_latency_ms: float


class DeliveryCSVLogger:
    """Append subscriber-side delivery metrics to a CSV file."""

    FIELDNAMES = REPRODUCIBILITY_FIELDS_V1 + [
        "timestamp",
        "client_id",
        "policy_id",
        "policy_name",
        "plaintext_filter",
        "token_topic",
        "token_mode",
        "rotation_enabled",
        "message_id",
        "logical_seq",
        "publisher_timestamp",
        "delivery_latency_ms",
        "decrypt_success",
        "duplicate",
        "payload_bytes",
        "error",
    ]

    def __init__(
        self,
        path: str | Path,
        *,
        experiment_id: str = DEFAULT_EXPERIMENT_ID,
        run_id: str = DEFAULT_RUN_ID,
        metrics_schema_version: int = METRICS_SCHEMA_VERSION,
    ):
        self.path = Path(path)
        self.experiment_id = experiment_id
        self.run_id = run_id
        self.metrics_schema_version = metrics_schema_version
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open("w", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._file, fieldnames=self.FIELDNAMES)
        self._writer.writeheader()
        self._file.flush()
        self._metrics: list[DeliveryMetric] = []

    @property
    def metrics(self) -> list[DeliveryMetric]:
        return list(self._metrics)

    def write(self, metric: DeliveryMetric) -> None:
        self._metrics.append(metric)
        row = {
            "metrics_schema_version": self.metrics_schema_version,
            "experiment_id": self.experiment_id,
            "run_id": self.run_id,
        }
        row.update(metric.to_row())
        self._writer.writerow(row)
        self._file.flush()

    def write_many(self, metrics: Iterable[DeliveryMetric]) -> None:
        for metric in metrics:
            self.write(metric)

    def summary(self) -> DeliverySummary:
        return summarize_delivery_metrics(self._metrics)

    def close(self) -> None:
        self._file.close()

    def __enter__(self) -> "DeliveryCSVLogger":
        return self

    def __exit__(self, exc_type, exc, tb) -> Optional[bool]:
        self.close()
        return None


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    idx = min(len(values) - 1, int(p * (len(values) - 1)))
    return values[idx]


def summarize_delivery_metrics(metrics: list[DeliveryMetric]) -> DeliverySummary:
    total = len(metrics)
    ok = [m for m in metrics if m.decrypt_success]
    failed = total - len(ok)
    seen = {m.message_id for m in ok if m.message_id}
    duplicates = sum(1 for m in ok if m.duplicate)
    latencies = [m.delivery_latency_ms for m in ok if m.delivery_latency_ms >= 0]
    avg = sum(latencies) / len(latencies) if latencies else 0.0
    return DeliverySummary(
        total_received=total,
        decrypt_success=len(ok),
        decrypt_failed=failed,
        unique_messages=len(seen),
        duplicates=duplicates,
        duplicate_rate=(duplicates / len(ok)) if ok else 0.0,
        avg_delivery_latency_ms=avg,
        p95_delivery_latency_ms=_percentile(latencies, 0.95),
    )


def _first_present(row: dict[str, Any], *keys: str, default: Any = "") -> Any:
    """Return the first present row value while preserving valid 0 values."""
    for key in keys:
        if key in row and row[key] is not None and row[key] != "":
            return row[key]
    return default


def summarize_loss_and_duplicates(
    publish_rows: Iterable[dict[str, Any]],
    delivery_rows: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Summarize application-level loss/duplicate using logical message IDs.

    Input rows may come from ``csv.DictReader``. Publisher rows should include
    ``logical_seq`` or ``message_id``; delivery rows should include ``message_id``
    or ``logical_seq``. Rotation-overlap duplicate publish rows are collapsed to
    one logical publisher ID.
    """

    pub_ids: set[str] = set()
    for row in publish_rows:
        msg_id = str(_first_present(row, "message_id", "logical_seq", default=""))
        if msg_id:
            pub_ids.add(msg_id)

    recv_counts: dict[str, int] = {}
    for row in delivery_rows:
        msg_id = str(_first_present(row, "message_id", "logical_seq", default=""))
        if msg_id:
            recv_counts[msg_id] = recv_counts.get(msg_id, 0) + 1

    recv_ids = set(recv_counts)
    lost_ids = sorted(pub_ids - recv_ids)
    duplicate_ids = sorted(msg_id for msg_id, count in recv_counts.items() if count > 1)
    total_published = len(pub_ids)
    unique_received = len(recv_ids)
    return {
        "published_logical_messages": total_published,
        "unique_received_messages": unique_received,
        "lost_messages": len(lost_ids),
        "loss_rate": (len(lost_ids) / total_published) if total_published else 0.0,
        "duplicate_message_ids": len(duplicate_ids),
        "duplicate_rate_per_unique_received": (len(duplicate_ids) / unique_received) if unique_received else 0.0,
        "lost_ids": lost_ids,
        "duplicate_ids": duplicate_ids,
    }
