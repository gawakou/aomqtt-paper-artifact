#!/usr/bin/env python3
"""
Summarize successful AOMQTT E5 formal closed-loop runs.

By default, scans results/e5/e5-*/final/closed_loop_summary.json and includes
only runs with formal_pass=true. Pilot/failed runs remain untouched and are
reported separately.

Outputs under --out-root:
  e5_formal_runs.csv
  e5_formal_summary.json
  e5_formal_summary.txt
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from pathlib import Path
from typing import Any


REQUIRED_TRUE_GATES = [
    "pre_publisher_reconnect_zero",
    "pre_publisher_failed_logical_zero",
    "pre_duplicate_rate_gt_0_10",
    "controller_action_decrease_overlap",
    "generated_overlap_expected",
    "publisher_ack_applied",
    "subscriber_ack_applied",
    "post_generated_policy_publisher",
    "post_generated_policy_subscriber",
    "post_duplicate_rate_lower",
    "post_duplicate_rate_below_threshold",
    "post_publisher_reconnect_zero",
    "post_publisher_failed_logical_zero",
    "post_loss_zero",
    "post_decrypt_success_one",
]


def mean_sd(values: list[float]) -> tuple[float | None, float | None]:
    if not values:
        return None, None
    mean = statistics.mean(values)
    sd = statistics.stdev(values) if len(values) >= 2 else 0.0
    return mean, sd


def fmt(v: float | None, digits: int = 6) -> str:
    if v is None:
        return "None"
    return f"{v:.{digits}f}"


def pct(v: float | None, digits: int = 3) -> str:
    if v is None:
        return "None"
    return f"{100.0 * v:.{digits}f}%"


def load_run(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    data["_summary_path"] = str(path)
    data["_run_dir"] = str(path.parents[1])
    return data


def get_metric(run: dict[str, Any], phase: str, key: str) -> float | None:
    v = run.get(phase, {}).get(key)
    return None if v is None else float(v)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results-root", default="results/e5")
    ap.add_argument("--out-root", default="results/analysis/e5-closed-loop")
    ap.add_argument(
        "--expected-runs",
        type=int,
        default=5,
        help="expected number of successful formal runs",
    )
    args = ap.parse_args()

    results_root = Path(args.results_root).resolve()
    out_root = Path(args.out_root).resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    summary_paths = sorted(
        results_root.glob("e5-*/final/closed_loop_summary.json")
    )
    if not summary_paths:
        raise SystemExit(f"no E5 summaries found under {results_root}")

    all_runs = [load_run(p) for p in summary_paths]
    formal_runs: list[dict[str, Any]] = []
    rejected_runs: list[dict[str, Any]] = []

    for run in all_runs:
        gates = run.get("gates", {})
        gate_complete = all(g in gates for g in REQUIRED_TRUE_GATES)
        gates_true = gate_complete and all(bool(gates[g]) for g in REQUIRED_TRUE_GATES)
        if bool(run.get("formal_pass")) and gates_true:
            formal_runs.append(run)
        else:
            rejected_runs.append(run)

    rows = []
    for run in formal_runs:
        pre_dup = get_metric(run, "pre", "duplicate_rate_per_received_row")
        post_dup = get_metric(run, "post", "duplicate_rate_per_received_row")
        pre_loss = get_metric(run, "pre", "loss_rate")
        post_loss = get_metric(run, "post", "loss_rate")
        pre_dec = get_metric(run, "pre", "decrypt_success_rate")
        post_dec = get_metric(run, "post", "decrypt_success_rate")
        pre_phys = get_metric(
            run, "pre", "physical_publish_rows_per_successful_logical_message"
        )
        post_phys = get_metric(
            run, "post", "physical_publish_rows_per_successful_logical_message"
        )

        abs_dup_drop = (
            pre_dup - post_dup
            if pre_dup is not None and post_dup is not None
            else None
        )
        rel_dup_drop = (
            abs_dup_drop / pre_dup
            if abs_dup_drop is not None and pre_dup not in (None, 0.0)
            else None
        )

        rows.append(
            {
                "run_id": run.get("run_id"),
                "broker": run.get("broker"),
                "initial_overlap_sec": run.get("initial_overlap_sec"),
                "generated_overlap_sec": run.get("generated_overlap_sec"),
                "overlap_step_sec": run.get("overlap_step_sec"),
                "pre_duplicate_rate": pre_dup,
                "post_duplicate_rate": post_dup,
                "duplicate_rate_drop": abs_dup_drop,
                "duplicate_rate_relative_reduction": rel_dup_drop,
                "pre_loss_rate": pre_loss,
                "post_loss_rate": post_loss,
                "pre_decrypt_success_rate": pre_dec,
                "post_decrypt_success_rate": post_dec,
                "pre_physical_per_logical": pre_phys,
                "post_physical_per_logical": post_phys,
                "pre_publisher_reconnects": run.get("pre", {}).get(
                    "publisher_reconnect_count"
                ),
                "post_publisher_reconnects": run.get("post", {}).get(
                    "publisher_reconnect_count"
                ),
                "pre_failed_publisher_logical": run.get("pre", {}).get(
                    "failed_publisher_logical_messages"
                ),
                "post_failed_publisher_logical": run.get("post", {}).get(
                    "failed_publisher_logical_messages"
                ),
                "formal_pass": run.get("formal_pass"),
                "summary_path": run.get("_summary_path"),
            }
        )

    csv_path = out_root / "e5_formal_runs.csv"
    if rows:
        with csv_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
    else:
        csv_path.write_text("", encoding="utf-8")

    metrics_to_aggregate = {
        "pre_duplicate_rate": [r["pre_duplicate_rate"] for r in rows],
        "post_duplicate_rate": [r["post_duplicate_rate"] for r in rows],
        "duplicate_rate_drop": [r["duplicate_rate_drop"] for r in rows],
        "duplicate_rate_relative_reduction": [
            r["duplicate_rate_relative_reduction"] for r in rows
        ],
        "pre_loss_rate": [r["pre_loss_rate"] for r in rows],
        "post_loss_rate": [r["post_loss_rate"] for r in rows],
        "pre_physical_per_logical": [r["pre_physical_per_logical"] for r in rows],
        "post_physical_per_logical": [r["post_physical_per_logical"] for r in rows],
    }

    aggregate: dict[str, Any] = {}
    for key, vals in metrics_to_aggregate.items():
        clean = [float(v) for v in vals if v is not None]
        m, sd = mean_sd(clean)
        aggregate[key] = {
            "n": len(clean),
            "mean": m,
            "sd": sd,
            "min": min(clean) if clean else None,
            "max": max(clean) if clean else None,
        }

    formal_summary = {
        "schema": "aomqtt-e5-formal-summary-v1",
        "results_root": str(results_root),
        "successful_formal_runs": len(formal_runs),
        "expected_formal_runs": args.expected_runs,
        "formal_set_complete": len(formal_runs) >= args.expected_runs,
        "formal_run_ids": [r.get("run_id") for r in formal_runs],
        "nonformal_or_failed_run_ids": [r.get("run_id") for r in rejected_runs],
        "all_required_gates": REQUIRED_TRUE_GATES,
        "aggregate": aggregate,
    }

    json_path = out_root / "e5_formal_summary.json"
    json_path.write_text(
        json.dumps(formal_summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    lines = [
        "AOMQTT E5 formal closed-loop summary",
        "====================================",
        f"successful formal runs: {len(formal_runs)} / expected {args.expected_runs}",
        f"formal set complete: {formal_summary['formal_set_complete']}",
        f"formal run IDs: {formal_summary['formal_run_ids']}",
        f"nonformal/failed run IDs: {formal_summary['nonformal_or_failed_run_ids']}",
        "",
    ]

    if formal_runs:
        pre_dup = aggregate["pre_duplicate_rate"]
        post_dup = aggregate["post_duplicate_rate"]
        drop = aggregate["duplicate_rate_drop"]
        rel = aggregate["duplicate_rate_relative_reduction"]
        pre_phys = aggregate["pre_physical_per_logical"]
        post_phys = aggregate["post_physical_per_logical"]

        lines += [
            "duplicate rate / received row:",
            f"  pre mean ± SD:  {pct(pre_dup['mean'])} ± {pct(pre_dup['sd'])}",
            f"  post mean ± SD: {pct(post_dup['mean'])} ± {pct(post_dup['sd'])}",
            f"  absolute drop:   {pct(drop['mean'])} ± {pct(drop['sd'])}",
            f"  relative reduction: {pct(rel['mean'])} ± {pct(rel['sd'])}",
            "",
            "physical MQTT rows / successful logical message:",
            f"  pre mean ± SD:  {fmt(pre_phys['mean'])} ± {fmt(pre_phys['sd'])}",
            f"  post mean ± SD: {fmt(post_phys['mean'])} ± {fmt(post_phys['sd'])}",
            "",
            "loss:",
            f"  pre mean:  {pct(aggregate['pre_loss_rate']['mean'])}",
            f"  post mean: {pct(aggregate['post_loss_rate']['mean'])}",
            "",
        ]

    lines.append(
        "E5-FORMAL-SET="
        + ("PASS" if formal_summary["formal_set_complete"] else "INCOMPLETE")
    )

    txt_path = out_root / "e5_formal_summary.txt"
    txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print()
    print(f"CSV:  {csv_path}")
    print(f"JSON: {json_path}")
    print(f"TXT:  {txt_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
