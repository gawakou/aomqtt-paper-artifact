#!/usr/bin/env python3
"""Collect v1.3.0 large-scale evaluation planning artifacts into paper-ready tables."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


def load_json(path: Path) -> Any:
    with path.open() as f:
        return json.load(f)


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("")
        return
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def collect_release_rows(summary: dict[str, Any]) -> list[dict[str, Any]]:
    rows = [
        {"category": "aggregate", "name": "scenario_count", "value": summary.get("scenario_count", 0)},
        {"category": "aggregate", "name": "environment_count", "value": summary.get("environment_count", 0)},
        {"category": "aggregate", "name": "planned_logical_messages", "value": summary.get("planned_logical_messages", 0)},
        {"category": "aggregate", "name": "planned_expected_mqtt_messages", "value": summary.get("planned_expected_mqtt_messages", 0)},
        {"category": "aggregate", "name": "planned_control_messages", "value": summary.get("planned_control_messages", 0)},
        {"category": "aggregate", "name": "planned_transparency_entries", "value": summary.get("planned_transparency_entries", 0)},
        {"category": "safety", "name": "public_broker_allowed_scenarios", "value": summary.get("public_broker_allowed_scenarios", 0)},
        {"category": "safety", "name": "public_broker_disallowed_scenarios", "value": summary.get("public_broker_disallowed_scenarios", 0)},
    ]
    for category, count in sorted(summary.get("category_counts", {}).items()):
        rows.append({"category": "scenario_category", "name": category, "value": count})
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result-dir", default="results/run-v130-large-scale-evaluation-001")
    args = parser.parse_args(argv)

    result_dir = Path(args.result_dir)
    summary_path = result_dir / "v130_large_scale_summary.json"
    if not summary_path.exists():
        raise SystemExit(f"missing {summary_path}; run experiments/run_v130_large_scale_scenarios.py first")

    summary = load_json(summary_path)
    rows = collect_release_rows(summary)
    out_csv = result_dir / "v130_release_table.csv"
    out_json = result_dir / "v130_release_table.json"

    write_csv(rows, out_csv)
    with out_json.open("w") as f:
        json.dump({"rows": rows}, f, indent=2, sort_keys=True)

    print(f"wrote {out_csv}")
    print(f"wrote {out_json}")
    with out_csv.open() as f:
        print(f.read(), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

