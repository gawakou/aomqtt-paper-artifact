#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from statistics import mean


def as_bool(value: str) -> bool:
    return str(value).lower() in {"true", "1", "yes"}


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    idx = min(len(values) - 1, int(p * (len(values) - 1)))
    return values[idx]


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize AOMQTT subscriber delivery metrics CSV")
    parser.add_argument("csv_file")
    args = parser.parse_args()

    with open(args.csv_file, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    total = len(rows)
    ok = [r for r in rows if as_bool(r.get("decrypt_success", ""))]
    failed = total - len(ok)
    ids = [r.get("message_id", "") for r in ok if r.get("message_id", "")]
    unique = len(set(ids))
    duplicates = sum(1 for r in ok if as_bool(r.get("duplicate", "")))
    lat = [float(r["delivery_latency_ms"]) for r in ok if float(r.get("delivery_latency_ms") or -1) >= 0]

    print("AOMQTT delivery metrics summary")
    print(f"  total received:       {total}")
    print(f"  decrypt success:      {len(ok)}")
    print(f"  decrypt failed:       {failed}")
    print(f"  unique messages:      {unique}")
    print(f"  duplicates:           {duplicates}")
    print(f"  duplicate_rate:       {(duplicates / len(ok)) if ok else 0.0:.3f}")
    print(f"  avg_delivery_ms:      {mean(lat) if lat else 0.0:.3f}")
    print(f"  p95_delivery_ms:      {percentile(lat, 0.95):.3f}")


if __name__ == "__main__":
    main()
