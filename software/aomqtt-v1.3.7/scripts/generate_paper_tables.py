#!/usr/bin/env python3
"""Generate paper-ready CSV tables for AOMQTT evaluation results.

This script reads derived evaluation summaries under:

    results/<run_id>/derived/

and writes paper-ready CSV tables under:

    results/<run_id>/paper/tables/

The script is intentionally lightweight and depends only on the Python
standard library so that it can run in minimal research environments.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Iterable


TABLE_SPECS = {
    "policy_comparison": {
        "source": "policy_comparison_summary.csv",
        "target": "table_policy_comparison.csv",
        "preferred_columns": [
            "run_id",
            "scenario",
            "policy_id",
            "token_mode",
            "padding_mode",
            "rotation_enabled",
            "publish_count",
            "receive_count",
            "duplicate_count",
            "loss_count",
            "success_rate",
            "delivery_rate",
            "duplicate_rate",
            "avg_publish_complete_ms",
            "p95_publish_complete_ms",
            "avg_padding_added_bytes",
            "avg_encrypted_bytes",
        ],
        "fallback_columns": [
            "run_id",
            "scenario",
            "policy_id",
            "success_rate",
            "delivery_rate",
            "duplicate_rate",
            "avg_publish_complete_ms",
        ],
    },
    "ack_status": {
        "source": "ack_status_summary.csv",
        "target": "table_ack_status_summary.csv",
        "preferred_columns": [
            "run_id",
            "scenario",
            "ack_status",
            "count",
            "ratio",
        ],
        "fallback_columns": [
            "run_id",
            "scenario",
            "ack_status",
            "count",
            "ratio",
        ],
    },
    "reason_code": {
        "source": "reason_code_summary.csv",
        "target": "table_reason_code_summary.csv",
        "preferred_columns": [
            "run_id",
            "scenario",
            "reason_code",
            "count",
            "ratio",
        ],
        "fallback_columns": [
            "run_id",
            "scenario",
            "reason_code",
            "count",
            "ratio",
        ],
    },
}


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    return fieldnames, rows


def write_csv(path: Path, fieldnames: Iterable[str], rows: Iterable[dict[str, str]]) -> None:
    field_list = list(fieldnames)
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=field_list, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in field_list})


def choose_columns(
    actual_columns: list[str],
    preferred_columns: list[str],
    fallback_columns: list[str],
) -> list[str]:
    selected = [column for column in preferred_columns if column in actual_columns]
    if selected:
        return selected
    return fallback_columns


def generate_tables(results_dir: Path, strict: bool = False) -> list[Path]:
    derived_dir = results_dir / "derived"
    tables_dir = results_dir / "paper" / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)

    generated: list[Path] = []

    for name, spec in TABLE_SPECS.items():
        source_path = derived_dir / spec["source"]
        target_path = tables_dir / spec["target"]

        if not source_path.exists():
            message = f"[WARN] Missing source file for {name}: {source_path}"
            if strict:
                raise FileNotFoundError(message)
            print(message, file=sys.stderr)
            write_csv(target_path, spec["fallback_columns"], [])
            generated.append(target_path)
            continue

        actual_columns, rows = read_csv(source_path)
        columns = choose_columns(
            actual_columns,
            spec["preferred_columns"],
            spec["fallback_columns"],
        )
        write_csv(target_path, columns, rows)
        generated.append(target_path)
        print(f"[OK] Generated {target_path}")

    return generated


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate paper-ready CSV tables for AOMQTT evaluation results."
    )
    parser.add_argument(
        "--results-dir",
        required=True,
        type=Path,
        help="Path to results/<run_id>/",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail if required derived CSV files are missing.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    results_dir = args.results_dir

    if not results_dir.exists():
        print(f"[ERROR] Results directory does not exist: {results_dir}", file=sys.stderr)
        return 1

    generate_tables(results_dir, strict=args.strict)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
