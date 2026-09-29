#!/usr/bin/env python3
"""Collect AOMQTT publisher/subscriber metrics into v1.3.1 unified summary JSON.

This script converts existing AOMQTT example metrics into the summary format
consumed by experiments/run_v131_local_measurements.py --mode collect.

It is intentionally tolerant of small schema differences across AOMQTT versions.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from pathlib import Path
from typing import Any


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def first_existing_column(rows: list[dict[str, str]], candidates: list[str]) -> str | None:
    if not rows:
        return None
    columns = set(rows[0].keys())
    for c in candidates:
        if c in columns:
            return c
    return None


def to_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if text == "" or text.lower() in {"none", "nan", "null"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def to_bool(value: Any) -> bool:
    text = str(value).strip().lower()
    return text in {"1", "true", "yes", "y", "success", "ok"}


def numeric_values(rows: list[dict[str, str]], candidates: list[str]) -> list[float]:
    col = first_existing_column(rows, candidates)
    if col is None:
        return []
    values: list[float] = []
    for row in rows:
        value = to_float(row.get(col))
        if value is not None:
            values.append(value)
    return values


def avg(rows: list[dict[str, str]], candidates: list[str]) -> str:
    values = numeric_values(rows, candidates)
    if not values:
        return ""
    return str(float(statistics.mean(values)))


def percentile(values: list[float], q: float) -> str:
    if not values:
        return ""
    values = sorted(values)
    idx = min(len(values) - 1, max(0, int(round((len(values) - 1) * q))))
    return str(float(values[idx]))


def summarize_metric(rows: list[dict[str, str]], candidates: list[str]) -> dict[str, str]:
    values = numeric_values(rows, candidates)
    return {
        "avg": str(float(statistics.mean(values))) if values else "",
        "p50": percentile(values, 0.50),
        "p95": percentile(values, 0.95),
        "p99": percentile(values, 0.99),
    }


def unique_count(rows: list[dict[str, str]], candidates: list[str]) -> int:
    if not rows:
        return 0
    columns = set(rows[0].keys())
    for col in candidates:
        if col not in columns:
            continue
        values = {row.get(col, "") for row in rows if row.get(col, "") != ""}
        if values:
            return len(values)
    return 0


def count_success(rows: list[dict[str, str]]) -> int:
    col = first_existing_column(rows, ["success", "decrypt_success", "accepted", "delivered"])
    if col is None:
        return len(rows)
    return sum(1 for row in rows if to_bool(row.get(col)))


def count_truthy(rows: list[dict[str, str]], candidates: list[str]) -> int:
    col = first_existing_column(rows, candidates)
    if col is None:
        return 0
    return sum(1 for row in rows if to_bool(row.get(col)))


def infer_logical_messages(pub_rows: list[dict[str, str]], sub_rows: list[dict[str, str]]) -> int:
    for rows in (pub_rows, sub_rows):
        n = unique_count(rows, ["logical_seq", "seq", "message_id", "id"])
        if n:
            return n
    return len(pub_rows) or len(sub_rows)


def infer_duplicates(sub_rows: list[dict[str, str]], mqtt_messages: int, logical_messages: int) -> int:
    explicit = count_truthy(sub_rows, ["duplicate", "is_duplicate", "overlap_duplicate"])
    if explicit:
        return explicit
    unique_sub = unique_count(sub_rows, ["logical_seq", "seq", "message_id", "id"])
    if unique_sub and len(sub_rows) >= unique_sub:
        return len(sub_rows) - unique_sub
    return max(0, mqtt_messages - logical_messages)


def build_summary(
    *,
    run_id: str,
    scenario_id: str,
    scenario_type: str,
    broker: str,
    qos: int,
    publisher_csv: Path,
    subscriber_csv: Path,
) -> dict[str, Any]:
    pub_rows = read_csv(publisher_csv)
    sub_rows = read_csv(subscriber_csv)

    logical_messages = infer_logical_messages(pub_rows, sub_rows)
    mqtt_messages = len(pub_rows) if pub_rows else logical_messages
    success_messages = unique_count(sub_rows, ["logical_seq", "seq", "message_id", "id"]) or count_success(sub_rows)
    if not sub_rows and pub_rows:
        success_messages = count_success(pub_rows)

    # In rotation/overlap scenarios, subscriber CSVs may contain duplicate
    # deliveries for the same logical message.  The success count should mean
    # unique logical messages successfully delivered, so it must not exceed the
    # number of logical messages.
    if logical_messages:
        success_messages = min(success_messages, logical_messages)

    duplicates = infer_duplicates(sub_rows, mqtt_messages, logical_messages)
    missing_messages = max(0, logical_messages - success_messages)
    failed_messages = missing_messages

    publish = summarize_metric(pub_rows, ["publish_complete_ms", "publish_ms", "publish_latency_ms"])

    # Subscriber-side latency is recorded as delivery_latency_ms in the current
    # delivery CSV schema.  Keep fallback names for older artifacts.
    delivery = summarize_metric(sub_rows, ["delivery_latency_ms", "latency_ms", "end_to_end_latency_ms"])

    rotation_overlap_duplicates = count_truthy(pub_rows, ["overlap_duplicate", "rotation_overlap_duplicate"])
    if not rotation_overlap_duplicates and "rotation" in scenario_id:
        rotation_overlap_duplicates = max(0, mqtt_messages - logical_messages)

    return {
        "run_id": run_id,
        "scenario_id": scenario_id,
        "scenario_type": scenario_type,
        "environment": "local_broker",
        "broker": broker,
        "qos": qos,
        "logical_messages": logical_messages,
        "mqtt_messages": mqtt_messages,
        "success_messages": success_messages,
        "failed_messages": failed_messages,
        "duplicates": duplicates,
        "missing_messages": missing_messages,
        "publish_complete_ms_avg": publish["avg"],
        "publish_complete_ms_p50": publish["p50"],
        "publish_complete_ms_p95": publish["p95"],
        "publish_complete_ms_p99": publish["p99"],
        "delivery_latency_ms_avg": delivery["avg"],
        "delivery_latency_ms_p50": delivery["p50"],
        "delivery_latency_ms_p95": delivery["p95"],
        "delivery_latency_ms_p99": delivery["p99"],
        "payload_plain_bytes_avg": avg(pub_rows, ["payload_plain_bytes", "plain_bytes", "payload_bytes"]),
        "payload_padded_bytes_avg": avg(pub_rows, ["payload_padded_bytes", "padded_plain_bytes", "padded_bytes"]),
        "payload_encrypted_bytes_avg": avg(pub_rows, ["payload_encrypted_bytes", "encrypted_bytes", "mqtt_payload_bytes"]),
        "padding_added_bytes_avg": avg(pub_rows, ["padding_added_bytes", "padding_bytes"]),
        "rotation_overlap_duplicates": rotation_overlap_duplicates,
        "control_accepted": "",
        "control_rejected": "",
        "transparency_entries": "",
        "transparency_verified_entries": "",
        "status": "measured",
        "notes": f"AOMQTT measurement collected from {publisher_csv} and {subscriber_csv}",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--scenario-id", default="aomqtt_basic")
    parser.add_argument("--scenario-type", default="aomqtt_data_plane")
    parser.add_argument("--broker", default="localhost:1883")
    parser.add_argument("--qos", type=int, default=1)
    parser.add_argument("--publisher-csv", required=True)
    parser.add_argument("--subscriber-csv", required=True)
    parser.add_argument("--summary-json", required=True)
    args = parser.parse_args(argv)

    summary = build_summary(
        run_id=args.run_id,
        scenario_id=args.scenario_id,
        scenario_type=args.scenario_type,
        broker=args.broker,
        qos=args.qos,
        publisher_csv=Path(args.publisher_csv),
        subscriber_csv=Path(args.subscriber_csv),
    )

    out = Path(args.summary_json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2, sort_keys=True))
    print(f"wrote {out}")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

