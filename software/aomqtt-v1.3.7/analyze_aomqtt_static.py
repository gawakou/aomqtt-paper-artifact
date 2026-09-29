#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import pandas as pd


def analyze_publisher(path: Path) -> None:
    df = pd.read_csv(path)
    logical = int(df["logical_seq"].nunique())
    correct_total = int(
        df.groupby("logical_seq")["mqtt_messages_for_logical"].max().sum()
    )

    print(f"file: {path}")
    print(f"rows: {len(df)}")
    print(f"logical messages: {logical}")
    print(f"correct MQTT total: {correct_total}")
    print(f"extra sends: {correct_total - logical}")
    print(f"extra-send rate: {(correct_total - logical) / logical:.6f}")
    print(f"success: {int(df['success'].sum())}")
    print(f"error count: {int(df['error'].notna().sum())}")
    print(f"publish avg ms: {df['publish_complete_ms'].mean():.6f}")
    print(f"publish p95 ms: {df['publish_complete_ms'].quantile(0.95):.6f}")
    print(f"publish p99 ms: {df['publish_complete_ms'].quantile(0.99):.6f}")
    print(f"publish max ms: {df['publish_complete_ms'].max():.6f}")
    if "payload_encrypted_bytes" in df:
        print(f"encrypted payload avg bytes: {df['payload_encrypted_bytes'].mean():.3f}")


def analyze_subscriber(path: Path, expected: int) -> None:
    df = pd.read_csv(path)
    logical = int(df["logical_seq"].nunique())
    duplicate = df["duplicate"].astype(bool)
    latency = df.loc[~duplicate, "delivery_latency_ms"]

    print(f"file: {path}")
    print(f"rows: {len(df)}")
    print(f"logical messages: {logical}")
    print(f"missing: {max(0, expected - logical)}")
    print(f"duplicates: {int(duplicate.sum())}")
    print(f"decrypt success: {int(df['decrypt_success'].sum())}")
    print(f"decrypt failure: {int((~df['decrypt_success'].astype(bool)).sum())}")
    print(f"error count: {int(df['error'].notna().sum())}")
    print(f"first-receive latency rows: {len(latency)}")
    print(f"latency avg ms: {latency.mean():.6f}")
    print(f"latency p50 ms: {latency.quantile(0.50):.6f}")
    print(f"latency p95 ms: {latency.quantile(0.95):.6f}")
    print(f"latency p99 ms: {latency.quantile(0.99):.6f}")
    print(f"latency max ms: {latency.max():.6f}")
    if "payload_bytes" in df:
        print(f"payload avg bytes: {df['payload_bytes'].mean():.3f}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("role", choices=["publisher", "subscriber"])
    parser.add_argument("run_id")
    parser.add_argument("--results-dir", default="results")
    parser.add_argument("--expected", type=int, default=6000)
    args = parser.parse_args()

    base = Path(args.results_dir) / args.run_id
    if args.role == "publisher":
        path = base / "publisher_metrics.csv"
        analyze_publisher(path)
    else:
        path = base / "subscriber_metrics.csv"
        analyze_subscriber(path, args.expected)


if __name__ == "__main__":
    main()
