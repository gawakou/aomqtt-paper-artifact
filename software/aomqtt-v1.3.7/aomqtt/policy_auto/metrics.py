"""Metrics aggregation for observation-driven Policy control."""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Optional


@dataclass
class ObservationMetrics:
    """Aggregated metrics used by the rule-based Policy controller."""

    avg_publish_complete_ms: Optional[float] = None
    avg_delivery_latency_ms: Optional[float] = None
    loss_rate: Optional[float] = None
    duplicate_rate: Optional[float] = None
    decrypt_success_rate: Optional[float] = None
    avg_payload_total_overhead_bytes: Optional[float] = None
    reconnect_count: Optional[int] = None

    publisher_rows: int = 0
    subscriber_rows: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


def _read_csv_rows(path: str | Path | None) -> list[dict[str, str]]:
    if path is None:
        return []

    p = Path(path)
    if not p.exists():
        return []

    with p.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _to_float(value) -> Optional[float]:
    if value is None:
        return None
    try:
        s = str(value).strip()
        if s == "":
            return None
        return float(s)
    except Exception:
        return None


def _to_int(value) -> Optional[int]:
    f = _to_float(value)
    if f is None:
        return None
    return int(f)


def _avg(rows: Iterable[dict[str, str]], candidates: list[str]) -> Optional[float]:
    values: list[float] = []
    for row in rows:
        for key in candidates:
            if key in row:
                v = _to_float(row.get(key))
                if v is not None:
                    values.append(v)
                break
    if not values:
        return None
    return sum(values) / len(values)


def _sum_int(rows: Iterable[dict[str, str]], candidates: list[str]) -> Optional[int]:
    values: list[int] = []
    for row in rows:
        for key in candidates:
            if key in row:
                v = _to_int(row.get(key))
                if v is not None:
                    values.append(v)
                break
    if not values:
        return None
    return sum(values)


def _truthy(value) -> Optional[bool]:
    if value is None:
        return None
    s = str(value).strip().lower()
    if s in {"1", "true", "yes", "y", "ok", "success", "succeeded"}:
        return True
    if s in {"0", "false", "no", "n", "ng", "fail", "failed"}:
        return False
    return None


def _bool_rate(
    rows: Iterable[dict[str, str]],
    candidates: list[str],
    *,
    true_is_success: bool = True,
) -> Optional[float]:
    total = 0
    true_count = 0

    for row in rows:
        for key in candidates:
            if key in row:
                b = _truthy(row.get(key))
                if b is not None:
                    total += 1
                    if b:
                        true_count += 1
                break

    if total == 0:
        return None

    rate = true_count / total
    return rate if true_is_success else 1.0 - rate


def _seq_loss_duplicate_rates(rows: list[dict[str, str]]) -> tuple[Optional[float], Optional[float]]:
    seq_candidates = ["seq", "sequence", "sequence_no", "message_id", "logical_seq"]
    seqs: list[int] = []

    for row in rows:
        for key in seq_candidates:
            if key in row:
                v = _to_int(row.get(key))
                if v is not None:
                    seqs.append(v)
                break

    if not seqs:
        return None, None

    unique_count = len(set(seqs))
    total_count = len(seqs)

    duplicate_rate = 0.0
    if total_count > 0:
        duplicate_rate = max(0.0, (total_count - unique_count) / total_count)

    min_seq = min(seqs)
    max_seq = max(seqs)
    expected = max_seq - min_seq + 1

    loss_rate = None
    if expected > 0:
        loss_rate = max(0.0, (expected - unique_count) / expected)

    return loss_rate, duplicate_rate


def aggregate_publisher_metrics(path: str | Path | None) -> dict:
    rows = _read_csv_rows(path)

    return {
        "rows": len(rows),
        "avg_publish_complete_ms": _avg(
            rows,
            [
                "avg_publish_complete_ms",
                "publish_complete_ms",
                "publish_complete_latency_ms",
                "publish_ack_latency_ms",
                "ack_latency_ms",
            ],
        ),
        "avg_payload_total_overhead_bytes": _avg(
            rows,
            [
                "avg_payload_total_overhead_bytes",
                "payload_total_overhead_bytes",
                "total_overhead_bytes",
                "overhead_bytes",
                "padding_added",
            ],
        ),
        "reconnect_count": _sum_int(
            rows,
            [
                "reconnect_count",
                "reconnects",
                "reconnect",
            ],
        ),
    }


def aggregate_subscriber_metrics(path: str | Path | None) -> dict:
    rows = _read_csv_rows(path)

    seq_loss_rate, seq_duplicate_rate = _seq_loss_duplicate_rates(rows)

    explicit_loss_rate = _avg(rows, ["loss_rate", "message_loss_rate"])
    explicit_duplicate_rate = _avg(rows, ["duplicate_rate", "dup_rate"])

    decrypt_success_rate = _bool_rate(
        rows,
        [
            "decrypt_success",
            "decrypt_ok",
            "payload_decrypt_success",
        ],
        true_is_success=True,
    )

    decrypt_failure_rate = _bool_rate(
        rows,
        [
            "decrypt_failed",
            "decrypt_error",
        ],
        true_is_success=False,
    )

    if decrypt_success_rate is None and decrypt_failure_rate is not None:
        decrypt_success_rate = 1.0 - decrypt_failure_rate

    return {
        "rows": len(rows),
        "avg_delivery_latency_ms": _avg(
            rows,
            [
                "avg_delivery_latency_ms",
                "delivery_latency_ms",
                "latency_ms",
                "end_to_end_latency_ms",
            ],
        ),
        "loss_rate": explicit_loss_rate if explicit_loss_rate is not None else seq_loss_rate,
        "duplicate_rate": explicit_duplicate_rate if explicit_duplicate_rate is not None else seq_duplicate_rate,
        "decrypt_success_rate": decrypt_success_rate,
    }


def aggregate_observation_metrics(
    *,
    publisher_metrics_csv: str | Path | None = None,
    subscriber_metrics_csv: str | Path | None = None,
) -> ObservationMetrics:
    pub = aggregate_publisher_metrics(publisher_metrics_csv)
    sub = aggregate_subscriber_metrics(subscriber_metrics_csv)

    return ObservationMetrics(
        avg_publish_complete_ms=pub.get("avg_publish_complete_ms"),
        avg_delivery_latency_ms=sub.get("avg_delivery_latency_ms"),
        loss_rate=sub.get("loss_rate"),
        duplicate_rate=sub.get("duplicate_rate"),
        decrypt_success_rate=sub.get("decrypt_success_rate"),
        avg_payload_total_overhead_bytes=pub.get("avg_payload_total_overhead_bytes"),
        reconnect_count=pub.get("reconnect_count"),
        publisher_rows=int(pub.get("rows") or 0),
        subscriber_rows=int(sub.get("rows") or 0),
    )
