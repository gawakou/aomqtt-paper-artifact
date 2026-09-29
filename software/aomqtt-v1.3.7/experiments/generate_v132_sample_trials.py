#!/usr/bin/env python3
"""Generate deterministic v1.3.2 sample repeated-trial inputs.

This script does not send network traffic.  It creates trial directories that
look like repeated v1.3.1 local-comparison outputs.  Use this for validating the
statistics pipeline.  Real repeated trials should use actual measured
v131_local_comparison_table.csv files.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Any


BASE_ROWS = [
    {
        "scenario_id": "plain_mqtt_baseline",
        "logical_messages": 6000,
        "mqtt_messages": 6000,
        "success_messages": 6000,
        "failed_messages": 0,
        "duplicates": 0,
        "delivery_latency_ms_p95": 1.2118816375732422,
        "publish_complete_ms_p95": 1.3044169172644615,
        "payload_plain_bytes_avg": 132.0025,
        "payload_encrypted_bytes_avg": "",
        "rotation_overlap_duplicates": 0,
        "status": "sample_trial",
    },
    {
        "scenario_id": "aomqtt_basic",
        "logical_messages": 6000,
        "mqtt_messages": 6000,
        "success_messages": 6000,
        "failed_messages": 0,
        "duplicates": 0,
        "delivery_latency_ms_p95": 1.3301372528076172,
        "publish_complete_ms_p95": 1.2691658921539783,
        "payload_plain_bytes_avg": 71.82833333333333,
        "payload_encrypted_bytes_avg": 216.044,
        "rotation_overlap_duplicates": 0,
        "status": "sample_trial",
    },
    {
        "scenario_id": "aomqtt_padding512",
        "logical_messages": 6000,
        "mqtt_messages": 6000,
        "success_messages": 6000,
        "failed_messages": 0,
        "duplicates": 0,
        "delivery_latency_ms_p95": 1.1518001556396484,
        "publish_complete_ms_p95": 1.11008295789361,
        "payload_plain_bytes_avg": 71.83166666666666,
        "payload_encrypted_bytes_avg": 802.0,
        "rotation_overlap_duplicates": 0,
        "status": "sample_trial",
    },
    {
        "scenario_id": "aomqtt_padding512_rotation30_overlap5",
        "logical_messages": 6000,
        "mqtt_messages": 9880,
        "success_messages": 6000,
        "failed_messages": 0,
        "duplicates": 3192,
        "delivery_latency_ms_p95": 1.8122196197509766,
        "publish_complete_ms_p95": 1.2501669116318226,
        "payload_plain_bytes_avg": 71.96487854251012,
        "payload_encrypted_bytes_avg": 802.0,
        "rotation_overlap_duplicates": 3880,
        "status": "sample_trial",
    },
]


FIELDS = [
    "scenario_id",
    "logical_messages",
    "mqtt_messages",
    "success_messages",
    "failed_messages",
    "duplicates",
    "delivery_latency_ms_p95",
    "publish_complete_ms_p95",
    "payload_plain_bytes_avg",
    "payload_encrypted_bytes_avg",
    "rotation_overlap_duplicates",
    "status",
]


def jitter(value: Any, trial_index: int, scale: float) -> Any:
    if value == "":
        return value
    if isinstance(value, int):
        return value
    try:
        v = float(value)
    except (TypeError, ValueError):
        return value
    # Deterministic centered variation: -2, -1, 0, 1, 2 for five trials.
    offset = trial_index - 3
    return v * (1.0 + offset * scale)


def generate_trials(out_dir: Path, trial_count: int) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for i in range(1, trial_count + 1):
        trial_dir = out_dir / f"trial-{i:02d}"
        trial_dir.mkdir(parents=True, exist_ok=True)
        rows = []
        for row in BASE_ROWS:
            r = dict(row)
            r["delivery_latency_ms_p95"] = jitter(r["delivery_latency_ms_p95"], i, 0.015)
            r["publish_complete_ms_p95"] = jitter(r["publish_complete_ms_p95"], i, 0.012)
            # Keep counts and payload sizes fixed in sample trials.
            rows.append(r)

        with (trial_dir / "v131_local_comparison_table.csv").open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)

    print(f"wrote {trial_count} sample trial directories under {out_dir}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", default="results/run-v132-repeated-trials-001/trials")
    parser.add_argument("--trial-count", type=int, default=5)
    args = parser.parse_args(argv)

    if args.trial_count < 1:
        raise SystemExit("--trial-count must be >= 1")

    generate_trials(Path(args.out_dir), args.trial_count)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

