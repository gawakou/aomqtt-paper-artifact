#!/usr/bin/env python3
"""Generate paper-ready figures for AOMQTT evaluation results.

This script reads paper-ready tables or derived summaries under:

    results/<run_id>/paper/tables/
    results/<run_id>/derived/

and writes PNG figures under:

    results/<run_id>/paper/figures/

The script uses matplotlib only. It does not use seaborn or custom color
settings so that generated figures remain simple and reproducible.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Iterable

import matplotlib.pyplot as plt


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []

    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def to_float(value: str, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def save_empty_figure(path: Path, title: str, message: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig = plt.figure(figsize=(8, 4.5))
    plt.title(title)
    plt.text(0.5, 0.5, message, ha="center", va="center")
    plt.axis("off")
    fig.tight_layout()
    fig.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"[WARN] Generated placeholder figure: {path}", file=sys.stderr)


def save_bar_figure(
    path: Path,
    title: str,
    xlabel: str,
    ylabel: str,
    labels: Iterable[str],
    values: Iterable[float],
) -> None:
    labels_list = list(labels)
    values_list = list(values)

    path.parent.mkdir(parents=True, exist_ok=True)

    if not labels_list:
        save_empty_figure(path, title, "No data available")
        return

    fig = plt.figure(figsize=(9, 5))
    x = range(len(labels_list))
    plt.bar(x, values_list)
    plt.xticks(list(x), labels_list, rotation=30, ha="right")
    plt.xlabel(xlabel)
    plt.ylabel(ylabel)
    plt.title(title)
    fig.tight_layout()
    fig.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"[OK] Generated {path}")


def first_existing(paths: list[Path]) -> Path | None:
    for path in paths:
        if path.exists():
            return path
    return None


def generate_ack_status_figure(results_dir: Path) -> Path:
    source = first_existing(
        [
            results_dir / "paper" / "tables" / "table_ack_status_summary.csv",
            results_dir / "derived" / "ack_status_summary.csv",
        ]
    )
    target = results_dir / "paper" / "figures" / "fig_ack_status_breakdown.png"

    rows = read_csv_rows(source) if source else []
    labels = [row.get("ack_status", "unknown") for row in rows]
    values = [to_float(row.get("count", "0")) for row in rows]

    save_bar_figure(
        target,
        title="ACK Status Breakdown",
        xlabel="ACK status",
        ylabel="Count",
        labels=labels,
        values=values,
    )
    return target


def generate_reason_code_figure(results_dir: Path) -> Path:
    source = first_existing(
        [
            results_dir / "paper" / "tables" / "table_reason_code_summary.csv",
            results_dir / "derived" / "reason_code_summary.csv",
        ]
    )
    target = results_dir / "paper" / "figures" / "fig_reason_code_breakdown.png"

    rows = read_csv_rows(source) if source else []
    labels = [row.get("reason_code", "unknown") for row in rows]
    values = [to_float(row.get("count", "0")) for row in rows]

    save_bar_figure(
        target,
        title="Reason Code Breakdown",
        xlabel="Reason code",
        ylabel="Count",
        labels=labels,
        values=values,
    )
    return target


def generate_policy_result_figure(results_dir: Path) -> Path:
    source = first_existing(
        [
            results_dir / "paper" / "tables" / "table_policy_comparison.csv",
            results_dir / "derived" / "policy_comparison_summary.csv",
            results_dir / "derived" / "deployment_summary.csv",
        ]
    )
    target = results_dir / "paper" / "figures" / "fig_policy_result_comparison.png"

    rows = read_csv_rows(source) if source else []

    labels: list[str] = []
    values: list[float] = []

    for index, row in enumerate(rows):
        scenario = row.get("scenario", "")
        policy_id = row.get("policy_id", "")
        label = policy_id or scenario or f"row-{index + 1}"
        labels.append(label)

        if "delivery_rate" in row:
            values.append(to_float(row.get("delivery_rate", "0")))
        elif "apply_rate" in row:
            values.append(to_float(row.get("apply_rate", "0")))
        elif "success_rate" in row:
            values.append(to_float(row.get("success_rate", "0")))
        elif "accept_rate" in row:
            values.append(to_float(row.get("accept_rate", "0")))
        else:
            values.append(0.0)

    save_bar_figure(
        target,
        title="Policy Result Comparison",
        xlabel="Policy or scenario",
        ylabel="Rate",
        labels=labels,
        values=values,
    )
    return target


def generate_figures(results_dir: Path) -> list[Path]:
    figures_dir = results_dir / "paper" / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    generated = [
        generate_ack_status_figure(results_dir),
        generate_policy_result_figure(results_dir),
        generate_reason_code_figure(results_dir),
    ]
    return generated


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate paper-ready PNG figures for AOMQTT evaluation results."
    )
    parser.add_argument(
        "--results-dir",
        required=True,
        type=Path,
        help="Path to results/<run_id>/",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    results_dir = args.results_dir

    if not results_dir.exists():
        print(f"[ERROR] Results directory does not exist: {results_dir}", file=sys.stderr)
        return 1

    generate_figures(results_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
