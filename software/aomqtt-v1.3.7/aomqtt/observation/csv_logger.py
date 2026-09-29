from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable, Optional

from ..evaluation import (
    DEFAULT_EXPERIMENT_ID,
    DEFAULT_RUN_ID,
    METRICS_SCHEMA_VERSION,
    REPRODUCIBILITY_FIELDS_V1,
)
from .metrics import PublishMetric, PublishSummary, summarize_publish_metrics


class PublishCSVLogger:
    """Append publish metrics to a CSV file."""

    FIELDNAMES = REPRODUCIBILITY_FIELDS_V1 + [
        "timestamp",
        "client_id",
        "policy_id",
        "policy_name",
        "plaintext_topic",
        "token_topic",
        "token_mode",
        "rotation_enabled",
        "rotation_epoch",
        "rotation_in_overlap",
        "overlap_duplicate",
        "mqtt_messages_for_logical",
        "logical_seq",
        "message_id",
        "qos",
        "retain",
        "payload_plain_bytes",
        "payload_padded_bytes",
        "payload_encrypted_bytes",
        "padding_enabled",
        "padding_mode",
        "padding_added_bytes",
        "padding_overhead_ratio",
        "payload_total_overhead_bytes",
        "mid",
        "rc",
        "success",
        "wait_for_publish",
        "publish_complete_ms",
        "reconnect_count",
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
        self._metrics: list[PublishMetric] = []

    @property
    def metrics(self) -> list[PublishMetric]:
        return list(self._metrics)

    def write(self, metric: PublishMetric) -> None:
        self._metrics.append(metric)
        row = {
            "metrics_schema_version": self.metrics_schema_version,
            "experiment_id": self.experiment_id,
            "run_id": self.run_id,
        }
        row.update(metric.to_row())
        self._writer.writerow(row)
        self._file.flush()

    def write_many(self, metrics: Iterable[PublishMetric]) -> None:
        for metric in metrics:
            self.write(metric)

    def summary(self) -> PublishSummary:
        return summarize_publish_metrics(self._metrics)

    def close(self) -> None:
        self._file.close()

    def __enter__(self) -> "PublishCSVLogger":
        return self

    def __exit__(self, exc_type, exc, tb) -> Optional[bool]:
        self.close()
        return None
