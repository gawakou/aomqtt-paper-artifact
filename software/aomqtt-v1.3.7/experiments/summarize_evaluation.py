#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def _float(row: dict[str, str], key: str) -> float:
    try:
        return float(row.get(key) or 0.0)
    except Exception:
        return 0.0


def main() -> None:
    parser = argparse.ArgumentParser(description="Print AOMQTT v0.6 comparison_summary.csv")
    parser.add_argument("result_dir", help="directory created by experiments/run_evaluation.py")
    args = parser.parse_args()

    result_dir = Path(args.result_dir)
    summary_csv = result_dir / "comparison_summary.csv"
    if not summary_csv.exists():
        raise SystemExit(f"not found: {summary_csv}")

    with summary_csv.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    print("AOMQTT v0.6 evaluation summary")
    for row in rows:
        print(
            f"  {row['mode']}: "
            f"pub_success={_float(row, 'publish_success_rate'):.3f}, "
            f"loss={_float(row, 'loss_rate'):.3f}, "
            f"dup={_float(row, 'duplicate_rate_per_unique_received'):.3f}, "
            f"pub_ack_avg_ms={_float(row, 'avg_publish_complete_ms'):.3f}, "
            f"delivery_avg_ms={_float(row, 'avg_delivery_latency_ms'):.3f}, "
            f"plain_B={_float(row, 'avg_payload_plain_bytes'):.1f}, "
            f"padded_B={_float(row, 'avg_payload_padded_bytes'):.1f}, "
            f"encrypted_B={_float(row, 'avg_payload_encrypted_bytes'):.1f}, "
            f"pad_added_B={_float(row, 'avg_padding_added_bytes'):.1f}"
        )

    print(f"\nCSV: {summary_csv}")
    for mode_dir in sorted(p for p in result_dir.iterdir() if p.is_dir()):
        path = mode_dir / "summary.json"
        if path.exists():
            with path.open(encoding="utf-8") as f:
                data = json.load(f)
            print(f"JSON: {path} ({data.get('published_logical_messages', 0)} logical messages)")


if __name__ == "__main__":
    main()
