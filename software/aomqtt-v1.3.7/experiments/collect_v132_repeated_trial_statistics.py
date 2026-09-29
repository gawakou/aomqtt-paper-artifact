#!/usr/bin/env python3
"""Collect repeated v1.3.1 local comparison trials into v1.3.2 statistics tables."""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from pathlib import Path
from typing import Any


METRICS = [
    "delivery_latency_ms_p95",
    "publish_complete_ms_p95",
    "payload_plain_bytes_avg",
    "payload_encrypted_bytes_avg",
    "mqtt_expansion_ratio",
    "duplicate_ratio_vs_logical",
    "success_ratio",
]


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


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def resolve_input_path(path: Path) -> Path:
    if path.is_file():
        return path
    candidates = [
        path / "v131_local_comparison_table.csv",
        path / "unified_measurements.csv",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"no supported measurement CSV found under {path}")


def trial_id_for_path(path: Path) -> str:
    parent = path.parent.name
    if parent:
        return parent
    return path.stem


def normalize_rows(path: Path) -> list[dict[str, Any]]:
    csv_path = resolve_input_path(path)
    rows = read_csv(csv_path)
    trial_id = trial_id_for_path(csv_path)

    normalized: list[dict[str, Any]] = []
    for row in rows:
        logical = to_float(row.get("logical_messages")) or 0.0
        mqtt = to_float(row.get("mqtt_messages")) or 0.0
        success = to_float(row.get("success_messages")) or 0.0
        duplicates = to_float(row.get("duplicates")) or 0.0

        out = dict(row)
        out["trial_id"] = trial_id
        out["source_file"] = str(csv_path)
        out["mqtt_expansion_ratio"] = mqtt / logical if logical else ""
        out["duplicate_ratio_vs_logical"] = duplicates / logical if logical else ""
        out["success_ratio"] = success / logical if logical else ""
        normalized.append(out)

    return normalized


def mean(values: list[float]) -> float:
    return float(statistics.mean(values)) if values else 0.0


def stdev(values: list[float]) -> float:
    return float(statistics.stdev(values)) if len(values) >= 2 else 0.0


def ci95(values: list[float]) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    m = mean(values)
    if len(values) < 2:
        return m, m
    se = stdev(values) / math.sqrt(len(values))
    margin = 1.96 * se
    return m - margin, m + margin


def summarize_metric(scenario_id: str, metric: str, values: list[float]) -> dict[str, Any]:
    low, high = ci95(values)
    return {
        "scenario_id": scenario_id,
        "metric": metric,
        "n": len(values),
        "mean": mean(values),
        "stddev": stdev(values),
        "stderr": stdev(values) / math.sqrt(len(values)) if len(values) >= 2 else 0.0,
        "ci95_low": low,
        "ci95_high": high,
        "min": min(values) if values else 0.0,
        "max": max(values) if values else 0.0,
    }


def build_statistics(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scenario_ids = sorted({str(row.get("scenario_id", "")) for row in rows if row.get("scenario_id")})
    stats_rows: list[dict[str, Any]] = []

    for scenario_id in scenario_ids:
        scenario_rows = [row for row in rows if row.get("scenario_id") == scenario_id]
        for metric in METRICS:
            values = []
            for row in scenario_rows:
                value = to_float(row.get(metric))
                if value is not None:
                    values.append(value)
            if values:
                stats_rows.append(summarize_metric(scenario_id, metric, values))

    return stats_rows


def build_paper_rows(stats_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_scenario: dict[str, dict[str, dict[str, Any]]] = {}
    for row in stats_rows:
        by_scenario.setdefault(row["scenario_id"], {})[row["metric"]] = row

    paper_rows: list[dict[str, Any]] = []
    for scenario_id in sorted(by_scenario):
        metrics = by_scenario[scenario_id]

        def m(metric: str, field: str = "mean") -> Any:
            return metrics.get(metric, {}).get(field, "")

        paper_rows.append(
            {
                "scenario_id": scenario_id,
                "n": m("delivery_latency_ms_p95", "n") or m("publish_complete_ms_p95", "n"),
                "delivery_p95_mean_ms": m("delivery_latency_ms_p95"),
                "delivery_p95_stddev_ms": m("delivery_latency_ms_p95", "stddev"),
                "delivery_p95_ci95_low_ms": m("delivery_latency_ms_p95", "ci95_low"),
                "delivery_p95_ci95_high_ms": m("delivery_latency_ms_p95", "ci95_high"),
                "publish_p95_mean_ms": m("publish_complete_ms_p95"),
                "publish_p95_stddev_ms": m("publish_complete_ms_p95", "stddev"),
                "publish_p95_ci95_low_ms": m("publish_complete_ms_p95", "ci95_low"),
                "publish_p95_ci95_high_ms": m("publish_complete_ms_p95", "ci95_high"),
                "payload_encrypted_bytes_avg_mean": m("payload_encrypted_bytes_avg"),
                "mqtt_expansion_ratio_mean": m("mqtt_expansion_ratio"),
                "duplicate_ratio_vs_logical_mean": m("duplicate_ratio_vs_logical"),
                "success_ratio_mean": m("success_ratio"),
            }
        )
    return paper_rows


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("")
        return
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_json(data: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", nargs="+", required=True, help="Trial directories or CSV files.")
    parser.add_argument("--out-dir", default="results/run-v132-repeated-trials-001")
    args = parser.parse_args(argv)

    trial_rows: list[dict[str, Any]] = []
    for item in args.inputs:
        trial_rows.extend(normalize_rows(Path(item)))

    if not trial_rows:
        raise SystemExit("no trial rows found")

    stats_rows = build_statistics(trial_rows)
    paper_rows = build_paper_rows(stats_rows)

    out_dir = Path(args.out_dir)
    write_csv(trial_rows, out_dir / "repeated_trial_measurements.csv")
    write_json({"rows": trial_rows}, out_dir / "repeated_trial_measurements.json")
    write_csv(stats_rows, out_dir / "repeated_trial_statistics.csv")
    write_json({"rows": stats_rows}, out_dir / "repeated_trial_statistics.json")
    write_csv(paper_rows, out_dir / "v132_paper_statistics_table.csv")
    write_json({"rows": paper_rows}, out_dir / "v132_paper_statistics_table.json")

    summary = {
        "trial_file_count": len(args.inputs),
        "measurement_row_count": len(trial_rows),
        "scenario_count": len({row["scenario_id"] for row in trial_rows}),
        "scenarios": sorted({row["scenario_id"] for row in trial_rows}),
        "metrics": METRICS,
        "artifacts": {
            "repeated_trial_measurements_csv": str(out_dir / "repeated_trial_measurements.csv"),
            "repeated_trial_statistics_csv": str(out_dir / "repeated_trial_statistics.csv"),
            "v132_paper_statistics_table_csv": str(out_dir / "v132_paper_statistics_table.csv"),
        },
    }
    write_json(summary, out_dir / "v132_repeated_trial_summary.json")

    print(json.dumps(summary, indent=2, sort_keys=True))
    print(f"wrote v1.3.2 repeated-trial artifacts under {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

