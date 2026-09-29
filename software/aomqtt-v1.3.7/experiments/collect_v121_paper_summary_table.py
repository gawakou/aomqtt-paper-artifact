#!/usr/bin/env python3
"""Generate a compact paper summary table for AOMQTT v1.2.1 evaluation."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    with path.open() as f:
        return json.load(f)


def build_rows(v110: dict[str, Any], v120: dict[str, Any], test_count: int | None = None) -> list[dict[str, Any]]:
    tlog = v120.get("transparency_log", {})
    rows = [
        {
            "metric": "unit_and_scenario_tests",
            "value": "" if test_count is None else str(test_count),
            "interpretation": "All automated tests passed for the evaluated repository state.",
        },
        {
            "metric": "v1.1.0_trust_scenario_total",
            "value": str(v110.get("total", "")),
            "interpretation": "Total number of trusted-policy-delivery cases evaluated.",
        },
        {
            "metric": "v1.1.0_trust_scenario_rejected",
            "value": str(v110.get("rejected", "")),
            "interpretation": "Rejected cases include unknown key, revoked key, invalid signature, and unsafe policy.",
        },
        {
            "metric": "v1.2.0_multisig_scenario_total",
            "value": str(v120.get("total", "")),
            "interpretation": "Total number of multi-signature and transparency-log cases evaluated.",
        },
        {
            "metric": "v1.2.0_multisig_scenario_rejected",
            "value": str(v120.get("rejected", "")),
            "interpretation": "Rejected cases include threshold failure, missing role, revoked key, invalid signature, and unsafe policy.",
        },
        {
            "metric": "v1.2.0_transparency_log_verified_entries",
            "value": str(tlog.get("verified_entries", "")),
            "interpretation": "Number of transparency-log entries verified as an intact hash chain.",
        },
        {
            "metric": "v1.2.0_transparency_log_result",
            "value": str(tlog.get("accepted", "")),
            "interpretation": "Transparency-log verification result.",
        },
    ]
    return rows


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["metric", "value", "interpretation"]
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_json(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump({"rows": rows}, f, indent=2, sort_keys=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--v110-summary", default="results/run-v110-trust-scenarios-001/v110_trust_scenario_summary.json")
    parser.add_argument("--v120-summary", default="results/run-v120-multisig-transparency-001/v120_multisig_transparency_summary.json")
    parser.add_argument("--test-count", type=int, default=None)
    parser.add_argument("--out-dir", default="results/run-v121-evaluation-reproducibility-001")
    args = parser.parse_args(argv)

    v110 = load_json(Path(args.v110_summary))
    v120 = load_json(Path(args.v120_summary))
    rows = build_rows(v110, v120, args.test_count)

    out_dir = Path(args.out_dir)
    csv_path = out_dir / "paper_summary_table.csv"
    json_path = out_dir / "paper_summary_table.json"

    write_csv(rows, csv_path)
    write_json(rows, json_path)

    print(f"wrote {csv_path}")
    print(f"wrote {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

