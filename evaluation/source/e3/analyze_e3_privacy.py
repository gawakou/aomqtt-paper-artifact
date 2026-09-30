#!/usr/bin/env python3
"""Analyze the frozen AOMQTT E3 privacy evaluation.

This script performs two analyses over the already accepted formal runs.

E3-A: broker-visible payload-length inference
----------------------------------------------
Conditions A0/A1/A2 are evaluated separately.  The only classifier input is
``mqtt_payload_bytes`` from the independent broker observer.  Ground-truth
class labels are joined by ``observer_seq == event_index`` only after the
formal gate report has been verified.  Validation is Leave-One-Run-Out (LORO)
over the five formal runs using Gaussian Naive Bayes.

Primary outputs:
    Accuracy
    Macro-F1
    Chance level = 1/8 = 12.5%

E3-B: cross-epoch topic linkability
------------------------------------
B0 is a persistent-token reference only and is not used to train a
cross-epoch classifier.

B1/B2/B3 are evaluated with one binary candidate-pair classifier per
condition.  For each 30-s epoch transition, broker-visible token profiles are
formed in the pre-frozen windows:

    old profile: [t0 - 20 s, t0)
    overlap:     [t0, t0 + 5 s)
    new profile: [t0 + 5 s, t0 + 25 s)

Profile features use only broker-observer data: message rate, inter-arrival
time statistics, and payload-size statistics.  Pair features are absolute
profile differences.  B3 additionally uses a timestamp co-occurrence ratio in
the 5-s overlap window with the pre-frozen 20-ms threshold.

Training is LORO over formal runs with StandardScaler +
LogisticRegression(class_weight="balanced").  For each held-out transition,
the 8x8 candidate probability matrix is converted into a one-to-one mapping
using Hungarian assignment.  Top-1 link accuracy is measured after that
assignment.  MRR is computed from each old token's unassigned candidate
probability ranking.

Important separation:
    * observer.csv supplies every classifier feature.
    * publisher_metrics.csv / ground_truth.csv are used only for evaluation
      labels and integrity checks; their plaintext/epoch fields are never
      classifier features.

The script is analysis-only.  It does not modify any frozen E3-A/E3-B input
artifact.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
import subprocess
import sys
import warnings
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence


ANALYSIS_SCHEMA_VERSION = "e3-privacy-analysis-v1"

E3A_HARNESS_COMMIT = "9f6e64bbb891508f793cc9ea883f9449cffb074a"
E3B_HARNESS_COMMIT = "0b38486ca60c1a7afcf398d96eb39e0388c333ab"
AOMQTT_BASE_COMMIT = "6dc0b2c497098aca569a636d1f8f8bb2adc4253a"

FORMAL_RUN_DIRS = tuple(f"formal-r{i:02d}" for i in range(1, 6))
E3A_CONDITIONS = ("A0", "A1", "A2")
E3B_REFERENCE_CONDITION = "B0"
E3B_CLASSIFIER_CONDITIONS = ("B1", "B2", "B3")
TOPIC_IDS = tuple(f"T{i}" for i in range(1, 9))

ROTATION_INTERVAL_SEC = 30.0
PROFILE_WINDOW_SEC = 20.0
OVERLAP_WINDOW_SEC = 5.0
NEW_PROFILE_OFFSET_SEC = 5.0
COOCCURRENCE_THRESHOLD_MS = 20.0
CHANCE_LEVEL = 1.0 / 8.0

PROFILE_FEATURE_NAMES = (
    "count",
    "rate_hz",
    "iat_mean_ms",
    "iat_std_ms",
    "iat_cv",
    "payload_mean_bytes",
    "payload_std_bytes",
    "payload_min_bytes",
    "payload_max_bytes",
)

PAIR_FEATURE_NAMES = (
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
)


@dataclass(frozen=True)
class ObserverRow:
    observer_seq: int
    recv_unix_ns: int
    mqtt_topic: str
    mqtt_payload_bytes: int


@dataclass(frozen=True)
class TokenProfile:
    token: str
    count: int
    rate_hz: float
    iat_mean_ms: float
    iat_std_ms: float
    iat_cv: float
    payload_mean_bytes: float
    payload_std_bytes: float
    payload_min_bytes: float
    payload_max_bytes: float

    def numeric(self) -> tuple[float, ...]:
        return (
            float(self.count),
            self.rate_hz,
            self.iat_mean_ms,
            self.iat_std_ms,
            self.iat_cv,
            self.payload_mean_bytes,
            self.payload_std_bytes,
            self.payload_min_bytes,
            self.payload_max_bytes,
        )


@dataclass(frozen=True)
class CandidatePair:
    run_dir: str
    condition: str
    transition_epoch: int
    old_token: str
    new_token: str
    old_topic_id: str
    new_topic_id: str
    label: int
    features: tuple[float, ...]


def _require_ml():
    """Import analysis-only dependencies with one actionable error."""
    try:
        import numpy as np
        import sklearn
        import scipy
        from scipy.optimize import linear_sum_assignment
        from sklearn.linear_model import LogisticRegression
        from sklearn.metrics import accuracy_score, f1_score
        from sklearn.naive_bayes import GaussianNB
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import StandardScaler
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError(
            "E3 privacy analysis requires analysis-only dependencies. "
            "Install them in the experiment venv with: "
            "python -m pip install numpy scipy scikit-learn"
        ) from exc

    return {
        "np": np,
        "scipy": scipy,
        "sklearn": sklearn,
        "linear_sum_assignment": linear_sum_assignment,
        "LogisticRegression": LogisticRegression,
        "accuracy_score": accuracy_score,
        "f1_score": f1_score,
        "GaussianNB": GaussianNB,
        "Pipeline": Pipeline,
        "StandardScaler": StandardScaler,
    }


def git_rev_parse(repo: Path, ref: str = "HEAD") -> str:
    try:
        p = subprocess.run(
            ["git", "rev-parse", ref],
            cwd=repo,
            check=True,
            text=True,
            capture_output=True,
        )
        return p.stdout.strip()
    except Exception:
        return ""


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def write_csv(path: Path, rows: Sequence[dict[str, Any]], fieldnames: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        w.writeheader()
        for row in rows:
            w.writerow(row)


def sample_std(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    return float(statistics.stdev(values))


def mean_or_zero(values: Sequence[float]) -> float:
    return float(statistics.mean(values)) if values else 0.0


def verify_gate_pass(condition_dir: Path) -> dict[str, Any]:
    gate = read_json(condition_dir / "gate_report.json")
    if not gate.get("overall_pass", False):
        raise RuntimeError(f"formal gate did not pass: {condition_dir}")
    return gate


def verify_manifest(
    condition_dir: Path,
    *,
    expected_harness_commit: str,
    expected_condition: str,
    require_formal: bool = True,
) -> dict[str, Any]:
    manifest = read_json(condition_dir / "run_manifest.json")
    if manifest.get("condition") != expected_condition:
        raise RuntimeError(
            f"condition mismatch in {condition_dir}: "
            f"{manifest.get('condition')!r} != {expected_condition!r}"
        )
    if manifest.get("harness_commit") != expected_harness_commit:
        raise RuntimeError(
            f"harness commit mismatch in {condition_dir}: "
            f"{manifest.get('harness_commit')!r} != {expected_harness_commit!r}"
        )
    if manifest.get("aomqtt_base_commit") != AOMQTT_BASE_COMMIT:
        raise RuntimeError(
            f"AOMQTT base commit mismatch in {condition_dir}: "
            f"{manifest.get('aomqtt_base_commit')!r}"
        )
    if require_formal and not manifest.get("formal_full_plan", False):
        raise RuntimeError(f"input is not a formal full plan: {condition_dir}")
    return manifest


def load_observer_rows(path: Path) -> list[ObserverRow]:
    rows = read_csv(path)
    out: list[ObserverRow] = []
    for expected_seq, row in enumerate(rows):
        seq = int(row["observer_seq"])
        if seq != expected_seq:
            raise RuntimeError(
                f"non-contiguous observer_seq in {path}: "
                f"row {expected_seq} has {seq}"
            )
        out.append(
            ObserverRow(
                observer_seq=seq,
                recv_unix_ns=int(row["recv_unix_ns"]),
                mqtt_topic=row["mqtt_topic"],
                mqtt_payload_bytes=int(row["mqtt_payload_bytes"]),
            )
        )
    return out


# ---------------------------------------------------------------------------
# E3-A
# ---------------------------------------------------------------------------

def load_e3a_condition(condition_dir: Path) -> tuple[list[list[float]], list[str], dict[str, Any]]:
    """Load one accepted E3-A condition.

    The broker-visible feature is *only* mqtt_payload_bytes.  The class label
    comes from ground_truth.csv after observer sequence integrity is checked.
    """
    gate = verify_gate_pass(condition_dir)
    manifest = verify_manifest(
        condition_dir,
        expected_harness_commit=E3A_HARNESS_COMMIT,
        expected_condition=condition_dir.name,
    )

    observer = load_observer_rows(condition_dir / "observer.csv")
    truth = read_csv(condition_dir / "ground_truth.csv")
    if len(observer) != len(truth):
        raise RuntimeError(
            f"E3-A row-count mismatch in {condition_dir}: "
            f"observer={len(observer)}, truth={len(truth)}"
        )

    X: list[list[float]] = []
    y: list[str] = []
    for i, (obs, gt) in enumerate(zip(observer, truth)):
        if int(gt["event_index"]) != i or obs.observer_seq != i:
            raise RuntimeError(
                f"E3-A join integrity failure in {condition_dir} at row {i}"
            )
        X.append([float(obs.mqtt_payload_bytes)])
        y.append(gt["class_id"])

    expected_labels = set(f"C{i}" for i in range(1, 9))
    if set(y) != expected_labels:
        raise RuntimeError(
            f"E3-A expected eight classes in {condition_dir}; got {sorted(set(y))}"
        )
    return X, y, {"gate": gate, "manifest": manifest}


def _fit_predict_gaussian_nb(X_train, y_train, X_test):
    """GaussianNB with deterministic handling of a completely constant feature.

    A2 intentionally makes mqtt_payload_bytes constant.  In that exact
    zero-information case, scikit-learn's GaussianNB receives zero within-class
    variances and can emit floating-point warnings.  The posterior then reduces
    to class priors.  We handle that mathematically degenerate case explicitly:
    predict the most frequent training class, tie-broken lexicographically.
    No additional feature or jitter is introduced.
    """
    ml = _require_ml()
    np = ml["np"]
    GaussianNB = ml["GaussianNB"]

    x_arr = np.asarray(X_train, dtype=float)
    if x_arr.ndim != 2 or x_arr.shape[1] != 1:
        raise ValueError("E3-A GaussianNB expects exactly one feature")
    if float(np.ptp(x_arr[:, 0])) == 0.0:
        counts = Counter(y_train)
        max_count = max(counts.values())
        choice = sorted(k for k, v in counts.items() if v == max_count)[0]
        return np.asarray([choice] * len(X_test), dtype=object), {
            "degenerate_constant_feature": True,
            "constant_value": float(x_arr[0, 0]),
        }

    model = GaussianNB()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        model.fit(x_arr, np.asarray(y_train))
        pred = model.predict(np.asarray(X_test, dtype=float))
    return pred, {"degenerate_constant_feature": False}


def analyze_e3a(
    e3a_root: Path,
    run_dirs: Sequence[str] = FORMAL_RUN_DIRS,
) -> dict[str, Any]:
    ml = _require_ml()
    np = ml["np"]
    accuracy_score = ml["accuracy_score"]
    f1_score = ml["f1_score"]

    loaded: dict[str, dict[str, tuple[list[list[float]], list[str], dict[str, Any]]]] = {}
    for run_dir in run_dirs:
        loaded[run_dir] = {}
        for condition in E3A_CONDITIONS:
            loaded[run_dir][condition] = load_e3a_condition(
                e3a_root / run_dir / condition
            )

    conditions_out: dict[str, Any] = {}
    fold_rows: list[dict[str, Any]] = []

    for condition in E3A_CONDITIONS:
        folds: list[dict[str, Any]] = []
        pooled_true: list[str] = []
        pooled_pred: list[str] = []

        for held_out in run_dirs:
            X_train: list[list[float]] = []
            y_train: list[str] = []
            for run_dir in run_dirs:
                if run_dir == held_out:
                    continue
                X, y, _meta = loaded[run_dir][condition]
                X_train.extend(X)
                y_train.extend(y)

            X_test, y_test, _meta = loaded[held_out][condition]
            pred, model_meta = _fit_predict_gaussian_nb(
                X_train, y_train, X_test
            )
            pred_list = [str(x) for x in pred.tolist()]

            accuracy = float(accuracy_score(y_test, pred_list))
            macro_f1 = float(
                f1_score(
                    y_test,
                    pred_list,
                    labels=[f"C{i}" for i in range(1, 9)],
                    average="macro",
                    zero_division=0,
                )
            )
            fold = {
                "held_out_run": held_out,
                "test_samples": len(y_test),
                "accuracy": accuracy,
                "macro_f1": macro_f1,
                **model_meta,
            }
            folds.append(fold)
            fold_rows.append({"condition": condition, **fold})
            pooled_true.extend(y_test)
            pooled_pred.extend(pred_list)

        conditions_out[condition] = {
            "feature_names": ["mqtt_payload_bytes"],
            "classifier": "GaussianNB",
            "validation": "Leave-One-Run-Out",
            "chance_level": CHANCE_LEVEL,
            "folds": folds,
            "mean_accuracy": mean_or_zero([f["accuracy"] for f in folds]),
            "std_accuracy": sample_std([f["accuracy"] for f in folds]),
            "mean_macro_f1": mean_or_zero([f["macro_f1"] for f in folds]),
            "std_macro_f1": sample_std([f["macro_f1"] for f in folds]),
            "pooled_accuracy": float(accuracy_score(pooled_true, pooled_pred)),
            "pooled_macro_f1": float(
                f1_score(
                    pooled_true,
                    pooled_pred,
                    labels=[f"C{i}" for i in range(1, 9)],
                    average="macro",
                    zero_division=0,
                )
            ),
        }

    return {
        "analysis": "E3-A broker-visible payload-length inference",
        "conditions": conditions_out,
        "fold_rows": fold_rows,
        "chance_level": CHANCE_LEVEL,
    }


# ---------------------------------------------------------------------------
# E3-B
# ---------------------------------------------------------------------------

def build_token_truth(
    condition_dir: Path,
) -> tuple[dict[str, tuple[str, int | None]], dict[str, str]]:
    """Build token -> (logical_topic_id, epoch) evaluation truth.

    publisher_metrics.csv is used here only for ground-truth labels.  None of
    these fields enter any classifier feature.
    """
    truth_rows = read_csv(condition_dir / "ground_truth.csv")
    logical_to_id: dict[str, str] = {}
    for row in truth_rows:
        topic = row["logical_topic"]
        tid = row["logical_topic_id"]
        if topic in logical_to_id and logical_to_id[topic] != tid:
            raise RuntimeError(f"inconsistent logical topic ID in {condition_dir}")
        logical_to_id[topic] = tid

    if set(logical_to_id.values()) != set(TOPIC_IDS):
        raise RuntimeError(
            f"expected logical topic IDs {TOPIC_IDS} in {condition_dir}; "
            f"got {sorted(set(logical_to_id.values()))}"
        )

    publisher_rows = read_csv(condition_dir / "publisher_metrics.csv")
    token_truth: dict[str, tuple[str, int | None]] = {}
    for row in publisher_rows:
        token = row.get("token_topic", "")
        logical_topic = row.get("plaintext_topic", "")
        if not token or logical_topic not in logical_to_id:
            continue
        epoch_raw = row.get("rotation_epoch", "").strip()
        epoch = int(epoch_raw) if epoch_raw else None
        value = (logical_to_id[logical_topic], epoch)
        previous = token_truth.get(token)
        if previous is not None and previous != value:
            raise RuntimeError(
                f"token maps to multiple ground-truth identities in "
                f"{condition_dir}: {token!r} -> {previous!r}, {value!r}"
            )
        token_truth[token] = value

    if not token_truth:
        raise RuntimeError(f"no token ground truth found in {condition_dir}")
    return token_truth, logical_to_id


def profile_rows(
    rows: Sequence[ObserverRow],
    *,
    start_ns: int,
    end_ns: int,
) -> dict[str, TokenProfile]:
    if end_ns <= start_ns:
        raise ValueError("profile window must have positive duration")

    grouped: dict[str, list[ObserverRow]] = defaultdict(list)
    for row in rows:
        if start_ns <= row.recv_unix_ns < end_ns:
            grouped[row.mqtt_topic].append(row)

    duration_sec = (end_ns - start_ns) / 1_000_000_000.0
    out: dict[str, TokenProfile] = {}
    for token, token_rows in grouped.items():
        token_rows = sorted(token_rows, key=lambda r: r.recv_unix_ns)
        times = [r.recv_unix_ns for r in token_rows]
        payloads = [float(r.mqtt_payload_bytes) for r in token_rows]
        iats_ms = [
            (times[i] - times[i - 1]) / 1_000_000.0
            for i in range(1, len(times))
        ]
        iat_mean = mean_or_zero(iats_ms)
        iat_std = sample_std(iats_ms)
        iat_cv = iat_std / iat_mean if iat_mean > 0 else 0.0

        out[token] = TokenProfile(
            token=token,
            count=len(token_rows),
            rate_hz=len(token_rows) / duration_sec,
            iat_mean_ms=iat_mean,
            iat_std_ms=iat_std,
            iat_cv=iat_cv,
            payload_mean_bytes=mean_or_zero(payloads),
            payload_std_bytes=sample_std(payloads),
            payload_min_bytes=min(payloads) if payloads else 0.0,
            payload_max_bytes=max(payloads) if payloads else 0.0,
        )
    return out


def overlap_times_by_token(
    rows: Sequence[ObserverRow],
    *,
    start_ns: int,
    end_ns: int,
) -> dict[str, list[int]]:
    grouped: dict[str, list[int]] = defaultdict(list)
    for row in rows:
        if start_ns <= row.recv_unix_ns < end_ns:
            grouped[row.mqtt_topic].append(row.recv_unix_ns)
    for values in grouped.values():
        values.sort()
    return grouped


def one_to_one_time_match_count(
    a_ns: Sequence[int],
    b_ns: Sequence[int],
    *,
    threshold_ns: int,
) -> int:
    """Maximum greedy one-to-one matches for sorted one-dimensional times."""
    i = 0
    j = 0
    matched = 0
    a = sorted(a_ns)
    b = sorted(b_ns)
    while i < len(a) and j < len(b):
        delta = a[i] - b[j]
        if abs(delta) <= threshold_ns:
            matched += 1
            i += 1
            j += 1
        elif delta < -threshold_ns:
            i += 1
        else:
            j += 1
    return matched


def cooccurrence_ratio(
    old_times_ns: Sequence[int],
    new_times_ns: Sequence[int],
    *,
    threshold_ms: float = COOCCURRENCE_THRESHOLD_MS,
) -> float:
    if not old_times_ns or not new_times_ns:
        return 0.0
    threshold_ns = int(round(threshold_ms * 1_000_000.0))
    matched = one_to_one_time_match_count(
        old_times_ns,
        new_times_ns,
        threshold_ns=threshold_ns,
    )
    return matched / float(min(len(old_times_ns), len(new_times_ns)))


def pair_features(
    old: TokenProfile,
    new: TokenProfile,
    *,
    overlap_ratio: float,
) -> tuple[float, ...]:
    a = old.numeric()
    b = new.numeric()
    diffs = tuple(abs(x - y) for x, y in zip(a, b))
    return diffs + (float(overlap_ratio),)


def _expected_epoch_tokens(
    token_truth: dict[str, tuple[str, int | None]],
    epoch: int,
) -> dict[str, str]:
    """Return logical_topic_id -> token for one rotating epoch."""
    out: dict[str, str] = {}
    for token, (topic_id, token_epoch) in token_truth.items():
        if token_epoch == epoch:
            if topic_id in out and out[topic_id] != token:
                raise RuntimeError(
                    f"multiple tokens for topic {topic_id} in epoch {epoch}"
                )
            out[topic_id] = token
    return out


def build_transition_pairs(
    *,
    run_dir: str,
    condition: str,
    observer_rows: Sequence[ObserverRow],
    token_truth: dict[str, tuple[str, int | None]],
    pacing_start_unix_ns: int,
    transition_epoch: int,
) -> tuple[list[CandidatePair], dict[str, Any]]:
    """Build all 8x8 candidate pairs for one adjacent-epoch transition."""
    if transition_epoch < 1 or transition_epoch > 11:
        raise ValueError("transition_epoch must be in 1..11")

    t0_ns = pacing_start_unix_ns + int(
        transition_epoch * ROTATION_INTERVAL_SEC * 1_000_000_000
    )
    old_start = t0_ns - int(PROFILE_WINDOW_SEC * 1_000_000_000)
    old_end = t0_ns
    overlap_start = t0_ns
    overlap_end = t0_ns + int(OVERLAP_WINDOW_SEC * 1_000_000_000)
    new_start = t0_ns + int(NEW_PROFILE_OFFSET_SEC * 1_000_000_000)
    new_end = new_start + int(PROFILE_WINDOW_SEC * 1_000_000_000)

    old_profiles_all = profile_rows(
        observer_rows, start_ns=old_start, end_ns=old_end
    )
    new_profiles_all = profile_rows(
        observer_rows, start_ns=new_start, end_ns=new_end
    )

    old_truth = _expected_epoch_tokens(token_truth, transition_epoch - 1)
    new_truth = _expected_epoch_tokens(token_truth, transition_epoch)
    expected_old_tokens = set(old_truth.values())
    expected_new_tokens = set(new_truth.values())

    # Candidate selection remains broker-visible: select the eight most active
    # tokens in each fixed profile window.  This tolerates a rare boundary
    # straggler (e.g., a B3 previous-epoch duplicate received a millisecond
    # after the +5-s overlap boundary) without using plaintext truth to choose
    # candidates.  Ground truth below is used only to verify the selected set
    # and attach evaluation labels.
    def select_eight(profiles: dict[str, TokenProfile]) -> dict[str, TokenProfile]:
        ranked = sorted(
            profiles.values(),
            key=lambda p: (-p.count, p.token),
        )
        if len(ranked) < 8:
            raise RuntimeError(
                f"{run_dir}/{condition} transition {transition_epoch}: "
                f"fewer than eight broker-visible profile tokens"
            )
        return {p.token: p for p in ranked[:8]}

    old_profiles = select_eight(old_profiles_all)
    new_profiles = select_eight(new_profiles_all)
    visible_old = set(old_profiles)
    visible_new = set(new_profiles)
    if visible_old != expected_old_tokens:
        missing = sorted(expected_old_tokens - visible_old)
        extra = sorted(visible_old - expected_old_tokens)
        raise RuntimeError(
            f"{run_dir}/{condition} transition {transition_epoch}: "
            f"old profile token set mismatch; missing={missing}, extra={extra}"
        )
    if visible_new != expected_new_tokens:
        missing = sorted(expected_new_tokens - visible_new)
        extra = sorted(visible_new - expected_new_tokens)
        raise RuntimeError(
            f"{run_dir}/{condition} transition {transition_epoch}: "
            f"new profile token set mismatch; missing={missing}, extra={extra}"
        )

    overlap_times = (
        overlap_times_by_token(
            observer_rows,
            start_ns=overlap_start,
            end_ns=overlap_end,
        )
        if condition == "B3"
        else {}
    )

    topic_by_old_token = {token: tid for tid, token in old_truth.items()}
    topic_by_new_token = {token: tid for tid, token in new_truth.items()}

    pairs: list[CandidatePair] = []
    for old_token in sorted(visible_old):
        for new_token in sorted(visible_new):
            ratio = 0.0
            if condition == "B3":
                ratio = cooccurrence_ratio(
                    overlap_times.get(old_token, []),
                    overlap_times.get(new_token, []),
                )
            old_tid = topic_by_old_token[old_token]
            new_tid = topic_by_new_token[new_token]
            pairs.append(
                CandidatePair(
                    run_dir=run_dir,
                    condition=condition,
                    transition_epoch=transition_epoch,
                    old_token=old_token,
                    new_token=new_token,
                    old_topic_id=old_tid,
                    new_topic_id=new_tid,
                    label=int(old_tid == new_tid),
                    features=pair_features(
                        old_profiles[old_token],
                        new_profiles[new_token],
                        overlap_ratio=ratio,
                    ),
                )
            )

    positives = sum(p.label for p in pairs)
    if len(pairs) != 64 or positives != 8:
        raise RuntimeError(
            f"{run_dir}/{condition} transition {transition_epoch}: "
            f"expected 64 candidate pairs / 8 positives, got "
            f"{len(pairs)} / {positives}"
        )

    return pairs, {
        "transition_epoch": transition_epoch,
        "old_token_count": len(visible_old),
        "new_token_count": len(visible_new),
        "candidate_pairs": len(pairs),
        "positive_pairs": positives,
        "window_ns": {
            "old": [old_start, old_end],
            "overlap": [overlap_start, overlap_end],
            "new": [new_start, new_end],
        },
    }


def load_e3b_run_condition(
    condition_dir: Path,
    *,
    run_dir: str,
    condition: str,
) -> tuple[list[CandidatePair], dict[str, Any]]:
    verify_gate_pass(condition_dir)
    manifest = verify_manifest(
        condition_dir,
        expected_harness_commit=E3B_HARNESS_COMMIT,
        expected_condition=condition,
    )
    if abs(float(manifest.get("pace_scale", 0.0)) - 1.0) > 1e-12:
        raise RuntimeError(f"formal E3-B pace_scale != 1.0 in {condition_dir}")

    observer = load_observer_rows(condition_dir / "observer.csv")
    token_truth, _logical_to_id = build_token_truth(condition_dir)
    pacing_start = manifest.get("pacing_start_unix_ns")
    if pacing_start is None:
        raise RuntimeError(
            f"missing pacing_start_unix_ns in {condition_dir}/run_manifest.json"
        )

    all_pairs: list[CandidatePair] = []
    transition_meta: list[dict[str, Any]] = []
    for transition_epoch in range(1, 12):
        pairs, meta = build_transition_pairs(
            run_dir=run_dir,
            condition=condition,
            observer_rows=observer,
            token_truth=token_truth,
            pacing_start_unix_ns=int(pacing_start),
            transition_epoch=transition_epoch,
        )
        all_pairs.extend(pairs)
        transition_meta.append(meta)

    return all_pairs, {
        "manifest": manifest,
        "transition_meta": transition_meta,
        "observer_rows": len(observer),
        "token_truth_count": len(token_truth),
    }


def summarize_e3b_reference(
    e3b_root: Path,
    run_dirs: Sequence[str] = FORMAL_RUN_DIRS,
) -> dict[str, Any]:
    per_run: list[dict[str, Any]] = []
    for run_dir in run_dirs:
        condition_dir = e3b_root / run_dir / E3B_REFERENCE_CONDITION
        gate = verify_gate_pass(condition_dir)
        manifest = verify_manifest(
            condition_dir,
            expected_harness_commit=E3B_HARNESS_COMMIT,
            expected_condition=E3B_REFERENCE_CONDITION,
        )
        observer = load_observer_rows(condition_dir / "observer.csv")
        token_truth, _ = build_token_truth(condition_dir)

        by_topic: dict[str, set[str]] = defaultdict(set)
        for token, (topic_id, epoch) in token_truth.items():
            if epoch is not None:
                raise RuntimeError(
                    f"B0 reference unexpectedly has rotating epoch in {condition_dir}"
                )
            by_topic[topic_id].add(token)

        stable = (
            set(by_topic) == set(TOPIC_IDS)
            and all(len(tokens) == 1 for tokens in by_topic.values())
        )
        per_run.append(
            {
                "run": run_dir,
                "observer_rows": len(observer),
                "unique_broker_visible_tokens": len({r.mqtt_topic for r in observer}),
                "one_persistent_token_per_logical_topic": stable,
                "overall_gate_pass": bool(gate.get("overall_pass")),
                "pace_scale": manifest.get("pace_scale"),
            }
        )

    return {
        "role": "persistent-token reference; not classifier input",
        "per_run": per_run,
        "all_runs_one_persistent_token_per_logical_topic": all(
            r["one_persistent_token_per_logical_topic"] for r in per_run
        ),
    }


def _fit_pair_classifier(train_pairs: Sequence[CandidatePair]):
    ml = _require_ml()
    np = ml["np"]
    Pipeline = ml["Pipeline"]
    StandardScaler = ml["StandardScaler"]
    LogisticRegression = ml["LogisticRegression"]

    X = np.asarray([p.features for p in train_pairs], dtype=float)
    y = np.asarray([p.label for p in train_pairs], dtype=int)
    if X.ndim != 2 or X.shape[1] != len(PAIR_FEATURE_NAMES):
        raise RuntimeError("unexpected E3-B pair-feature matrix shape")
    if set(y.tolist()) != {0, 1}:
        raise RuntimeError("E3-B pair classifier requires both classes")

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


def _score_transition(
    transition_pairs: Sequence[CandidatePair],
    probabilities: Sequence[float],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    ml = _require_ml()
    np = ml["np"]
    linear_sum_assignment = ml["linear_sum_assignment"]

    if len(transition_pairs) != 64 or len(probabilities) != 64:
        raise ValueError("transition scoring expects exactly 64 candidate pairs")

    old_tokens = sorted({p.old_token for p in transition_pairs})
    new_tokens = sorted({p.new_token for p in transition_pairs})
    if len(old_tokens) != 8 or len(new_tokens) != 8:
        raise RuntimeError("transition scoring expects eight old and eight new tokens")

    old_idx = {t: i for i, t in enumerate(old_tokens)}
    new_idx = {t: i for i, t in enumerate(new_tokens)}
    matrix = np.zeros((8, 8), dtype=float)
    lookup: dict[tuple[str, str], CandidatePair] = {}

    for pair, prob in zip(transition_pairs, probabilities):
        matrix[old_idx[pair.old_token], new_idx[pair.new_token]] = float(prob)
        lookup[(pair.old_token, pair.new_token)] = pair

    row_ind, col_ind = linear_sum_assignment(-matrix)
    assigned: dict[str, str] = {
        old_tokens[int(r)]: new_tokens[int(c)]
        for r, c in zip(row_ind.tolist(), col_ind.tolist())
    }

    correct = 0
    reciprocal_ranks: list[float] = []
    detail_rows: list[dict[str, Any]] = []

    for old_token in old_tokens:
        candidates = []
        for new_token in new_tokens:
            pair = lookup[(old_token, new_token)]
            prob = float(matrix[old_idx[old_token], new_idx[new_token]])
            candidates.append((prob, new_token, pair))

        # Deterministic tie-break by token string after descending probability.
        candidates.sort(key=lambda x: (-x[0], x[1]))
        true_rank = next(
            idx + 1
            for idx, (_prob, _new, pair) in enumerate(candidates)
            if pair.label == 1
        )
        reciprocal_ranks.append(1.0 / true_rank)

        chosen_new = assigned[old_token]
        chosen_pair = lookup[(old_token, chosen_new)]
        is_correct = int(chosen_pair.label == 1)
        correct += is_correct
        detail_rows.append(
            {
                "old_token": old_token,
                "old_topic_id": chosen_pair.old_topic_id,
                "assigned_new_token": chosen_new,
                "assigned_new_topic_id": chosen_pair.new_topic_id,
                "assigned_probability": float(
                    matrix[old_idx[old_token], new_idx[chosen_new]]
                ),
                "assignment_correct": is_correct,
                "true_candidate_rank": true_rank,
                "reciprocal_rank": 1.0 / true_rank,
            }
        )

    return (
        {
            "links": 8,
            "correct_links": correct,
            "top1_assignment_accuracy": correct / 8.0,
            "mrr": mean_or_zero(reciprocal_ranks),
        },
        detail_rows,
    )


def analyze_e3b_condition(
    *,
    condition: str,
    run_pairs: dict[str, list[CandidatePair]],
    run_dirs: Sequence[str],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    ml = _require_ml()
    np = ml["np"]

    folds: list[dict[str, Any]] = []
    assignment_rows: list[dict[str, Any]] = []
    pair_score_rows: list[dict[str, Any]] = []

    for held_out in run_dirs:
        train_pairs = [
            pair
            for run_dir in run_dirs
            if run_dir != held_out
            for pair in run_pairs[run_dir]
        ]
        test_pairs = run_pairs[held_out]
        model = _fit_pair_classifier(train_pairs)

        X_test = np.asarray([p.features for p in test_pairs], dtype=float)
        probs = model.predict_proba(X_test)[:, 1]

        transition_metrics: list[dict[str, Any]] = []
        total_correct = 0
        total_links = 0
        reciprocal_ranks: list[float] = []

        by_transition: dict[int, list[int]] = defaultdict(list)
        for idx, pair in enumerate(test_pairs):
            by_transition[pair.transition_epoch].append(idx)

        for transition_epoch in sorted(by_transition):
            indices = by_transition[transition_epoch]
            pairs = [test_pairs[i] for i in indices]
            pvals = [float(probs[i]) for i in indices]
            metric, details = _score_transition(pairs, pvals)
            transition_metrics.append(
                {"transition_epoch": transition_epoch, **metric}
            )
            total_correct += metric["correct_links"]
            total_links += metric["links"]
            reciprocal_ranks.extend(d["reciprocal_rank"] for d in details)

            for d in details:
                assignment_rows.append(
                    {
                        "condition": condition,
                        "held_out_run": held_out,
                        "transition_epoch": transition_epoch,
                        **d,
                    }
                )

            for pair, prob in zip(pairs, pvals):
                pair_score_rows.append(
                    {
                        "condition": condition,
                        "held_out_run": held_out,
                        "transition_epoch": transition_epoch,
                        "old_token": pair.old_token,
                        "new_token": pair.new_token,
                        "old_topic_id": pair.old_topic_id,
                        "new_topic_id": pair.new_topic_id,
                        "label": pair.label,
                        "probability_same_topic": prob,
                        **{
                            name: value
                            for name, value in zip(
                                PAIR_FEATURE_NAMES, pair.features
                            )
                        },
                    }
                )

        fold = {
            "held_out_run": held_out,
            "training_candidate_pairs": len(train_pairs),
            "test_candidate_pairs": len(test_pairs),
            "transitions": len(transition_metrics),
            "links": total_links,
            "correct_links": total_correct,
            "top1_assignment_accuracy": (
                total_correct / total_links if total_links else 0.0
            ),
            "mrr": mean_or_zero(reciprocal_ranks),
            "transition_metrics": transition_metrics,
        }
        folds.append(fold)

    result = {
        "classifier": (
            "StandardScaler + LogisticRegression("
            "class_weight='balanced', solver='liblinear', random_state=0)"
        ),
        "validation": "Leave-One-Run-Out",
        "pair_feature_names": list(PAIR_FEATURE_NAMES),
        "profile_feature_names": list(PROFILE_FEATURE_NAMES),
        "chance_level": CHANCE_LEVEL,
        "profile_windows_sec": {
            "old": [-20.0, 0.0],
            "overlap": [0.0, 5.0],
            "new": [5.0, 25.0],
        },
        "overlap_cooccurrence_threshold_ms": COOCCURRENCE_THRESHOLD_MS,
        "folds": folds,
        "mean_top1_assignment_accuracy": mean_or_zero(
            [f["top1_assignment_accuracy"] for f in folds]
        ),
        "std_top1_assignment_accuracy": sample_std(
            [f["top1_assignment_accuracy"] for f in folds]
        ),
        "mean_mrr": mean_or_zero([f["mrr"] for f in folds]),
        "std_mrr": sample_std([f["mrr"] for f in folds]),
        "pooled_top1_assignment_accuracy": (
            sum(f["correct_links"] for f in folds)
            / sum(f["links"] for f in folds)
        ),
        "pooled_mrr": mean_or_zero(
            [row["reciprocal_rank"] for row in assignment_rows]
        ),
    }
    return result, assignment_rows, pair_score_rows


def analyze_e3b(
    e3b_root: Path,
    run_dirs: Sequence[str] = FORMAL_RUN_DIRS,
) -> dict[str, Any]:
    reference = summarize_e3b_reference(e3b_root, run_dirs)

    conditions: dict[str, Any] = {}
    all_assignment_rows: list[dict[str, Any]] = []
    all_pair_score_rows: list[dict[str, Any]] = []
    load_metadata: dict[str, Any] = {}

    for condition in E3B_CLASSIFIER_CONDITIONS:
        run_pairs: dict[str, list[CandidatePair]] = {}
        load_metadata[condition] = {}
        for run_dir in run_dirs:
            pairs, meta = load_e3b_run_condition(
                e3b_root / run_dir / condition,
                run_dir=run_dir,
                condition=condition,
            )
            run_pairs[run_dir] = pairs
            load_metadata[condition][run_dir] = {
                "observer_rows": meta["observer_rows"],
                "token_truth_count": meta["token_truth_count"],
                "transitions": len(meta["transition_meta"]),
            }

        result, assignment_rows, pair_score_rows = analyze_e3b_condition(
            condition=condition,
            run_pairs=run_pairs,
            run_dirs=run_dirs,
        )
        conditions[condition] = result
        all_assignment_rows.extend(assignment_rows)
        all_pair_score_rows.extend(pair_score_rows)

    return {
        "analysis": "E3-B cross-epoch broker-visible topic linkability",
        "reference_B0": reference,
        "conditions": conditions,
        "load_metadata": load_metadata,
        "assignment_rows": all_assignment_rows,
        "pair_score_rows": all_pair_score_rows,
        "chance_level": CHANCE_LEVEL,
    }


# ---------------------------------------------------------------------------
# CLI / artifact output
# ---------------------------------------------------------------------------

def dependency_versions() -> dict[str, str]:
    ml = _require_ml()
    return {
        "python": sys.version.split()[0],
        "numpy": ml["np"].__version__,
        "scipy": ml["scipy"].__version__,
        "scikit_learn": ml["sklearn"].__version__,
    }


def build_summary_text(result: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("AOMQTT E3 privacy analysis")
    lines.append("==========================")
    lines.append("")

    e3a = result["e3a"]
    lines.append("E3-A payload-length inference (chance = 12.5%)")
    for condition in E3A_CONDITIONS:
        c = e3a["conditions"][condition]
        lines.append(
            f"  {condition}: accuracy={c['mean_accuracy']:.4f} "
            f"(SD={c['std_accuracy']:.4f}), "
            f"macro-F1={c['mean_macro_f1']:.4f} "
            f"(SD={c['std_macro_f1']:.4f})"
        )
    lines.append("")

    e3b = result["e3b"]
    lines.append("E3-B cross-epoch linkability (chance = 12.5%)")
    lines.append(
        "  B0: persistent-token reference; classifier not trained; "
        f"stable={e3b['reference_B0']['all_runs_one_persistent_token_per_logical_topic']}"
    )
    for condition in E3B_CLASSIFIER_CONDITIONS:
        c = e3b["conditions"][condition]
        lines.append(
            f"  {condition}: Top-1={c['mean_top1_assignment_accuracy']:.4f} "
            f"(SD={c['std_top1_assignment_accuracy']:.4f}), "
            f"MRR={c['mean_mrr']:.4f} (SD={c['std_mrr']:.4f})"
        )
    lines.append("")
    return "\n".join(lines)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Analyze frozen AOMQTT E3-A/E3-B privacy evaluation"
    )
    p.add_argument(
        "--e3a-root",
        type=Path,
        default=Path("results/e3/e3a"),
    )
    p.add_argument(
        "--e3b-root",
        type=Path,
        default=Path("results/e3/e3b"),
    )
    p.add_argument(
        "--out-root",
        type=Path,
        default=Path("results/e3/privacy-analysis"),
    )
    p.add_argument(
        "--run-dirs",
        nargs="+",
        default=list(FORMAL_RUN_DIRS),
        help="formal run directory names; default: formal-r01 ... formal-r05",
    )
    return p.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = Path(__file__).resolve().parents[2]
    out_root: Path = args.out_root
    out_root.mkdir(parents=True, exist_ok=True)

    run_dirs = tuple(args.run_dirs)
    if len(run_dirs) != 5:
        raise RuntimeError(
            "formal E3 analysis is frozen to five Leave-One-Run-Out runs"
        )

    e3a = analyze_e3a(args.e3a_root, run_dirs)
    e3b = analyze_e3b(args.e3b_root, run_dirs)

    result = {
        "schema_version": ANALYSIS_SCHEMA_VERSION,
        "aomqtt_base_commit": AOMQTT_BASE_COMMIT,
        "e3a_harness_commit": E3A_HARNESS_COMMIT,
        "e3b_harness_commit": E3B_HARNESS_COMMIT,
        "analysis_harness_commit": git_rev_parse(repo_root),
        "analysis_script_sha256": sha256_file(Path(__file__).resolve()),
        "run_dirs": list(run_dirs),
        "dependency_versions": dependency_versions(),
        "e3a": {
            k: v for k, v in e3a.items() if k != "fold_rows"
        },
        "e3b": {
            k: v
            for k, v in e3b.items()
            if k not in {"assignment_rows", "pair_score_rows"}
        },
    }

    write_json(out_root / "privacy_analysis.json", result)
    write_csv(
        out_root / "e3a_loro_folds.csv",
        e3a["fold_rows"],
        fieldnames=[
            "condition",
            "held_out_run",
            "test_samples",
            "accuracy",
            "macro_f1",
            "degenerate_constant_feature",
            "constant_value",
        ],
    )

    assignment_fields = [
        "condition",
        "held_out_run",
        "transition_epoch",
        "old_token",
        "old_topic_id",
        "assigned_new_token",
        "assigned_new_topic_id",
        "assigned_probability",
        "assignment_correct",
        "true_candidate_rank",
        "reciprocal_rank",
    ]
    write_csv(
        out_root / "e3b_transition_assignments.csv",
        e3b["assignment_rows"],
        fieldnames=assignment_fields,
    )

    pair_fields = [
        "condition",
        "held_out_run",
        "transition_epoch",
        "old_token",
        "new_token",
        "old_topic_id",
        "new_topic_id",
        "label",
        "probability_same_topic",
        *PAIR_FEATURE_NAMES,
    ]
    write_csv(
        out_root / "e3b_pair_scores.csv",
        e3b["pair_score_rows"],
        fieldnames=pair_fields,
    )

    summary = build_summary_text(result)
    (out_root / "privacy_analysis_summary.txt").write_text(
        summary, encoding="utf-8"
    )

    manifest = {
        "schema_version": ANALYSIS_SCHEMA_VERSION,
        "analysis_harness_commit": result["analysis_harness_commit"],
        "analysis_script_sha256": result["analysis_script_sha256"],
        "dependency_versions": result["dependency_versions"],
        "inputs": {
            "e3a_root": str(args.e3a_root),
            "e3b_root": str(args.e3b_root),
            "run_dirs": list(run_dirs),
        },
        "outputs": {},
    }
    for filename in (
        "privacy_analysis.json",
        "e3a_loro_folds.csv",
        "e3b_transition_assignments.csv",
        "e3b_pair_scores.csv",
        "privacy_analysis_summary.txt",
    ):
        path = out_root / filename
        manifest["outputs"][filename] = {
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        }
    write_json(out_root / "analysis_manifest.json", manifest)

    print(summary)
    print(f"analysis artifacts: {out_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
