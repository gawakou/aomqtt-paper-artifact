from __future__ import annotations

import csv
import importlib.util
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "experiments" / "e3" / "analyze_e3_privacy.py"

spec = importlib.util.spec_from_file_location("analyze_e3_privacy", MODULE_PATH)
assert spec is not None and spec.loader is not None
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


def write_csv(path: Path, fieldnames, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def profile(token: str, *, rate=1.0, iat=1000.0, payload=300.0):
    return mod.TokenProfile(
        token=token,
        count=20,
        rate_hz=rate,
        iat_mean_ms=iat,
        iat_std_ms=10.0,
        iat_cv=0.01,
        payload_mean_bytes=payload,
        payload_std_bytes=5.0,
        payload_min_bytes=payload - 10.0,
        payload_max_bytes=payload + 10.0,
    )


def test_sample_std_singleton_is_zero():
    assert mod.sample_std([1.0]) == 0.0


def test_pair_features_are_absolute_differences_plus_overlap():
    old = profile("old", rate=1.0, iat=1000.0, payload=200.0)
    new = profile("new", rate=1.2, iat=800.0, payload=250.0)
    features = mod.pair_features(old, new, overlap_ratio=0.75)
    assert len(features) == len(mod.PAIR_FEATURE_NAMES)
    assert features[1] == pytest.approx(0.2)
    assert features[2] == pytest.approx(200.0)
    assert features[-1] == pytest.approx(0.75)


def test_time_match_count_one_to_one():
    a = [1_000, 2_000, 10_000]
    b = [1_005, 1_995, 50_000]
    assert mod.one_to_one_time_match_count(a, b, threshold_ns=10) == 2


def test_cooccurrence_ratio_uses_smaller_side_denominator():
    a = [1_000, 2_000, 3_000]
    b = [1_005, 1_995]
    ratio = mod.cooccurrence_ratio(a, b, threshold_ms=0.00001)
    assert ratio == pytest.approx(1.0)


def test_profile_rows_uses_broker_visible_fields_only():
    rows = [
        mod.ObserverRow(0, 1_000_000_000, "tok", 200),
        mod.ObserverRow(1, 2_000_000_000, "tok", 220),
        mod.ObserverRow(2, 2_500_000_000, "other", 300),
    ]
    p = mod.profile_rows(
        rows,
        start_ns=0,
        end_ns=4_000_000_000,
    )
    assert set(p) == {"tok", "other"}
    assert p["tok"].count == 2
    assert p["tok"].rate_hz == pytest.approx(0.5)
    assert p["tok"].iat_mean_ms == pytest.approx(1000.0)
    assert p["tok"].payload_mean_bytes == pytest.approx(210.0)


def test_gaussian_nb_constant_feature_degenerates_to_prior():
    pytest.importorskip("sklearn")
    pytest.importorskip("numpy")
    X_train = [[802.0]] * 16
    y_train = ["C1", "C2"] * 8
    pred, meta = mod._fit_predict_gaussian_nb(
        X_train, y_train, [[802.0], [802.0]]
    )
    assert meta["degenerate_constant_feature"] is True
    assert pred.tolist() == ["C1", "C1"]


def test_gaussian_nb_separates_clear_length_classes():
    pytest.importorskip("sklearn")
    pytest.importorskip("numpy")
    X_train = [[100.0], [101.0], [200.0], [201.0]]
    y_train = ["C1", "C1", "C2", "C2"]
    pred, meta = mod._fit_predict_gaussian_nb(
        X_train, y_train, [[100.5], [200.5]]
    )
    assert meta["degenerate_constant_feature"] is False
    assert pred.tolist() == ["C1", "C2"]


def test_score_transition_hungarian_and_mrr():
    pytest.importorskip("scipy")
    pytest.importorskip("numpy")

    pairs = []
    probs = []
    for oi in range(8):
        for ni in range(8):
            old_tid = f"T{oi + 1}"
            new_tid = f"T{ni + 1}"
            pairs.append(
                mod.CandidatePair(
                    run_dir="formal-r01",
                    condition="B2",
                    transition_epoch=1,
                    old_token=f"old{oi}",
                    new_token=f"new{ni}",
                    old_topic_id=old_tid,
                    new_topic_id=new_tid,
                    label=int(oi == ni),
                    features=(0.0,) * len(mod.PAIR_FEATURE_NAMES),
                )
            )
            probs.append(0.99 if oi == ni else 0.01)

    metric, details = mod._score_transition(pairs, probs)
    assert metric["correct_links"] == 8
    assert metric["top1_assignment_accuracy"] == pytest.approx(1.0)
    assert metric["mrr"] == pytest.approx(1.0)
    assert all(d["true_candidate_rank"] == 1 for d in details)


def test_fit_pair_classifier_prefers_small_profile_differences():
    pytest.importorskip("sklearn")
    pytest.importorskip("numpy")

    train = []
    for r in range(30):
        positive = mod.CandidatePair(
            "formal-r01", "B2", 1, f"o{r}", f"n{r}",
            "T1", "T1", 1,
            (0.05,) * 9 + (0.0,),
        )
        negative = mod.CandidatePair(
            "formal-r01", "B2", 1, f"o{r}", f"x{r}",
            "T1", "T2", 0,
            (5.0,) * 9 + (0.0,),
        )
        train.extend([positive, negative])

    model = mod._fit_pair_classifier(train)
    import numpy as np
    X = np.asarray(
        [
            (0.05,) * 9 + (0.0,),
            (5.0,) * 9 + (0.0,),
        ],
        dtype=float,
    )
    p = model.predict_proba(X)[:, 1]
    assert p[0] > p[1]


def test_build_token_truth_rejects_ambiguous_token(tmp_path: Path):
    d = tmp_path / "B1"
    write_csv(
        d / "ground_truth.csv",
        [
            "event_index", "relative_time_ns", "epoch_slot", "message_id",
            "logical_topic_id", "logical_topic", "target_plain_bytes",
        ],
        [
            {
                "event_index": 0, "relative_time_ns": 0, "epoch_slot": 0,
                "message_id": "m0", "logical_topic_id": f"T{i}",
                "logical_topic": f"topic/{i}", "target_plain_bytes": 100,
            }
            for i in range(1, 9)
        ],
    )
    rows = []
    for i in range(1, 9):
        rows.append(
            {
                "token_topic": "same-token" if i <= 2 else f"tok{i}",
                "plaintext_topic": f"topic/{i}",
                "rotation_epoch": "0",
            }
        )
    write_csv(
        d / "publisher_metrics.csv",
        ["token_topic", "plaintext_topic", "rotation_epoch"],
        rows,
    )
    with pytest.raises(RuntimeError, match="multiple ground-truth identities"):
        mod.build_token_truth(d)


def test_load_observer_requires_contiguous_seq(tmp_path: Path):
    path = tmp_path / "observer.csv"
    write_csv(
        path,
        [
            "run_id", "condition", "observer_seq", "recv_unix_ns",
            "recv_monotonic_ns", "mqtt_topic", "mqtt_payload_bytes",
            "qos", "retain", "dup",
        ],
        [
            {
                "run_id": "r", "condition": "A0", "observer_seq": 0,
                "recv_unix_ns": 1, "recv_monotonic_ns": 1,
                "mqtt_topic": "t", "mqtt_payload_bytes": 100,
                "qos": 1, "retain": 0, "dup": 0,
            },
            {
                "run_id": "r", "condition": "A0", "observer_seq": 2,
                "recv_unix_ns": 2, "recv_monotonic_ns": 2,
                "mqtt_topic": "t", "mqtt_payload_bytes": 100,
                "qos": 1, "retain": 0, "dup": 0,
            },
        ],
    )
    with pytest.raises(RuntimeError, match="non-contiguous"):
        mod.load_observer_rows(path)


def test_verify_manifest_enforces_frozen_harness(tmp_path: Path):
    d = tmp_path / "A0"
    write_json(
        d / "run_manifest.json",
        {
            "condition": "A0",
            "harness_commit": "wrong",
            "aomqtt_base_commit": mod.AOMQTT_BASE_COMMIT,
            "formal_full_plan": True,
        },
    )
    with pytest.raises(RuntimeError, match="harness commit mismatch"):
        mod.verify_manifest(
            d,
            expected_harness_commit=mod.E3A_HARNESS_COMMIT,
            expected_condition="A0",
        )


def test_build_transition_pairs_exact_8x8():
    start = 1_000_000_000_000
    rows = []
    token_truth = {}

    # transition epoch 1 at +30 s.  Give every old and new token events in its
    # profile window.  Topic rates/sizes are intentionally distinct.
    seq = 0
    for i in range(8):
        old = f"old{i}"
        new = f"new{i}"
        tid = f"T{i+1}"
        token_truth[old] = (tid, 0)
        token_truth[new] = (tid, 1)
        for sec in (12, 18, 24, 28):
            rows.append(
                mod.ObserverRow(
                    seq,
                    start + sec * 1_000_000_000 + i * 1_000,
                    old,
                    200 + 10 * i,
                )
            )
            seq += 1
        for sec in (36, 42, 48, 54):
            rows.append(
                mod.ObserverRow(
                    seq,
                    start + sec * 1_000_000_000 + i * 1_000,
                    new,
                    200 + 10 * i,
                )
            )
            seq += 1

    pairs, meta = mod.build_transition_pairs(
        run_dir="formal-r01",
        condition="B2",
        observer_rows=rows,
        token_truth=token_truth,
        pacing_start_unix_ns=start,
        transition_epoch=1,
    )
    assert len(pairs) == 64
    assert sum(p.label for p in pairs) == 8
    assert meta["old_token_count"] == 8
    assert meta["new_token_count"] == 8


def test_B3_transition_overlap_feature_marks_true_pair():
    start = 1_000_000_000_000
    rows = []
    token_truth = {}
    seq = 0
    for i in range(8):
        old = f"old{i}"
        new = f"new{i}"
        tid = f"T{i+1}"
        token_truth[old] = (tid, 0)
        token_truth[new] = (tid, 1)

        # old and new profile windows
        for sec in (12, 18, 24, 28):
            rows.append(
                mod.ObserverRow(seq, start + sec*1_000_000_000 + i*1000, old, 802)
            )
            seq += 1
        for sec in (36, 42, 48, 54):
            rows.append(
                mod.ObserverRow(seq, start + sec*1_000_000_000 + i*1000, new, 802)
            )
            seq += 1

        # same logical message appears on old/new tokens within 1 ms in overlap
        for sec in (31, 33):
            base = start + sec*1_000_000_000 + i*2_000_000
            rows.append(mod.ObserverRow(seq, base, old, 802))
            seq += 1
            rows.append(mod.ObserverRow(seq, base + 1_000_000, new, 802))
            seq += 1

    pairs, _ = mod.build_transition_pairs(
        run_dir="formal-r01",
        condition="B3",
        observer_rows=rows,
        token_truth=token_truth,
        pacing_start_unix_ns=start,
        transition_epoch=1,
    )
    true_pair = next(
        p for p in pairs if p.old_topic_id == "T1" and p.new_topic_id == "T1"
    )
    assert true_pair.features[-1] == pytest.approx(1.0)



def test_transition_candidate_selection_ignores_one_low_count_boundary_straggler():
    start = 1_000_000_000_000
    rows = []
    token_truth = {}
    seq = 0
    for i in range(8):
        old = f"old{i}"
        new = f"new{i}"
        tid = f"T{i+1}"
        token_truth[old] = (tid, 0)
        token_truth[new] = (tid, 1)
        for sec in (12, 18, 24, 28):
            rows.append(mod.ObserverRow(seq, start + sec*1_000_000_000 + i, old, 802))
            seq += 1
        for sec in (36, 42, 48, 54):
            rows.append(mod.ObserverRow(seq, start + sec*1_000_000_000 + i, new, 802))
            seq += 1

    # Simulate one stale token arriving just after the +5-s boundary.  It is
    # broker-visible but has only one row, so the top-eight activity rule
    # excludes it without consulting plaintext truth.
    rows.append(
        mod.ObserverRow(
            seq,
            start + 35_000_500_000,
            "stale-old-boundary-token",
            802,
        )
    )

    pairs, _ = mod.build_transition_pairs(
        run_dir="formal-r01",
        condition="B3",
        observer_rows=rows,
        token_truth=token_truth,
        pacing_start_unix_ns=start,
        transition_epoch=1,
    )
    assert len(pairs) == 64
    assert all(p.new_token != "stale-old-boundary-token" for p in pairs)

def test_parse_args_defaults():
    args = mod.parse_args([])
    assert args.e3a_root == Path("results/e3/e3a")
    assert args.e3b_root == Path("results/e3/e3b")
    assert args.out_root == Path("results/e3/privacy-analysis")
    assert args.run_dirs == list(mod.FORMAL_RUN_DIRS)
