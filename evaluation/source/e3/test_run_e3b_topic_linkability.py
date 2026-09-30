from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
GENERATOR_PATH = ROOT / "experiments" / "e3" / "generate_e3_event_plan.py"
MODULE_PATH = ROOT / "experiments" / "e3" / "run_e3b_topic_linkability.py"

gen_spec = importlib.util.spec_from_file_location(
    "generate_e3_event_plan", GENERATOR_PATH
)
assert gen_spec is not None and gen_spec.loader is not None
gen = importlib.util.module_from_spec(gen_spec)
sys.modules[gen_spec.name] = gen
gen_spec.loader.exec_module(gen)

spec = importlib.util.spec_from_file_location(
    "run_e3b_topic_linkability", MODULE_PATH
)
assert spec is not None and spec.loader is not None
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


def make_plan(path: Path, *, duration_sec: float = 95.0) -> None:
    events = gen.generate_e3b_events(
        run_index=1,
        seed=20261102,
        duration_sec=duration_sec,
    )
    gen.write_e3b_csv(events, path)


def test_prefix_and_observer_filter_are_condition_scoped():
    assert mod.condition_prefix("e3b-r01", "B3") == "e3/b/e3b-r01/B3"
    assert mod.observer_filter("e3b-r01", "B3") == "e3/b/e3b-r01/B3/#"


def test_load_plan_revalidates_epoch_slot_and_payload(tmp_path: Path):
    plan = tmp_path / "plan.csv"
    make_plan(plan)
    events = mod.load_plan(plan)
    assert events
    assert all(
        e.epoch_slot
        == e.relative_time_ns // (30 * 1_000_000_000)
        for e in events
    )


def test_load_plan_limit_duration_keeps_original_event_indices(tmp_path: Path):
    plan = tmp_path / "plan.csv"
    make_plan(plan, duration_sec=120.0)
    full = mod.load_plan(plan)
    limited = mod.load_plan(plan, limit_duration_sec=65.0)
    assert limited
    assert limited == [
        e for e in full if e.relative_time_ns < 65_000_000_000
    ]


def test_physical_epochs_B3_overlap_semantics():
    before = mod.PlanEvent(
        0, 29_900_000_000, 0, "m0", "T1", "e3/site/temp", 100
    )
    overlap = mod.PlanEvent(
        1, 31_000_000_000, 1, "m1", "T1", "e3/site/temp", 100
    )
    after = mod.PlanEvent(
        2, 36_000_000_000, 1, "m2", "T1", "e3/site/temp", 100
    )
    assert mod.physical_epochs_for_event(before, "B3") == ("0",)
    assert mod.physical_epochs_for_event(overlap, "B3") == ("1", "0")
    assert mod.physical_epochs_for_event(after, "B3") == ("1",)


def test_B0_B1_B2_have_one_physical_publish_per_logical():
    events = [
        mod.PlanEvent(0, 1_000_000_000, 0, "m0", "T1", "e3/site/temp", 100),
        mod.PlanEvent(1, 31_000_000_000, 1, "m1", "T2", "e3/site/humidity", 110),
    ]
    for condition in ("B0", "B1", "B2"):
        assert mod.expected_physical_count(events, condition) == 2
        assert mod.expected_overlap_duplicates(events, condition) == 0


def test_B3_expected_duplicate_count():
    events = [
        mod.PlanEvent(0, 1_000_000_000, 0, "m0", "T1", "e3/site/temp", 100),
        mod.PlanEvent(1, 31_000_000_000, 1, "m1", "T1", "e3/site/temp", 100),
        mod.PlanEvent(2, 36_000_000_000, 1, "m2", "T1", "e3/site/temp", 100),
        mod.PlanEvent(3, 61_000_000_000, 2, "m3", "T1", "e3/site/temp", 100),
    ]
    assert mod.expected_physical_count(events, "B3") == 6
    assert mod.expected_overlap_duplicates(events, "B3") == 2


def test_expected_token_pairs_B0_are_persistent():
    events = [
        mod.PlanEvent(0, 1_000_000_000, 0, "m0", "T1", "e3/site/temp", 100),
        mod.PlanEvent(1, 31_000_000_000, 1, "m1", "T1", "e3/site/temp", 100),
        mod.PlanEvent(2, 31_500_000_000, 1, "m2", "T2", "e3/site/humidity", 110),
    ]
    pairs = mod.expected_token_identity_pairs(events, "B0")
    assert pairs == {
        ("e3/site/temp", None),
        ("e3/site/humidity", None),
    }


def test_expected_token_pairs_B3_include_previous_epoch_identity():
    events = [
        mod.PlanEvent(0, 1_000_000_000, 0, "m0", "T1", "e3/site/temp", 100),
        mod.PlanEvent(1, 31_000_000_000, 1, "m1", "T1", "e3/site/temp", 100),
    ]
    pairs = mod.expected_token_identity_pairs(events, "B3")
    assert pairs == {
        ("e3/site/temp", "0"),
        ("e3/site/temp", "1"),
    }


def test_gate_accepts_valid_B3_overlap_result():
    events = [
        mod.PlanEvent(0, 1_000_000_000, 0, "m0", "T1", "e3/site/temp", 100),
        mod.PlanEvent(1, 31_000_000_000, 1, "m1", "T1", "e3/site/temp", 100),
    ]
    gate = mod.evaluate_gate(
        condition="B3",
        events=events,
        full_formal_plan=False,
        publisher_summary={"physical": 3, "success": 3, "failed": 0},
        publisher_token_summary={
            "unique_token_topic_count": 2,
            "token_count_per_logical_topic": {"e3/site/temp": 2},
            "overlap_duplicate_rows": 1,
        },
        observer_summary={
            "row_count": 3,
            "sequence_contiguous": True,
            "unique_payload_sizes": [802],
            "unique_payload_size_count": 1,
            "unique_mqtt_topic_count": 2,
        },
        delivery_summary={
            "total_received": 3,
            "decrypt_success": 3,
            "decrypt_failed": 0,
            "unique_messages": 2,
            "duplicates": 1,
        },
        callback_unique_received=2,
    )
    assert gate["overall_pass"] is True
    assert gate["expected_overlap_duplicates"] == 1


def test_gate_rejects_wrong_B3_duplicate_count():
    events = [
        mod.PlanEvent(0, 31_000_000_000, 1, "m0", "T1", "e3/site/temp", 100),
    ]
    gate = mod.evaluate_gate(
        condition="B3",
        events=events,
        full_formal_plan=False,
        publisher_summary={"physical": 2, "success": 2, "failed": 0},
        publisher_token_summary={
            "unique_token_topic_count": 2,
            "token_count_per_logical_topic": {"e3/site/temp": 2},
            "overlap_duplicate_rows": 1,
        },
        observer_summary={
            "row_count": 2,
            "sequence_contiguous": True,
            "unique_payload_sizes": [802],
            "unique_payload_size_count": 1,
            "unique_mqtt_topic_count": 2,
        },
        delivery_summary={
            "total_received": 2,
            "decrypt_success": 2,
            "decrypt_failed": 0,
            "unique_messages": 1,
            "duplicates": 0,
        },
        callback_unique_received=1,
    )
    assert gate["overall_pass"] is False
    assert gate["checks"]["duplicates_equal_expected_overlap"] is False


def test_observer_command_uses_raw_condition_prefix(tmp_path: Path):
    cmd = mod.build_observer_command(
        observer_script=Path("/repo/experiments/e3/e3_broker_observer.py"),
        broker="localhost",
        port=1883,
        run_id="e3b-r01",
        condition="B2",
        condition_dir=tmp_path / "B2",
    )
    assert "e3/b/e3b-r01/B2/#" in cmd
    assert str(tmp_path / "B2" / "observer.csv") in cmd


def test_nonlocal_broker_requires_explicit_opt_in(tmp_path: Path):
    plan = tmp_path / "plan.csv"
    make_plan(plan)
    with pytest.raises(SystemExit):
        mod.parse_args(
            [
                "--plan", str(plan),
                "--run-id", "e3b-r01",
                "--out-root", str(tmp_path / "out"),
                "--broker", "192.0.2.1",
                "--dry-run",
            ]
        )


def test_dry_run_writes_execution_plan_without_network(tmp_path: Path):
    plan = tmp_path / "plan.csv"
    make_plan(plan, duration_sec=95.0)
    out = tmp_path / "out"

    rc = mod.main(
        [
            "--plan", str(plan),
            "--run-id", "e3b-r01",
            "--out-root", str(out),
            "--broker", "localhost",
            "--limit-duration-sec", "65",
            "--pace-scale", "0.05",
            "--dry-run",
        ]
    )
    assert rc == 0
    payload = json.loads((out / "e3b_execution_plan.json").read_text())
    assert payload["mode"] == "dry-run"
    assert payload["conditions"] == ["B0", "B1", "B2", "B3"]
    assert payload["aomqtt_base_commit"] == mod.AOMQTT_BASE_COMMIT
    assert payload["pace_scale"] == 0.05


def test_r01_frozen_plan_expected_counts():
    events = gen.generate_e3b_events(
        run_index=1,
        seed=20261102,
    )
    assert len(events) == 4108
    assert mod.expected_physical_count(events, "B0") == 4108
    assert mod.expected_physical_count(events, "B1") == 4108
    assert mod.expected_physical_count(events, "B2") == 4108
    assert mod.expected_overlap_duplicates(events, "B3") == 635
    assert mod.expected_physical_count(events, "B3") == 4743
    assert len(mod.expected_token_identity_pairs(events, "B0")) == 8
    assert len(mod.expected_token_identity_pairs(events, "B1")) == 96
    assert len(mod.expected_token_identity_pairs(events, "B2")) == 96
    assert len(mod.expected_token_identity_pairs(events, "B3")) == 96
