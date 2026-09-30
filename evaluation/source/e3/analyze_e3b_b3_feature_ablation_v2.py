#!/usr/bin/env python3
"""
B3 feature ablation for the AOMQTT E3 privacy evaluation.

Purpose
-------
Recompute the E3-B3 Leave-One-Run-Out (LORO) token-linking analysis from the
frozen `e3b_pair_scores.csv` with three feature sets:

1. full:
   the original 10 pair features, including `overlap_cooccurrence_ratio`
2. base_no_cooccurrence:
   the same analysis with `overlap_cooccurrence_ratio` excluded
3. cooccurrence_only:
   only `overlap_cooccurrence_ratio`

This script does NOT use the existing `probability_same_topic` column; all
classifier probabilities are recomputed from the frozen pair features.

The classifier and assignment procedure mirror `analyze_e3_privacy.py`:
- StandardScaler
- LogisticRegression(class_weight="balanced", solver="liblinear",
                     max_iter=2000, random_state=0)
- five-fold Leave-One-Run-Out
- 8 x 8 same-topic probability matrix per transition
- Hungarian one-to-one assignment
- Top-1 assignment accuracy and MRR

Expected validation:
The `full` recomputation should reproduce the frozen B3 result
approximately:
  Top-1 = 0.9955
  MRR   = 0.9919
before the base-only ablation is interpreted.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np
from scipy.optimize import linear_sum_assignment
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


FULL_FEATURES = [
    "abs_count_diff",
    "abs_rate_hz_diff",
    "abs_iat_mean_ms_diff",
    "abs_iat_std_ms_diff",
    "abs_iat_cv_diff",
    "abs_payload_mean_bytes_diff",
    "abs_payload_std_bytes_diff",
    "abs_payload_min_bytes_diff",
    "abs_payload_max_bytes_diff",
    "overlap_cooccurrence_ratio",
]

BASE_FEATURES = [
    x for x in FULL_FEATURES if x != "overlap_cooccurrence_ratio"
]

COOCCURRENCE_ONLY_FEATURES = [
    "overlap_cooccurrence_ratio",
]

EXPECTED_RUNS = [f"formal-r{i:02d}" for i in range(1, 6)]
EXPECTED_TRANSITIONS = list(range(1, 12))


def sample_std(values: Sequence[float]) -> float:
    return float(statistics.stdev(values)) if len(values) >= 2 else 0.0


def mean(values: Sequence[float]) -> float:
    return float(statistics.mean(values)) if values else 0.0


def read_b3_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(path)

    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise RuntimeError("CSV has no header")

        required = {
            "condition",
            "held_out_run",
            "transition_epoch",
            "old_token",
            "new_token",
            "old_topic_id",
            "new_topic_id",
            "label",
            *FULL_FEATURES,
        }
        missing = sorted(required - set(reader.fieldnames))
        if missing:
            raise RuntimeError(f"missing required CSV columns: {missing}")

        rows = [row for row in reader if row["condition"] == "B3"]

    validate_b3_rows(rows)
    return rows


def validate_b3_rows(rows: Sequence[dict[str, str]]) -> None:
    if len(rows) != 5 * 11 * 64:
        raise RuntimeError(
            f"expected 3520 B3 candidate-pair rows, got {len(rows)}"
        )

    runs = sorted({row["held_out_run"] for row in rows})
    if runs != EXPECTED_RUNS:
        raise RuntimeError(
            f"expected runs {EXPECTED_RUNS}, got {runs}"
        )

    by_run_transition: dict[tuple[str, int], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        by_run_transition[
            (row["held_out_run"], int(row["transition_epoch"]))
        ].append(row)

    for run in EXPECTED_RUNS:
        transitions = sorted(
            t for (r, t) in by_run_transition if r == run
        )
        if transitions != EXPECTED_TRANSITIONS:
            raise RuntimeError(
                f"{run}: expected transitions 1..11, got {transitions}"
            )

        for transition in EXPECTED_TRANSITIONS:
            group = by_run_transition[(run, transition)]
            if len(group) != 64:
                raise RuntimeError(
                    f"{run}/transition-{transition}: "
                    f"expected 64 candidate pairs, got {len(group)}"
                )
            positives = sum(int(row["label"]) for row in group)
            if positives != 8:
                raise RuntimeError(
                    f"{run}/transition-{transition}: "
                    f"expected 8 positive pairs, got {positives}"
                )

            old_tokens = {row["old_token"] for row in group}
            new_tokens = {row["new_token"] for row in group}
            if len(old_tokens) != 8 or len(new_tokens) != 8:
                raise RuntimeError(
                    f"{run}/transition-{transition}: "
                    f"expected 8 old and 8 new tokens, got "
                    f"{len(old_tokens)} / {len(new_tokens)}"
                )


def fit_model(
    train_rows: Sequence[dict[str, str]],
    feature_names: Sequence[str],
) -> Pipeline:
    X = np.asarray(
        [[float(row[name]) for name in feature_names] for row in train_rows],
        dtype=float,
    )
    y = np.asarray([int(row["label"]) for row in train_rows], dtype=int)

    if X.ndim != 2 or X.shape[1] != len(feature_names):
        raise RuntimeError("unexpected feature matrix shape")
    if set(y.tolist()) != {0, 1}:
        raise RuntimeError("training set must contain both classes")

    model = Pipeline(
        steps=[
            ("scale", StandardScaler()),
            (
                "logreg",
                LogisticRegression(
                    class_weight="balanced",
                    solver="liblinear",
                    max_iter=2000,
                    random_state=0,
                ),
            ),
        ]
    )
    model.fit(X, y)
    return model


def score_transition(
    rows: Sequence[dict[str, str]],
    probabilities: Sequence[float],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if len(rows) != 64 or len(probabilities) != 64:
        raise RuntimeError("transition scoring requires exactly 64 pairs")

    old_tokens = sorted({row["old_token"] for row in rows})
    new_tokens = sorted({row["new_token"] for row in rows})
    if len(old_tokens) != 8 or len(new_tokens) != 8:
        raise RuntimeError("expected eight old and eight new tokens")

    old_idx = {token: i for i, token in enumerate(old_tokens)}
    new_idx = {token: i for i, token in enumerate(new_tokens)}

    matrix = np.zeros((8, 8), dtype=float)
    lookup: dict[tuple[str, str], dict[str, str]] = {}

    for row, prob in zip(rows, probabilities):
        old_token = row["old_token"]
        new_token = row["new_token"]
        matrix[old_idx[old_token], new_idx[new_token]] = float(prob)
        lookup[(old_token, new_token)] = row

    # Maximize total same-topic probability.
    row_ind, col_ind = linear_sum_assignment(-matrix)
    assigned = {
        old_tokens[int(r)]: new_tokens[int(c)]
        for r, c in zip(row_ind.tolist(), col_ind.tolist())
    }

    correct = 0
    reciprocal_ranks: list[float] = []
    details: list[dict[str, Any]] = []

    for old_token in old_tokens:
        candidates: list[tuple[float, str, dict[str, str]]] = []
        for new_token in new_tokens:
            row = lookup[(old_token, new_token)]
            prob = float(matrix[old_idx[old_token], new_idx[new_token]])
            candidates.append((prob, new_token, row))

        # Same deterministic ranking rule as the frozen analyzer:
        # descending probability, then lexical token order.
        candidates.sort(key=lambda x: (-x[0], x[1]))

        true_rank = next(
            idx + 1
            for idx, (_prob, _new_token, row) in enumerate(candidates)
            if int(row["label"]) == 1
        )
        reciprocal_rank = 1.0 / true_rank
        reciprocal_ranks.append(reciprocal_rank)

        chosen_new = assigned[old_token]
        chosen_row = lookup[(old_token, chosen_new)]
        is_correct = int(chosen_row["label"]) == 1
        correct += int(is_correct)

        details.append(
            {
                "old_token": old_token,
                "old_topic_id": chosen_row["old_topic_id"],
                "assigned_new_token": chosen_new,
                "assigned_new_topic_id": chosen_row["new_topic_id"],
                "assigned_probability": float(
                    matrix[old_idx[old_token], new_idx[chosen_new]]
                ),
                "assignment_correct": int(is_correct),
                "true_candidate_rank": true_rank,
                "reciprocal_rank": reciprocal_rank,
            }
        )

    return (
        {
            "links": 8,
            "correct_links": correct,
            "top1_assignment_accuracy": correct / 8.0,
            "mrr": mean(reciprocal_ranks),
        },
        details,
    )


def analyze_feature_set(
    rows: Sequence[dict[str, str]],
    *,
    analysis_name: str,
    feature_names: Sequence[str],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    folds: list[dict[str, Any]] = []
    transition_rows: list[dict[str, Any]] = []

    for held_out in EXPECTED_RUNS:
        train_rows = [
            row for row in rows if row["held_out_run"] != held_out
        ]
        test_rows = [
            row for row in rows if row["held_out_run"] == held_out
        ]

        model = fit_model(train_rows, feature_names)
        X_test = np.asarray(
            [[float(row[name]) for name in feature_names] for row in test_rows],
            dtype=float,
        )
        probabilities = model.predict_proba(X_test)[:, 1]

        by_transition: dict[int, list[int]] = defaultdict(list)
        for idx, row in enumerate(test_rows):
            by_transition[int(row["transition_epoch"])].append(idx)

        total_correct = 0
        total_links = 0
        reciprocal_ranks: list[float] = []

        for transition in EXPECTED_TRANSITIONS:
            indices = by_transition[transition]
            group_rows = [test_rows[i] for i in indices]
            group_probs = [float(probabilities[i]) for i in indices]

            metric, details = score_transition(group_rows, group_probs)
            total_correct += metric["correct_links"]
            total_links += metric["links"]
            reciprocal_ranks.extend(
                d["reciprocal_rank"] for d in details
            )

            transition_rows.append(
                {
                    "analysis": analysis_name,
                    "held_out_run": held_out,
                    "transition_epoch": transition,
                    **metric,
                }
            )

        folds.append(
            {
                "analysis": analysis_name,
                "held_out_run": held_out,
                "training_candidate_pairs": len(train_rows),
                "test_candidate_pairs": len(test_rows),
                "links": total_links,
                "correct_links": total_correct,
                "top1_assignment_accuracy": total_correct / total_links,
                "mrr": mean(reciprocal_ranks),
            }
        )

    result = {
        "analysis": analysis_name,
        "feature_names": list(feature_names),
        "classifier": (
            "StandardScaler + LogisticRegression("
            "class_weight='balanced', solver='liblinear', random_state=0)"
        ),
        "validation": "Leave-One-Run-Out",
        "folds": folds,
        "mean_top1_assignment_accuracy": mean(
            [f["top1_assignment_accuracy"] for f in folds]
        ),
        "std_top1_assignment_accuracy": sample_std(
            [f["top1_assignment_accuracy"] for f in folds]
        ),
        "mean_mrr": mean([f["mrr"] for f in folds]),
        "std_mrr": sample_std([f["mrr"] for f in folds]),
        "pooled_top1_assignment_accuracy": (
            sum(f["correct_links"] for f in folds)
            / sum(f["links"] for f in folds)
        ),
    }
    return result, transition_rows


def write_csv(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise RuntimeError("no rows to write")
    fieldnames = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="AOMQTT E3-B3 co-occurrence feature ablation"
    )
    p.add_argument(
        "--input",
        type=Path,
        default=Path(
            "results/analysis/e3-privacy/e3b_pair_scores.csv"
        ),
        help="frozen E3-B pair-score CSV",
    )
    p.add_argument(
        "--out-root",
        type=Path,
        default=Path(
            "results/analysis/e3-privacy-b3-ablation"
        ),
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    args.out_root.mkdir(parents=True, exist_ok=True)

    rows = read_b3_rows(args.input)

    full, full_transitions = analyze_feature_set(
        rows,
        analysis_name="B3_full",
        feature_names=FULL_FEATURES,
    )
    base, base_transitions = analyze_feature_set(
        rows,
        analysis_name="B3_base_no_cooccurrence",
        feature_names=BASE_FEATURES,
    )
    co_only, co_only_transitions = analyze_feature_set(
        rows,
        analysis_name="B3_cooccurrence_only",
        feature_names=COOCCURRENCE_ONLY_FEATURES,
    )

    result = {
        "input": str(args.input),
        "condition": "B3",
        "candidate_pair_rows": len(rows),
        "expected_chance_level": 0.125,
        "full": full,
        "base_no_cooccurrence": base,
        "cooccurrence_only": co_only,
        "delta_base_minus_full": {
            "top1": (
                base["mean_top1_assignment_accuracy"]
                - full["mean_top1_assignment_accuracy"]
            ),
            "mrr": base["mean_mrr"] - full["mean_mrr"],
        },
        "delta_cooccurrence_only_minus_full": {
            "top1": (
                co_only["mean_top1_assignment_accuracy"]
                - full["mean_top1_assignment_accuracy"]
            ),
            "mrr": co_only["mean_mrr"] - full["mean_mrr"],
        },
        "delta_full_minus_cooccurrence_only": {
            "top1": (
                full["mean_top1_assignment_accuracy"]
                - co_only["mean_top1_assignment_accuracy"]
            ),
            "mrr": full["mean_mrr"] - co_only["mean_mrr"],
        },
    }

    json_path = args.out_root / "b3_feature_ablation.json"
    json_path.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    fold_rows = full["folds"] + base["folds"] + co_only["folds"]
    write_csv(args.out_root / "b3_feature_ablation_folds.csv", fold_rows)

    transition_rows = (
        full_transitions + base_transitions + co_only_transitions
    )
    write_csv(
        args.out_root / "b3_feature_ablation_transitions.csv",
        transition_rows,
    )

    print("AOMQTT E3-B3 feature ablation")
    print("==============================")
    print(f"input: {args.input}")
    print(f"B3 candidate pairs: {len(rows)}")
    print()
    print(
        "FULL: "
        f"Top-1={full['mean_top1_assignment_accuracy']:.4f} "
        f"(SD={full['std_top1_assignment_accuracy']:.4f}), "
        f"MRR={full['mean_mrr']:.4f} "
        f"(SD={full['std_mrr']:.4f})"
    )
    print(
        "BASE (co-occurrence OFF): "
        f"Top-1={base['mean_top1_assignment_accuracy']:.4f} "
        f"(SD={base['std_top1_assignment_accuracy']:.4f}), "
        f"MRR={base['mean_mrr']:.4f} "
        f"(SD={base['std_mrr']:.4f})"
    )
    print(
        "CO-OCCURRENCE ONLY: "
        f"Top-1={co_only['mean_top1_assignment_accuracy']:.4f} "
        f"(SD={co_only['std_top1_assignment_accuracy']:.4f}), "
        f"MRR={co_only['mean_mrr']:.4f} "
        f"(SD={co_only['std_mrr']:.4f})"
    )
    print(
        "DELTA (BASE - FULL): "
        f"Top-1={result['delta_base_minus_full']['top1']:+.4f}, "
        f"MRR={result['delta_base_minus_full']['mrr']:+.4f}"
    )
    print(
        "DELTA (CO-ONLY - FULL): "
        f"Top-1={result['delta_cooccurrence_only_minus_full']['top1']:+.4f}, "
        f"MRR={result['delta_cooccurrence_only_minus_full']['mrr']:+.4f}"
    )
    print()
    print(f"artifacts: {args.out_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
