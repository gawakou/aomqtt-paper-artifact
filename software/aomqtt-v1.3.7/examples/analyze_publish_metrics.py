#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from statistics import mean


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    idx = min(len(values) - 1, int(p * (len(values) - 1)))
    return values[idx]


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize AOMQTT publish metrics CSV")
    parser.add_argument("csv_file")
    args = parser.parse_args()

    with open(args.csv_file, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    total = len(rows)
    success = sum(1 for r in rows if r.get("success") == "True")
    failed = total - success
    lat = [float(r["publish_complete_ms"]) for r in rows if r.get("success") == "True"]
    duplicates = sum(1 for r in rows if r.get("overlap_duplicate") == "True")
    overlap = sum(1 for r in rows if r.get("rotation_in_overlap") == "True")
    reconnect_count = int(rows[-1]["reconnect_count"]) if rows else 0
    plain_sizes = [int(r.get("payload_plain_bytes") or 0) for r in rows]
    padded_sizes = [int(r.get("payload_padded_bytes") or r.get("payload_plain_bytes") or 0) for r in rows]
    encrypted_sizes = [int(r.get("payload_encrypted_bytes") or 0) for r in rows]
    padding_added = [int(r.get("padding_added_bytes") or 0) for r in rows]
    total_overhead = [int(r.get("payload_total_overhead_bytes") or (int(r.get("payload_encrypted_bytes") or 0) - int(r.get("payload_plain_bytes") or 0))) for r in rows]

    print("AOMQTT publish metrics summary")
    print(f"  total MQTT messages: {total}")
    print(f"  success:             {success}")
    print(f"  failed:              {failed}")
    print(f"  success_rate:        {(success / total) if total else 0.0:.3f}")
    print(f"  avg_complete_ms:     {mean(lat) if lat else 0.0:.3f}")
    print(f"  p95_complete_ms:     {percentile(lat, 0.95):.3f}")
    print(f"  overlap_messages:    {overlap}")
    print(f"  overlap_duplicates:  {duplicates}")
    print(f"  reconnect_count:     {reconnect_count}")
    if rows:
        print(f"  avg_plain_bytes:     {mean(plain_sizes):.1f}")
        print(f"  avg_padded_bytes:    {mean(padded_sizes):.1f}")
        print(f"  avg_encrypted_bytes: {mean(encrypted_sizes):.1f}")
        print(f"  avg_padding_added:   {mean(padding_added):.1f}")
        print(f"  avg_total_overhead:  {mean(total_overhead):.1f}")


if __name__ == "__main__":
    main()
